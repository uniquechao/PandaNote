#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "runtime.h"
#include "../../../third_party/sha256/sha256.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static unsigned char buffer[BT_FILE_MAX];
static void put32(unsigned char *p,unsigned n){for(int i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));}
static unsigned char peer[6]={1,2,3,4,5,6};
static void ready(struct c3 *s,int dir){
 c3_init(s,buffer,sizeof buffer,dir);bt_pair_window(&s->policy,100);
 assert(c3_pair_request(s,peer,123456,101)==1);
 unsigned char zero[16]={0};assert(memcmp(s->policy.nonce,zero,16));
 assert(bt_pair_confirm(&s->policy,peer,s->policy.nonce,1,5,102));
 assert(bt_link_authorize(&s->policy,peer,7,103));
}
static size_t record(struct c3 *s,unsigned char *b,unsigned op,unsigned seq,const unsigned char *body,size_t n){
 b[0]=1;b[1]=(unsigned char)op;put32(b+2,seq);memcpy(b+6,s->policy.nonce,16);if(n)memcpy(b+22,body,n);return n+22;
}
static int send(struct c3 *s,unsigned char *b,size_t n,unsigned id,unsigned now){
 unsigned char f[20];size_t offset=0;int rc=0;
 while(offset<n){size_t take=n-offset;if(take>16)take=16;f[0]=(offset==0?1:0)|(offset+take==n?2:0);f[1]=(unsigned char)id;f[2]=(unsigned char)offset;f[3]=(unsigned char)(offset>>8);memcpy(f+4,b+offset,take);rc=c3_fragment(s,f,take+4,23,now);assert(rc==(offset+take==n?1:0));offset+=take;}
 return rc;
}
int main(int argc,char **argv){
 assert(argc==2);int dir=open(argv[1],O_RDONLY|O_DIRECTORY);assert(dir>=0);struct c3 s;ready(&s,dir);
 unsigned char b[160],body[160];body[0]=1;size_t n=record(&s,b,1,1,body,1);send(&s,b,n,7,104);
 assert(s.effect.kind==1&&s.effect.control==1&&s.policy.next_sequence==2);
 unsigned char duplicate[11]={2,7,16,0};memcpy(duplicate+4,b+16,7);assert(c3_fragment(&s,duplicate,11,23,105)==1);assert(s.policy.next_sequence==2&&s.effect_generation==1);
 struct bt_effect effect;assert(c3_take_effect(&s,&effect)==1&&effect.control==1);assert(c3_take_effect(&s,&effect)==0);
 duplicate[4]^=1;assert(c3_fragment(&s,duplicate,11,23,106)==-1);assert(s.policy.next_sequence==2&&s.effect_generation==1);
 /* Mandatory low-MTU fragmentation and invalid offsets. */
 unsigned char bad[]={0,8,1,0,1};assert(c3_fragment(&s,bad,sizeof bad,23,107)==-1);
 unsigned char large[21]={1,8,0,0};assert(c3_fragment(&s,large,sizeof large,23,107)==-1);
 /* Actual durable finalization; no replacement or symlink following. */
 const unsigned char text[]="hello\n";SHA256_CTX sha;unsigned char digest[32];sha256_init(&sha);sha256_update(&sha,text,6);sha256_final(&sha,digest);
 body[0]=8;memcpy(body+1,"book.txt",8);put32(body+9,6);memcpy(body+13,digest,32);n=record(&s,b,3,2,body,45);send(&s,b,n,9,110);assert(c3_take_effect(&s,&effect));
 put32(body,0);memcpy(body+4,text,6);n=record(&s,b,4,3,body,10);send(&s,b,n,10,111);assert(c3_take_effect(&s,&effect));
 n=record(&s,b,5,4,NULL,0);send(&s,b,n,11,112);assert(s.ack[1]==1&&s.effect.kind==5&&s.policy.file_state==0&&s.effect_generation==2);assert(c3_take_effect(&s,&effect));
 int f=openat(dir,"book.txt",O_RDONLY|O_NOFOLLOW);assert(f>=0);unsigned char got[6];assert(read(f,got,6)==6&&!memcmp(got,text,6));struct stat st;assert(!fstat(f,&st)&&(st.st_mode&0777)==0600&&st.st_nlink==1);close(f);
 assert(c3_store(dir,"book.txt",text,6)==-1);assert(!symlinkat("book.txt",dir,"link.txt"));assert(c3_store(dir,"link.txt",text,6)==-1);
 c3_tick(&s,40000);assert(s.policy.active);
 /* Timeout without traffic clears nonce/buffer/partial state; rejected provisioning. */
 ready(&s,dir);body[0]=1;n=record(&s,b,2,1,body,1);unsigned char f1[20]={1,1,0,0};memcpy(f1+4,b,16);assert(c3_fragment(&s,f1,20,23,104)==0);c3_tick(&s,5104);assert(s.assembled==0);c3_tick(&s,120103);assert(!s.policy.active&&!s.policy.nonce[0]);
 memset(buffer,7,sizeof buffer);c3_close(&s);for(size_t i=0;i<sizeof buffer;i++)assert(buffer[i]==0);
 close(dir);puts("PASS low-MTU, idempotent ACK, nonce, policy binding, owned durable file and timeout");return 0;
}
