#ifndef PANDANOTE_BT_C3_RUNTIME_H
#define PANDANOTE_BT_C3_RUNTIME_H
#include "../policy.h"
#define C3_RECORD_MAX (BT_FRAME_HEADER+4+BT_CHUNK_MAX)
#define C3_ACK_BYTES 12
#define C3_SERVICE_UUID "c23586e2-a8cb-4fe1-95a9-28109b983001"
#define C3_RX_UUID "c23586e2-a8cb-4fe1-95a9-28109b983002"
#define C3_ACK_UUID "c23586e2-a8cb-4fe1-95a9-28109b983003"
#define C3_SESSION_UUID "c23586e2-a8cb-4fe1-95a9-28109b983004"
struct c3 {
 struct bt_policy policy;struct bt_effect effect;
 unsigned char record[C3_RECORD_MAX],last_fragment[C3_RECORD_MAX+4],ack[C3_ACK_BYTES];
 size_t assembled,last_size;unsigned char fragment_id;uint64_t assembly_until;int inbox_fd,last_result;
 /* Nonzero CONTROL/committed-FILE generation is allocated by the producer,
  * not by a consumer peek. It survives take_effect until the nonce closes. */
 unsigned passkey,effect_generation;
};
void c3_init(struct c3 *,unsigned char *,size_t,int inbox_fd);
void c3_close(struct c3 *);
int c3_pair_request(struct c3 *,const unsigned char peer[6],unsigned passkey,uint64_t now);
void c3_tick(struct c3 *,uint64_t now);
int c3_fragment(struct c3 *,const unsigned char *,size_t,unsigned mtu,uint64_t now);
int c3_take_effect(struct c3 *,struct bt_effect *);
int c3_store(int inbox_fd,const char *name,const unsigned char *,size_t);
#endif
