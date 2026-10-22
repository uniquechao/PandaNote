#ifndef PANDANOTE_BT_C4_SESSION_H
#define PANDANOTE_BT_C4_SESSION_H
#include "supervisor.h"
#include "../c2/inspect.h"
#include <sys/stat.h>
#define C4_ROOT "/tmp/pandanote-connectivity/bluetooth"
#define C4_SOCKET C4_ROOT "/service/local.sock"
struct c4_socket {int directory;const char *name,*path;struct stat identity;int seen;};
struct c4_context {DBusConnection *bus;char owner[64],daemon_pid[32];struct c4_socket bus_socket,service_socket;};
int c4_ready(void *,unsigned,struct child [3],int64_t deadline);
int c4_healthy(void *,struct child [3]);
int c4_unlink_socket(struct c4_socket *);
#endif
