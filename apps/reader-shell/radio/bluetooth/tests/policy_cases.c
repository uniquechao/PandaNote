#include <stdio.h>
#include <string.h>
#include "../policy.h"
static int failures;static unsigned char storage[512],peer[]={1,2,3,4,5,6},nonce[16]={1};
static struct bt_policy p;static struct bt_effect effect;static unsigned char frame[256];
#define CHECK(x) do {if(!(x)){fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x);failures++;}}while(0)
static void ready(unsigned grant) {
    bt_policy_init(&p,storage,sizeof(storage));bt_pair_window(&p,100);
    CHECK(bt_pair_request(&p,peer,123456,nonce,101));
    CHECK(bt_pair_confirm(&p,peer,nonce,1,grant,102));
    CHECK(bt_link_authorize(&p,peer,7,103));
}
static size_t packet(unsigned op,unsigned seq,const void *data,size_t n) {
    memset(frame,0,sizeof(frame));frame[0]=1;frame[1]=op;
    frame[2]=seq&255;frame[3]=(seq>>8)&255;frame[4]=(seq>>16)&255;frame[5]=seq>>24;
    memcpy(frame+6,nonce,16);if(n)memcpy(frame+22,data,n);return n+22;
}
int main(void) {
    size_t n;unsigned char zero[512]={0};unsigned char command=1;
    bt_policy_init(&p,storage,sizeof(storage));
    CHECK(!bt_pair_request(&p,peer,123456,nonce,1));
    bt_pair_window(&p,100);CHECK(!bt_pair_request(&p,peer,1000000,nonce,101));
    CHECK(!bt_pair_request(&p,peer,123456,nonce,60100));
    bt_pair_window(&p,100);CHECK(bt_pair_request(&p,peer,123456,nonce,101));
    unsigned char wrong[16]={2};CHECK(!bt_pair_confirm(&p,peer,wrong,1,7,102));
    CHECK(!bt_pair_confirm(&p,peer,nonce,1,5,30101));
    ready(5);n=packet(1,1,&command,1);
    CHECK(bt_frame(&p,frame,n,104,&effect)&&effect.kind==1&&effect.control==1);
    CHECK(!bt_frame(&p,frame,n,105,&effect)&&!effect.kind);
    n=packet(1,3,&command,1);CHECK(!bt_frame(&p,frame,n,106,&effect));
    command=9;n=packet(1,2,&command,1);CHECK(!bt_frame(&p,frame,n,107,&effect));
    command=2;n=packet(1,2,&command,1);frame[6]=2;CHECK(!bt_frame(&p,frame,n,108,&effect));frame[6]=1;
    CHECK(bt_frame(&p,frame,n,109,&effect)&&effect.control==2);
    CHECK(!bt_frame(&p,frame,n,120103,&effect)&&!p.active);
    bt_pair_window(&p,200);CHECK(bt_pair_request(&p,peer,123456,nonce,201));
    CHECK(bt_pair_confirm(&p,peer,nonce,1,5,202));
    CHECK(!bt_link_authorize(&p,peer,3,203));
    ready(5);n=packet(2,1,NULL,0);CHECK(!bt_frame(&p,frame,n,104,&effect));
    ready(4);
    /* SHA256("abc"), independently published test vector. */
    unsigned char begin[64]={5,'b','.','t','x','t',3,0,0,0,0xba,0x78,0x16,0xbf,0x8f,0x01,0xcf,0xea,0x41,0x41,0x40,0xde,0x5d,0xae,0x22,0x23,0xb0,0x03,0x61,0xa3,0x96,0x17,0x7a,0x9c,0xb4,0x10,0xff,0x61,0xf2,0x00,0x15,0xad};
    n=packet(3,1,begin,42);frame[23]='/';CHECK(!bt_frame(&p,frame,n,104,&effect));
    frame[23]='b';memcpy(frame+25,"exe",3);CHECK(!bt_frame(&p,frame,n,104,&effect));
    memcpy(frame+25,"txt",3);frame[28]=0xff;frame[29]=2;CHECK(!bt_frame(&p,frame,n,104,&effect));
    n=packet(3,1,begin,42);CHECK(bt_frame(&p,frame,n,104,&effect)&&p.file_state==1);
    CHECK(!bt_frame(&p,frame,n,105,&effect));
    unsigned char chunk[]={0,0,0,0,'a','b','c'};
    n=packet(4,2,chunk,sizeof(chunk));frame[22]=1;CHECK(!bt_frame(&p,frame,n,106,&effect)&&p.received==0);
    frame[22]=0;CHECK(bt_frame(&p,frame,n,107,&effect)&&p.received==3);
    n=packet(5,3,NULL,0);CHECK(bt_frame(&p,frame,n,108,&effect)&&effect.kind==5&&effect.file_bytes==3&&!strcmp(effect.filename,"b.txt")&&!memcmp(storage,"abc",3)&&p.file_state==2);
    bt_file_release(&p);CHECK(!p.file_state&&!memcmp(storage,zero,3));
    ready(4);n=packet(3,1,begin,42);CHECK(bt_frame(&p,frame,n,104,&effect));
    chunk[4]='x';n=packet(4,2,chunk,7);CHECK(bt_frame(&p,frame,n,105,&effect));
    n=packet(5,3,NULL,0);CHECK(!bt_frame(&p,frame,n,106,&effect)&&!p.file_state&&!memcmp(storage,zero,3));
    ready(4);n=packet(3,1,begin,42);CHECK(bt_frame(&p,frame,n,104,&effect));
    n=packet(4,2,chunk,7);CHECK(bt_frame(&p,frame,n,105,&effect));
    bt_policy_close(&p);CHECK(!p.active&&!p.approved&&!memcmp(storage,zero,sizeof(storage)));
    ready(4);n=packet(3,1,begin,42);CHECK(bt_frame(&p,frame,n,104,&effect));
    n=packet(4,2,chunk,7);CHECK(bt_frame(&p,frame,n,105,&effect));
    command=0;n=packet(1,3,&command,1);CHECK(!bt_frame(&p,frame,n,106,&effect));
    n=packet(6,3,NULL,0);CHECK(bt_frame(&p,frame,n,107,&effect)&&effect.kind==6&&!p.file_state&&!memcmp(storage,zero,sizeof(storage)));
    ready(4);n=packet(3,1,begin,42);CHECK(bt_frame(&p,frame,n,104,&effect));
    n=packet(4,2,chunk,7);CHECK(bt_frame(&p,frame,n,105,&effect));
    n=packet(5,3,NULL,0);CHECK(!bt_frame(&p,frame,n,120103,&effect)&&!p.active&&!memcmp(storage,zero,sizeof(storage)));
    ready(1);command=0;n=packet(1,1,&command,1);frame[0]=2;CHECK(!bt_frame(&p,frame,n,104,&effect));
    frame[0]=1;CHECK(!bt_frame(&p,frame,21,104,&effect));
    CHECK(!bt_frame(&p,frame,sizeof(frame),104,&effect));
    CHECK(!bt_frame(&p,frame,n,102,&effect)&&!p.active);
    bt_pair_window(&p,100);CHECK(bt_pair_request(&p,peer,123456,nonce,101));
    CHECK(!bt_pair_confirm(&p,peer,nonce,1,2,102));
    printf("policy fixture failures=%d\n",failures);return failures?1:0;
}
