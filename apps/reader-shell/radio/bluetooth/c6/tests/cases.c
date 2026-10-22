#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "runner.h"
#include "controller.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <unistd.h>
static volatile sig_atomic_t stopping;
static void stop(int s){(void)s;stopping=1;}
struct context {const char *root;int mode,calls;};
static int ready(void *data,struct child *child,int64_t deadline){struct context *c=data;if(c->mode==1)return -1;char p[512];snprintf(p,sizeof p,"%s/T.ready",c->root);while(c2_now()<deadline&&c2_alive(child)==1){if(!access(p,F_OK))return 0;usleep(1000);}return -1;}
static int healthy(void *data,struct child *child){struct context *c=data;(void)child;return c->mode==6&&++c->calls==3?-1:0;}
static void initial_names(const char *root){
 char path[512];snprintf(path,sizeof path,"%s/name",root);int dir=open(root,O_RDONLY|O_DIRECTORY|O_CLOEXEC);assert(dir>=3);
 const char *names[]={"AIC8820\n","PandaNote 966U2\n","PandaNote966U2\n","Unknown\n","PandaNote 966U2x\n","PandaNote 966U2 \n","pandanote 966u2\n","PandaNote 966U2\n\n","PandaNote 966U2","AIC8820x\n","\n"};
 for(unsigned i=0;i<sizeof names/sizeof names[0];i++){int fd=open(path,O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC,0600);assert(fd>=3);size_t size=strlen(names[i]);assert(write(fd,names[i],size)==(ssize_t)size);close(fd);assert(c6_initial_name(dir)==(i<2?0:-1));}
 assert(!unlink(path));close(dir);
}
int main(int argc,char **argv){assert(argc==3);initial_names(argv[2]);assert(c6_class_entry("hci0")==1);assert(c6_class_entry("hci0:12")==0);assert(c6_class_entry("hci1")==-1);assert(c6_class_entry("hci1:12")==-1);assert(c6_class_entry("hci0:")==-1);assert(c6_class_entry("hci0:abc")==-1);signal(SIGALRM,stop);int executable=open(argv[1],O_RDONLY|O_CLOEXEC);assert(executable>=3);
 for(int mode=0;mode<9;mode++){
 char root[256],p[512];snprintf(root,sizeof root,"%s/case-%d",argv[2],mode);assert(!mkdir(root,0700));snprintf(p,sizeof p,"%s/transport.log",root);int tl=open(p,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);snprintf(p,sizeof p,"%s/service.log",root);int sl=open(p,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);assert(tl>=3&&sl>=3);
 char *ta[]={argv[1],root,"T",mode==2?"die":"wait",NULL};char *sa[]={argv[1],root,"S",mode==3?"die":mode==7?"cleanup-fail":mode==4?"ignore":mode==5?"slow":"wait",NULL};char *env[]={"PATH=/usr/bin:/bin",NULL};struct context context={root,mode,0};struct c6_plan plan={{executable,tl,ta,env,32,16384,40},{executable,sl,sa,env,32,16384,40},&stopping,ready,healthy,&context,300,50};struct c6_result result;
 pid_t sentinel=fork();assert(sentinel>=0);if(!sentinel){signal(SIGALRM,SIG_DFL);for(;;)pause();}
 stopping=0;struct itimerval timer={{0,0},{mode==8?5:0,mode==8?200000:250000}};assert(!setitimer(ITIMER_REAL,&timer,NULL));int64_t began=c2_now();int code=c6_run(&plan,&result);memset(&timer,0,sizeof timer);assert(!setitimer(ITIMER_REAL,&timer,NULL));assert(!kill(sentinel,0));kill(sentinel,SIGTERM);int status;assert(waitpid(sentinel,&status,0)==sentinel);
 assert(code==((mode==0||mode==5||mode==8)?0:(mode==4||mode==7)?6:4));assert(result.reaped_all);if(mode==8)assert(c2_now()-began>=5200);if(mode==1){assert(!result.started_service);snprintf(p,sizeof p,"%s/S.ready",root);assert(access(p,F_OK));}
 if(mode==0||mode==5){snprintf(p,sizeof p,"%s/order",root);int fd=open(p,O_RDONLY);assert(fd>=0);char order[3]={0};assert(read(fd,order,3)==2&&!strcmp(order,"ST"));close(fd);}if(mode==4)assert(result.forced_service);close(tl);close(sl);
 }
 close(executable);puts("PASS C6 owned long-lived core: ordered stop, readiness refusal, transport death, service death, forced cleanup, slow service, unhealthy session, cleanup failure, beyond C5 five seconds, unrelated sentinel");return 0;}
