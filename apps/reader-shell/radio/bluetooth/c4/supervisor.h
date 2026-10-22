#ifndef PANDANOTE_BT_C4_SUPERVISOR_H
#define PANDANOTE_BT_C4_SUPERVISOR_H
#include "../c2/core.h"
#include <signal.h>
#define C4_SHORT_FILE_LIMIT 16384U
#define C4_SERVICE_FILE_LIMIT 262144U
struct c4_program {int executable,log;char *const *argv;char *const *environment;unsigned memory_mb,file_limit,grace_ms;};
struct c4_plan {
 struct c4_program program[3];volatile sig_atomic_t *stop;
 int (*ready)(void *,unsigned,struct child [3],int64_t);
 int (*healthy)(void *,struct child [3]);void *context;unsigned health_ms;
};
struct c4_result {struct child child[3];unsigned ready,started,reaped,killed;int running,exit;};
int c4_spawn(struct child *,const struct c4_program *);
int c4_stop(struct child *,unsigned grace_ms);
int c4_run(const struct c4_plan *,struct c4_result *);
#endif
