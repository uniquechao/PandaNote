#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "ipc.h"
#include <assert.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
static void malformed(struct c3_ipc *ipc,struct c3 *state){
 pid_t p=fork();assert(p>=0);if(!p){int fd=socket(AF_UNIX,SOCK_STREAM,0);struct sockaddr_un a;memset(&a,0,sizeof a);a.sun_family=AF_UNIX;strcpy(a.sun_path,ipc->path);assert(!connect(fd,(struct sockaddr *)&a,sizeof a));unsigned char bad[24]={0};assert(write(fd,bad,sizeof bad)==sizeof bad);close(fd);_exit(0);}
 for(int i=0;i<20;i++){assert(c3_ipc_poll(ipc,state,99)>=0);struct timespec t={0,1000000};nanosleep(&t,NULL);}int status;assert(waitpid(p,&status,0)==p&&WIFEXITED(status)&&WEXITSTATUS(status)==0);
}
static void roundtrip(struct c3_ipc *ipc,struct c3 *s,unsigned char request[24],unsigned flags,unsigned status,unsigned now){
 pid_t child=fork();assert(child>=0);
 if(!child){int fd=socket(AF_UNIX,SOCK_STREAM,0);struct sockaddr_un a;memset(&a,0,sizeof a);a.sun_family=AF_UNIX;strcpy(a.sun_path,ipc->path);assert(!connect(fd,(struct sockaddr *)&a,sizeof a));assert(write(fd,request,24)==24);unsigned char reply[48];size_t n=0;while(n<48){ssize_t got=read(fd,reply+n,48-n);assert(got>0);n+=(size_t)got;}assert(!memcmp(reply,"OBT1",4)&&reply[4]==status&&reply[5]==flags);if(request[4]==5&&!request[5]&&!request[6])assert(reply[38]==1&&reply[7]==2&&reply[44]==1);close(fd);_exit(0);}
 int result=0;for(int i=0;i<30&&result==0;i++){result=c3_ipc_poll(ipc,s,now);struct timespec t={0,1000000};nanosleep(&t,NULL);}assert(result==1);int status_code;assert(waitpid(child,&status_code,0)==child&&WIFEXITED(status_code)&&WEXITSTATUS(status_code)==0);
}
int main(int argc,char **argv){assert(argc==2);int dir=open(argv[1],O_RDONLY|O_DIRECTORY);assert(dir>=0);struct c3_ipc ipc,other;struct c3 s;unsigned char buffer[32],request[24]={0},peer[6]={1,2,3,4,5,6};c3_init(&s,buffer,sizeof buffer,dir);assert(!c3_ipc_open(&ipc,dir,argv[1]));assert(c3_ipc_open(&other,dir,argv[1])==-1);malformed(&ipc,&s);struct stat st;assert(!fstatat(dir,"local.sock",&st,AT_SYMLINK_NOFOLLOW)&&(st.st_mode&0777)==0600);memcpy(request,"OBT1",4);request[4]=1;roundtrip(&ipc,&s,request,0,0,100);assert(c3_pair_request(&s,peer,123456,101));request[4]=3;request[5]=5;request[6]=1;roundtrip(&ipc,&s,request,1,1,102);memcpy(request+8,s.policy.nonce,16);roundtrip(&ipc,&s,request,2,0,103);s.effect.kind=1;s.effect.control=2;s.effect_generation=1;request[4]=5;request[5]=request[6]=0;memset(request+8,0,16);roundtrip(&ipc,&s,request,2,0,104);roundtrip(&ipc,&s,request,2,0,105);assert(s.effect.kind==1);request[5]=1;memcpy(request+8,s.policy.nonce,16);roundtrip(&ipc,&s,request,2,0,106);assert(!s.effect.kind);roundtrip(&ipc,&s,request,2,0,107);request[4]=4;roundtrip(&ipc,&s,request,0,0,108);assert(!s.policy.active&&!s.policy.pending);assert(!c3_ipc_close(&ipc));assert(fstatat(dir,"local.sock",&st,AT_SYMLINK_NOFOLLOW)==-1);assert(!symlinkat("outside",dir,"local.sock"));assert(c3_ipc_open(&other,dir,argv[1])==-1);assert(!fstatat(dir,"local.sock",&st,AT_SYMLINK_NOFOLLOW)&&S_ISLNK(st.st_mode));close(dir);puts("PASS private IPC credentials/modes/exclusivity, exact nonce, deny/cancel, owned unlink");return 0;}
