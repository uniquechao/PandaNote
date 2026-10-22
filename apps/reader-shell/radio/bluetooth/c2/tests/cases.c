#define _GNU_SOURCE
#include "core.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
static void nap(void){usleep(20000);}
int main(int argc,char **argv) {
 assert(argc==3); umask(077);
 int d=open(argv[2],O_RDONLY|O_DIRECTORY);assert(d>=0);
 int sub=c2_dir(d,"private");assert(sub>=0);struct stat st;assert(!fstat(sub,&st)&&((st.st_mode&0777)==0700));
 assert(c2_dir(d,"../bad")<0);
 assert(!symlinkat("private",d,"link"));assert(c2_dir(d,"link")<0);
 assert(!mkdirat(d,"wide",0755));assert(!fchmodat(d,"wide",0755,0));assert(c2_dir(d,"wide")<0);
 int f=c2_file(sub,"log",1);assert(f>=0);assert(!fstat(f,&st)&&(st.st_mode&0777)==0600);
 assert(c2_file(sub,"log",1)<0);assert(c2_file(sub,"../bad",1)<0);
 assert(!c2_hash(f,"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",4096));
 assert(c2_hash(f,"0000000000000000000000000000000000000000000000000000000000000000",4096)<0);
 assert(!c2_lock(f));int other=openat(sub,"log",O_RDWR);assert(other>=0&&c2_lock(other)<0);close(other);
 assert(c2_empty(sub)<0);
 int exe=open(argv[1],O_RDONLY);assert(exe>=0);char *args[]={argv[1],"ignore",NULL};char *env[]={"PATH=/usr/bin:/bin",NULL};struct child c={0};
 assert(!c2_spawn(&c,exe,args,env,f,64));int64_t deadline=c2_now()+2000;
 while(c2_now()<deadline){assert(!fstat(f,&st));if(st.st_size>=6)break;nap();}assert(st.st_size>=6);
 pid_t sentinel=fork();assert(sentinel>=0);if(!sentinel){for(;;)pause();}
 assert(c2_alive(&c)==1);int64_t start=c2_now();assert(!c2_stop(&c));assert(c.reaped&&WIFSIGNALED(c.status)&&WTERMSIG(c.status)==SIGKILL);assert(c2_now()-start<2000);
 assert(!kill(sentinel,0));assert(!kill(sentinel,SIGTERM));assert(waitpid(sentinel,NULL,0)==sentinel);
 assert(!c2_stop(&c));assert(waitpid(c.pid,NULL,WNOHANG)<0&&errno==ECHILD);
 c=(struct child){0};args[1]="exit";assert(!c2_spawn(&c,exe,args,env,f,64));while(c2_alive(&c)==1)nap();assert(c.reaped&&WIFEXITED(c.status)&&WEXITSTATUS(c.status)==17);
 c=(struct child){0};args[1]="flood";assert(!ftruncate(f,0));assert(!lseek(f,0,SEEK_SET));assert(!c2_spawn(&c,exe,args,env,f,64));deadline=c2_now()+2000;while(c2_alive(&c)==1&&c2_now()<deadline)nap();assert(!c2_stop(&c));assert(!fstat(f,&st)&&st.st_size<=16384);
 c=(struct child){0};assert(c2_spawn(&c,-1,args,env,f,64)<0);assert(!c.pid);
 c=(struct child){0};assert(c2_spawn(&c,f,args,env,f,64)<0);assert(c.reaped&&WIFEXITED(c.status)&&WEXITSTATUS(c.status)==126);
 close(exe);close(f);assert(!unlinkat(sub,"log",0));assert(!c2_empty(sub));
 unsigned count=0,bytes=0;int keys=c2_dir(sub,"keys");assert(keys>=0);
 int key=c2_file(keys,"key",1);assert(key>=0&&write(key,"secret",6)==6);close(key);close(keys);
 assert(!c2_erase(sub,0,&count,&bytes)&&count==2&&bytes==6&&!c2_empty(sub));
 assert(!symlinkat("../wide",sub,"escape"));count=bytes=0;assert(c2_erase(sub,0,&count,&bytes)<0);
 assert(!fstatat(d,"wide",&st,0)&&S_ISDIR(st.st_mode));assert(!unlinkat(sub,"escape",0));
 key=c2_file(sub,"large",1);assert(key>=0&&!ftruncate(key,65537));close(key);count=bytes=0;
 assert(c2_erase(sub,0,&count,&bytes)<0);assert(!unlinkat(sub,"large",0));
 struct child alien={getppid(),0,0};assert(c2_stop(&alien)<0);assert(!kill(getppid(),0));close(sub);close(d);
 puts("PASS native: exact modes / nofollow / hash / lock / TERM-KILL-reap / unrelated child / exit / log cap / spawn failure");return 0;
}
