// Controlled single evdev stream; never reads hardware or invokes ioctls.
#include "../powerkeys.h"
#include <stdio.h>
#include <vector>
static int checks=0,failures=0;
#define CHECK(n,x) do{++checks;if(!(x)){++failures;fprintf(stderr,"FAIL %s line %d\n",n,__LINE__);}}while(0)
static std::vector<PowerKeyEvent> input;static unsigned cursor;static bool heldPower,heldPrevious,heldNext,failSnapshot;static int64_t now;
int powerKeyOpenCandidate(int i,bool*out){if(i!=1)return -1;*out=heldPower;return 42;}
bool powerKeyHeld(int,bool*out){*out=heldPower;return true;}
bool powerKeySnapshotHeld(int,bool*out){if(failSnapshot)return false;*out=heldPower;return true;}
int powerKeyReadEvents(int,PowerKeyEvent*out,unsigned capacity){if(cursor==input.size())return PowerReadAgain;unsigned count=0;while(count<capacity&&cursor<input.size())out[count++]=input[cursor++];return count;}
int powerKeyOpenCandidate(int i,PowerKeyHeldState*out){bool power=false;int fd=powerKeyOpenCandidate(i,&power);if(fd>=0){out->power=power;out->previous=heldPrevious;out->next=heldNext;}return fd;}
bool powerKeyHeld(int fd,PowerKeyHeldState*out){bool power=false;if(!powerKeyHeld(fd,&power))return false;out->power=power;out->previous=heldPrevious;out->next=heldNext;return true;}
bool powerKeySnapshotHeld(int fd,PowerKeyHeldState*out){bool power=false;if(!powerKeySnapshotHeld(fd,&power))return false;out->power=power;out->previous=heldPrevious;out->next=heldNext;return true;}
int64_t powerKeyNowMs(){return now;}void powerKeyClose(int){}
static void reset(){input.clear();cursor=0;heldPower=heldPrevious=heldNext=failSnapshot=false;now=10000;}
static void key(int code,int value){PowerKeyEvent e={PowerInputKey,code,value,int64_t(input.size()*10)};input.push_back(e);}
static void syn(int code){PowerKeyEvent e={PowerInputSyn,code,0,int64_t(input.size()*10)};input.push_back(e);}
int main(){
 reset();{PowerKeys k;CHECK("open",k.open());key(104,1);CHECK("page_up_no_power",k.poll()==NoPowerAction);CHECK("page_up_previous",k.takeListNavigation()==-1);CHECK("page_pop_once",k.takeListNavigation()==0);CHECK("page_not_power_activity",!k.takeActivity());}
 reset();{PowerKeys k;k.open();key(109,1);key(109,1);key(109,2);key(109,2);k.poll();CHECK("down_once",k.takeListNavigation()==1&&k.takeListNavigation()==0);key(109,0);key(109,1);k.poll();CHECK("release_rearms",k.takeListNavigation()==1&&k.takeListNavigation()==0);}
 reset();{PowerKeys k;k.open();key(104,0);key(109,2);k.poll();CHECK("orphan_up_repeat_no_nav",k.takeListNavigation()==0);}
 reset();{PowerKeys k;k.open();key(104,1);key(109,1);key(104,0);key(104,1);k.poll();CHECK("both_keys_preserve_order",k.takeListNavigation()==-1&&k.takeListNavigation()==1&&k.takeListNavigation()==-1&&k.takeListNavigation()==0);}
 reset();{PowerKeys k;k.open();key(104,1);key(87,1);key(87,0);key(109,1);CHECK("f11_short_unchanged",k.poll()==ShortPowerPress);CHECK("nav_queue_independent",k.takeListNavigation()==-1&&k.takeListNavigation()==1&&k.takeListNavigation()==0);CHECK("f11_activity_unchanged",k.takeActivity());}
 reset();{PowerKeys k;k.open();for(int i=0;i<20;i++){key(109,1);key(109,0);}key(87,1);key(87,0);CHECK("nav_overflow_does_not_disconnect_or_hide_power",k.poll()==ShortPowerPress&&k.available());int n=0;while(k.takeListNavigation())++n;CHECK("navigation_queue_bounded16",n==16);}
 reset();{PowerKeys k;k.open();key(104,1);k.poll();key(109,1);key(109,0);CHECK("reset_discards_queued_and_old_page_edges",k.resetAfterResume()&&k.takeListNavigation()==0&&!k.takeActivity());CHECK("reset_page_history_not_action",k.poll()==NoPowerAction&&k.takeListNavigation()==0);key(104,1);k.poll();CHECK("reset_page_fresh_down",k.takeListNavigation()==-1);}
 reset();heldPrevious=true;{PowerKeys k;k.open();key(104,1);key(104,2);k.poll();CHECK("startup_held_page_suppressed",k.takeListNavigation()==0);key(104,0);key(104,1);k.poll();CHECK("startup_page_release_rearms",k.takeListNavigation()==-1);}
 reset();{PowerKeys k;k.open();heldNext=true;CHECK("reset_held_page_not_power_activity",k.resetAfterResume()&&!k.takeActivity());key(109,1);key(109,2);k.poll();CHECK("reset_held_page_suppressed",k.takeListNavigation()==0);key(109,0);key(109,1);k.poll();CHECK("reset_held_page_release_rearms",k.takeListNavigation()==1);}
 reset();{PowerKeys k;k.open();key(104,1);syn(PowerSyncDropped);heldNext=true;syn(PowerSyncReport);k.poll();CHECK("dropped_discards_navigation",k.takeListNavigation()==0&&k.available());key(109,1);key(109,2);k.poll();CHECK("dropped_held_page_suppressed",k.takeListNavigation()==0);key(109,0);key(109,1);k.poll();CHECK("dropped_held_page_release_rearms",k.takeListNavigation()==1);}
 reset();{PowerKeys k;k.open();key(115,1);key(114,1);key(116,1);k.poll();CHECK("unconfigured_key_codes_ignored",k.takeListNavigation()==0&&!k.takeActivity());}
 reset();{PowerKeys k;k.open();key(104,1);k.poll();failSnapshot=true;CHECK("reset_error_clears_nav",!k.resetAfterResume()&&k.takeListNavigation()==0&&!k.available());}
 printf("%d list checks, %d failures\n",checks,failures);return failures?1:0;
}
