// Host-only fixture: no device opens, ioctls, clocks or shutdown syscalls.
#include "../powerkeys.h"
#include <stdio.h>
#include <vector>
static int failures=0,checks=0;
#define CHECK(n,x) do{++checks;if(!(x)){++failures;fprintf(stderr,"FAIL %s line %d\n",n,__LINE__);}}while(0)
static std::vector<PowerKeyEvent> input;static unsigned cursor=0;static bool held=false,ready=true,readFailure=false,baselineFailure=false;static int64_t now=0;static int closed=0,scans=0,chosen=3,readResult=9999;static bool heldPrevious=false,heldNext=false;static bool requireDrained=false,againSeen=false;
int powerKeyOpenCandidate(int i,bool *out){++scans;if(!ready||i!=chosen)return -1;*out=held;return 42;}
int powerKeyReadEvents(int,PowerKeyEvent *out,unsigned capacity){if(readFailure){readFailure=false;return -1;}if(readResult!=9999)return readResult;if(cursor==input.size()){againSeen=true;return PowerReadAgain;}unsigned n=0;while(n<capacity&&cursor<input.size())out[n++]=input[cursor++];return int(n);}
bool powerKeyHeld(int,bool *out){if(baselineFailure||(requireDrained&&!againSeen))return false;*out=held;return true;}
bool powerKeySnapshotHeld(int fd,bool *out){return powerKeyHeld(fd,out);}
int powerKeyOpenCandidate(int i,PowerKeyHeldState*out){bool power=false;int fd=powerKeyOpenCandidate(i,&power);if(fd>=0){out->power=power;out->previous=heldPrevious;out->next=heldNext;}return fd;}
bool powerKeyHeld(int fd,PowerKeyHeldState*out){bool power=false;if(!powerKeyHeld(fd,&power))return false;out->power=power;out->previous=heldPrevious;out->next=heldNext;return true;}
bool powerKeySnapshotHeld(int fd,PowerKeyHeldState*out){bool power=false;if(!powerKeySnapshotHeld(fd,&power))return false;out->power=power;out->previous=heldPrevious;out->next=heldNext;return true;}
int64_t powerKeyNowMs(){return now;}void powerKeyClose(int){++closed;}
static void reset(){input.clear();cursor=0;held=false;ready=true;readFailure=false;baselineFailure=false;now=0;scans=0;chosen=3;readResult=9999;requireDrained=false;againSeen=false;}
static void event(int value,int64_t ms){PowerKeyEvent e={PowerInputKey,PowerKeyF11,value,ms};input.push_back(e);}
static void syn(int code,int64_t ms){PowerKeyEvent e={PowerInputSyn,code,0,ms};input.push_back(e);}
int main(){
 PowerKeyPolicy p;
 p.baseline(false);CHECK("down_no_action",p.observe(1,100)==NoPowerAction);CHECK("2999_not_long",p.tick(3099)==NoPowerAction);CHECK("2999_release_short",p.observe(0,3099)==ShortPowerPress);
 p.baseline(false);p.observe(1,100);CHECK("3000_long",p.tick(3100)==LongPowerPress);CHECK("long_once",p.tick(9000)==NoPowerAction);CHECK("long_release_not_short",p.observe(0,9000)==NoPowerAction);
 p.baseline(false);p.observe(1,100);CHECK("queued_long_release",p.observe(0,3100)==LongPowerPress);
 p.baseline(true);CHECK("held_no_tick",p.tick(10000)==NoPowerAction);CHECK("held_duplicate",p.observe(1,10000)==NoPowerAction);CHECK("held_release_ignored",p.observe(0,11000)==NoPowerAction);p.observe(1,12000);CHECK("held_rearmed",p.observe(0,12001)==ShortPowerPress);
 p.baseline(false);p.observe(1,100);p.observe(1,1000);p.observe(2,2000);CHECK("duplicate_repeat_do_not_restart",p.tick(3100)==LongPowerPress);
 p.baseline(false);CHECK("orphan_up_ignored",p.observe(0,10)==NoPowerAction);p.observe(1,100);p.cancel();CHECK("cancel_no_long",p.tick(9999)==NoPowerAction);CHECK("cancel_release_ignored",p.observe(0,10000)==NoPowerAction);
 p.baseline(false);p.observe(1,1000);CHECK("backward_event_cancel",p.observe(0,900)==NoPowerAction);CHECK("backward_tick_cancel",p.tick(9999)==NoPowerAction);
 p.baseline(false);p.observe(1,1000);CHECK("backward_clock_cancel",p.tick(999)==NoPowerAction);CHECK("backward_clock_release_ignored",p.observe(0,2000)==NoPowerAction);
 reset();{PowerKeys k;CHECK("scan_open",k.open()&&k.available()&&scans==4);event(1,100);event(0,200);now=10000;CHECK("backlog_short_not_long",k.poll()==ShortPowerPress);CHECK("backlog_short_once",k.poll()==NoPowerAction);}
 reset();{PowerKeys k;k.open();event(1,100);event(0,3100);now=10000;CHECK("backlog_long",k.poll()==LongPowerPress);CHECK("backlog_long_once",k.poll()==NoPowerAction);}
 reset();held=true;{PowerKeys k;k.open();event(0,10);now=10000;CHECK("startup_held_ignored",k.poll()==NoPowerAction);event(1,10001);event(0,10002);now=10002;CHECK("startup_held_rearmed",k.poll()==ShortPowerPress);}
 reset();{PowerKeys k;k.open();event(1,100);syn(PowerSyncDropped,200);event(0,300);syn(PowerSyncReport,400);now=9000;CHECK("dropped_cancels",k.poll()==NoPowerAction);event(1,9001);event(0,9002);now=9002;CHECK("report_rebaselines",k.poll()==ShortPowerPress);}
 reset();{PowerKeys k;k.open();event(1,100);now=200;k.poll();readFailure=true;now=10000;CHECK("read_error_disconnects",k.poll()==NoPowerAction&&!k.available());held=true;CHECK("reconnect",k.open());event(0,10001);now=10001;CHECK("reconnect_held_ignored",k.poll()==NoPowerAction);}
 reset();{PowerKeys k;k.open();event(1,100);now=3099;CHECK("io_2999",k.poll()==NoPowerAction);now=3100;CHECK("io_3000",k.poll()==LongPowerPress);event(0,3101);now=3101;CHECK("io_longrelease",k.poll()==NoPowerAction);}
 reset();{PowerKeys k;k.open();event(1,10);event(0,20);event(1,30);event(0,40);now=5000;CHECK("queue_first",k.poll()==ShortPowerPress);CHECK("queue_second",k.poll()==ShortPowerPress);CHECK("queue_empty",k.poll()==NoPowerAction);}
 reset();{PowerKeys k;k.open();event(1,100);syn(PowerSyncDropped,200);syn(PowerSyncReport,300);baselineFailure=true;now=9000;CHECK("baseline_error_disconnects",k.poll()==NoPowerAction&&!k.available());}
 reset();ready=false;{PowerKeys k;CHECK("absent_scans_all",!k.open()&&!k.available()&&scans==16);CHECK("absent_no_action",k.poll()==NoPowerAction);}
 reset();{PowerKeys k;k.open();event(1,100);now=200;k.poll();now=-1;CHECK("clock_error_disconnects",k.poll()==NoPowerAction&&!k.available());}
 reset();{PowerKeys k;k.open();for(int i=0;i<17;++i){event(1,i*10);event(0,i*10+1);}now=10000;CHECK("queue_overflow_fails_closed",k.poll()==NoPowerAction&&!k.available());}
 reset();{PowerKeys k;k.open();event(1,100);event(0,200);syn(PowerSyncDropped,300);now=10000;CHECK("dropped_discards_prior_actions",k.poll()==NoPowerAction);CHECK("dropped_waits_for_report",k.poll()==NoPowerAction);held=true;syn(PowerSyncReport,10001);now=10001;CHECK("dropped_held_baseline",k.poll()==NoPowerAction);event(1,10002);event(0,10003);now=10003;CHECK("dropped_held_requires_release",k.poll()==NoPowerAction);event(1,10004);event(0,10005);now=10005;CHECK("dropped_held_rearmed",k.poll()==ShortPowerPress);}
 reset();{PowerKeys k;k.open();PowerKeyEvent other={PowerInputKey,116,1,100};input.push_back(other);other.value=0;other.milliseconds=200;input.push_back(other);now=10000;CHECK("key_power_not_accepted",k.poll()==NoPowerAction);}
 reset();{PowerKeys k;k.open();event(1,100);for(int i=0;i<100;++i)event(2,200+i);event(1,2000);now=3100;CHECK("io_duplicate_repeat_not_restart",k.poll()==LongPowerPress);}
 // Linux EVIOCGKEY snapshots current state and flushes unread EV_KEY. An
 // already-read batch tail must not recreate a down whose up was flushed.
 reset();{PowerKeys k;k.open();syn(PowerSyncDropped,100);syn(PowerSyncReport,200);event(1,300);held=false;now=10000;CHECK("dropped_batch_tail_not_long",k.poll()==NoPowerAction&&k.available());CHECK("dropped_batch_tail_no_delayed_long",k.poll()==NoPowerAction);event(1,10001);event(0,10002);now=10002;CHECK("dropped_batch_tail_fresh_press",k.poll()==ShortPowerPress);}
 // Resume must discard history rather than replay wake edges or queued actions.
 reset();{PowerKeys k;CHECK("resume_closed_fails",!k.resetAfterResume()&&!k.available());}
 reset();{PowerKeys k;k.open();event(1,10);event(0,20);event(1,30);event(0,40);now=100;CHECK("resume_setup_queued_action",k.poll()==ShortPowerPress);event(1,500);event(0,4500);now=10000;CHECK("resume_clears_queued_and_history",k.resetAfterResume()&&k.available());CHECK("resume_no_queued_action",k.poll()==NoPowerAction);now=20000;CHECK("resume_no_delayed_action",k.poll()==NoPowerAction);event(1,20001);event(0,20002);now=20002;CHECK("resume_fresh_short",k.poll()==ShortPowerPress);}
 reset();{PowerKeys k;k.open();event(1,100);now=200;k.poll();now=10000;CHECK("resume_cancels_prior_down",k.resetAfterResume());CHECK("resume_prior_down_not_long",k.poll()==NoPowerAction);}
 reset();{PowerKeys k;k.open();for(int i=0;i<40;++i){event(1,i*100);event(0,i*100+50);}requireDrained=true;now=10000;CHECK("resume_drains_all_batches_before_baseline",k.resetAfterResume()&&k.available());CHECK("resume_all_history_ignored",k.poll()==NoPowerAction);event(1,10001);event(0,13001);now=13001;CHECK("resume_new_long_once",k.poll()==LongPowerPress);CHECK("resume_new_long_once_only",k.poll()==NoPowerAction);}
 reset();{PowerKeys k;k.open();event(1,100);event(2,5000);held=true;now=10000;CHECK("resume_held_baseline",k.resetAfterResume());event(1,10001);event(2,10002);now=20000;CHECK("resume_held_and_repeat_not_long",k.poll()==NoPowerAction);event(0,20001);now=20001;CHECK("resume_held_release_not_short",k.poll()==NoPowerAction);event(1,20002);event(0,20003);now=20003;CHECK("resume_held_then_fresh_short",k.poll()==ShortPowerPress);}
 reset();{PowerKeys k;k.open();syn(PowerSyncDropped,100);now=200;CHECK("resume_setup_dropped",k.poll()==NoPowerAction);event(1,300);event(0,400);now=10000;CHECK("resume_recovers_dropped_without_report",k.resetAfterResume());event(1,10001);event(0,10002);now=10002;CHECK("resume_dropped_fresh_short",k.poll()==ShortPowerPress);}
 reset();{PowerKeys k;k.open();syn(PowerSyncDropped,100);syn(PowerSyncReport,200);event(1,300);event(0,400);now=10000;CHECK("resume_drain_ignores_sync_dropped",k.resetAfterResume());CHECK("resume_drain_report_not_replayed",k.poll()==NoPowerAction);}
 reset();{PowerKeys k;k.open();for(int i=0;i<2048;++i)event(2,i);now=10000;CHECK("resume_exact_limit_can_finish",k.resetAfterResume()&&k.available());CHECK("resume_limit_no_action",k.poll()==NoPowerAction);}
 reset();{PowerKeys k;k.open();for(int i=0;i<2049;++i)event(2,i);now=10000;CHECK("resume_over_limit_disconnects",!k.resetAfterResume()&&!k.available());CHECK("resume_limit_failure_no_action",k.poll()==NoPowerAction);}
 reset();{PowerKeys k;k.open();event(1,100);now=200;k.poll();readFailure=true;CHECK("resume_read_error_disconnects",!k.resetAfterResume()&&!k.available());CHECK("resume_read_error_no_action",k.poll()==NoPowerAction);}
 reset();{PowerKeys k;k.open();baselineFailure=true;CHECK("resume_baseline_error_disconnects",!k.resetAfterResume()&&!k.available());}
 reset();{PowerKeys k;k.open();readResult=0;CHECK("resume_eof_disconnects",!k.resetAfterResume()&&!k.available());}
 reset();{PowerKeys k;k.open();readResult=33;CHECK("resume_oversize_batch_disconnects",!k.resetAfterResume()&&!k.available());}
 reset();{PowerKeys k;k.open();readResult=-1;CHECK("resume_partial_record_error_disconnects",!k.resetAfterResume()&&!k.available());}
 // A down edge must cancel automatic re-suspend before a complete short press.
 reset();{PowerKeys k;k.open();event(1,10);now=10;CHECK("wake_down_has_no_action_yet",k.poll()==NoPowerAction);CHECK("wake_down_activity_is_latched",k.takeActivity());CHECK("activity_is_consumed_once",!k.takeActivity());}
 reset();{PowerKeys k;k.open();PowerKeyEvent other={PowerInputKey,116,1,10};input.push_back(other);now=10;k.poll();CHECK("unrelated_key_not_wake_activity",!k.takeActivity());}
 reset();{PowerKeys k;k.open();event(2,10);now=10;CHECK("repeat_not_power_action",k.poll()==NoPowerAction);CHECK("repeat_still_prevents_timer_sleep",k.takeActivity());}
 reset();{PowerKeys k;k.open();syn(PowerSyncDropped,10);now=10;k.poll();CHECK("dropped_stream_is_unknown_human_priority",k.takeActivity());}
 reset();{PowerKeys k;k.open();event(1,10);now=10;k.poll();CHECK("resume_baseline_discards_consumed_activity",k.resetAfterResume()&&!k.takeActivity());}
 reset();{PowerKeys k;k.open();event(1,10);event(0,20);CHECK("resume_drain_preserves_wake_activity",k.resetAfterResume()&&k.takeActivity());CHECK("resume_activity_does_not_replay_action",k.poll()==NoPowerAction);}
 reset();{PowerKeys k;k.open();held=true;CHECK("resume_held_preserves_wake_activity",k.resetAfterResume()&&k.takeActivity());}
 reset();{PowerKeys k;k.open();syn(PowerSyncDropped,10);CHECK("resume_dropped_preserves_unknown_activity",k.resetAfterResume()&&k.takeActivity());}
 printf("%d checks, %d failures\n",checks,failures);return failures?1:0;
}
