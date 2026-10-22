#include "shell.h"
#include "ota/core.h"
#include <QtGui/qpainter.h>
#include <QtCore/qcoreapplication.h>
#include <QtCore/qfile.h>
#include <unistd.h>
using namespace Ota;
static QString ot(const char*s){return QString::fromUtf8(s);}
static QString os(const std::string &s){return QString::fromUtf8(s.data(),int(s.size()));}
static std::string ob(const QString&s){QByteArray b=s.toUtf8();return std::string(b.constData(),b.size());}
static QString otaError(const std::string &e){
 if(e=="power_unsafe")return ot("请保持充电，电量与充电状态确认安全后安装");
 if(e=="network_failure")return ot("网络连接失败，将自动重试");
 if(e=="signature_invalid")return ot("升级签名校验失败，已停止安装");
 if(e=="authorization_expired")return ot("升级授权已过期，请重新检测");
 if(e=="baseline_mismatch")return ot("当前程序与受控基线不一致，需要核对");
 if(e=="storage_insufficient")return ot("存储空间不足或状态文件无法持久化");
 if(e=="bundle_invalid")return ot("升级包校验失败，可重新确认下载");
 if(e=="proof_invalid"||e=="window_busy")return ot("升级安全窗口未就绪，请稍后重试");
 if(e=="apply_failed"||e=="recovery_required"||e=="health_failed")return ot("升级结果需要受控核对，已保留恢复材料");
 if(e=="reboot_failed")return ot("重启未完成，请保留现场等待核对");
 return ot("升级暂不可用，请稍后检查");
}
static bool readOta(const std::string &name,Json &j){std::string s;return readFile(std::string(runRoot())+"/"+name,s,65536)&&parse(s,j,65536);}
void ReaderShell::otaInitialize(){if(otaTimer_)return;Json status;if(readOta("status.json",status)&&status.num("schema")==1){otaTimer_=startTimer(1000);otaTick();}else otaMessage_=ot("OTA 尚未启用");}
bool ReaderShell::otaGesture(int x,int y)const{return confirmationGesture(ob(otaPressAttempt_),ob(otaPressGeneration_),ob(otaAttempt_),ob(otaGeneration_),otaPressPrompt_,otaPromptVisible(),x-press_.x(),y-press_.y());}
void ReaderShell::otaCommand(const char *action){if(!otaTimer_)otaInitialize();if(!otaTimer_){update();return;}Json j=Json::obj();j.object["schema"]=Json::integer(1);j.object["action"]=Json(std::string(action));j.object["attempt_id"]=Json(ob(otaAttempt_));j.object["generation"]=Json(ob(otaGeneration_));if(!atomic(std::string(runRoot())+"/command.json",encode(j)))otaMessage_=ot("升级请求未发送，请重试");}
bool ReaderShell::otaInput(){if(otaPreparing_&&!otaLocked_){otaCommand("defer");otaPreparing_=false;otaPrepareAt_=-1;removeFile(std::string(runRoot())+"/prepare.reply");return true;}return false;}
bool ReaderShell::otaTap(int x,int y){if(otaLocked_)return true;if(otaPromptVisible()){if(QRect(32,512,192,54).contains(x,y))otaCommand("defer");else if(QRect(256,512,192,54).contains(x,y))otaCommand("upgrade");return true;}if(page()==Info&&QRect(24,704,432,56).contains(x,y)){otaCommand(otaOffered_?"show":"check");return true;}if(otaPreparing_&&QRect(24,704,432,56).contains(x,y)){otaCommand("defer");return true;}return false;}
void ReaderShell::otaTick(){Json s;if(!readOta("status.json",s)||s.num("schema")!=1||bootMs()-s.num("worker_heartbeat_ms")>10000||s.num("worker_heartbeat_ms")>bootMs()){if(otaMessage_.isEmpty())otaMessage_=ot("OTA 尚未启用");return;}QString previous=otaMessage_;std::string phase=s.text("state");otaAttempt_=os(s.text("attempt_id"));otaGeneration_=os(s.text("generation"));otaVersion_=os(s.text("version"));otaCurrent_=os(s.text("current_native_sha256")).left(12);otaOffered_=phase=="OFFERED";otaProgress_=phase=="DOWNLOADING"||phase=="VERIFIED"||phase=="WAITING_SAFE_WINDOW";otaDeferred_=s.num("deferred")==1;otaLocked_=phase=="APPLYING"||phase=="COMMITTED_PENDING_REBOOT";
 if(phase=="OFFERED")otaMessage_=ot("发现新版本：")+otaVersion_;
 else if(phase=="CHECKING")otaMessage_=ot("正在检查新版本");
 else if(phase=="DOWNLOADING")otaMessage_=ot("正在下载升级包：")+QString::number(qMax(int64_t(0),s.num("downloaded"))/1024)+ot(" KiB");
 else if(phase=="WAITING_SAFE_WINDOW"||phase=="VERIFIED")otaMessage_=ot("等待保存草稿与安全电源条件");
 else if(phase=="APPLYING")otaMessage_=ot("正在安装升级，请保持供电");
 else if(phase=="COMMITTED_PENDING_REBOOT")otaMessage_=ot("升级已安装，正在重启");
 else if(phase=="BOOT_VERIFYING")otaMessage_=ot("正在确认新版运行状态");
 else if(phase=="HEALTHY")otaMessage_=ot("升级成功");
 else if(phase=="ROLLED_BACK")otaMessage_=ot("升级失败，旧入口已恢复，等待受控核对");
 else if(phase=="RECOVERY_REQUIRED")otaMessage_=ot("升级需要受控恢复，请保留现场");
 else otaMessage_=s.num("last_check")>0?ot("已完成版本检查，暂无新版本"):ot("每天联网检查一次，升级前会询问");
 if(s.text("error_code")!="none"&&!s.text("error_code").empty())otaMessage_+=ot("\n原因：")+otaError(s.text("error_code"));
 Process p;if(!process(getpid(),p))return;std::string generation;if(!readFile(std::string(runRoot())+"/boot.generation",generation,64))return;
 Json activity=processJson(p);activity.object["schema"]=Json::integer(1);activity.object["boot_generation"]=Json(generation);activity.object["heartbeat_ms"]=Json::integer(bootMs());activity.object["time_trusted"]=Json::integer(otaTimeTrusted());activity.object["awake"]=Json::integer(!standby_&&!shutdownPending_);activity.object["shutdown"]=Json::integer(shutdownPending_);activity.object["busy"]=Json::integer(otaSyncBusy_||radio_->busy()||inputActive()||bluetoothActive());atomic(std::string(runRoot())+"/activity.json",encode(activity));
 Json q;bool prepare=phase=="WAITING_SAFE_WINDOW"&&readOta("prepare.request",q)&&q.text("attempt_id")==ob(otaAttempt_)&&q.text("generation")==ob(otaGeneration_)&&q.text("boot_generation")==generation&&q.num("native_pid")==p.pid&&q.num("native_starttime")==p.start;
 if(prepare&&!otaLocked_){if(!otaPreparing_){otaPrepareAt_=bootMs();otaPreparing_=true;}bool busy=standby_||shutdownPending_||otaSyncBusy_||radio_->busy()||bluetoothActive()||inputActive();if(busy)otaPrepareAt_=bootMs();Json reply=q;reply.object["heartbeat_ms"]=Json::integer(bootMs());bool saved=false;if(!busy&&bootMs()-otaPrepareAt_>=30000)saved=persistPowerDraft();reply.object["result"]=Json(std::string(busy?"busy":bootMs()-otaPrepareAt_<30000?"busy":saved?"ready":"save_failed"));atomic(std::string(runRoot())+"/prepare.reply",encode(reply));if(saved)otaLocked_=true;otaMessage_=busy?ot("升级等待当前操作完成"):ot("即将升级，触摸屏幕可推迟：")+QString::number(qMax<qint64>(0,30000-(bootMs()-otaPrepareAt_))/1000)+ot(" 秒");}
 else if(!otaLocked_){otaPreparing_=false;otaPrepareAt_=-1;removeFile(std::string(runRoot())+"/prepare.reply");}
 if(otaLocked_&&readOta("prepare.reply",q)){q.object["heartbeat_ms"]=Json::integer(bootMs());atomic(std::string(runRoot())+"/prepare.reply",encode(q));}
 if(!standby_&&!shutdownPending_&&otaPaintCount_>0){Json h=activity;h.object["paint_count"]=Json::integer(otaPaintCount_);h.object["workspace_ready"]=Json::integer(local_.available());h.object["event_loop_ready"]=Json::integer(1);QByteArray exe=QFile::encodeName(QCoreApplication::applicationDirPath());std::string path(exe.constData(),exe.size());size_t end=path.rfind('/');std::string identity=end==std::string::npos?"":path.substr(end+1);h.object["native_sha256"]=Json(identity);atomic(std::string(runRoot())+"/health.ready",encode(h));}
 if(previous!=otaMessage_)update();}
void ReaderShell::drawOta(QPainter &p){if(otaProgress_&&!standby_&&!shutdownPending_&&powerMessage_.isEmpty()&&page()!=Info){p.fillRect(QRect(16,108,448,80),Qt::white);QFont f=font();f.setPixelSize(18);p.setFont(f);p.drawText(QRect(24,112,432,72),Qt::TextWordWrap,otaMessage_);}if(standby_||shutdownPending_||(!otaLocked_&&(!otaOffered_||otaDeferred_||inputActive()||noteEditing_)))return;p.fillRect(QRect(16,218,448,374),Qt::white);p.setPen(QPen(Qt::black,2));p.drawRect(QRect(16,218,448,374));QFont f=font();f.setPixelSize(24);f.setBold(true);p.setFont(f);p.drawText(QRect(32,242,416,64),Qt::AlignLeft|Qt::AlignVCenter,otaLocked_?ot("正在升级"):ot("软件更新"));f.setPixelSize(20);f.setBold(false);p.setFont(f);p.drawText(QRect(32,322,416,160),Qt::TextWordWrap,otaMessage_+(otaLocked_?QString():ot("\n是否下载并升级？重启后确认运行结果。")));if(!otaLocked_){drawButton(p,QRect(32,512,192,54),ot("稍后再说"));drawButton(p,QRect(256,512,192,54),ot("确认升级"));}}
