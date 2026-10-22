#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <assert.h>
#include <fcntl.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>
static int bound_tx,bound_rx,paused;
/* Keep the actual C3 implementation unchanged. Pause precisely at its real
 * successful post-bind stat; then perform stat again after release. No fake
 * ownership/mode/inode/syscall return value is injected. */
static int controlled_stat(int dir,const char *name,struct stat *s,int flags){
 int result=fstatat(dir,name,s,flags);
 if(!paused&&!result&&!strcmp(name,"local.sock")&&S_ISSOCK(s->st_mode)){
  paused=1;assert(write(bound_tx,"B",1)==1);char command;assert(read(bound_rx,&command,1)==1&&command=='G');
  return fstatat(dir,name,s,flags);
 }
 return result;
}
#define fstatat controlled_stat
#include "../../c3/ipc.c"
#undef fstatat
int c4_socket_child(int dir,const char *path,int tx,int rx){
 bound_tx=tx;bound_rx=rx;paused=0;struct c3_ipc ipc;
 int result=c3_ipc_open(&ipc,dir,path);assert(write(tx,result?"F":"R",1)==1);
 if(result)return 2;
 /* One wrong-PID connection closes without a request; one valid health poll
  * exercises the real C4 SO_PEERCRED/framing/EOF verifier. No policy is opened. */
 for(int i=0;i<2;i++){
  struct pollfd p={ipc.socket,POLLIN,0};assert(poll(&p,1,1000)>0);int fd=accept(ipc.socket,NULL,NULL);assert(fd>=0);
  unsigned char request[24];size_t got=0;while(got<sizeof request){ssize_t n=read(fd,request+got,sizeof request-got);if(n==0)break;assert(n>0);got+=(size_t)n;}
  if(got){assert(got==sizeof request&&!memcmp(request,"OBT1",4)&&request[4]==2);unsigned char reply[48]={0};memcpy(reply,"OBT1",4);assert(write(fd,reply,sizeof reply)==sizeof reply);}
  else assert(i==0);
  close(fd);
 }
 return c3_ipc_close(&ipc)?3:0;
}
