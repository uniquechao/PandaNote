#ifndef PANDANOTE_BT_C3_SERVICE_H
#define PANDANOTE_BT_C3_SERVICE_H
#include "runtime.h"
#include <dbus/dbus.h>
#include <sys/types.h>
#define C3_APP "/org/pandanote/Bluetooth/app"
#define C3_SERVICE C3_APP "/service0"
#define C3_RX C3_SERVICE "/rx"
#define C3_ACK C3_SERVICE "/ack"
#define C3_SESSION C3_SERVICE "/session"
#define C3_AGENT "/org/pandanote/Bluetooth/agent"
#define C3_ADV "/org/pandanote/Bluetooth/advertisement"
struct c3_server {DBusConnection *bus;struct c3 *runtime;char owner[64],device[128];pid_t expected_pid;DBusMessage *confirmation;unsigned registered;uint64_t next_check;int exported,handling;};
/* Caller owns the private bus and exact unreaped daemon handle. No global bus. */
int c3_server_export(struct c3_server *,DBusConnection *,struct c3 *,pid_t expected_daemon_pid);
int c3_server_register(struct c3_server *); /* Explicit reviewed activation only. */
int c3_server_tick(struct c3_server *,uint64_t now);
int c3_server_close(struct c3_server *);
#endif
