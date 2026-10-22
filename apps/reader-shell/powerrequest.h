#ifndef PANDANOTE_POWERREQUEST_H
#define PANDANOTE_POWERREQUEST_H
// true means the complete request became visible to the service. Publication
// is irrevocable: a later directory-fsync/close error still returns true,
// because the service may already have consumed the request. This is not an
// acknowledgement of shutdown or a guarantee of power-loss durability.
// false means this call published nothing; an existing request is untouched.
bool publishPowerOffRequest(const char *privateDirectory);
enum SuspendReply { NoSuspendReply, SuspendResumed, SuspendRejected, SuspendTimerResumed };
bool readSuspendGeneration(const char *privateDirectory,char generation[49]);
bool publishSuspendRequest(const char *privateDirectory,const char *generation,const char *token);
// Call after draining pending power-key input. Intent never needs the service
// lease; allow is accepted only for this helper's newly published ready marker.
bool publishSuspendWakeIntent(const char *privateDirectory,const char *generation,const char *token);
// Observe ready BEFORE polling/draining input, then acknowledge that same
// token. Reading ready for the first time only after a poll leaves a gap.
bool suspendInputReady(const char *privateDirectory,const char *generation,const char *token);
bool acknowledgeSuspendInput(const char *privateDirectory,const char *generation,const char *token);
SuspendReply readSuspendReply(const char *privateDirectory,const char *generation,const char *token);
// The service must hold this same lease before claiming and through completion.
// Success removes only the matching request while no helper can enter mem.
bool cancelSuspendRequest(const char *privateDirectory,const char *leaseDirectory,const char *generation,const char *token);
#endif
