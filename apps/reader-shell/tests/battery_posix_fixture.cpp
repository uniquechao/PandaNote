// Exercise the real fork/pipe/deadline boundary with a fake ADC worker only.
#include "../battery.h"
#include <errno.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>
static int mode=0,failures=0,checks=0;
#define CHECK(n,x) do{++checks;if(!(x)){++failures;fprintf(stderr,"FAIL %s line %d\n",n,__LINE__);}}while(0)
void batteryFixtureSample(unsigned char *bytes,int *count,int *error){
 if(mode==3)::usleep(500000);
 bytes[0]=0x14;bytes[1]=5;bytes[2]=bytes[3]=0;*count=mode==1?2:4;*error=mode==2?EIO:0;
}
static long long nowMs(){struct timespec t;::clock_gettime(CLOCK_MONOTONIC,&t);return static_cast<long long>(t.tv_sec)*1000+t.tv_nsec/1000000;}
int main(){
 unsigned char bytes[4]={0,0,0,0};int error=0;
 CHECK("bounded_worker_success",batteryAdcRead(bytes,&error)==4&&error==0&&bytes[0]==0x14&&bytes[1]==5);
 ::usleep(10000);mode=1;CHECK("worker_partial_rejected",batteryAdcRead(bytes,&error)==-1&&error==EIO);
 ::usleep(10000);mode=2;CHECK("worker_error_preserved",batteryAdcRead(bytes,&error)==-1&&error==EIO);
 ::usleep(10000);mode=3;const long long started=nowMs();int result=batteryAdcRead(bytes,&error);const long long elapsed=nowMs()-started;
 CHECK("worker_timeout_preserved",result==-1&&error==ETIMEDOUT);CHECK("parent_wait_is_bounded",elapsed>=200&&elapsed<750);
 ::usleep(10000);mode=0;CHECK("timeout_child_reaped_before_reuse",batteryAdcRead(bytes,&error)==4&&error==0);
 printf("%d checks, %d failures; timeout_ms=%lld\n",checks,failures,elapsed);return failures?1:0;
}
