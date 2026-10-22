/* Even an accidental BR/EDR fallback cannot bind global /var/run/sdp.
 * Runtime is pinned LE-only; this header is an additional source-build bound.
 * Include upstream header first so its guard retains the reviewed override. */
#ifndef PANDANOTE_BLUEZ_COMPAT_PATHS_H
#define PANDANOTE_BLUEZ_COMPAT_PATHS_H
#include <bluetooth/sdp.h>
#undef SDP_UNIX_PATH
#define SDP_UNIX_PATH "/tmp/pandanote-connectivity/bluetooth/run/sdp"
#endif
