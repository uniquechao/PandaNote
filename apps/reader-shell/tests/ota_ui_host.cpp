// 使用真实 ReaderShell/otaTick，只有 ADC 与墨水屏硬件入口替换为无操作。
#include "../shell.h"
#include "../ota/core.h"
#include "../battery.h"
#include <QtWidgets/qapplication.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdarg.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
using namespace Ota;
static const char *cloneRoot;
extern "C" int __real_open(const char*,int,...);
extern "C" int __wrap_open(const char*p,int flags,...){mode_t mode=0600;if(flags&O_CREAT){va_list v;va_start(v,flags);mode=va_arg(v,int);va_end(v);}return __real_open(!strcmp(p,"/")?cloneRoot:p,flags,mode);}
BatteryReading readBattery(bool){return BatteryReading();}
EinkRefreshResult performDeviceFullRefresh(){return EinkRefreshUnavailable;}
class OtaUiFixture {
public:static void capture(ReaderShell &u,const char*name){const char*folder=getenv("PANDANOTE_OTA_UI_SCREENSHOTS");if(!folder)return;QImage frame(480,800,QImage::Format_RGB32);u.render(&frame);frame.save(QString::fromUtf8(folder)+"/"+QString::fromLatin1(name)+".png");}
 static int run(ReaderShell &u){
 Json s=Json::obj();s.object["schema"]=Json::integer(1);s.object["attempt_id"]=Json(std::string(32,'1'));s.object["generation"]=Json(std::string(32,'2'));s.object["state"]=Json("OFFERED");s.object["version"]=Json("2.0");s.object["bundle_bytes"]=Json::integer(204800);s.object["worker_heartbeat_ms"]=Json::integer(bootMs());s.object["error_code"]=Json("none");s.object["deferred"]=Json::integer(1);
 atomic(std::string(stateRoot())+"/state.json",encode(s));atomic(std::string(runRoot())+"/status.json",encode(s));u.otaTick();
 if(u.otaPromptVisible()||!u.otaOffered_)return 10;
 u.navigation_.restore(Info,0);u.otaTick();if(u.otaPromptVisible())return 20;u.show();QApplication::processEvents();int paints=u.otaPaintCount_;s.object["deferred"]=Json::integer(0);atomic(std::string(runRoot())+"/status.json",encode(s));u.otaTick();QApplication::processEvents();if(u.otaPaintCount_<=paints)return 21;if(!u.otaPromptVisible()||!u.otaSummary_.contains(QString::fromUtf8("更新说明：未提供")))return 11;
 capture(u,"confirmation");u.inputField_=0;if(u.otaPromptVisible())return 12;u.inputField_=-1;
 s.object["state"]=Json("DOWNLOADING");s.object["downloaded"]=Json::integer(102400);atomic(std::string(runRoot())+"/status.json",encode(s));u.otaTick();if(!u.otaMessage_.contains("50%")||!u.otaTap(40,720))return 13;
 capture(u,"download");s.object["state"]=Json("WAITING_SAFE_WINDOW");s.object["confirmed"]=Json::integer(1);atomic(std::string(stateRoot())+"/state.json",encode(s));atomic(std::string(runRoot())+"/status.json",encode(s));
 Process self;process(getpid(),self);Json q=processJson(self);q.object["schema"]=Json::integer(1);q.object["attempt_id"]=s.get("attempt_id");q.object["generation"]=s.get("generation");q.object["boot_generation"]=Json(std::string(32,'3'));q.object["started_ms"]=Json::integer(bootMs()-31000);atomic(std::string(runRoot())+"/prepare.request",encode(q));
 u.otaPreparing_=true;u.otaPrepareAt_=bootMs()-2000;u.otaTick();capture(u,"preparing");u.otaPrepareAt_=bootMs()-31000;u.otaTick();if(!u.otaInstalling()||u.otaMessage_.contains(QString::fromUtf8("触摸屏幕可推迟")))return 14;
 capture(u,"ready");
 // 心跳丢失时撤销真实 ready，UI 立即恢复输入，持久化取消证据防止 worker 复活重放。
 s.object["worker_heartbeat_ms"]=Json::integer(bootMs()-15000);atomic(std::string(runRoot())+"/status.json",encode(s));u.otaTick();if(u.otaInstalling())return 15;std::string raw;if(readFile(std::string(runRoot())+"/prepare.reply",raw,4096)||!readFile(std::string(runRoot())+"/prepare.cancelled",raw,4096))return 16;
 s.object["worker_heartbeat_ms"]=Json::integer(bootMs());s.object["worker_stopped"]=Json::integer(1);atomic(std::string(runRoot())+"/status.json",encode(s));u.otaTick();if(u.otaInstalling())return 18;
 // APPLYING 与不确定结果绝不因失去心跳恢复普通输入。
 const char *phases[]={"APPLYING","COMMITTED_PENDING_REBOOT","RECOVERY_REQUIRED"};for(unsigned i=0;i<3;i++){s.object["state"]=Json(std::string(phases[i]));atomic(std::string(stateRoot())+"/state.json",encode(s));u.otaTick();if(!u.otaInstalling())return 17;}
 if(!u.otaMessage_.contains(QString::fromUtf8("诊断编号")))return 19;capture(u,"recovery");return 0;
 }};
int main(int argc,char **argv){if(argc!=2)return 2;cloneRoot=argv[1];QApplication app(argc,argv);Content content;ReaderShell u(content);int result=OtaUiFixture::run(u);if(result)fprintf(stderr,"界面交接断言失败：%d\n",result);return result;}
