// This fixture replaces only the dangerous syscall symbol. No host clock writes.
#include "../systemclock.h"
#include <errno.h>
#include <stdio.h>
static int calls=0,failWith=0;
static clockid_t seenClock;
static struct timespec seenTime;
int setSystemRealtime(clockid_t clock,const struct timespec *value) {
 ++calls;seenClock=clock;seenTime=*value;
 if(failWith){errno=failWith;return -1;}return 0;
}
#define CHECK(name,condition) do { if(!(condition)){fprintf(stderr,"FAIL %s\n",name);return 1;}printf("PASS %s\n",name); } while(0)
struct Display { int updates;int64_t epoch;Display():updates(0),epoch(0){}void setTrustedTime(int64_t value){++updates;epoch=value;} };
struct Http { int updates;int64_t epoch;Http():updates(0),epoch(0){}void trustEpoch(int64_t value){++updates;epoch=value;} };
int main() {
 // Wrong trust guard or stale/cached input must never reach the syscall.
 SystemClockResult result=setAuthenticatedSystemClock(false,1792458000LL);
 CHECK("unauthenticated_rejected",result.status==SystemClockResult::Skipped&&calls==0);
 result=setAuthenticatedSystemClock(true,0);
 CHECK("no_fresh_manifest_rejected",result.status==SystemClockResult::Skipped&&calls==0);
 const int64_t invalid[]={-1,1,946684799LL,2147483647LL,4133980799LL};
 for(unsigned i=0;i<sizeof(invalid)/sizeof(invalid[0]);++i){
  result=setAuthenticatedSystemClock(true,invalid[i]);
  CHECK("invalid_or_unrepresentable_epoch_rejected",result.status==SystemClockResult::InvalidEpoch&&calls==0);
 }
 // Device evidence was UTC+28814s. Set exact UTC seconds, never local UTC+8.
 result=setAuthenticatedSystemClock(true,1792458000LL);
 CHECK("authenticated_utc_applied",result.status==SystemClockResult::Applied&&result.errorNumber==0&&calls==1);
 CHECK("realtime_only_exact_utc",seenClock==CLOCK_REALTIME&&seenTime.tv_sec==1792458000LL&&seenTime.tv_nsec==0);
 failWith=EPERM;
 result=setAuthenticatedSystemClock(true,1792458060LL);
 CHECK("syscall_failure_not_reported_synced",result.status==SystemClockResult::Failed&&result.errorNumber==EPERM&&calls==2);
 failWith=0;
 result=setAuthenticatedSystemClock(true,1792457900LL);
 CHECK("backwards_large_correction_allowed",result.status==SystemClockResult::Applied&&seenTime.tv_sec==1792457900LL&&calls==3);
 result=setAuthenticatedSystemClock(false,1792457900LL);
 CHECK("failed_receive_cannot_reuse_previous_fresh_epoch",result.status==SystemClockResult::Skipped&&calls==3);
 result=setAuthenticatedSystemClock(true,946684800LL);
 CHECK("minimum_epoch_supported",result.status==SystemClockResult::Applied&&seenTime.tv_sec==946684800LL);
 result=setAuthenticatedSystemClock(true,2147483646LL);
 CHECK("maximum_mips_epoch_supported",result.status==SystemClockResult::Applied&&seenTime.tv_sec==2147483646LL);
 Display display;Http http;failWith=EPERM;
 result=applyAuthenticatedTime(true,1792458000LL,display,http);
 CHECK("display_and_tls_survive_system_write_failure",result.status==SystemClockResult::Failed&&display.updates==1&&http.updates==1&&display.epoch==1792458000LL&&http.epoch==1792458000LL);
 int previous=calls;
 result=applyAuthenticatedTime(false,1792458000LL,display,http);
 result=applyAuthenticatedTime(true,0,display,http);
 CHECK("resource_ack_and_failed_receive_keep_existing_anchor",result.status==SystemClockResult::Skipped&&display.updates==1&&http.updates==1&&calls==previous);
 return 0;
}
