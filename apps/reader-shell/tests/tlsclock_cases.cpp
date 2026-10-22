#include "../tlsclock.h"
#include <time.h>
#include <stdio.h>
static int checks=0,failures=0;
#define CHECK(n,x) do{++checks;if(!(x)){++failures;fprintf(stderr,"FAIL %s\n",n);}}while(0)
static int scenario=0;
extern "C" int clock_gettime(clockid_t which,struct timespec *t){if(scenario==1)return -1;t->tv_sec=which==CLOCK_REALTIME?1792600000:which==7?180:12;t->tv_nsec=500000000;return 0;}
int main(){
 CHECK("numeric bootstrap unchanged",tlsInitialEpoch(false,1792458000,1792600000)==1792458000);
 CHECK("domain uses realtime above floor",tlsInitialEpoch(true,1792458000,1792600000)==1792600000);
 CHECK("domain cannot roll below USB floor",tlsInitialEpoch(true,1792458000,1577836800)==1792458000);
 CHECK("invalid future realtime ignored",tlsInitialEpoch(true,1792458000,4133980799LL)==1792458000);
 CHECK("bad floor rejected",tlsInitialEpoch(true,0,1792600000)==0);
 CHECK("sleep delta counted",tlsAdvanceEpoch(1792458000,1000,181000)==1792458180);
 CHECK("regressed clock rejected",tlsAdvanceEpoch(1792458000,1000,999)==0);
 CHECK("epoch overflow rejected",tlsAdvanceEpoch(2147483646,0,1000)==0);
 CHECK("boottime selected",tlsBootMs()==180500);CHECK("realtime queried",tlsRealtimeEpoch()==1792600000);
 scenario=1;CHECK("clock errors rejected",tlsBootMs()==-1&&tlsRealtimeEpoch()==0);
 printf("%d checks, %d failures\n",checks,failures);return failures?1:0;
}
