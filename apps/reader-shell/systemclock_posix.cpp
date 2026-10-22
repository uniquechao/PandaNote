#include "systemclock.h"
int setSystemRealtime(clockid_t clock,const struct timespec *utc) { return ::clock_settime(clock,utc); }
