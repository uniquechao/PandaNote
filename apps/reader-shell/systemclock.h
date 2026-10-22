#ifndef PANDANOTE_SYSTEM_CLOCK_H
#define PANDANOTE_SYSTEM_CLOCK_H
#include <stdint.h>
#include <time.h>
struct SystemClockResult {
 enum Status {Skipped,InvalidEpoch,Applied,Failed};
 Status status;int errorNumber;
 SystemClockResult(Status value,int error=0):status(value),errorNumber(error){}
};
// Narrow syscall boundary; production links systemclock_posix.cpp.
int setSystemRealtime(clockid_t clock,const struct timespec *utc);
// Caller supplies only DeviceSync's fresh epoch from the current authenticated
// HTTPS receive, never an HTTP Date, cached content, RTC or simulated UI anchor.
SystemClockResult setAuthenticatedSystemClock(bool authenticated,int64_t freshEpoch);
// Keep display/TLS anchors available even if the root-only system write fails.
// These still use their existing monotonic time basis after a realtime step.
template<class Display,class Http>
SystemClockResult applyAuthenticatedTime(bool authenticated,int64_t freshEpoch,Display &display,Http &http) {
 if(authenticated&&freshEpoch>0){
  display.setTrustedTime(freshEpoch);http.trustEpoch(freshEpoch);
 }
 return setAuthenticatedSystemClock(authenticated,freshEpoch);
}
#endif
