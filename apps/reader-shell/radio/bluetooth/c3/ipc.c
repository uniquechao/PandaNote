#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "ipc.h"
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>
static int64_t clock_ms(void){struct timespec t;
 if(clock_gettime(CLOCK_MONOTONIC,&t))return -1;
 return (int64_t)t.tv_sec*1000+t.tv_nsec/1000000;
 }
static void put32(unsigned char *p,uint32_t n){for(int i=0; i<4; i++)p[i]=(unsigned char)(n>>(8*i));
 }
static int same_user(int fd){
#ifdef __linux__
 struct ucred c;
 socklen_t n=sizeof c;
 return getsockopt(fd,SOL_SOCKET,SO_PEERCRED,&c,&n)==0&&n==sizeof c&&c.uid==geteuid();
#else
 uid_t uid;
 gid_t gid;
 return getpeereid(fd,&uid,&gid)==0&&uid==geteuid();
#endif
}
int c3_ipc_open(struct c3_ipc *ipc,int dir,const char *path){
 memset(ipc,0,sizeof *ipc);
 ipc->socket=ipc->lock=-1;
 ipc->directory=dir;
 struct stat given,opened;
 if(!path||path[0]!='/'||strlen(path)+12>=sizeof ipc->path||fstat(dir,&given)||!S_ISDIR(given.st_mode)||given.st_uid!=geteuid()||(given.st_mode&07777)!=0700)return -1;
 int check=open(path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
 if(check<0)return -1;
 int ok=!fstat(check,&opened)&&opened.st_dev==given.st_dev&&opened.st_ino==given.st_ino;
 close(check);
 if(!ok)return -1;
 ipc->lock=openat(dir,"local.lock",O_RDWR|O_CREAT|O_NOFOLLOW|O_CLOEXEC,0600);
 if(ipc->lock<0||fstat(ipc->lock,&opened)||!S_ISREG(opened.st_mode)||opened.st_uid!=geteuid()||opened.st_nlink!=1||(opened.st_mode&07777)!=0600||flock(ipc->lock,LOCK_EX|LOCK_NB))goto fail;
 if(!fstatat(dir,"local.sock",&opened,AT_SYMLINK_NOFOLLOW)||errno!=ENOENT)goto fail;
 snprintf(ipc->path,sizeof ipc->path,"%s/local.sock",path);
 ipc->socket=socket(AF_UNIX,SOCK_STREAM,0);
 if(ipc->socket<0||fcntl(ipc->socket,F_SETFD,FD_CLOEXEC)||fcntl(ipc->socket,F_SETFL,O_NONBLOCK))goto fail;
 struct sockaddr_un address;
 memset(&address,0,sizeof address);
 address.sun_family=AF_UNIX;
 if(strlen(ipc->path)>=sizeof address.sun_path)goto fail;
 strcpy(address.sun_path,ipc->path);
 mode_t old=umask(077);
 int bound=bind(ipc->socket,(struct sockaddr *)&address,sizeof address);
 umask(old);
 if(bound)goto fail;
 if(fstatat(dir,"local.sock",&opened,AT_SYMLINK_NOFOLLOW)||!S_ISSOCK(opened.st_mode)||opened.st_uid!=geteuid()||(opened.st_mode&07777)!=0700)goto fail;
 ipc->device=opened.st_dev;
 ipc->inode=opened.st_ino;
 if(fchmodat(dir,"local.sock",0600,0)||listen(ipc->socket,1))goto fail;
 return 0;
 fail:(void)c3_ipc_close(ipc);
 return -1;
}
int c3_ipc_close(struct c3_ipc *ipc){int result=0;
 if(ipc->socket>=0){close(ipc->socket);
 ipc->socket=-1;
 }if(ipc->inode){struct stat s;
 if(fstatat(ipc->directory,"local.sock",&s,AT_SYMLINK_NOFOLLOW)||!S_ISSOCK(s.st_mode)||s.st_ino!=ipc->inode||s.st_dev!=ipc->device||unlinkat(ipc->directory,"local.sock",0))result=-1;
 ipc->inode=0;
 }if(ipc->lock>=0){close(ipc->lock);
 ipc->lock=-1;
 }return result;
 }
static int transfer(int fd,unsigned char *data,size_t size,int writing){
 size_t offset=0;
 int64_t end=clock_ms()+100;
 while(offset<size){int64_t left=end-clock_ms();
 if(left<=0)return -1;
 struct pollfd p={fd,writing?POLLOUT:POLLIN,0};
 int n=poll(&p,1,(int)left);
 if(n<0&&errno==EINTR)continue;
 if(n<=0)return -1;
 ssize_t count=writing?send(fd,data+offset,size-offset,
#ifdef MSG_NOSIGNAL
 MSG_NOSIGNAL
#else
 0
#endif
 ):recv(fd,data+offset,size-offset,0);
 if(count>0)offset+=(size_t)count;
 else if(count<0&&(errno==EINTR||errno==EAGAIN))continue;
 else return -1;
 }return 0;
}
int c3_ipc_poll(struct c3_ipc *ipc,struct c3 *state,uint64_t now){
 c3_tick(state,now);
 int fd=accept(ipc->socket,NULL,NULL);
 if(fd<0)return errno==EAGAIN||errno==EWOULDBLOCK?0:-1;
 int result=0;
 if(fcntl(fd,F_SETFD,FD_CLOEXEC)||fcntl(fd,F_SETFL,O_NONBLOCK)||!same_user(fd))goto done;
#ifdef SO_NOSIGPIPE
 int yes=1;
 if(setsockopt(fd,SOL_SOCKET,SO_NOSIGPIPE,&yes,sizeof yes))goto done;
#endif
 unsigned char request[24],reply[48]={0};
 if(transfer(fd,request,sizeof request,0)||memcmp(request,"OBT1",4)||request[7])goto done;
 unsigned char extra;
 if(recv(fd,&extra,1,MSG_PEEK|MSG_DONTWAIT)>0)goto done;
 int ok=0;
 unsigned op=request[4];
 if(op==1){c3_close(state);
 bt_pair_window(&state->policy,now);
 ok=1;
 }
 else if(op==2)ok=1;
 else if(op==3)ok=bt_pair_confirm(&state->policy,state->policy.peer,request+8,request[6],request[5],now);
 else if(op==4){c3_close(state);
 ok=1;
 }
 else if(op==5){
 unsigned id=(unsigned)request[5]|((unsigned)request[6]<<8);
 if(memcmp(ipc->event_nonce,state->policy.nonce,16)){
  ipc->event=ipc->last_ack=0;memcpy(ipc->event_nonce,state->policy.nonce,16);memset(ipc->last_ack_nonce,0,16);
 }
 /* Bind every actual queued generation before interpreting ANY ACK. A
  * duplicate ACK must not identify a newer effect that has not been peeked.
  * Producer identity also survives a trusted alternate take_effect(). */
 if(state->effect.kind==1||state->effect.kind==5){
  if(!state->effect_generation||state->effect_generation>65535)c3_close(state);
  else ipc->event=state->effect_generation;
 }
 if(id){
  if(!memcmp(request+8,state->policy.nonce,16)){
   if(id==ipc->event&&state->effect.kind){bt_effect_clear(&state->effect);ipc->last_ack=id;memcpy(ipc->last_ack_nonce,request+8,16);ok=1;}
   else if(id==ipc->last_ack&&!memcmp(request+8,ipc->last_ack_nonce,16))ok=1;
  }
 }else{
  ok=1;reply[7]=(unsigned char)state->effect.control;reply[38]=(unsigned char)state->effect.kind;put32(reply+40,(uint32_t)state->effect.file_bytes);
  if(state->effect.kind){reply[44]=(unsigned char)ipc->event;reply[45]=(unsigned char)(ipc->event>>8);}
 }
 }
 memcpy(reply,"OBT1",4);
 reply[4]=(unsigned char)(ok?0:1);
 reply[5]=(unsigned char)((state->policy.pending?1:0)|(state->policy.approved?2:0)|(state->policy.active?4:0));
 reply[6]=(unsigned char)state->policy.grants;
 put32(reply+8,state->passkey);
 memcpy(reply+12,state->policy.nonce,16);
 uint64_t until=state->policy.active?state->policy.session_until:state->policy.pending_until;
 put32(reply+28,until>now?(uint32_t)(until-now):0);
 memcpy(reply+32,state->policy.peer,6);
 result=transfer(fd,reply,sizeof reply,1)?0:1;
 done:close(fd);
 return result;
}
