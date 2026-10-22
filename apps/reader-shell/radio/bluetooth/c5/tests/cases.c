#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "runner.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
int main(int argc,char **argv){
 assert(argc==3);int executable=open(argv[1],O_RDONLY|O_CLOEXEC);assert(executable>=3);
 for(int mode=0;mode<3;mode++){
  char root[256],path[512];snprintf(root,sizeof root,"%s/case-%d",argv[2],mode);assert(!mkdir(root,0700));snprintf(path,sizeof path,"%s/log",root);int log=open(path,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);assert(log>=3);
  char *args[]={argv[1],root,"0",mode==1?"die":mode==2?"ignore":"wait","16384",NULL};char *env[]={"PATH=/usr/bin:/bin",NULL};struct c4_program program={executable,log,args,env,32,16384,30};volatile sig_atomic_t stop=0;struct c5_result result;
  pid_t sentinel=fork();assert(sentinel>=0);if(!sentinel)for(;;)pause();
  int status,code=c5_run(&program,&stop,100,&result);assert(!kill(sentinel,0));assert(!kill(sentinel,SIGTERM));assert(waitpid(sentinel,&status,0)==sentinel);
  assert(code==(mode==1?4:0));assert(result.reaped&&result.child.reaped&&result.elapsed_ms>=0&&result.elapsed_ms<1500);if(mode==2)assert(result.killed);if(mode==0)assert(result.elapsed_ms>=100);close(log);
 }
 close(executable);puts("PASS C5 owned bounded attach core: timeout, early exit, KILL/reap, unrelated sentinel");return 0;
}
