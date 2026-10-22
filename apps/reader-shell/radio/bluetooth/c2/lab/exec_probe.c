/* Fixed unprivileged lab entry. Links the SAME production core.o; no exec shim. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "core.h"
#include "inputs.h"
#include <fcntl.h>
#include <stdio.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
int main(void){
 if(geteuid()!=65534)return 3;
 umask(077);
 int executable=open("/case/bin/bluetoothd",O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
 int log=open("/tmp/pandanote-connectivity/bluetooth/probe-child.out",O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
 struct stat st;
 if(executable<0||log<0||fstat(executable,&st)||!S_ISREG(st.st_mode)||
    c2_hash(executable,C2_DAEMON_SHA,1048576))return 3;
 char *args[]={"bluetoothd","--version",NULL};
 char *env[]={"PATH=/usr/bin:/bin","HOME=/tmp/pandanote-connectivity/bluetooth",NULL};
 struct child child={0};
 int spawn=c2_spawn(&child,executable,args,env,log,24);
 int64_t deadline=c2_now()+2000;
 while(c2_alive(&child)==1&&c2_now()<deadline){struct timespec t={0,10000000};nanosleep(&t,NULL);}
 int cleanup=c2_stop(&child);
 int status=child.reaped&&WIFEXITED(child.status)?WEXITSTATUS(child.status):-1;
 printf("{\"spawn\":%d,\"child_exit\":%d,\"cleanup\":%s,\"reaped\":%s}\n",spawn,status,cleanup?"false":"true",child.reaped?"true":"false");
 close(log);close(executable);
 return spawn==0&&status==0&&cleanup==0&&child.reaped?0:4;
}
