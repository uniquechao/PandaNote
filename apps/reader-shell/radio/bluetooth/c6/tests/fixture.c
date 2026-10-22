#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <assert.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
static volatile sig_atomic_t stopped;
static void stop(int s){(void)s;stopped=1;}
int main(int argc,char **argv){
 assert(argc==4);signal(SIGTERM,!strcmp(argv[3],"ignore")?SIG_IGN:stop);
 char path[512];snprintf(path,sizeof path,"%s/%s.ready",argv[1],argv[2]);int fd=open(path,O_WRONLY|O_CREAT|O_EXCL,0600);assert(fd>=0);close(fd);
 if(!strcmp(argv[3],"die")||!strcmp(argv[3],"cleanup-fail")){struct timespec t={0,60000000};nanosleep(&t,0);return !strcmp(argv[3],"cleanup-fail")?6:7;}
 while(!stopped)pause();
 if(!strcmp(argv[3],"slow")){struct timespec t={0,150000000};nanosleep(&t,0);}
 snprintf(path,sizeof path,"%s/order",argv[1]);fd=open(path,O_WRONLY|O_CREAT|O_APPEND,0600);assert(fd>=0);assert(write(fd,argv[2],1)==1);close(fd);return 0;
}
