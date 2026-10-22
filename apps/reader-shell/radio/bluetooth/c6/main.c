#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "preflight.h"
#include "controller.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/resource.h>
#include <unistd.h>
#define ROOT "/tmp/pandanote-connectivity/bluetooth"
static volatile sig_atomic_t stopping;
static void stop(int signal){(void)signal;stopping=1;}
static int empty_or_absent(int parent,const char *name){int fd=openat(parent,name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return errno==ENOENT?0:-1;struct stat s;int code=fstat(fd,&s)||s.st_uid||(s.st_mode&07777)!=0700||c2_empty(fd);close(fd);return code?-1:0;}
int main(int argc,char **argv){
 if(argc!=3||strcmp(argv[1],"--enable-owned-transport")){puts("C6 disabled; explicit --enable-owned-transport ABS_PRIVATE_INBOX required; no power setup");return 2;}
 if(geteuid()!=0)return 3;
 int content=c6_inbox(argv[2]);if(content<0)return 3;
 umask(077);struct sigaction action;memset(&action,0,sizeof action);action.sa_handler=stop;sigemptyset(&action.sa_mask);if(sigaction(SIGTERM,&action,NULL)||sigaction(SIGINT,&action,NULL)){close(content);return 3;}action.sa_handler=SIG_DFL;if(sigaction(SIGCHLD,&action,NULL)){close(content);return 3;}
 struct rlimit core={0,0},memory={12*1024*1024,64*1024*1024},stack={512*1024,512*1024};if(setrlimit(RLIMIT_CORE,&core)||setrlimit(RLIMIT_AS,&memory)||setrlimit(RLIMIT_STACK,&stack)){close(content);return 3;}
 int code=4,tmp=-1,parent=-1,base=-1,lock=-1,dir=-1,tl=-1,sl=-1,attach=-1,supervisor=-1;struct c6_result result;memset(&result,0,sizeof result);struct c6_controller controller={-1,-1,{0}};
 tmp=open("/tmp",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);struct stat temporary;if(tmp<0||fstat(tmp,&temporary)||temporary.st_uid||((temporary.st_mode&0022)&&(temporary.st_mode&07777)!=01777))goto done;
 parent=c2_dir(tmp,"pandanote-connectivity");if(parent<0)goto done;base=c2_dir(parent,"bluetooth");if(base<0)goto done;
 lock=c2_file(base,"transport.lock",1);if(lock<0)lock=c2_file(base,"transport.lock",0);if(lock<0||c2_lock(lock)||empty_or_absent(base,"attach"))goto done;
 /* Never archive/erase ended C5 evidence, claim an existing C6 session, or retry. */
 dir=c2_dir(base,"attach-session");if(dir<0||c2_empty(dir))goto done;
 supervisor=c6_pin(ROOT "/bin/pandanote-bt-supervisor","88b008d1371e5b476ab78f25a7544f8902f9b9beca7ce894c73c9dc732db29ad",74748,0700);if(supervisor<0)goto done;
 attach=c6_preflight();if(attach<0)goto done;
 controller.directory=open("/sys/class/bluetooth",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(controller.directory<0||c2_empty(controller.directory))goto done;
 tl=c2_file(dir,"attach.log",1);sl=c2_file(dir,"c4.log",1);if(tl<0||sl<0)goto done;
 char *ta[]={"btattach","-P","h4","-S","1500000","-B","/dev/ttyS3",NULL};char *sa[]={"pandanote-bt-supervisor","--enable-private-session",argv[2],NULL};char *env[]={"PATH=/usr/bin:/bin","HOME=" ROOT,NULL};
 struct c6_plan plan={{attach,tl,ta,env,8,16384,500},{supervisor,sl,sa,env,64,262144,500},&stopping,c6_controller_ready,c6_controller_healthy,&controller,12000,1000};
 puts("{\"stage\":\"owned-transport-starting\",\"phone_validated\":false}");fflush(stdout);code=c6_run(&plan,&result);
 done:
 printf("{\"exit\":%d,\"transport_pid\":%ld,\"c4_pid\":%ld,\"started_c4\":%s,\"reaped_all\":%s,\"forced_c4\":%s,\"phone_validated\":false,\"power_configured\":false}\n",code,(long)result.transport.pid,(long)result.service.pid,result.started_service?"true":"false",result.reaped_all?"true":"false",result.forced_service?"true":"false");
 int fds[]={controller.held,controller.directory,supervisor,attach,sl,tl,dir,lock,base,parent,tmp,content};for(unsigned i=0;i<sizeof fds/sizeof fds[0];i++)if(fds[i]>=0)close(fds[i]);return code;
}
