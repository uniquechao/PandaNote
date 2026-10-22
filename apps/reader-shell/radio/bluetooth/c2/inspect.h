#ifndef C2_INSPECT_H
#define C2_INSPECT_H
#include "core.h"
#include "capability.h"
#include <signal.h>
#include <dbus/dbus.h>
extern volatile sig_atomic_t c2_cancelled;
DBusConnection *c2_bus(int64_t deadline);
int c2_inspect(DBusConnection *,struct child *,struct child *,struct c2_capability *,int64_t deadline);
#endif
