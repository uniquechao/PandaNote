#include "powerkeys.h"
PowerKeyPolicy::PowerKeyPolicy():blocked_(true),down_(false),longSent_(false),pressedAt_(-1),lastEvent_(-1){}
void PowerKeyPolicy::baseline(bool held){cancel();blocked_=held;}
void PowerKeyPolicy::cancel(){blocked_=true;down_=false;longSent_=false;pressedAt_=lastEvent_=-1;}
PowerAction PowerKeyPolicy::observe(int value,int64_t at){
 if(value==2)return NoPowerAction;
 if((value!=0&&value!=1)||at<0||(lastEvent_>=0&&at<lastEvent_)){cancel();return NoPowerAction;}
 lastEvent_=at;
 if(blocked_){if(value==0)blocked_=false;return NoPowerAction;}
 if(value==1){if(!down_){down_=true;longSent_=false;pressedAt_=at;}return NoPowerAction;}
 if(!down_)return NoPowerAction;
 down_=false;
 if(longSent_)return NoPowerAction;
 longSent_=true;return at-pressedAt_>=3000?LongPowerPress:ShortPowerPress;
}
PowerAction PowerKeyPolicy::tick(int64_t now){
 if(now<0||(lastEvent_>=0&&now<lastEvent_)){cancel();return NoPowerAction;}
 if(!blocked_&&down_&&!longSent_&&now-pressedAt_>=3000){longSent_=true;return LongPowerPress;}
 return NoPowerAction;
}
PowerKeys::PowerKeys():fd_(-1),dropped_(false),activity_(false),head_(0),count_(0),navigationHead_(0),navigationCount_(0){navigationHeld_[0]=navigationHeld_[1]=true;}
PowerKeys::~PowerKeys(){disconnect();}
void PowerKeys::disconnect(){if(fd_>=0)powerKeyClose(fd_);fd_=-1;dropped_=false;activity_=false;head_=count_=navigationHead_=navigationCount_=0;navigationHeld_[0]=navigationHeld_[1]=true;policy_.cancel();}
bool PowerKeys::open(){
 if(available())return true;
 disconnect();
 for(int index=0;index<16;++index){PowerKeyHeldState held;const int candidate=powerKeyOpenCandidate(index,&held);if(candidate<0)continue;fd_=candidate;policy_.baseline(held.power);navigationHeld_[0]=held.previous;navigationHeld_[1]=held.next;return true;}
 return false;
}
bool PowerKeys::available()const{return fd_>=0;}
bool PowerKeys::resetAfterResume(){
 // Cancel action timing first. Only the separately opened snapshot client may
 // use GETKEY: the old client's queue must retain edges racing the snapshot.
 head_=count_=navigationHead_=navigationCount_=0;navigationHeld_[0]=navigationHeld_[1]=true;dropped_=false;activity_=false;policy_.cancel();
 if(!available())return false;
 unsigned total=0;PowerKeyHeldState held={false,true,true};
 for(unsigned phase=0;phase<2;++phase){
  for(;;){
   PowerKeyEvent events[32];const int count=powerKeyReadEvents(fd_,events,32);
   if(count==PowerReadAgain)break;
   if(count<=0||count>32||total+unsigned(count)>2048){disconnect();return false;}
   total+=unsigned(count);
   for(int i=0;i<count;++i){
    const PowerKeyEvent &e=events[i];
    if(e.type==PowerInputSyn&&e.code==PowerSyncDropped){
     activity_=true;
     // A new snapshot can recover an earlier drop. A drop after that anchor
     // makes the final state unknowable; do not manufacture a held baseline.
     if(phase){disconnect();return false;}
    }
    if(e.type==PowerInputKey&&e.code==PowerKeyF11){
     activity_=true;if(e.value<0||e.value>2){disconnect();return false;}
     if(phase&&e.value!=2)held.power=e.value==1;
    }
    if(phase&&e.type==PowerInputKey&&(e.code==PowerKeyPageUp||e.code==PowerKeyPageDown)){
     if(e.value<0||e.value>2){disconnect();return false;}
     if(e.value!=2){if(e.code==PowerKeyPageUp)held.previous=e.value==1;else held.next=e.value==1;}
    }
   }
  }
  if(!phase){if(!powerKeySnapshotHeld(fd_,&held)){disconnect();return false;}if(held.power)activity_=true;}
 }
 policy_.baseline(held.power);navigationHeld_[0]=held.previous;navigationHeld_[1]=held.next;return true;
}

int PowerKeys::takeListNavigation(){
 if(!navigationCount_)return 0;int direction=navigationQueue_[navigationHead_];navigationHead_=(navigationHead_+1)%QueueSize;--navigationCount_;return direction;
}
void PowerKeys::navigationKey(int code,int value){
 const unsigned index=code==PowerKeyPageUp?0:1;
 if(value==0){navigationHeld_[index]=false;return;}
 if(value==2)return;
 if(value!=1){navigationHead_=navigationCount_=0;navigationHeld_[0]=navigationHeld_[1]=true;return;}
 if(navigationHeld_[index])return;navigationHeld_[index]=true;
 // List input may be dropped under backpressure, while the F11 stream and
 // its independent action queue remain available for standby/shutdown.
 if(navigationCount_==QueueSize)return;
 navigationQueue_[(navigationHead_+navigationCount_)%QueueSize]=index?1:-1;++navigationCount_;
}

bool PowerKeys::enqueue(PowerAction action){
 if(action==NoPowerAction)return true;
 if(count_==QueueSize){disconnect();return false;}
 queue_[(head_+count_)%QueueSize]=action;++count_;return true;
}
PowerAction PowerKeys::poll(){
 if(!available())return NoPowerAction;
 // Drain before checking elapsed time: a queued down/up remains a short press
 // even when a slow e-ink paint prevented GUI dispatch for several seconds.
 unsigned total=0;
 for(;;){
  PowerKeyEvent events[32];const int count=powerKeyReadEvents(fd_,events,32);
  if(count==PowerReadAgain)break;
  if(count<=0||count>32||total+unsigned(count)>2048){disconnect();return NoPowerAction;}
  total+=unsigned(count);
  for(int i=0;i<count;++i){
   const PowerKeyEvent &e=events[i];
   if(e.type==PowerInputSyn&&e.code==PowerSyncDropped){activity_=true;policy_.cancel();dropped_=true;head_=count_=navigationHead_=navigationCount_=0;navigationHeld_[0]=navigationHeld_[1]=true;continue;}
   if(dropped_){
    if(e.type==PowerInputSyn&&e.code==PowerSyncReport){PowerKeyHeldState held;if(!powerKeyHeld(fd_,&held)){disconnect();return NoPowerAction;}policy_.baseline(held.power);navigationHeld_[0]=held.previous;navigationHeld_[1]=held.next;dropped_=false;
     // EVIOCGKEY snapshots current state and flushes unread EV_KEY. The
     // remainder already copied into this batch predates that snapshot too;
     // replaying its down after the matching up was flushed can fake a hold.
     break;
    }
    continue;
   }
   if(e.type==PowerInputKey&&e.code==PowerKeyF11){activity_=true;if(!enqueue(policy_.observe(e.value,e.milliseconds)))return NoPowerAction;}
   else if(e.type==PowerInputKey&&(e.code==PowerKeyPageUp||e.code==PowerKeyPageDown))navigationKey(e.code,e.value);
  }
 }
 // A dropped stream cannot resume timing until a report and fresh key state.
 const int64_t now=powerKeyNowMs();if(now<0){disconnect();return NoPowerAction;}
 if(!dropped_&&!enqueue(policy_.tick(now)))return NoPowerAction;
 if(!count_)return NoPowerAction;
 PowerAction result=queue_[head_];head_=(head_+1)%QueueSize;--count_;return result;
}
