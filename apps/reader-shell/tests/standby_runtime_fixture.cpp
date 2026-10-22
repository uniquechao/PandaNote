#include "standbypolicy.h"
#include "startupretry.h"
#include "powerkeys.h"
#include "powerrequest.h"
#include <stdio.h>
#include <string>
#include <deque>
typedef int64_t qint64;
static qint64 bootNow=1000;
static bool readyAvailable=true;static int step=0,readyStep=0,pollStep=0;
qint64 tlsBootMs(){return bootNow;}
void logRecord(const char *,const char *){}
struct Clock{qint64 now;Clock():now(1000){}qint64 elapsed()const{return now;}};
struct Text{std::string value;Text(const char*s=""):value(s){}bool isEmpty()const{return value.empty();}};
struct Request{Text path;};
struct Transport{bool running;int cancelled;Transport():running(false),cancelled(0){}bool busy()const{return running;}void cancel(){running=false;++cancelled;}};
struct Pipeline{bool pending;Text failure;Request queued;int failedCalls;Pipeline():pending(false),failedCalls(0){}bool waitingForPaint()const{return pending;}Text error()const{return failure;}Request request()const{return queued;}void failed(const char*s){failure=Text(s);queued=Request();++failedCalls;}};
struct Keys{std::deque<int> navigation;int takeListNavigation(){if(navigation.empty())return 0;int n=navigation.front();navigation.pop_front();return n;}bool activity,available_,resetOk,resetActivity;PowerAction next;int resets;Keys():activity(false),available_(true),resetOk(true),resetActivity(false),next(NoPowerAction),resets(0){}PowerAction poll(){pollStep=++step;PowerAction a=next;next=NoPowerAction;return a;}bool takeActivity(){bool a=activity;activity=false;return a;}bool available()const{return available_;}bool resetAfterResume(){++resets;activity=resetActivity;return resetOk;}};
static int wakeIntents=0,inputAllows=0;
bool suspendInputReady(const char*,const char*,const char*){readyStep=++step;return readyAvailable;}
bool publishSuspendWakeIntent(const char*,const char*,const char*){++wakeIntents;return true;}
bool acknowledgeSuspendInput(const char*,const char*,const char*){++inputAllows;return true;}
class RuntimeShell {
public:
 bool asleep,shutdown,suspendPending_,suspendArmed_,pendingWakeActivity_,failedUi,paintCompletes;PowerAction pendingWakeAction_;
 char suspendGeneration_[49],suspendToken_[49];
 Keys power_;StandbyMaintenance maintenance_;StartupSyncRetry startupRetry_;Transport http_;Pipeline sync_;Clock syncClock_,powerClock_;qint64 nextPoll_,suspendAt_;int syncTimer_,snapshots,home,off,listCalls,lastDirection;bool resumeOk;
 RuntimeShell():asleep(true),shutdown(false),suspendPending_(true),suspendArmed_(false),pendingWakeActivity_(false),failedUi(false),paintCompletes(true),pendingWakeAction_(NoPowerAction),nextPoll_(300000),suspendAt_(0),syncTimer_(1),snapshots(0),home(0),off(0),listCalls(0),lastDirection(0),resumeOk(false){}
 bool listNavigate(int direction){++listCalls;lastDirection=direction;return true;}
 bool standby()const{return asleep;}bool shuttingDown()const{return shutdown;}
 void systemStandbyCompleted(bool ok){resumeOk=ok;asleep=false;++home;maintenance_.cancel();}
 void shortPowerPress(){asleep=!asleep;++home;maintenance_.cancel();}
 void longPowerPress(){asleep=false;shutdown=true;++off;maintenance_.cancel();}
 void refreshStandbySnapshot(){++snapshots;if(paintCompletes&&sync_.pending){sync_.pending=false;sync_.queued.path=Text("ack");}}
 void setSyncActivity(bool){}void setSyncFailed(bool value){failedUi=value;}
 /* ACTUAL METHODS */
};
static int checks=0,failures=0;
#define CHECK(n,c) do{++checks;if(!(c)){++failures;fprintf(stderr,"FAIL %s line %d\n",n,__LINE__);}}while(0)
int main(){
 {RuntimeShell r;r.resumeSuspend(SuspendTimerResumed);CHECK("timer_stays_locked",r.asleep&&r.home==0&&r.maintenance_.active());CHECK("timer_starts_fresh_bounded_sync",r.nextPoll_==0&&r.snapshots==1&&!r.suspendArmed_);}
 {RuntimeShell r;r.power_.activity=true;r.observeSuspendedPower();r.resumeSuspend(SuspendTimerResumed);CHECK("down_edge_wins_before_release",!r.asleep&&r.home==1&&!r.maintenance_.active());}
 {RuntimeShell r;r.power_.next=LongPowerPress;r.power_.activity=true;r.observeSuspendedPower();r.resumeSuspend(SuspendTimerResumed);CHECK("pending_long_press_shuts_down",r.off==1&&!r.maintenance_.active());}
 {RuntimeShell r;r.power_.resetOk=false;r.resumeSuspend(SuspendTimerResumed);CHECK("untrusted_input_cannot_auto_sleep",r.home==1&&!r.resumeOk&&!r.maintenance_.active());}
 {RuntimeShell r;r.resumeSuspend(SuspendResumed);CHECK("manual_resume_home",r.home==1&&r.resumeOk&&!r.asleep);}
 {RuntimeShell r;r.resumeSuspend(SuspendRejected);CHECK("failed_resume_home_error",r.home==1&&!r.resumeOk&&!r.maintenance_.active());}
 {RuntimeShell r;r.resumeSuspend(SuspendTimerResumed);r.http_.running=true;bootNow=30999;r.standbyMaintenanceTick();CHECK("pending_pipeline_before_deadline_waits",r.maintenance_.active()&&!r.suspendArmed_);bootNow=31000;r.standbyMaintenanceTick();CHECK("hard_deadline_cancels_then_resuspends",!r.maintenance_.active()&&r.suspendArmed_&&!r.http_.running&&r.failedUi&&r.asleep);CHECK("paint_settle_guard_before_mem",r.suspendAt_==1750);}
 bootNow=1000;
 {RuntimeShell r;r.resumeSuspend(SuspendTimerResumed);r.maintenance_.authenticatedContact();r.sync_.failure=Text();r.sync_.pending=true;r.standbyMaintenanceTick();CHECK("paint_precedes_ack_wait",!r.sync_.pending&&!r.sync_.queued.path.isEmpty()&&r.maintenance_.active()&&!r.suspendArmed_);r.sync_.queued=Request();r.standbyMaintenanceTick();CHECK("ack_completion_rearms_sleep",r.suspendArmed_&&r.asleep&&!r.maintenance_.active()&&!r.failedUi);}
 {RuntimeShell r;r.resumeSuspend(SuspendTimerResumed);r.power_.activity=true;CHECK("maintenance_down_dispatches_home",r.dispatchPower()&&r.home==1&&!r.asleep&&!r.maintenance_.active());}
 {RuntimeShell r;r.resumeSuspend(SuspendTimerResumed);r.power_.available_=false;CHECK("lost_input_cannot_automatic_sleep",r.dispatchPower()&&r.home==1&&!r.maintenance_.active());}
 {RuntimeShell r;r.syncTimer_=0;r.resumeSuspend(SuspendTimerResumed);r.standbyMaintenanceTick();CHECK("unconfigured_sync_reuses_cache_and_sleeps",r.suspendArmed_&&!r.maintenance_.active());}
 {RuntimeShell r;r.power_.resetActivity=true;r.resumeSuspend(SuspendTimerResumed);CHECK("reset_drain_activity_wins_timer",r.home==1&&!r.asleep&&!r.maintenance_.active());}
 {RuntimeShell r;wakeIntents=inputAllows=0;r.observeSuspendedPower();CHECK("idle_input_ack_after_drain",inputAllows==1&&wakeIntents==0);r.power_.activity=true;r.observeSuspendedPower();CHECK("human_intent_skips_input_allow",inputAllows==1&&wakeIntents==1);r.observeSuspendedPower();CHECK("latched_intent_cannot_later_allow",inputAllows==1&&wakeIntents==2);}
 {RuntimeShell r;step=readyStep=pollStep=0;inputAllows=0;r.observeSuspendedPower();CHECK("ready_must_precede_evdev_drain",readyStep>0&&readyStep<pollStep&&inputAllows==1);readyAvailable=false;inputAllows=0;r.observeSuspendedPower();CHECK("new_ready_after_drain_cannot_allow",inputAllows==0);readyAvailable=true;}
 {RuntimeShell r;r.resumeSuspend(SuspendTimerResumed);r.power_.navigation.push_back(1);CHECK("side_key_does_not_interrupt_timer_maintenance",!r.dispatchPower());r.dispatchListNavigation();CHECK("maintenance_stays_locked_after_side_key",r.asleep&&r.home==0&&r.listCalls==0&&r.maintenance_.active()&&r.power_.navigation.empty());}
 {RuntimeShell r;r.asleep=false;r.power_.navigation.push_back(-1);r.dispatchListNavigation();CHECK("awake_list_previous",r.listCalls==1&&r.lastDirection==-1&&r.power_.navigation.empty());}
 {RuntimeShell r;r.asleep=false;r.power_.navigation.push_back(1);r.dispatchListNavigation();CHECK("awake_list_next",r.listCalls==1&&r.lastDirection==1);}
 {RuntimeShell r;r.power_.navigation.push_back(1);r.dispatchListNavigation();CHECK("standby_drops_page_without_wake",r.asleep&&r.home==0&&r.listCalls==0&&r.power_.navigation.empty());r.asleep=false;r.dispatchListNavigation();CHECK("no_stale_page_on_resume",r.listCalls==0);}
 {RuntimeShell r;r.asleep=false;r.shutdown=true;r.power_.navigation.push_back(-1);r.dispatchListNavigation();CHECK("shutdown_drops_page",r.listCalls==0&&r.power_.navigation.empty());}
 printf("%d checks, %d failures\n",checks,failures);return failures?1:0;
}
