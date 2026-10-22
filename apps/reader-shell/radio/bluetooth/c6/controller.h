#ifndef PANDANOTE_C6_CONTROLLER_H
#define PANDANOTE_C6_CONTROLLER_H
#include "runner.h"
#include <sys/stat.h>
struct c6_controller {int directory,held;struct stat identity;};
int c6_initial_name(int);
int c6_class_entry(const char *);
int c6_controller_ready(void *,struct child *,int64_t);
int c6_controller_healthy(void *,struct child *);
#endif
