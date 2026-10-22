#ifndef PANDANOTE_C5_RUNNER_H
#define PANDANOTE_C5_RUNNER_H
#include "../c4/supervisor.h"
struct c5_result {struct child child;int elapsed_ms,reaped,killed;};
int c5_run(const struct c4_program *,volatile sig_atomic_t *,unsigned,struct c5_result *);
#endif
