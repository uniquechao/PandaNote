// Offline Qt/runtime tests use the real policy, never the host realtime syscall.
#include "../systemclock.h"
#include <errno.h>
int setSystemRealtime(clockid_t,const struct timespec *) { errno=EPERM;return -1; }
