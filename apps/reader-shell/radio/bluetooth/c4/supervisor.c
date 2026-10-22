#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "supervisor.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
static void nap(void){struct timespec delay={0,10000000};nanosleep(&delay,NULL);}
static int limit(int key,rlim_t value){struct rlimit bound={value,value};return setrlimit(key,&bound);}
int c4_stop(struct child *child,unsigned grace_ms){
 int alive=c2_alive(child);if(alive<=0)return alive;
 if(grace_ms>5000)return -1;
 if(kill(child->pid,SIGTERM))return errno==ESRCH?c2_alive(child):-1;
 int64_t deadline=c2_now()+(int64_t)grace_ms;
 while((alive=c2_alive(child))==1&&c2_now()<deadline)nap();
 if(alive<=0)return alive;
 if(kill(child->pid,SIGKILL)&&errno!=ESRCH)return -1;
 deadline=c2_now()+1000;
 while((alive=c2_alive(child))==1&&c2_now()<deadline)nap();
 return alive==0?0:-1;
}
/* Enumerate actual inherited descriptors, not a potentially million-entry
 * OPEN_MAX loop. The supervisor is single-threaded; no other thread may create
 * descriptors between this snapshot and fork. No fd/PID is adopted from a file. */
static int descriptors(int out[128]){
 DIR *directory=opendir("/proc/self/fd");if(!directory)return -1;
 int own=dirfd(directory),count=0;struct dirent *entry;int result=-1;
 for(;;){errno=0;entry=readdir(directory);if(!entry){if(!errno)result=count;break;}
  if(entry->d_name[0]=='.')continue;
  char *end=NULL;errno=0;long fd=strtol(entry->d_name,&end,10);
  if(errno||!end||*end||fd<0||fd>INT_MAX)break;
  if(fd<=2||fd==own)continue;
  if(count==128)break;
  out[count++]=(int)fd;
 }
 closedir(directory);return result;
}
int c4_spawn(struct child *child,const struct c4_program *program){
 struct stat executable,log;struct rlimit cpu;
 if(child->pid||program->executable<3||program->log<3||!program->argv||!program->environment||program->memory_mb<8||program->memory_mb>64||program->file_limit>C4_SERVICE_FILE_LIMIT||program->file_limit<C4_SHORT_FILE_LIMIT||fstat(program->executable,&executable)||!S_ISREG(executable.st_mode)||fstat(program->log,&log)||!S_ISREG(log.st_mode)||log.st_uid!=geteuid()||log.st_nlink!=1||(log.st_mode&07777)!=0600||getrlimit(RLIMIT_CPU,&cpu)||cpu.rlim_cur!=RLIM_INFINITY||cpu.rlim_max!=RLIM_INFINITY)return -1;
 int pipefd[2];if(pipe(pipefd))return -1;
 if(fcntl(pipefd[0],F_SETFD,FD_CLOEXEC)||fcntl(pipefd[1],F_SETFD,FD_CLOEXEC)){close(pipefd[0]);close(pipefd[1]);return -1;}
 int list[128];int count=descriptors(list);if(count<0){close(pipefd[0]);close(pipefd[1]);return -1;}
 pid_t parent_pid=getpid();pid_t pid=fork();if(pid<0){close(pipefd[0]);close(pipefd[1]);return -1;}
 if(!pid){
  signal(SIGTERM,SIG_DFL);signal(SIGINT,SIG_DFL);signal(SIGALRM,SIG_DFL);signal(SIGXFSZ,SIG_DFL);
  int error=1;
  /* Fatal parent termination must not leave radio daemons orphaned. Check the
   * captured PID after arming: the parent can die between fork and prctl. */
  if(prctl(PR_SET_PDEATHSIG,SIGKILL,0,0,0)||getppid()!=parent_pid)goto failed;
  if(dup2(program->log,1)<0||dup2(program->log,2)<0)goto failed;
  close(0);
  for(int i=0;i<count;i++)if(list[i]!=program->executable&&list[i]!=pipefd[1])close(list[i]);
  if(limit(RLIMIT_CORE,0)||limit(RLIMIT_FSIZE,program->file_limit)||limit(RLIMIT_NOFILE,32)||limit(RLIMIT_AS,(rlim_t)program->memory_mb*1024*1024)||limit(RLIMIT_STACK,512*1024))goto failed;
  fexecve(program->executable,program->argv,program->environment);
 failed:error=errno;(void)write(pipefd[1],&error,sizeof error);_exit(126);
 }
 child->pid=pid;child->reaped=0;child->status=0;close(pipefd[1]);
 struct pollfd ready={pipefd[0],POLLIN|POLLHUP,0};int polled;int64_t deadline=c2_now()+1500;
 do{int left=(int)(deadline-c2_now());if(left<=0){polled=0;break;}polled=poll(&ready,1,left);}while(polled<0&&errno==EINTR);
 int error=0;ssize_t got=polled>0?read(pipefd[0],&error,sizeof error):-1;close(pipefd[0]);
 if(got!=0){(void)c4_stop(child,program->grace_ms);return -1;}return 0;
}
static int live(struct c4_result *result,unsigned count){for(unsigned i=0;i<count;i++)if(c2_alive(&result->child[i])!=1)return 0;return 1;}
int c4_run(const struct c4_plan *plan,struct c4_result *result){
 memset(result,0,sizeof *result);result->exit=3;
 if(!plan||!plan->stop||!plan->ready||!plan->healthy||plan->health_ms<10||plan->health_ms>10000)return 3;
 result->exit=4;
 for(unsigned i=0;i<3;i++){
  if(*plan->stop){result->exit=7;goto done;}
  int spawned=c4_spawn(&result->child[i],&plan->program[i]);if(result->child[i].pid>0)result->started|=1U<<i;
  if(spawned)goto done;
  int ready=plan->ready(plan->context,i,result->child,c2_now()+3000);
  if(*plan->stop){result->exit=7;goto done;}
  if(ready||!live(result,i+1))goto done;
  result->ready++;
 }
 result->running=1;int64_t next=c2_now();
 while(!*plan->stop){
  if(!live(result,3))goto done;
  int64_t now=c2_now();if(now<0)goto done;
  if(now>=next){if(plan->healthy(plan->context,result->child))goto done;next=now+plan->health_ms;}
  nap();
 }
 result->exit=0;
 done:
 for(int i=2;i>=0;i--){if(c4_stop(&result->child[i],plan->program[i].grace_ms))result->exit=6;
  if(result->child[i].reaped){result->reaped|=1U<<i;if(WIFSIGNALED(result->child[i].status)&&WTERMSIG(result->child[i].status)==SIGKILL)result->killed|=1U<<i;}
 }
 return result->exit;
}
