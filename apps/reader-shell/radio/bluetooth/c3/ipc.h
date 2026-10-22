#ifndef PANDANOTE_BT_C3_IPC_H
#define PANDANOTE_BT_C3_IPC_H
#include "runtime.h"
#include <sys/types.h>
#define C3_LOCAL_REQUEST 24
#define C3_LOCAL_REPLY 48
struct c3_ipc {int socket,lock,directory;dev_t device;ino_t inode;char path[104];unsigned event,last_ack;unsigned char event_nonce[16],last_ack_nonce[16];};
/* Private pre-existing0700 owner directory, absolute path, no old socket adoption. */
int c3_ipc_open(struct c3_ipc *,int dir,const char *absolute_directory);
int c3_ipc_poll(struct c3_ipc *,struct c3 *,uint64_t now);
int c3_ipc_close(struct c3_ipc *);
#endif
