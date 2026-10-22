#ifndef PANDANOTE_BT_POLICY_H
#define PANDANOTE_BT_POLICY_H
#include <stdint.h>
#include <stddef.h>
#define BT_GRANT_CONTROL 1U
#define BT_GRANT_FILE 4U
#define BT_LINK_BONDED 1U
#define BT_LINK_ENCRYPTED 2U
#define BT_LINK_MITM 4U
#define BT_FILE_MAX 262144U
#define BT_CHUNK_MAX 128U
#define BT_FRAME_HEADER 22U
/* Local, trusted backend API. No field here is accepted from remote frames.
 * Runtime supplies a private volatile buffer and a fresh OS-random nonce. */
struct bt_policy {
    unsigned char *buffer;size_t capacity,received,total;
    unsigned char peer[6],nonce[16],digest[32];
    uint64_t window_from,window_until,pending_from,pending_until,session_from,session_until;
    uint32_t next_sequence;unsigned grants;
    int pending,approved,active,file_state;
    char filename[49];
};
struct bt_effect {int kind,control;size_t file_bytes;char filename[49];};
void bt_policy_init(struct bt_policy *,unsigned char *,size_t);
void bt_policy_close(struct bt_policy *);
void bt_pair_window(struct bt_policy *,uint64_t);
int bt_pair_request(struct bt_policy *,const unsigned char[6],unsigned,const unsigned char[16],uint64_t);
int bt_pair_confirm(struct bt_policy *,const unsigned char[6],const unsigned char[16],int,unsigned,uint64_t);
int bt_link_authorize(struct bt_policy *,const unsigned char[6],unsigned,uint64_t);
/* 1 accepted, 0 rejected. Accepted frames consume exactly one sequence.
 * Effects only describe an allowlisted action; this library executes none.
 * Call with a monotonic millisecond clock; clear input+effect after dispatch. */
int bt_frame(struct bt_policy *,const unsigned char *,size_t,uint64_t,struct bt_effect *);
void bt_effect_clear(struct bt_effect *);
void bt_file_release(struct bt_policy *);
#endif
