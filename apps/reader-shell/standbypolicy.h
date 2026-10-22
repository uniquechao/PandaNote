#ifndef PANDANOTE_STANDBY_POLICY_H
#define PANDANOTE_STANDBY_POLICY_H
#include <stdint.h>
// A same-boot maintenance budget. Caller owns network cancellation/paint/reap.
class StandbyMaintenance {
 bool active_,contact_;int64_t began_,deadline_;
public:
 StandbyMaintenance():active_(false),contact_(false),began_(-1),deadline_(-1){}
 bool begin(int64_t now){cancel();if(now<0||now>0x7fffffffffffffffLL-30000)return false;active_=true;began_=now;deadline_=now+30000;return true;}
 bool active()const{return active_;}
 void authenticatedContact(){if(active_)contact_=true;}
 void cancel(){active_=false;contact_=false;began_=deadline_=-1;}
 bool finish(int64_t now,bool pipelineBusy,bool terminalFailure)const{
  return active_&&(now<began_||now>=deadline_||(!pipelineBusy&&(contact_||terminalFailure)));
 }
};
#endif
