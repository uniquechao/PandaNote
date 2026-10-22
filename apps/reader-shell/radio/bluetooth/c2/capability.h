#ifndef C2_CAPABILITY_H
#define C2_CAPABILITY_H
#include <sys/types.h>
struct c2_capability { unsigned flags, objects, interfaces; };
int c2_interface(struct c2_capability *,const char *path,const char *interface);
int c2_owner(const char *before,const char *after,pid_t expected,unsigned actual);
#endif
