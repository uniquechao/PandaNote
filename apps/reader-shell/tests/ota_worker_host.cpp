// Use the real worker state machine and crypto; only the filesystem root is redirected.
#define PANDANOTE_OTA_FIXTURE
#include "../ota_worker.cpp"
#include <fstream>
#include <iterator>
#include <stdarg.h>
static const char *cloneRoot;
extern "C" int __real_open(const char*,int,...);
extern "C" int __wrap_open(const char*path,int flags,...){mode_t mode=0600;if(flags&O_CREAT){va_list v;va_start(v,flags);mode=va_arg(v,int);va_end(v);}return __real_open(!strcmp(path,"/")&&cloneRoot?cloneRoot:path,flags,mode);}
static std::string input(const std::string&p){std::ifstream f(p.c_str(),std::ios::binary);return std::string(std::istreambuf_iterator<char>(f),std::istreambuf_iterator<char>());}
int main(int argc,char **argv){QCoreApplication app(argc,argv);if(argc!=5)return 2;cloneRoot=argv[1];OtaWorker w;parse(input(argv[2]),w.config);parse(input(argv[3]),w.request_);w.bootGeneration=std::string(32,'2');w.state=Json::obj();w.state.object["schema"]=Json::integer(1);w.state.object["state"]=Json("CHECKING");w.state.object["attempt_id"]=Json(std::string(32,'1'));w.state.object["generation"]=Json(std::string(32,'3'));w.state.object["confirmed"]=Json::integer(0);w.state.object["error_code"]=Json("none");
 w.received("check",200,input(argv[4]));if(w.stopped||w.state.text("state")!="OFFERED"||w.state.num("confirmed")!=0)return 10;
 // Receiving a signed update never authorizes downloading.
 Json activity=Json::obj();Process self;if(!process(getpid(),self))return 11;activity=processJson(self);activity.object["schema"]=Json::integer(1);activity.object["heartbeat_ms"]=Json::integer(bootMs());activity.object["awake"]=Json::integer(1);activity.object["shutdown"]=Json::integer(0);activity.object["time_trusted"]=Json::integer(1);activity.object["boot_generation"]=Json(w.bootGeneration);if(!atomic(std::string(runRoot())+"/activity.json",encode(activity)))return 12;
 Json command=Json::obj();command.object["schema"]=Json::integer(1);command.object["attempt_id"]=w.state.get("attempt_id");command.object["generation"]=Json(std::string(32,'9'));command.object["action"]=Json("upgrade");atomic(std::string(runRoot())+"/command.json",encode(command));w.commands();if(w.state.text("state")!="OFFERED")return 13;
 command.object["generation"]=w.state.get("generation");atomic(std::string(runRoot())+"/command.json",encode(command));w.commands();if(w.state.text("state")!="DOWNLOADING"||w.state.num("confirmed")!=1||w.stopped)return 14;
 std::string wire=input(std::string(cloneRoot)+"/wire");w.received("chunk",200,wire);if(w.state.text("state")!="VERIFIED"||w.state.num("downloaded")!=int64_t(wire.size())||w.stopped)return 15;
 w.transition("WAITING_SAFE_WINDOW");command.object["action"]=Json("defer");atomic(std::string(runRoot())+"/command.json",encode(command));w.commands();if(w.state.text("state")!="OFFERED"||w.state.num("confirmed")!=0||w.state.num("deferred")!=1||w.stopped)return 16;
 // Deferral and network/report errors must not silently grant consent again.
 for(int i=0;i<100;i++)w.fail("network_failure");if(w.stopped)return 18;if(w.state.num("confirmed")!=0||w.state.text("state")!="OFFERED")return 17;
 // 已过期或 nonce 冲突的检查必须清除旧请求和确认，由后续联网检查生成新 nonce。
 const char*expiredCodes[]={"grant_expired","nonce_conflict","release_revoked"};
 for(unsigned i=0;i<3;i++){w.state.object["state"]=Json("CHECKING");w.state.object["attempt_id"]=Json(std::string(32,'1'));w.state.object["confirmed"]=Json::integer(1);w.request_=Json::obj();w.request_.object["request_nonce"]=Json(std::string(64,'9'));Json error=Json::obj();error.object["schema"]=Json::integer(1);error.object["error"]=Json::obj();error.object["error"].object["code"]=Json(std::string(expiredCodes[i]));w.received("check",409,encode(error));if(w.stopped||w.state.text("state")!="IDLE"||w.state.num("confirmed")!=0||!w.state.text("attempt_id").empty()||w.request_.type!=Json::Null||w.haveAuth||w.state.num("last_check")!=0)return 19;}
 return 0;}
