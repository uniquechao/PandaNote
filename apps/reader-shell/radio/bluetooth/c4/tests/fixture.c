#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <assert.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
int main(int argc,char **argv){
 assert(argc==5);struct rlimit limit;assert(getrlimit(RLIMIT_FSIZE,&limit)==0&&limit.rlim_cur==strtoul(argv[4],NULL,10));assert(getrlimit(RLIMIT_CPU,&limit)==0&&limit.rlim_cur==RLIM_INFINITY);assert(getrlimit(RLIMIT_NOFILE,&limit)==0&&limit.rlim_cur==32);assert(fcntl(198,F_GETFD)==-1);
 char name[256];assert(snprintf(name,sizeof name,"%s/%s.ready",argv[1],argv[2])>0);int fd=open(name,O_WRONLY|O_CREAT|O_EXCL,0600);assert(fd>=0);assert(write(fd,"R",1)==1);close(fd);
 if(!strcmp(argv[3],"die")){struct timespec t={0,30000000};nanosleep(&t,NULL);return 7;}
 if(!strcmp(argv[3],"ignore"))signal(SIGTERM,SIG_IGN);
 if(!strcmp(argv[3],"flood")){unsigned char bytes[4096];memset(bytes,1,sizeof bytes);for(;;)(void)write(1,bytes,sizeof bytes);}
 for(;;)pause();
}
