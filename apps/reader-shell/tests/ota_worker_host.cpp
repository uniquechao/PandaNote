// Use the real worker state machine and crypto; only the filesystem root is redirected.
#define PANDANOTE_OTA_FIXTURE
#include "../ota_worker.cpp"
#include <fstream>
#include <iterator>
#include <stdarg.h>
static const char *cloneRoot;
static time_t fixtureClock;
extern "C" time_t __real_time(time_t*);
extern "C" time_t __wrap_time(time_t*out){if(!fixtureClock)return __real_time(out);if(out)*out=fixtureClock;return fixtureClock;}
extern "C" int __real_open(const char*,int,...);
extern "C" int __real_lstat(const char*,struct stat*);
extern "C" int __wrap_lstat(const char*p,struct stat*s){std::string mapped=p;if(cloneRoot&&(!strncmp(p,"/user/",6)||!strncmp(p,"/run/pandanote-normal/",21)))mapped=std::string(cloneRoot)+p;return __real_lstat(mapped.c_str(),s);}
extern "C" int __wrap_open(const char*path,int flags,...){mode_t mode=0600;if(flags&O_CREAT){va_list v;va_start(v,flags);mode=va_arg(v,int);va_end(v);}return __real_open(!strcmp(path,"/")&&cloneRoot?cloneRoot:path,flags,mode);}
static std::string input(const std::string&p){std::ifstream f(p.c_str(),std::ios::binary);return std::string(std::istreambuf_iterator<char>(f),std::istreambuf_iterator<char>());}
int main(int argc,char **argv){QCoreApplication app(argc,argv);if(argc!=5&&argc!=6)return 2;Json plan;if(argc==6){if(!parse(input(argv[5]),plan))return 3;fixtureClock=plan.num("now");}cloneRoot=argv[1];OtaWorker w;parse(input(argv[2]),w.config);parse(input(argv[3]),w.request_);w.bootGeneration=std::string(32,'2');w.state=Json::obj();w.state.object["schema"]=Json::integer(1);w.state.object["state"]=Json("CHECKING");w.state.object["attempt_id"]=Json(argc==6?plan.text("attempt_id"):std::string(32,'1'));w.state.object["generation"]=Json(std::string(32,'3'));w.state.object["confirmed"]=Json::integer(0);w.state.object["error_code"]=Json("none");
 w.received("check",200,input(argv[4]));if(w.stopped||w.state.text("state")!="OFFERED"||w.state.num("confirmed")!=0)return 10;

 if(argc==6){
  std::string id=w.state.text("attempt_id"),generation=w.state.text("generation");
  if(plan.num("downloading")==1){w.state.object["confirmed"]=Json::integer(1);w.transition("DOWNLOADING");}
  if(!w.init()||w.state.text("attempt_id")!=id||w.state.num("confirmed")!=0)return 37;
  fixtureClock=plan.num("renewed_at");w.received("chunk",404,"");
  if(w.state.text("attempt_id")!=id||w.state.num("confirmed")!=0||w.state.text("generation")==generation||w.state.num("renewing")!=1)return 30;
  // 请求字段由生产管理端签名向量提供；事务身份与 generation 走生产 beginCheck。
  if(!w.beginCheck(plan.get("request"))||w.state.text("attempt_id")!=id)return 38;
  w.received("check",200,encode(plan.get("offer")));
  if(w.stopped||w.state.text("state")!="OFFERED"||w.state.text("attempt_id")!=id||w.state.num("confirmed")!=0)return 31;
  // 重启恢复读取生产原子授权快照；旧 nonce 与新封装不匹配。
  Authorization renewed;Json req;std::string error;if(!loadAttempt(id,w.config,renewed,req,error)||req.text("request_nonce")!=w.request_.text("request_nonce"))return 32;
  Json stale;parse(input(argv[3]),stale);if(authorize(plan.get("offer"),w.config,stale,epoch(),renewed,error))return 33;
  w.state.object["confirmed"]=Json::integer(1);w.transition("DOWNLOADING");w.received("chunk",200,input(std::string(cloneRoot)+"/wire"));if(w.state.text("state")!="VERIFIED")return 34;
  // 仅模拟健康事件的设备身份；不声称执行闪存、重启或真机健康预算。
  atomic("/user/pandanote/apps/current",w.auth.release.text("native_sha256")+"\n");atomic("/run/pandanote-normal/early.ready",w.auth.release.text("boot_id")+"\n");
  if(!w.transition("HEALTHY"))return 35;atomic(w.dir()+"/authorization.json","{");if(loadAttempt(id,w.config,renewed,req,error))return 36;return 0;
 }
 // Receiving a signed update never authorizes downloading.
 Json activity=Json::obj();Process self;if(!process(getpid(),self))return 11;activity=processJson(self);activity.object["schema"]=Json::integer(1);activity.object["heartbeat_ms"]=Json::integer(bootMs());activity.object["awake"]=Json::integer(1);activity.object["shutdown"]=Json::integer(0);activity.object["time_trusted"]=Json::integer(1);activity.object["boot_generation"]=Json(w.bootGeneration);if(!atomic(std::string(runRoot())+"/activity.json",encode(activity)))return 12;
 Json command=Json::obj();command.object["schema"]=Json::integer(1);command.object["attempt_id"]=w.state.get("attempt_id");command.object["generation"]=Json(std::string(32,'9'));command.object["action"]=Json("upgrade");atomic(std::string(runRoot())+"/command.json",encode(command));w.commands();if(w.state.text("state")!="OFFERED")return 13;
 command.object["generation"]=w.state.get("generation");atomic(std::string(runRoot())+"/command.json",encode(command));w.commands();if(w.state.text("state")!="DOWNLOADING"||w.state.num("confirmed")!=1||w.stopped)return 14;
 std::string wire=input(std::string(cloneRoot)+"/wire");w.received("chunk",200,wire);if(w.state.text("state")!="VERIFIED"||w.state.num("downloaded")!=int64_t(wire.size())||w.stopped)return 15;
 w.transition("WAITING_SAFE_WINDOW");command.object["generation"]=w.state.get("generation");command.object["action"]=Json("defer");atomic(std::string(runRoot())+"/command.json",encode(command));w.commands();if(w.state.text("state")!="OFFERED"||w.state.num("confirmed")!=0||w.state.num("deferred")!=1||w.stopped)return 16;
 // Deferral and network/report errors must not silently grant consent again.
 for(int i=0;i<100;i++)w.fail("network_failure");if(w.stopped)return 18;if(w.state.num("confirmed")!=0||w.state.text("state")!="OFFERED")return 17;
 // 已过期或 nonce 冲突的检查必须清除旧请求和确认，由后续联网检查生成新 nonce。
 const char*expiredCodes[]={"grant_expired","nonce_conflict","release_revoked"};
 for(unsigned i=0;i<3;i++){w.state.object["state"]=Json("CHECKING");w.state.object["attempt_id"]=Json(std::string(32,'1'));w.state.object["confirmed"]=Json::integer(1);w.request_=Json::obj();w.request_.object["request_nonce"]=Json(std::string(64,'9'));Json error=Json::obj();error.object["schema"]=Json::integer(1);error.object["error"]=Json::obj();error.object["error"].object["code"]=Json(std::string(expiredCodes[i]));w.received("check",409,encode(error));if(w.stopped||w.state.text("state")!="IDLE"||w.state.num("confirmed")!=0||w.state.text("attempt_id")!=std::string(32,'1')||w.request_.type!=Json::Null||w.haveAuth||w.state.num("last_check")!=0)return 19;}

 // UI 和 worker 共用撤销原语：过期准备即使电源不安全也先撤销，旧 ready 不能重放。
 w.haveAuth=true;Json response;parse(input(argv[4]),response);std::string error;Authorization a;
 Json config=w.config;Json ledger;loadJson(std::string(stateRoot())+"/accepted.json",ledger,4096);config.object["accepted_release_sha256"]=ledger.get("release_sha256");Json original;parse(input(argv[3]),original);if(!authorize(response,config,original,epoch(),a,error))return 20;w.auth=a;w.request_=original;
 w.state.object["state"]=Json("WAITING_SAFE_WINDOW");w.state.object["confirmed"]=Json::integer(1);w.save();
 Json q=activity;q.object["attempt_id"]=w.state.get("attempt_id");q.object["generation"]=w.state.get("generation");q.object["started_ms"]=Json::integer(bootMs()-90001);q.object["result"]=Json("ready");atomic(std::string(runRoot())+"/prepare.request",encode(q));atomic(std::string(runRoot())+"/prepare.reply",encode(q));
 w.prepare();if(w.state.text("state")!="OFFERED"||w.state.num("confirmed")!=0||prepareValid(w.state.text("attempt_id"),q.text("generation")))return 21;
 // 在已经持久化 APPLYING 后，UI 绝不因失去心跳释放普通输入。
 w.state.object["state"]=Json("APPLYING");w.save();if(revokePreparation()||restartCheck())return 22;
 w.state.object["state"]=Json("WAITING_SAFE_WINDOW");w.save();{PrepareGuard held;if(!held.locked()||revokePreparation())return 23;}
 if(!revokePreparation()||!restartCheck())return 24;
 w.state.object["state"]=Json("IDLE");w.state.object["confirmed"]=Json::integer(0);w.state.object["last_check"]=Json::integer(0);w.save();
 return 0;}
