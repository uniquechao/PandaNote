#include "policy.h"
#include "../../third_party/sha256/sha256.h"
#include <string.h>
#include <limits.h>
static void wipe(void *data,size_t n){volatile unsigned char *p=data;while(n--)*p++=0;}
static uint32_t read32(const unsigned char *p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static int during(uint64_t now,uint64_t from,uint64_t until){return until>from&&now>=from&&now<until;}
void bt_effect_clear(struct bt_effect *e){if(e)wipe(e,sizeof(*e));}
void bt_file_release(struct bt_policy *p){
    if(p->buffer)wipe(p->buffer,p->capacity);
    p->received=p->total=0;p->file_state=0;wipe(p->digest,32);wipe(p->filename,sizeof(p->filename));
}
void bt_policy_init(struct bt_policy *p,unsigned char *b,size_t c){
    memset(p,0,sizeof(*p));p->buffer=b;p->capacity=b?(c>BT_FILE_MAX?BT_FILE_MAX:c):0;
    if(b)wipe(b,p->capacity);
}
void bt_policy_close(struct bt_policy *p){
    unsigned char *buffer=p->buffer;size_t capacity=p->capacity;
    bt_file_release(p);wipe(p,sizeof(*p));p->buffer=buffer;p->capacity=capacity;
}
void bt_pair_window(struct bt_policy *p,uint64_t now){
    bt_policy_close(p);if(now>UINT64_MAX-60000)return;
    p->window_from=now;p->window_until=now+60000;
}
int bt_pair_request(struct bt_policy *p,const unsigned char peer[6],unsigned passkey,
                    const unsigned char nonce[16],uint64_t now){
    unsigned char any=0;size_t i;
    if(!p||!peer||!nonce||passkey>999999||p->pending||p->approved||p->active||!during(now,p->window_from,p->window_until))return 0;
    for(i=0;i<16;i++)any|=nonce[i];
    if(!any)return 0;
    memcpy(p->peer,peer,6);memcpy(p->nonce,nonce,16);p->pending=1;p->pending_from=now;
    p->pending_until=now+30000;if(p->pending_until>p->window_until)p->pending_until=p->window_until;
    return 1;
}
int bt_pair_confirm(struct bt_policy *p,const unsigned char peer[6],const unsigned char nonce[16],
                    int allow,unsigned grants,uint64_t now){
    if(!p||!peer||!nonce||!p->pending)return 0;
    if(!during(now,p->pending_from,p->pending_until)){bt_policy_close(p);return 0;}
    if(memcmp(peer,p->peer,6)||memcmp(nonce,p->nonce,16))return 0;
    if(allow!=1||!grants||(grants&~(BT_GRANT_CONTROL|BT_GRANT_FILE))){bt_policy_close(p);return 0;}
    p->pending=0;p->approved=1;p->grants=grants;return 1;
}
int bt_link_authorize(struct bt_policy *p,const unsigned char peer[6],unsigned security,uint64_t now){
    if(!p||!peer||!p->approved||p->active)return 0;
    if(security!=7||memcmp(peer,p->peer,6)||!during(now,p->pending_from,p->pending_until)||now>UINT64_MAX-120000){bt_policy_close(p);return 0;}
    p->session_from=now;p->session_until=now+120000;p->active=1;p->next_sequence=1;return 1;
}
static int filename(const unsigned char *p,size_t n){
    size_t i;if(!n||n>48||p[0]=='.')return 0;
    for(i=0;i<n;i++)if(!((p[i]>='a'&&p[i]<='z')||(p[i]>='A'&&p[i]<='Z')||(p[i]>='0'&&p[i]<='9')||p[i]=='_'||p[i]=='-'||p[i]=='.'))return 0;
    for(i=1;i<n;i++)if(p[i]=='.'&&p[i-1]=='.')return 0;
    return (n>4&&(!memcmp(p+n-4,".txt",4)||!memcmp(p+n-4,".pdf",4)))||(n>5&&!memcmp(p+n-5,".epub",5));
}
int bt_frame(struct bt_policy *p,const unsigned char *wire,size_t n,uint64_t now,struct bt_effect *e){
    const unsigned char *body;size_t len,name_len;uint32_t sequence,total;unsigned op;
    unsigned char hash[32];SHA256_CTX sha;
    bt_effect_clear(e);if(!p||!e||!wire)return 0;
    if(!p->active)return 0;
    if(!during(now,p->session_from,p->session_until)){bt_policy_close(p);return 0;}
    if(n<BT_FRAME_HEADER||n>BT_FRAME_HEADER+4+BT_CHUNK_MAX||wire[0]!=1||memcmp(wire+6,p->nonce,16))return 0;
    sequence=read32(wire+2);if(sequence!=p->next_sequence||sequence==UINT32_MAX)return 0;
    op=wire[1];body=wire+BT_FRAME_HEADER;len=n-BT_FRAME_HEADER;
    switch(op){
    case 1:
        if(!(p->grants&BT_GRANT_CONTROL)||len!=1||body[0]>2)return 0;
        e->kind=1;e->control=body[0];break;
    case 3:
        if(!(p->grants&BT_GRANT_FILE)||p->file_state||len<38)return 0;
        name_len=body[0];if(len!=37+name_len||!filename(body+1,name_len))return 0;
        total=read32(body+1+name_len);if(!total||total>p->capacity||total>BT_FILE_MAX)return 0;
        memcpy(p->filename,body+1,name_len);p->total=total;memcpy(p->digest,body+5+name_len,32);
        p->received=0;p->file_state=1;e->kind=3;break;
    case 4:
        if(!(p->grants&BT_GRANT_FILE)||p->file_state!=1||len<5||len>4+BT_CHUNK_MAX||read32(body)!=p->received||len-4>p->total-p->received)return 0;
        memcpy(p->buffer+p->received,body+4,len-4);p->received+=len-4;e->kind=4;break;
    case 5:
        if(!(p->grants&BT_GRANT_FILE)||p->file_state!=1||len||p->received!=p->total)return 0;
        sha256_init(&sha);sha256_update(&sha,p->buffer,p->total);sha256_final(&sha,hash);wipe(&sha,sizeof(sha));
        if(memcmp(hash,p->digest,32)){wipe(hash,32);bt_file_release(p);return 0;}wipe(hash,32);
        p->file_state=2;e->kind=5;e->file_bytes=p->total;memcpy(e->filename,p->filename,sizeof(e->filename));break;
    case 6:
        if(!(p->grants&BT_GRANT_FILE)||len)return 0;
        bt_file_release(p);e->kind=6;break;
    default:return 0;
    }
    p->next_sequence++;return 1;
}
