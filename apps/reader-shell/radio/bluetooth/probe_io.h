#ifndef PANDANOTE_BT_PROBE_IO_H
#define PANDANOTE_BT_PROBE_IO_H
#include <stdint.h>
#include <stddef.h>
int64_t bt_deadline(int milliseconds);
int bt_exchange(int,const unsigned char *,size_t,int64_t,int (*)(const unsigned char *,size_t,void *),void *);
#endif
