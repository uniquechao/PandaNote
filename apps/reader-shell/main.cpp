#include "shell.h"
#include "systemclock.h"
#include "startupretry.h"
#include "standbypolicy.h"
#include "tlsclock.h"
#include "powerkeys.h"
#include "powerrequest.h"
#include <fcntl.h>
#include <errno.h>
#include <QtGui/qapplication.h>
#include <QtGui/qevent.h>
#include <QtCore/qcoreapplication.h>
#include <QtCore/qstringlist.h>
#include <stdio.h>
#include <string.h>
#include <QtCore/qfile.h>
#include <QtCore/qfileinfo.h>
#include <QtCore/qsettings.h>
#include <QtCore/qregexp.h>
#include <sys/stat.h>
#include <unistd.h>
#include <limits.h>
// No static Qt objects, moc, constructors or wall-clock assumptions.
typedef char ProductionQrealIsFloat32[sizeof(qreal)==4 ? 1 : -1];
static QByteArray quoted(const QString &value) {
    QByteArray out="\"";
    for(int i=0;i<value.size();++i) {
        ushort c=value[i].unicode();
        if(c=='"' || c=='\\') { out+='\\';out+=char(c); }
        else if(c<32 || c>126) { char escaped[7];snprintf(escaped,sizeof(escaped),"\\u%04x",unsigned(c));out+=escaped; }
        else out+=QString(value[i]).toUtf8();
    }
    return out+'"';
}
static void logRecord(const char *event,const QByteArray &fields) {
    fprintf(stdout,"{\"event\":\"%s\",%s}\n",event,fields.constData());fflush(stdout);
}
static void logExit(const char *reason,int code) {
    logRecord("EXIT_REASON",QByteArray("\"reason\":")+quoted(reason)+",\"code\":"+QByteArray::number(code));
}
class RuntimeShell:public ReaderShell {
public:
    explicit RuntimeShell(const QString &syncCache="/tmp/pandanote-reader-cache"):ReaderShell(Content()),refreshTimer_(startTimer(30000)),timeoutTimer_(0),loggedExit_(false),powerTimer_(0),nextPowerOpen_(0),suspendArmed_(false),suspendPending_(false),pendingWakeActivity_(false),pendingWakeAction_(NoPowerAction),suspendAt_(0),suspendPendingAt_(0),suspendCounter_(0),sync_(syncCache),syncTimer_(0),nextPoll_(0),lastContact_(0) { syncClock_.start();systemClockStatus_=QString::fromUtf8("系统时钟：尚未校时");setConnectionStatus(QString::fromUtf8("离线 · 尚未配置 HTTPS 与 USB 信任资料")); }
    bool configurePowerKeys(){if(!power_.open())return false;powerClock_.start();powerTimer_=startTimer(25);logRecord("POWER_KEYS","\"available\":true");return true;}
    bool loadCached() { Content c=sync_.cachedContent();if(c.schema!=1)return false;current_=c;setContent(c);return true; }
    bool loadSyncConfiguration(const QString &path) {
        QByteArray raw;if(!readSyncFile(path,4096,true,&raw))return false;
        // USB-provisioned private config with an explicit trusted TLS profile.
        // Small canonical config grammar avoids permissive QSettings escapes/duplicates.
        QList<QByteArray> lines=raw.split('\n');if(lines.size()!=8||lines[0]!="[sync]"||lines[1]!="schema=1"||!lines[2].startsWith("endpoint64=")||!lines[3].startsWith("token64=")||!lines[4].startsWith("certificate64=")||!lines[5].startsWith("certificateSha256=")||!lines[6].startsWith("bootstrapEpoch=")||!lines[7].isEmpty())return false;
        QByteArray endpoint64=lines[2].mid(11),token64=lines[3].mid(8),cert64=lines[4].mid(14);QByteArray endpoint=QByteArray::fromBase64(endpoint64),token=QByteArray::fromBase64(token64),cert=QByteArray::fromBase64(cert64);if(endpoint.toBase64()!=endpoint64||token.toBase64()!=token64||cert.toBase64()!=cert64)return false;
        QString certificate=QString::fromUtf8(cert);if(certificate.toUtf8()!=cert||(!certificate.startsWith("/tmp/")&&!certificate.startsWith("/user/pandanote/config/"))||!readSyncFile(certificate,16384,false,&profile_.certificatePem))return false;profile_.certificateSha256=QString::fromLatin1(lines[5].mid(18));bool epochOk=false;profile_.bootstrapEpoch=lines[6].mid(15).toLongLong(&epochOk);if(!epochOk||!QRegExp("[0-9a-f]{64}").exactMatch(profile_.certificateSha256)||profile_.bootstrapEpoch<946684800LL||profile_.bootstrapEpoch>2147483646LL)return false;
        bool ok=configureSync(QString::fromUtf8(endpoint),token);token.fill('\0');raw.fill('\0');return ok;
    }
    bool configureSync(const QString &endpoint,const QByteArray &token) {
        DeviceEndpoint candidate;QString error;if(!parseDeviceEndpoint(endpoint,&candidate,&error)||!candidate.tls||profile_.certificatePem.isEmpty()||token.size()<16||token.size()>512||!QRegExp("[A-Za-z0-9._~-]+").exactMatch(QString::fromLatin1(token))) { setConnectionStatus(QString::fromUtf8("配置未应用：需要 HTTPS、USB 预置证书与有效设备凭据"));return false; }
        http_.cancel();candidate.certificatePem=profile_.certificatePem;candidate.certificateSha256=profile_.certificateSha256;candidate.bootstrapEpoch=profile_.bootstrapEpoch;endpoint_=candidate;token_.fill('\0');token_=token;setEndpointLabel(endpoint);if(!syncTimer_)syncTimer_=startTimer(50);nextPoll_=syncClock_.elapsed();setConnectionStatus(QString::fromUtf8("同步参数已应用；等待认证同步"));return true;
    }
    void syncRequested() { if(syncTimer_){nextPoll_=0;setSyncActivity(true);}else{setConnectionStatus(QString::fromUtf8("请先配置 HTTPS 与 USB 信任资料、设备凭据"));setSyncActivity(false);} }
    void contentPainted(const QString &version) { sync_.painted(version); }
    void syncTick() {
        int status=0;QByteArray body;QString error;bool received=false;
        bool manifest=sync_.request().path=="/reader/v1/manifest";
        int result=http_.poll(&status,&body,&error);
        if(result!=0)logRecord("SYNC_TRANSPORT",QByteArray("\"tls\":")+(endpoint_.tls?"true":"false")+",\"manifest\":"+(manifest?"true":"false")+",\"transport_ok\":"+(result>0?"true":"false")+",\"http_status\":"+QByteArray::number(result>0?status:0));
        if(result<0)sync_.failed(error);
        else if(result>0){
            received=sync_.receive(status,body);
            // freshEpoch is zero on resource/ACK replies. Never use HTTP Date,
            // cached content or the developer display anchor for system time.
            SystemClockResult clock=applyAuthenticatedTime(received,sync_.freshEpoch(),*this,http_);
            if(received&&sync_.freshEpoch()>0){lastContact_=sync_.freshEpoch();maintenance_.authenticatedContact();}
            if(clock.status!=SystemClockResult::Skipped){
                bool applied=clock.status==SystemClockResult::Applied;
                systemClockStatus_=applied?QString::fromUtf8("系统时钟：已按认证 UTC 校准"):
                    clock.status==SystemClockResult::InvalidEpoch?QString::fromUtf8("系统校时失败：UTC 超出支持范围"):
                    QString::fromUtf8("系统校时失败：clock_settime errno=")+QString::number(clock.errorNumber);
                logRecord("SYSTEM_CLOCK",QByteArray("\"applied\":")+(applied?"true":"false")+",\"epoch_utc\":"+QByteArray::number(sync_.freshEpoch())+",\"errno\":"+QByteArray::number(clock.errorNumber)+",\"status\":"+quoted(clock.status==SystemClockResult::InvalidEpoch?"invalid-epoch":applied?"applied":"syscall-failed"));
            }
            Content c;if(received&&sync_.takeUpdate(&c)){current_=c;setContent(c);}
        }
        if(result!=0){qint64 now=syncClock_.elapsed();nextPoll_=now+startupRetry_.delayAfterResult(now,sync_.error().toLatin1().constData(),sync_.pollSeconds()*1000LL,received&&sync_.freshEpoch()>0);setSyncFailed(!sync_.error().isEmpty());QString label=sync_.error().isEmpty()?QString::fromUtf8("认证联系成功"):QString::fromUtf8("同步失败，保留上次内容：")+sync_.error();label+=QString::fromUtf8("\n最近联系 UTC：")+(lastContact_?QString::number(lastContact_):QString::fromUtf8("尚无"));label+=QString::fromUtf8("\n已绘制版本：")+(sync_.lastDisplayed().isEmpty()?QString::fromUtf8("尚无确认"):sync_.lastDisplayed());label+=QString::fromUtf8("\n")+systemClockStatus_;setConnectionStatus(label);}
        if(!http_.busy()&&sync_.request().path.isEmpty())nextPoll_=startupRetry_.pollDeadline(syncClock_.elapsed(),nextPoll_);
        if(!http_.busy()&&sync_.request().path.isEmpty()&&syncClock_.elapsed()>=nextPoll_){sync_.refresh();nextPoll_=syncClock_.elapsed()+sync_.pollSeconds()*1000LL;}
        if(!http_.busy()&&!sync_.request().path.isEmpty()){
            startupRetry_.beginAttempt(syncClock_.elapsed());
            if(!http_.start(endpoint_,token_,sync_.request(),&error)){sync_.failed(error);qint64 now=syncClock_.elapsed();nextPoll_=now+startupRetry_.delayAfterResult(now,error.toLatin1().constData(),300000,false);setSyncFailed(true);setConnectionStatus(error);}
        }
        // A committed version waits for asynchronous paint before its ACK is
        // queued. Keep activity through that gap and settle only after start.
        setSyncActivity(http_.busy()||!sync_.request().path.isEmpty()||sync_.waitingForPaint());
    }
    bool loadDirectory(const QString &directory) {
        Content candidate;QString error;
        bool ok=loadContent(directory,&candidate,&error);
        if(ok) { current_=candidate;setContent(candidate);setSyncFailed(false); }
        else setSyncFailed(true);
        logRecord("CONTENT_LOADED",QByteArray("\"success\":")+(ok?"true":"false")+",\"retained\":"+(!ok && current_.schema==1?"true":"false")+",\"version\":"+quoted(current_.version)+",\"error\":"+quoted(error));
        return ok;
    }
    void developerTimeout(int ms) { timeoutTimer_=startTimer(ms); }
    void recordExit(int code) { if(!loggedExit_) { loggedExit_=true;logExit("event_loop_return",code); } }
protected:
    void navigationChanged(Page from,Page to,const char *source,int x,int y) {
        logRecord("NAVIGATION",QByteArray("\"from\":")+QByteArray::number(int(from))+",\"to\":"+QByteArray::number(int(to))+",\"source\":"+quoted(source)+",\"x\":"+QByteArray::number(x)+",\"y\":"+QByteArray::number(y));
    }
    void observeSuspendedPower() {
        // The helper must already hold its input FD before this drain can authorize mem.
        bool inputReady=suspendInputReady("/run/pandanote-normal",suspendGeneration_,suspendToken_);
        PowerAction action=power_.poll();
        if(power_.takeActivity()||!power_.available())pendingWakeActivity_=true;
        if(action==LongPowerPress||(action==ShortPowerPress&&pendingWakeAction_==NoPowerAction))pendingWakeAction_=action;
        if(pendingWakeActivity_)publishSuspendWakeIntent("/run/pandanote-normal",suspendGeneration_,suspendToken_);
        else if(inputReady)acknowledgeSuspendInput("/run/pandanote-normal",suspendGeneration_,suspendToken_);
    }
    void resumeSuspend(SuspendReply reply) {
        suspendPending_=false;suspendArmed_=false;
        bool reset=power_.resetAfterResume();bool resetActivity=power_.takeActivity();bool human=pendingWakeActivity_||resetActivity;PowerAction action=pendingWakeAction_;
        pendingWakeActivity_=false;pendingWakeAction_=NoPowerAction;
        logRecord("SYSTEM_RESUME",!reset?"\"success\":false,\"input_reset\":false":(reply==SuspendResumed||reply==SuspendTimerResumed)?"\"success\":true,\"input_reset\":true":"\"success\":false,\"input_reset\":true");
        if(action==LongPowerPress){longPowerPress();return;}
        if(reply==SuspendTimerResumed&&!human&&reset&&maintenance_.begin(tlsBootMs())) {
            logRecord("STANDBY_MAINTENANCE","\"started\":true");
            http_.cancel();sync_.failed("standby-resume");startupRetry_=StartupSyncRetry();nextPoll_=0;
            refreshStandbySnapshot();return;
        }
        systemStandbyCompleted(reset&&(human||reply==SuspendResumed||reply==SuspendTimerResumed));
    }
    bool dispatchPower() {
        PowerAction action=power_.poll();bool activity=power_.takeActivity();
        if((maintenance_.active()||(standby()&&suspendArmed_))&&(activity||!power_.available())) {
            if(action==LongPowerPress)longPowerPress();else shortPowerPress();
            power_.resetAfterResume();return true;
        }
        if(action==NoPowerAction)return false;
        logRecord("POWER_ACTION",action==LongPowerPress?"\"long\":true":"\"long\":false");
        if(action==LongPowerPress)longPowerPress();else shortPowerPress();return true;
    }
    void dispatchListNavigation() {
        // Consume side-key input even while locked, never replay it on wake.
        for(int i=0;i<16;++i){
            int direction=power_.takeListNavigation();if(!direction)break;
            if(!standby()&&!shuttingDown())listNavigate(direction);
        }
    }
    void standbyMaintenanceTick() {
        if(!maintenance_.active()||!standby()||shuttingDown())return;
        if(sync_.waitingForPaint())refreshStandbySnapshot();
        bool pipeline=http_.busy()||!sync_.request().path.isEmpty()||sync_.waitingForPaint();
        bool terminal=!syncTimer_||(!sync_.error().isEmpty()&&nextPoll_-syncClock_.elapsed()>=300000);
        if(!maintenance_.finish(tlsBootMs(),pipeline,terminal))return;
        http_.cancel();
        if(pipeline||!sync_.error().isEmpty()){sync_.failed("standby-maintenance-timeout");setSyncFailed(true);}
        maintenance_.cancel();setSyncActivity(false);refreshStandbySnapshot();
        suspendArmed_=true;suspendAt_=powerClock_.elapsed()+750;
        logRecord("STANDBY_MAINTENANCE","\"finished\":true");
    }
    void timerEvent(QTimerEvent *event) {
        http_.reapCancelledResolver();
        if(event->timerId()==powerTimer_){
            if(suspendPending_){
                observeSuspendedPower();
                SuspendReply reply=readSuspendReply("/run/pandanote-normal",suspendGeneration_,suspendToken_);
                if(reply==NoSuspendReply){
                    if(powerClock_.elapsed()-suspendPendingAt_>=15000 && cancelSuspendRequest("/run/pandanote-normal","/user/pandanote/state",suspendGeneration_,suspendToken_)){
                        resumeSuspend(SuspendRejected);
                        logRecord("SYSTEM_SUSPEND_CANCELLED","\"safe\":true");
                    }
                    return;
                }
                resumeSuspend(reply);return;
            }
            if(!power_.available()&&powerClock_.elapsed()>=nextPowerOpen_){power_.open();nextPowerOpen_=powerClock_.elapsed()+2000;}
            bool powerAction=dispatchPower();
            dispatchListNavigation();
            if(powerAction)return;
            standbyMaintenanceTick();
            if(suspendArmed_&&standby()&&!shuttingDown()&&powerClock_.elapsed()>=suspendAt_){
                if(!http_.reapCancelledResolver())return;
                suspendArmed_=false;
                if(!readSuspendGeneration("/run/pandanote-normal",suspendGeneration_)){systemStandbyCompleted(false);return;}
                if(suspendCounter_==UINT_MAX){systemStandbyCompleted(false);return;}
                snprintf(suspendToken_,sizeof(suspendToken_),"%ld-%u",long(::getpid()),++suspendCounter_);
                pendingWakeActivity_=false;pendingWakeAction_=NoPowerAction;power_.takeActivity();
                suspendPendingAt_=powerClock_.elapsed();suspendPending_=publishSuspendRequest("/run/pandanote-normal",suspendGeneration_,suspendToken_);
                logRecord("SYSTEM_SUSPEND_REQUEST",QByteArray("\"published\":")+(suspendPending_?"true":"false"));
                if(!suspendPending_)systemStandbyCompleted(false);
            }
            return;
        }
        if(event->timerId()==syncTimer_){if((!standby()||maintenance_.active())&&!shuttingDown())syncTick();}
        else if(event->timerId()==refreshTimer_){if(!standby()&&!shuttingDown())refreshTime();}
        else if(timeoutTimer_ && event->timerId()==timeoutTimer_) {
            killTimer(timeoutTimer_);timeoutTimer_=0;loggedExit_=true;logExit("developer_timeout",0);QCoreApplication::exit(0);
        } else ReaderShell::timerEvent(event);
    }
    void standbyChanged(bool sleeping){maintenance_.cancel();suspendArmed_=sleeping&&!shuttingDown();if(sleeping){http_.cancel();suspendAt_=powerClock_.elapsed()+750;}else{startupRetry_=StartupSyncRetry();nextPoll_=0;}}
    bool shutdownRequested(){
        QByteArray marker;if(!powerTimer_||!readSyncFile("/run/pandanote-normal/power.ready",64,true,&marker)||marker!="power-keys-v1\n")return false;
        return publishPowerOffRequest("/run/pandanote-normal");
    }
    void closeEvent(QCloseEvent *event) { event->ignore(); }
    void keyPressEvent(QKeyEvent *event) { event->ignore(); }
private:
    QString systemClockStatus_;Content current_;int refreshTimer_,timeoutTimer_;bool loggedExit_;int powerTimer_;qint64 nextPowerOpen_;PowerKeys power_;bool suspendArmed_,suspendPending_,pendingWakeActivity_;PowerAction pendingWakeAction_;StandbyMaintenance maintenance_;qint64 suspendAt_,suspendPendingAt_;unsigned suspendCounter_;char suspendGeneration_[49],suspendToken_[49];QElapsedTimer powerClock_;
    StartupSyncRetry startupRetry_;DeviceSync sync_;DeviceHttp http_;DeviceEndpoint endpoint_,profile_;QByteArray token_;QElapsedTimer syncClock_;int syncTimer_;qint64 nextPoll_,lastContact_;
};
int main(int argc,char **argv) {
    if(argc==3&&!strcmp(argv[1],"--resolve-host"))return runDnsWorker(argv[2]);
    bool developer=false,qwsServer=false,powerKeys=false;int timeout=0;qint64 simulated=0;QString syncCache="/tmp/pandanote-reader-cache",bluetoothIpc,workspace,directory,syncConfiguration="/tmp/pandanote-reader-sync.ini";bool invalid=false;
    // Parse before QApplication so unknown options cannot silently affect production.
    for(int i=1;i<argc;++i) {
        QString arg=QString::fromLocal8Bit(argv[i]);
        if(arg=="--developer-mode")developer=true;
        else if(arg=="--qws-server")qwsServer=true;
        else if(arg=="--power-keys")powerKeys=true;
        else if(arg=="--sync-config" && i+1<argc)syncConfiguration=QString::fromLocal8Bit(argv[++i]);
        else if(arg=="--sync-cache-dir" && i+1<argc){syncCache=QString::fromLocal8Bit(argv[++i]);if(!validSyncPath(syncCache))invalid=true;}
        else if(arg=="--bluetooth-ipc" && i+1<argc){bluetoothIpc=QString::fromLocal8Bit(argv[++i]);if(!bluetoothIpc.startsWith("/")||bluetoothIpc=="/"||bluetoothIpc.toUtf8().size()>107)invalid=true;}
        else if(arg=="--workspace-dir" && i+1<argc){workspace=QString::fromLocal8Bit(argv[++i]);if(!workspace.startsWith("/")||workspace=="/"||workspace.size()>4096)invalid=true;}
        else if(arg=="--content-dir" && i+1<argc)directory=QString::fromLocal8Bit(argv[++i]);
        else if(arg=="--developer-timeout-ms" && i+1<argc) { bool ok=false;timeout=QString::fromLocal8Bit(argv[++i]).toInt(&ok);if(!ok || timeout<100 || timeout>300000)invalid=true; }
        else if(arg=="--developer-simulated-epoch" && i+1<argc) { bool ok=false;simulated=QString::fromLocal8Bit(argv[++i]).toLongLong(&ok);if(!ok || simulated<=0)invalid=true; }
        else invalid=true;
    }
    if(invalid || (developer && !timeout) || (!developer && (timeout || simulated))) { logExit("invalid_arguments",2);return 2; }
    if(!syncCacheDirectory(syncCache)){logExit("sync_cache_unavailable",4);return 4;}
    // Server role is explicit for guarded standalone environments without QWS.
    QApplication app(argc,argv,qwsServer?QApplication::GuiServer:QApplication::GuiClient);
    app.setQuitOnLastWindowClosed(false);
    RuntimeShell shell(syncCache);
    if(powerKeys&&!shell.configurePowerKeys()){logExit("power_keys_unavailable",4);return 4;}
    if(!bluetoothIpc.isEmpty())shell.configureBluetooth(bluetoothIpc);
    if(!workspace.isEmpty()&&!shell.configureWorkspace(workspace)){logExit("workspace_unavailable",4);return 4;}
    if(directory.isEmpty())directory=QCoreApplication::applicationDirPath()+"/data/current";
    if(!shell.loadCached())shell.loadDirectory(directory);
    shell.loadSyncConfiguration(syncConfiguration);
    if(!shell.fontReady()) { logExit("font_unavailable",3);return 3; }
    if(simulated) {
        logRecord("DEVELOPMENT",QByteArray("\"time_source\":\"SIMULATED\",\"epoch\":")+QByteArray::number(simulated));
        if(!shell.setTrustedTime(simulated)) { logExit("invalid_simulated_time",2);return 2; }
    }
    if(developer)shell.developerTimeout(timeout);
    shell.showFullScreen();int code=app.exec();shell.recordExit(code);return code;
}
