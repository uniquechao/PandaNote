#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "runner.h"
#include <string.h>
#include <sys/wait.h>
#include <time.h>
int c5_run(const struct c4_program *program,volatile sig_atomic_t *stop,unsigned duration,struct c5_result *result){
 memset(result,0,sizeof *result);if(!program||!stop||duration<10||duration>5000)return 3;
 if(*stop)return 7;
 int code=4;int64_t began=c2_now();if(began<0)return 3;
 if(c4_spawn(&result->child,program))goto done;
 int64_t deadline=c2_now()+duration;
 while(!*stop){
  int64_t now=c2_now();if(now<0)goto done;if(now>=deadline)break;
  if(c2_alive(&result->child)!=1)goto done;
  struct timespec delay={0,10000000};nanosleep(&delay,NULL);
 }
 code=0;
 done:
 if(c4_stop(&result->child,program->grace_ms))code=6;
 result->reaped=result->child.reaped;
 result->killed=result->reaped&&WIFSIGNALED(result->child.status)&&WTERMSIG(result->child.status)==SIGKILL;
 int64_t ended=c2_now();result->elapsed_ms=ended>=began?(int)(ended-began):-1;
 return code;
}
