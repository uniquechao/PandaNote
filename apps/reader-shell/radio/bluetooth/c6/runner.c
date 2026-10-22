#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "runner.h"
#include <errno.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
static void nap(void){struct timespec t={0,10000000};nanosleep(&t,NULL);}
/* The C4 parent needs enough time to clean its three children, each with its
 * own reviewed grace period. Killing it early would bypass socket/key cleanup. */
static int stop_service(struct child *child,unsigned grace,int *forced){
 int alive=c2_alive(child);if(alive<=0)return alive;
 if(kill(child->pid,SIGTERM)&&errno!=ESRCH)return -1;
 int64_t now=c2_now();if(now<0)return -1;int64_t deadline=now+grace;
 while((alive=c2_alive(child))==1){now=c2_now();if(now<0)return -1;if(now>=deadline)break;nap();}
 if(alive<=0)return alive;
 *forced=1;return c4_stop(child,0);
}
int c6_run(const struct c6_plan *plan,struct c6_result *result){
 memset(result,0,sizeof *result);
 if(!plan||!plan->stop||!plan->ready||!plan->healthy||plan->service_grace_ms<100||plan->service_grace_ms>12000||plan->health_ms<10||plan->health_ms>1000)return 3;
 if(*plan->stop)return 7;
 int code=4;
 if(c4_spawn(&result->transport,&plan->transport))goto done;
 int64_t now=c2_now();if(now<0)goto done;
 if(plan->ready(plan->context,&result->transport,now+3000)||*plan->stop||c2_alive(&result->transport)!=1)goto done;
 if(c4_spawn(&result->service,&plan->service))goto done;
 result->started_service=1;
 now=c2_now();if(now<0)goto done;int64_t next=now;
 while(!*plan->stop){
  if(c2_alive(&result->transport)!=1||c2_alive(&result->service)!=1)goto done;
  now=c2_now();if(now<0)goto done;
  if(now>=next){if(plan->healthy(plan->context,&result->transport))goto done;next=now+plan->health_ms;}
  nap();
 }
 code=0;
 done:
 if(stop_service(&result->service,plan->service_grace_ms,&result->forced_service)||result->forced_service)code=6;
 if(result->service.pid&&result->service.reaped){
  if(WIFEXITED(result->service.status)&&WEXITSTATUS(result->service.status)==6)code=6;
  else if(!WIFEXITED(result->service.status)||WEXITSTATUS(result->service.status)!=0)code=code==0?6:code;
 }
 if(c4_stop(&result->transport,plan->transport.grace_ms))code=6;
 result->reaped_all=(!result->transport.pid||result->transport.reaped)&&(!result->service.pid||result->service.reaped);
 if(!result->reaped_all)code=6;
 return code;
}
