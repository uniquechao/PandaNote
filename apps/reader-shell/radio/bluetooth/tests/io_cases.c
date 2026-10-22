#define _POSIX_C_SOURCE 200809L
#include <sys/socket.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <time.h>
#include <sys/time.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include "../probe_io.h"
static int parse(const unsigned char *p,size_t n,void *arg) { (void)arg;return n==2&&p[0]==0xab&&p[1]==0xcd?1:0; }
int main(void) {
    int s[2],status,fail=0;unsigned char req[]={4,0,0,0,0,0};pid_t child;
    socketpair(AF_UNIX,SOCK_DGRAM,0,s);fcntl(s[0],F_SETFL,O_NONBLOCK);
    struct timeval timeout={0,300000};setsockopt(s[1],SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));
    child=fork(); if(!child) {unsigned char b[16];ssize_t n=recv(s[1],b,sizeof(b),0);if(n!=6||memcmp(b,req,6))_exit(9);send(s[1],"ignored",7,0);send(s[1],"\253\315",2,0);_exit(0);}
    if(bt_exchange(s[0],req,6,bt_deadline(200),parse,NULL)!=1)fail++;
    waitpid(child,&status,0);if(status)fail++;
    int64_t start=bt_deadline(0);
    if(bt_exchange(s[0],req,6,bt_deadline(100),parse,NULL)!=-1)fail++;
    int64_t elapsed=bt_deadline(0)-start;if(elapsed<80||elapsed>500)fail++;
    if(bt_exchange(s[0],req,6,bt_deadline(-1),parse,NULL)!=-1)fail++;
    close(s[0]);close(s[1]);
    printf("io fixture failures=%d elapsed_ms=%lld\n",fail,(long long)elapsed);return fail?1:0;
}
