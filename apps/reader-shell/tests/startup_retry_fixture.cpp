// Test boundary only. main.cpp's complete syncTick method is inserted verbatim.
#include <string>
#include <vector>
#include <stdio.h>
#include <errno.h>
#include <string.h>
typedef long long qint64;
class QString {
 std::string s;
public:
 QString(const char *v=""):s(v){} QString(const char *v,int n):s(v,n){} explicit QString(const std::string &v):s(v){}
 static QString fromUtf8(const char *v){return QString(v);}
 static QString number(qint64 v){char b[32];snprintf(b,sizeof b,"%lld",v);return QString(b);}
 bool operator==(const char *v)const{return s==v;}
 QString toLatin1()const{return *this;} void fill(char value){s.assign(s.size(),value);} void clear(){s.clear();} int size()const{return int(s.size());} bool isEmpty()const{return s.empty();} const char *constData()const{return s.c_str();}
 QString operator+(const QString &v)const{return QString(s+v.s);}
 QString &operator+=(const QString &v){s+=v.s;return *this;}
};
QString operator+(const char *a,const QString &b){return QString(a)+b;}
typedef QString QByteArray;
static QByteArray quoted(const char *v){return QByteArray(v);}
static std::vector<std::string> transportLogs;
static void logRecord(const char *event,const QByteArray &fields){if(!strcmp(event,"SYNC_TRANSPORT"))transportLogs.push_back(fields.constData());}
struct Content{};
struct SyncRequest {QString path;};
struct Clock {qint64 now;Clock():now(0){}qint64 elapsed()const{return now;}};
struct Sync {
 QString failure;SyncRequest pending;QString afterReceivePath;bool afterReceiveWaitForPaint,pendingPaint;qint64 epoch;int refreshes;
 Sync():afterReceiveWaitForPaint(false),pendingPaint(false),epoch(0),refreshes(0){}
 void failed(const QString &v){failure=v;pending=SyncRequest();}
 bool receive(int status,const QByteArray &){pending=SyncRequest();if(status==200){pending.path=afterReceivePath;pendingPaint=afterReceiveWaitForPaint;}afterReceivePath.clear();afterReceiveWaitForPaint=false;epoch=status==200?1792458000:0;failure=status==200?"":"http-status-or-size";return status==200;}
 qint64 freshEpoch()const{return epoch;} int pollSeconds()const{return 300;}
 bool takeUpdate(Content *){return false;} QString error()const{return failure;}
 QString lastDisplayed()const{return QString();}SyncRequest request()const{return pending;}
 bool waitingForPaint()const{return pendingPaint;}
 void painted(const QString &){if(pendingPaint){pendingPaint=false;pending.path="/reader/v1/ack";}}
 void refresh(){if(!pending.path.isEmpty()||pendingPaint)return;++refreshes;epoch=0;pending.path="/reader/v1/manifest";}
};
struct Http {
 bool running,failStart;int result,status;QString error;std::vector<qint64> starts;Clock *clock;
 Http():running(false),failStart(false),result(0),status(0),clock(0){}
 int poll(int *s,QByteArray *,QString *e){int r=result;result=0;if(r){running=false;*s=status;*e=error;}return r;}
 void cancel(){running=false;}
 bool busy()const{return running;}
 template<class Endpoint>bool start(const Endpoint &,int,const SyncRequest &,QString *e){starts.push_back(clock->now);if(failStart){*e=error;return false;}running=true;return true;}
};
// Compile the actual production DeviceHttp::poll too. The syscall/TLS boundary
// is simulated; fake getsockopt/send/recv definitions cannot open any socket.
typedef unsigned socklen_t;
struct pollfd{int fd;short events,revents;};static const int POLLOUT=4;
int poll(struct pollfd *,unsigned long,int){return 1;}
struct DnsBoundary {bool running,deferExit,exited;DnsBoundary():running(false),deferExit(false),exited(false){}bool busy()const{return running;}int poll(char [4][16],unsigned *){if(exited)running=false;return running?0:-1;}void cancel(){if(!deferExit)running=false;}};
struct EndpointBoundary {QString host,certificatePem,certificateSha256;qint64 bootstrapEpoch;EndpointBoundary():bootstrapEpoch(1792458000){}};
static bool validDnsHost(const char *){return false;}static bool validTlsEpoch(qint64 e){return e>=946684800&&e<=2147483646;}
static qint64 tlsBootMs(){return 0;}static qint64 tlsAdvanceEpoch(qint64,qint64,qint64){return 1792458000;}
static int httpTlsSend(void *,unsigned char *,int){return -1;}static int httpTlsRecv(void *,unsigned char *,int){return -1;}

static const int SOL_SOCKET=1,SO_ERROR=4,MSG_NOSIGNAL=0;
int getsockopt(int,int,int,void *value,socklen_t *){*static_cast<int *>(value)=0;return 0;}
int send(int,const void *,unsigned long,int){return -1;}
int recv(int,void *,unsigned long,int){return -1;}
int close(int){return 0;}
static bool fail(QString *error,const char *value){*error=value;return false;}
struct TlsBoundary {void reset(){}bool configure(const QString &,const QString &,const QString &,qint64,void *,int(*)(void *,unsigned char *,int),int(*)(void *,unsigned char *,int),QString *){return true;}int handshake(QString *){return 1;}int write(const unsigned char *,int){return -2;}int read(unsigned char *,int){return -2;}};
struct HttpReplyBoundary {bool feed(const QByteArray &,int,QString *){return false;}bool complete()const{return false;}int status()const{return 0;}QByteArray body()const{return QByteArray();}};
class DeviceHttp {
public:
 int fd_,phase_,sent_,limit_;bool useTls_,resolving_;qint64 trustedEpoch_,trustedAtMs_;DnsBoundary resolver_;EndpointBoundary activeEndpoint_;char addresses_[4][16];unsigned nextAddress_,addressCount_;
 bool connectAddress(const char *,QString *){return false;}int pollResolver(QString *){return 0;}TlsBoundary tls_;QString outgoing_;Clock clock_;HttpReplyBoundary reply_;
 DeviceHttp(int phase):fd_(1),phase_(phase),sent_(0),limit_(65536),useTls_(true),resolving_(false),trustedEpoch_(0),trustedAtMs_(0),nextAddress_(0),addressCount_(0),outgoing_("synthetic"){}
 /* ACTUAL HTTP CANCEL */
 int poll(int *,QByteArray *,QString *);
};
/* ACTUAL DEVICE HTTP POLL */
struct SystemClockResult {enum Status{Skipped,Applied,InvalidEpoch};Status status;int errorNumber;SystemClockResult():status(Skipped),errorNumber(0){}};
template<class A,class B>static SystemClockResult applyAuthenticatedTime(bool,qint64,A &,B &){return SystemClockResult();}
struct RuntimeEndpoint{bool tls;RuntimeEndpoint():tls(true){}};
class RuntimeShell {
public:
 Sync sync_;Http http_;Clock syncClock_;qint64 nextPoll_,lastContact_;QString systemClockStatus_;Content current_;RuntimeEndpoint endpoint_;int token_,syncTimer_;bool syncActive_;std::vector<bool> activityCalls;
 bool suspendArmed_;qint64 suspendAt_;Clock powerClock_;
 bool shuttingDown()const{return false;}
 /* ACTUAL STANDBY CHANGED */
 /* POLICY MEMBER */
 RuntimeShell():nextPoll_(0),lastContact_(0),token_(0),syncTimer_(1),syncActive_(false),suspendArmed_(false),suspendAt_(0){http_.clock=&syncClock_;}
 void setContent(const Content &){}void setSyncFailed(bool){}void setConnectionStatus(const QString &){}
 void setSyncActivity(bool active){syncActive_=active;activityCalls.push_back(active);}
 /* ACTUAL SYNC REQUESTED */
 void at(qint64 ms){syncClock_.now=ms;syncTick();}
 void fail(const char *code,qint64 ms){http_.error=code;http_.result=-1;at(ms);}
 /* ACTUAL PRODUCTION METHOD */
};
static int checks=0,failures=0;
#define CHECK(n,c) do{++checks;if(!(c)){++failures;fprintf(stderr,"FAIL %s line %d\n",n,__LINE__);}}while(0)
int main(){
 {RuntimeShell r;r.at(0);r.http_.status=404;r.http_.result=1;r.at(1);CHECK("404 logging proves transport not sync success",!transportLogs.empty()&&transportLogs.back()=="\"tls\":true,\"manifest\":true,\"transport_ok\":true,\"http_status\":404");CHECK("404 is still sync failure",!r.sync_.failure.isEmpty());}
 {RuntimeShell r;r.at(0);r.http_.status=401;r.http_.result=1;r.at(1);CHECK("401 stays visible without credentials in diagnostic",!transportLogs.empty()&&transportLogs.back()=="\"tls\":true,\"manifest\":true,\"transport_ok\":true,\"http_status\":401");}
 {RuntimeShell r;r.at(0);r.http_.status=404;r.fail("http-connect",1);CHECK("failed transport never logs stale HTTP status",!transportLogs.empty()&&transportLogs.back()=="\"tls\":true,\"manifest\":true,\"transport_ok\":false,\"http_status\":0");}

 {DeviceHttp h(0);h.fd_=-1;h.resolving_=true;h.resolver_.running=true;h.resolver_.deferExit=true;h.cancel();CHECK("cancel retains unreaped resolver",h.resolver_.busy()&&!h.resolving_);CHECK("standby maintenance never blocks on pending resolver",!h.reapCancelledResolver());h.resolver_.exited=true;CHECK("standby maintenance reaps exited resolver with sync paused",h.reapCancelledResolver()&&!h.resolver_.busy());}

 {DeviceHttp h(0);h.fd_=-1;h.resolving_=true;h.resolver_.running=true;h.clock_.now=14999;int status=0;QByteArray body;QString error;CHECK("DNS is inside total deadline",h.poll(&status,&body,&error)==0&&h.resolving_);h.clock_.now=15001;CHECK("DNS deadline cancels worker",h.poll(&status,&body,&error)==-1&&!h.resolving_&&!h.resolver_.busy());}

 {RuntimeShell r;r.syncTimer_=0;r.setSyncActivity(true);r.syncRequested();CHECK("unconfigured manual request clears pending activity",!r.syncActive_);CHECK("unconfigured request starts no transport",r.http_.starts.empty());}
 {RuntimeShell r;r.nextPoll_=300000;r.syncRequested();CHECK("configured manual request shows activity before timer",r.syncActive_);CHECK("manual request does not synchronously start transport",r.http_.starts.empty());r.at(0);CHECK("manual request keeps activity when transport starts",r.syncActive_);r.at(50);CHECK("activity persists while transport polls",r.syncActive_);r.http_.status=200;r.http_.result=1;r.at(100);CHECK("completed pipeline clears activity",!r.syncActive_);}
 {
  RuntimeShell r;r.at(0);CHECK("automatic sync shows activity",r.syncActive_);r.activityCalls.clear();
  const char *paths[]={"/resource/content.ini","/resource/background.png","/resource/SHA256SUMS"};
  for(unsigned i=0;i<sizeof(paths)/sizeof(paths[0]);++i){
   r.sync_.afterReceivePath=paths[i];r.http_.status=200;r.http_.result=1;r.at(i+1);
   CHECK("chained resource keeps activity",r.syncActive_);CHECK("chained request starts immediately",r.http_.starts.size()==i+2);
  }
  r.sync_.afterReceiveWaitForPaint=true;r.http_.status=200;r.http_.result=1;r.at(10);
  CHECK("commit waits for paint with no HTTP or queued request",!r.http_.busy()&&r.sync_.request().path.isEmpty());
  CHECK("committed content keeps activity before asynchronous paint",r.syncActive_);
  r.at(20);CHECK("delayed paint keeps activity across timer ticks",r.syncActive_);
  CHECK("waiting paint never starts another manifest",r.http_.starts.size()==4);
  r.contentPainted("fixture-version");CHECK("paint queues ACK after transport gap",!r.sync_.request().path.isEmpty());
  r.at(30);CHECK("paint ACK starts with uninterrupted activity",r.syncActive_&&r.http_.starts.size()==5);
  for(unsigned i=0;i<r.activityCalls.size();++i)CHECK("no false activity through resources paint and ACK",r.activityCalls[i]);
  r.http_.status=200;r.http_.result=1;r.at(40);CHECK("ACK completion clears activity",!r.syncActive_);
 }

 {RuntimeShell r;r.nextPoll_=300000;r.sync_.pending.path="/reader/v1/ack";r.at(1);CHECK("paint queued ACK resumes activity",r.syncActive_);CHECK("paint queued ACK starts without waiting poll",r.http_.starts.size()==1);r.fail("http-connect",2);CHECK("transport failure clears activity",!r.syncActive_);r.at(2001);CHECK("retry wait stays idle",!r.syncActive_);r.at(2002);CHECK("retry starts activity again",r.syncActive_);}
 {RuntimeShell r;r.http_.failStart=true;r.http_.error="tls-profile";r.syncRequested();r.at(0);CHECK("immediate start failure clears manual activity",!r.syncActive_);}
 {RuntimeShell r;r.at(0);r.http_.status=401;r.http_.result=1;r.at(1);CHECK("protocol failure clears activity",!r.syncActive_);}

 {RuntimeShell r;r.at(0);CHECK("first request starts once",r.http_.starts.size()==1);r.fail("http-connect",10);r.at(2009);CHECK("not before deadline",r.http_.starts.size()==1);r.at(2010);CHECK("DHCP recovery retried at 2 seconds",r.http_.starts.size()==2);r.at(5000);CHECK("no concurrent request",r.http_.starts.size()==2);}
 {RuntimeShell r;r.http_.failStart=true;r.http_.error="http-connect";r.at(0);r.at(1999);CHECK("immediate start error waits deadline",r.http_.starts.size()==1);r.at(2000);CHECK("immediate connect error also retries",r.http_.starts.size()==2);r.at(7000);r.at(17000);r.at(37000);r.at(67000);r.at(89999);CHECK("bounded five fast retries",r.http_.starts.size()==6);r.at(90000);CHECK("no burst at window end",r.http_.starts.size()==6);r.at(367000);CHECK("exhaustion returns normal polling",r.http_.starts.size()==7);}
 {RuntimeShell r;r.at(0);r.fail("http-connect",100);r.at(88000);CHECK("late timer starts only one request",r.http_.starts.size()==2);r.fail("http-connect",88000);r.at(93000);CHECK("retry cannot escape 90 second startup window",r.http_.starts.size()==2);}
 {const char *errors[]={"tls-peer-verification","tls-certificate-pin","tls-profile","tls-setup","tls-unconfigured","tls-peer-missing","tls-pin-hash","tls-ip-san","http-status-or-size","manifest-json","http-config","http-connect-extra"};for(unsigned i=0;i<sizeof(errors)/sizeof(errors[0]);++i){RuntimeShell r;r.at(0);r.fail(errors[i],1);r.at(89999);CHECK("security/protocol errors preserve normal delay",r.http_.starts.size()==1);}}
 {RuntimeShell r;r.at(0);r.http_.status=200;r.http_.result=1;r.at(1);r.nextPoll_=2;r.at(2);CHECK("explicit post-auth refresh starts",r.http_.starts.size()==2);CHECK("new request clears fresh epoch",r.sync_.freshEpoch()==0);r.fail("http-connect",3);r.at(2003);CHECK("manifest contact permanently disables startup retry",r.http_.starts.size()==2);}
 {const int codes[]={401,403,429,500};for(unsigned i=0;i<sizeof(codes)/sizeof(codes[0]);++i){RuntimeShell r;r.at(0);r.http_.status=codes[i];r.http_.result=1;r.at(1);r.at(2001);CHECK("HTTP status errors never fast retry",r.http_.starts.size()==1);}}
 {const char *errors[]={"http-socket","http-connect","http-timeout"};for(unsigned i=0;i<sizeof(errors)/sizeof(errors[0]);++i){RuntimeShell r;r.at(0);r.fail(errors[i],1);r.at(2001);CHECK("explicit transport code fast retry",r.http_.starts.size()==2);}}
 {RuntimeShell r;r.at(0);r.fail("http-connect",10);r.at(100000);CHECK("late fast deadline waits original normal interval",r.http_.starts.size()==1);r.at(300009);CHECK("normal interval anchored to last failure",r.http_.starts.size()==1);r.at(300010);CHECK("original normal deadline starts one request",r.http_.starts.size()==2);r.at(300010);CHECK("normal recovery has no duplicate request",r.http_.starts.size()==2);}
 {RuntimeShell r;r.at(0);r.fail("http-connect",10);r.at(400000);CHECK("late timer past ordinary deadline starts one normal request",r.http_.starts.size()==2);r.at(400000);CHECK("very late ordinary request does not overlap",r.http_.starts.size()==2);}
 {RuntimeShell r;r.at(0);r.fail("http-connect",10);r.nextPoll_=0;r.at(100000);CHECK("explicit manual refresh is not blocked by stale fast deadline",r.http_.starts.size()==2);}
 {for(int phase=0;phase<2;++phase){DeviceHttp productionHttp(phase);int status=0;QByteArray body;QString error;CHECK("real DeviceHttp propagates fatal TLS record error",productionHttp.poll(&status,&body,&error)==-1);CHECK("real DeviceHttp closes failed transport",productionHttp.fd_==-1);RuntimeShell r;r.at(0);r.fail(error.constData(),10);r.at(2010);CHECK("real fatal TLS mapping cannot start fast retry",r.http_.starts.size()==1);}}
 // DeviceTls fatal record/protocol -2 is mapped to these labels by DeviceHttp.
 // They must not be interpreted as connection-unavailable errors.
 {const char *errors[]={"http-send","http-truncated"};for(unsigned i=0;i<sizeof(errors)/sizeof(errors[0]);++i){RuntimeShell r;r.at(0);r.fail(errors[i],10);r.at(2010);CHECK("collapsed TLS fatal error retains ordinary delay",r.http_.starts.size()==1);r.at(300010);CHECK("collapsed TLS fatal error ordinary deadline unchanged",r.http_.starts.size()==2);}}
 {RuntimeShell r;r.http_.failStart=true;r.http_.error="tls-profile";r.at(0);r.at(2000);CHECK("immediate TLS profile failure retains normal delay",r.http_.starts.size()==1);r.at(300000);CHECK("immediate TLS profile failure normal deadline unchanged",r.http_.starts.size()==2);}
 // A successful pre-suspend contact must not suppress the next Wi-Fi grace
 // period: service association_requested can precede actual connectivity.
 {RuntimeShell r;r.at(0);r.http_.status=200;r.http_.result=1;r.at(1);r.syncClock_.now=1000000;r.standbyChanged(true);r.standbyChanged(false);CHECK("wake immediately queues sync",r.nextPoll_==0);r.at(1000000);r.fail("http-connect",1000010);r.at(1002009);CHECK("wake waits full two second retry delay",r.http_.starts.size()==2);r.at(1002010);CHECK("prior authentication does not block wake connect retry",r.http_.starts.size()==3);}
 {const char *errors[]={"tls-peer-verification","tls-certificate-pin","tls-pin-hash","tls-profile","http-send","http-truncated"};for(unsigned i=0;i<sizeof(errors)/sizeof(errors[0]);++i){RuntimeShell r;r.at(0);r.http_.status=200;r.http_.result=1;r.at(1);r.standbyChanged(true);r.standbyChanged(false);r.at(1000000);r.fail(errors[i],1000010);r.at(1002010);CHECK("wake security/TLS error never fast retries",r.http_.starts.size()==2);r.at(1300010);CHECK("wake security/TLS error keeps ordinary deadline",r.http_.starts.size()==3);}}
 {RuntimeShell r;r.at(0);r.http_.status=200;r.http_.result=1;r.at(1);r.standbyChanged(true);r.standbyChanged(false);r.http_.failStart=true;r.http_.error="http-connect";r.at(1000000);r.at(1002000);r.at(1007000);r.at(1017000);r.at(1037000);r.at(1067000);CHECK("wake grants at most five fast retries",r.http_.starts.size()==7);r.at(1090000);CHECK("wake retry exhaustion does not burst at 90 seconds",r.http_.starts.size()==7);r.at(1367000);CHECK("wake exhaustion restores ordinary polling",r.http_.starts.size()==8);}
 {RuntimeShell r;r.at(0);r.http_.status=200;r.http_.result=1;r.at(1);r.standbyChanged(true);r.standbyChanged(false);r.at(1000000);r.fail("http-connect",1000100);r.at(1088000);CHECK("wake late timer starts one retry",r.http_.starts.size()==3);r.fail("http-connect",1088000);r.at(1093000);CHECK("wake retry cannot escape its 90 second window",r.http_.starts.size()==3);}
 {RuntimeShell r;r.at(0);r.http_.status=200;r.http_.result=1;r.at(1);r.standbyChanged(true);r.standbyChanged(false);r.at(1000000);r.http_.status=200;r.http_.result=1;r.at(1000001);r.nextPoll_=1000002;r.at(1000002);r.fail("http-connect",1000003);r.at(1002003);CHECK("reauthentication ends wake fast retry period",r.http_.starts.size()==3);}
 {StartupSyncRetry policy;CHECK("no retry before first attempt",policy.delayAfterResult(0,"http-connect",300000,false)==300000);policy.beginAttempt(10000);CHECK("backward clock cannot fast retry",policy.delayAfterResult(9999,"http-connect",300000,false)==300000);CHECK("retry may meet exact window boundary",policy.delayAfterResult(98000,"http-connect",300000,false)==2000);CHECK("expired window cannot fast retry",policy.delayAfterResult(100000,"http-connect",300000,false)==300000);}
 printf("%s startup scheduling: %d checks, monotonic time and transport SIMULATED\n",failures?"FAIL":"PASS",checks);return failures?1:0;
}
