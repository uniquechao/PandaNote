#include "tlsclock.h"
#include <time.h>
#ifndef CLOCK_BOOTTIME
#define CLOCK_BOOTTIME 7
#endif
int64_t tlsBootMs(){struct timespec t;if(clock_gettime(clockid_t(CLOCK_BOOTTIME),&t)||t.tv_sec<0||t.tv_nsec<0||t.tv_nsec>=1000000000||int64_t(t.tv_sec)>INT64_MAX/1000-1)return -1;return int64_t(t.tv_sec)*1000+t.tv_nsec/1000000;}
int64_t tlsRealtimeEpoch(){struct timespec t;if(clock_gettime(CLOCK_REALTIME,&t)||!validTlsEpoch(t.tv_sec)||t.tv_nsec<0||t.tv_nsec>=1000000000)return 0;return t.tv_sec;}
