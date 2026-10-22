#include "systemclock.h"
#include <errno.h>
SystemClockResult setAuthenticatedSystemClock(bool authenticated,int64_t freshEpoch) {
 if(!authenticated||freshEpoch==0)return SystemClockResult(SystemClockResult::Skipped);
 // The production MIPS ABI has signed 32-bit time_t; match the TLS time bound.
 if(freshEpoch<946684800LL||freshEpoch>2147483646LL)return SystemClockResult(SystemClockResult::InvalidEpoch);
 struct timespec utc;utc.tv_sec=static_cast<time_t>(freshEpoch);utc.tv_nsec=0;
 if(setSystemRealtime(CLOCK_REALTIME,&utc)!=0){int error=errno;return SystemClockResult(SystemClockResult::Failed,error);}
 return SystemClockResult(SystemClockResult::Applied);
}
