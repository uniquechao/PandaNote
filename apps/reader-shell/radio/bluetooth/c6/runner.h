#ifndef PANDANOTE_BT_C6_RUNNER_H
#define PANDANOTE_BT_C6_RUNNER_H
#include "../c4/supervisor.h"
struct c6_plan {struct c4_program transport,service;volatile sig_atomic_t *stop;int (*ready)(void *,struct child *,int64_t);int (*healthy)(void *,struct child *);void *context;unsigned service_grace_ms,health_ms;};
struct c6_result {struct child transport,service;int started_service,reaped_all,forced_service;};
int c6_run(const struct c6_plan *,struct c6_result *);
#endif
