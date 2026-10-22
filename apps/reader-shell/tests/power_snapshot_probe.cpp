// Explicit read-only smoke probe. Each open owns its independent evdev queue;
// no key injection, service marker, power syscall or device-global setting.
#include "../powerkeys.h"
#include <stdio.h>
int main(){
 for(int index=0;index<16;++index){
  bool initial=false;int fd=powerKeyOpenCandidate(index,&initial);if(fd<0)continue;
  bool held=false;bool snapshot=powerKeySnapshotHeld(fd,&held);
  PowerKeyEvent events[32];int count=powerKeyReadEvents(fd,events,32);powerKeyClose(fd);
  printf("POWER_SNAPSHOT_PROBE opened=1 index=%d initial_held=%d snapshot=%d held=%d read_count=%d\n",index,int(initial),int(snapshot),int(held),count);
  return snapshot&&(count==PowerReadAgain||count>0)?0:1;
 }
 puts("POWER_SNAPSHOT_PROBE opened=0");return 1;
}
