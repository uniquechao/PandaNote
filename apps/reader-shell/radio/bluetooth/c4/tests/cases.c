#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "supervisor.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
struct fixture {const char *root;volatile sig_atomic_t stop;int fail_ready,fail_health,cancel_ready;int64_t began;};
static int ready(void *context,unsigned index,struct child child[3],int64_t deadline){
 struct fixture *f=context;if(f->cancel_ready){f->stop=1;return -1;}if((int)index==f->fail_ready)return -1;char path[512];snprintf(path,sizeof path,"%s/%u.ready",f->root,index);
 while(c2_now()<deadline&&!f->stop){if(access(path,F_OK)==0)return 0;if(c2_alive(&child[index])!=1)return -1;struct timespec pause={0,1000000};nanosleep(&pause,NULL);}return -1;
}
static int healthy(void *context,struct child children[3]){(void)children;struct fixture *f=context;if(f->fail_health)return -1;if(c2_now()-f->began>120)f->stop=1;return 0;}
static void one(const char *binary,const char *root,int mode){
 assert(!mkdir(root,0700));struct fixture f={root,0,-1,0,0,c2_now()};struct c4_plan plan;memset(&plan,0,sizeof plan);plan.stop=&f.stop;plan.ready=ready;plan.healthy=healthy;plan.context=&f;plan.health_ms=20;
 char *argv[3][5];char role[3][2]={{'0',0},{'1',0},{'2',0}};char *env[]={"PATH=/usr/bin:/bin",NULL};char limit[3][12];int executable=open(binary,O_RDONLY|O_CLOEXEC);assert(executable>=3);
 for(unsigned i=0;i<3;i++){char log[512];snprintf(log,sizeof log,"%s/%u.log",root,i);int fd=open(log,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);assert(fd>=3);unsigned file_limit=i==2?C4_SERVICE_FILE_LIMIT:C4_SHORT_FILE_LIMIT;snprintf(limit[i],sizeof limit[i],"%u",file_limit);argv[i][0]=(char *)binary;argv[i][1]=(char *)root;argv[i][2]=role[i];argv[i][3]=mode==1&&i==1?"die":mode==2&&i==1?"ignore":mode==6&&i==2?"flood":"wait";argv[i][4]=limit[i];
  /* Null-terminated argv lives separately: six entries, no host credentials. */
  plan.program[i]=(struct c4_program){executable,fd,NULL,env,32,file_limit,30};
 }
 int invalid=-1;
 if(mode==7){char path[512];snprintf(path,sizeof path,"%s/invalid",root);int fd=open(path,O_WRONLY|O_CREAT|O_EXCL,0700);assert(fd>=0&&write(fd,"invalid ELF",11)==11);close(fd);invalid=open(path,O_RDONLY|O_CLOEXEC);assert(invalid>=3);plan.program[1].executable=invalid;}
 char *actual[3][6];for(unsigned i=0;i<3;i++){for(unsigned n=0;n<5;n++)actual[i][n]=argv[i][n];actual[i][5]=NULL;plan.program[i].argv=actual[i];}
 if(mode==3)f.fail_ready=1;
 if(mode==4)f.fail_health=1;
 if(mode==5)f.cancel_ready=1;
 pid_t sentinel=fork();assert(sentinel>=0);if(!sentinel)for(;;)pause();
 int leaked=open("/dev/null",O_RDONLY);assert(leaked>=0&&dup2(leaked,198)==198);close(leaked);
 struct c4_result result;int code=c4_run(&plan,&result);close(198);assert(kill(sentinel,0)==0);assert(!kill(sentinel,SIGTERM));int status;assert(waitpid(sentinel,&status,0)==sentinel);
 assert(result.started==result.reaped);if(mode==0||mode==2)assert(code==0&&result.running&&result.ready==3);else if(mode==5)assert(code==7&&!result.running);else assert(code==4);
 if(mode==2)assert(result.killed&(1U<<1));
 if(mode==3)assert(result.started==3&&!result.running);
 if(mode==6){struct stat s;assert(!fstat(plan.program[2].log,&s)&&s.st_size<=C4_SERVICE_FILE_LIMIT);}
 for(unsigned i=0;i<3;i++)close(plan.program[i].log);
 if(invalid>=0)close(invalid);
 close(executable);
}
static void parent_death(const char *binary,const char *root){
 char directory[512],log[512];snprintf(directory,sizeof directory,"%s/parent-death",root);assert(!mkdir(directory,0700));snprintf(log,sizeof log,"%s/death.log",root);
 assert(!prctl(PR_SET_CHILD_SUBREAPER,1,0,0,0));int channel[2];assert(!pipe(channel));pid_t owner=fork();assert(owner>=0);
 if(!owner){close(channel[0]);int executable=open(binary,O_RDONLY|O_CLOEXEC),fd=open(log,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);assert(executable>=3&&fd>=3);char *args[]={(char *)binary,directory,"0","wait","16384",NULL};char *env[]={"PATH=/usr/bin:/bin",NULL};struct c4_program program={executable,fd,args,env,32,C4_SHORT_FILE_LIMIT,30};struct child child={0};assert(!c4_spawn(&child,&program));assert(write(channel[1],&child.pid,sizeof child.pid)==sizeof child.pid);_exit(0);}
 close(channel[1]);pid_t owned=0;assert(read(channel[0],&owned,sizeof owned)==sizeof owned&&owned>0);close(channel[0]);int status;assert(waitpid(owner,&status,0)==owner&&WIFEXITED(status)&&WEXITSTATUS(status)==0);pid_t reaped=0;int64_t deadline=c2_now()+700;while(!(reaped=waitpid(owned,&status,WNOHANG))&&c2_now()<deadline){struct timespec delay={0,1000000};nanosleep(&delay,NULL);}int automatic=reaped==owned&&WIFSIGNALED(status)&&WTERMSIG(status)==SIGKILL;if(reaped==0){assert(!kill(owned,SIGTERM));assert(waitpid(owned,&status,0)==owned);}assert(automatic);assert(!prctl(PR_SET_CHILD_SUBREAPER,0,0,0,0));
}
int main(int argc,char **argv){assert(argc==3);for(int mode=0;mode<8;mode++){char path[256];snprintf(path,sizeof path,"%s/case-%d",argv[2],mode);one(argv[1],path,mode);}parent_death(argv[1],argv[2]);struct child nonchild={getpid(),0,0};assert(c4_stop(&nonchild,30)==-1);puts("PASS Linux owned fexecve lifecycle: steady stop, death, KILL, readiness/health/cancel/flood/exec failure, parent death, FD and role limits, unrelated sentinel");return 0;}
