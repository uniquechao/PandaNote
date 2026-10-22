#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "ipc.h"
#include "../../../third_party/sha256/sha256.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
static unsigned char buffer[BT_FILE_MAX];
static unsigned char peer[6]={1,2,3,4,5,6};
static unsigned clock_value=200;
static void put32(unsigned char *p,unsigned n){for(unsigned i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));}
static unsigned event_id(const unsigned char *reply){return (unsigned)reply[44]|((unsigned)reply[45]<<8);}
static void ready(struct c3 *s,int dir){
 c3_init(s,buffer,sizeof buffer,dir);bt_pair_window(&s->policy,100);assert(c3_pair_request(s,peer,123456,101));assert(bt_pair_confirm(&s->policy,peer,s->policy.nonce,1,5,102));assert(bt_link_authorize(&s->policy,peer,7,103));
}
static void exchange(struct c3_ipc *ipc,struct c3 *s,const unsigned char request[24],unsigned char reply[48],int lose){
 int pipefd[2];assert(!pipe(pipefd));pid_t child=fork();assert(child>=0);
 if(!child){close(pipefd[0]);int fd=socket(AF_UNIX,SOCK_STREAM,0);assert(fd>=0);struct sockaddr_un a;memset(&a,0,sizeof a);a.sun_family=AF_UNIX;strcpy(a.sun_path,ipc->path);assert(!connect(fd,(struct sockaddr *)&a,sizeof a));assert(write(fd,request,24)==24);
  unsigned char received[48];size_t n=0;while(n<48){ssize_t count=read(fd,received+n,48-n);assert(count>0);n+=(size_t)count;}
  /* A lost UI reply is a response delivered by the kernel that the UI never
   * records. Server cannot distinguish this from success; retry must be safe. */
  if(!lose)assert(write(pipefd[1],received,sizeof received)==sizeof received);
  close(fd);close(pipefd[1]);_exit(0);
 }
 close(pipefd[1]);int result=0;
 for(unsigned i=0;i<100&&result==0;i++){result=c3_ipc_poll(ipc,s,clock_value++);struct timespec delay={0,1000000};nanosleep(&delay,NULL);}
 assert(result==1);int status;assert(waitpid(child,&status,0)==child&&WIFEXITED(status)&&WEXITSTATUS(status)==0);
 if(!lose)assert(read(pipefd[0],reply,48)==48);
 close(pipefd[0]);
}
static void peek(struct c3_ipc *ipc,struct c3 *s,unsigned char reply[48],int lose){unsigned char request[24]={0};memcpy(request,"OBT1",4);request[4]=5;exchange(ipc,s,request,reply,lose);if(!lose)assert(reply[4]==0);}
static void acknowledge(struct c3_ipc *ipc,struct c3 *s,unsigned id,const unsigned char nonce[16],unsigned wanted){
 unsigned char request[24]={0},reply[48];memcpy(request,"OBT1",4);request[4]=5;request[5]=(unsigned char)id;request[6]=(unsigned char)(id>>8);memcpy(request+8,nonce,16);exchange(ipc,s,request,reply,0);assert(reply[4]==wanted);
}
static void acknowledge_lost(struct c3_ipc *ipc,struct c3 *s,unsigned id,const unsigned char nonce[16]){
 unsigned char request[24]={0},ignored[48];memcpy(request,"OBT1",4);request[4]=5;request[5]=(unsigned char)id;request[6]=(unsigned char)(id>>8);memcpy(request+8,nonce,16);exchange(ipc,s,request,ignored,1);
}
static void record(struct c3 *s,unsigned sequence,unsigned opcode,const unsigned char *body,size_t size){
 unsigned char bytes[C3_RECORD_MAX]={1,(unsigned char)opcode};put32(bytes+2,sequence);memcpy(bytes+6,s->policy.nonce,16);if(size)memcpy(bytes+22,body,size);size+=22;
 for(size_t offset=0;offset<size;){unsigned char fragment[20];size_t take=size-offset;if(take>16)take=16;fragment[0]=(offset?0:1)|(offset+take==size?2:0);fragment[1]=(unsigned char)sequence;fragment[2]=(unsigned char)offset;fragment[3]=0;memcpy(fragment+4,bytes+offset,take);int result=c3_fragment(s,fragment,take+4,23,clock_value++);assert(result==(offset+take==size?1:0));offset+=take;}
}
static void control(struct c3 *s,unsigned sequence){const unsigned char home=1;record(s,sequence,1,&home,1);assert(s->effect.kind==1&&s->effect.control==1);}
static void committed_file(struct c3 *s,unsigned sequence){
 const unsigned char text[]="hello\n";SHA256_CTX sha;unsigned char body[64],digest[32];sha256_init(&sha);sha256_update(&sha,text,6);sha256_final(&sha,digest);body[0]=8;memcpy(body+1,"book.txt",8);put32(body+9,6);memcpy(body+13,digest,32);record(s,sequence,3,body,45);assert(s->effect.kind==3);bt_effect_clear(&s->effect);put32(body,0);memcpy(body+4,text,6);record(s,sequence+1,4,body,10);assert(s->effect.kind==4);bt_effect_clear(&s->effect);record(s,sequence+2,5,NULL,0);assert(s->effect.kind==5&&s->effect.file_bytes==6);
}
int main(int argc,char **argv){
 assert(argc==2);int dir=open(argv[1],O_RDONLY|O_DIRECTORY);assert(dir>=0);struct c3 s;struct c3_ipc ipc;unsigned char reply[48],nonce[16];ready(&s,dir);assert(!c3_ipc_open(&ipc,dir,argv[1]));memcpy(nonce,s.policy.nonce,16);
 control(&s,1);peek(&ipc,&s,reply,0);unsigned first=event_id(reply);assert(first);acknowledge_lost(&ipc,&s,first,nonce);assert(!s.effect.kind);
 control(&s,2);acknowledge(&ipc,&s,first,nonce,0);assert(s.effect.kind==1); /* Frozen-source RED: old ACK consumes new unpublished event. */
 peek(&ipc,&s,reply,0);unsigned second=event_id(reply);assert(second&&second!=first);acknowledge(&ipc,&s,first,nonce,0);assert(s.effect.kind==1);peek(&ipc,&s,reply,1);assert(s.effect.kind==1);peek(&ipc,&s,reply,0);assert(event_id(reply)==second);acknowledge(&ipc,&s,second,nonce,0);assert(!s.effect.kind);acknowledge(&ipc,&s,second,nonce,0);
 committed_file(&s,3);acknowledge(&ipc,&s,second,nonce,0);assert(s.effect.kind==5);peek(&ipc,&s,reply,1);assert(s.effect.kind==5);peek(&ipc,&s,reply,0);unsigned third=event_id(reply);assert(third&&third!=second&&reply[38]==5&&reply[40]==6);acknowledge(&ipc,&s,second,nonce,0);assert(s.effect.kind==5);acknowledge(&ipc,&s,third,nonce,0);assert(!s.effect.kind);
 /* A trusted alternate take of a published effect cannot make the next equal
  * payload reuse its old identity. Production currently uses only IPC delivery. */
 control(&s,6);peek(&ipc,&s,reply,0);unsigned fourth=event_id(reply);struct bt_effect taken;assert(c3_take_effect(&s,&taken));control(&s,7);acknowledge(&ipc,&s,fourth,nonce,1);assert(s.effect.kind==1);peek(&ipc,&s,reply,0);unsigned fifth=event_id(reply);assert(fifth!=fourth);acknowledge(&ipc,&s,fifth,nonce,0);
 control(&s,8);unsigned char overwrite[20]={1,99,0,0,1,1,9,0,0,0};memcpy(overwrite+10,nonce,10);assert(c3_fragment(&s,overwrite,sizeof overwrite,23,clock_value++)==-1);assert(s.effect.kind==1&&s.policy.next_sequence==9);acknowledge(&ipc,&s,fifth,nonce,0);assert(s.effect.kind==1);peek(&ipc,&s,reply,0);unsigned sixth=event_id(reply);assert(sixth!=fifth);acknowledge(&ipc,&s,sixth,nonce,0);
 /* Old session ACK with the same numeric ID still cannot clear new-session
  * effect; identity includes the OS-random nonce as well as the generation. */
 c3_close(&s);ready(&s,dir);control(&s,1);acknowledge(&ipc,&s,first,nonce,1);assert(s.effect.kind==1);peek(&ipc,&s,reply,0);assert(memcmp(reply+12,nonce,16));memcpy(nonce,reply+12,16);acknowledge(&ipc,&s,event_id(reply),nonce,0);
 s.effect_generation=65535;unsigned char exhausted[20]={1,99,0,0,1,1,2,0,0,0};assert(c3_fragment(&s,exhausted,sizeof exhausted,23,clock_value++)==-1);assert(!s.policy.active&&!s.effect.kind&&!s.effect_generation);
 assert(!c3_ipc_close(&ipc));c3_close(&s);close(dir);puts("PASS producer-bound CONTROL/FILE identity, stale ACK before/after peek, lost reply, alternate consume, pending queue and nonce change");return 0;
}
