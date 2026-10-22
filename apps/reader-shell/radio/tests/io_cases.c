/* Test-only syscall fault injection around the actual production translation unit. */
#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/select.h>
#include <unistd.h>
#include <errno.h>
#include <string.h>
static ssize_t fault_send(int,const void*,size_t,int);
static ssize_t fault_recv(int,void*,size_t,int);
static ssize_t fault_read(int,void*,size_t);
static int fault_select(int,fd_set*,fd_set*,fd_set*,struct timeval*);
#define send fault_send
#define recv fault_recv
#define read fault_read
#define select fault_select
#define main helper_main
#include "../radio.c"
#undef main
#undef send
#undef recv
#undef read
#undef select
static unsigned sends,receives,reads,selects;
static int fail_twice(unsigned *count){unsigned attempt=(*count)++;if(attempt<2){errno=attempt?EAGAIN:EINTR;return 1;}return 0;}
static ssize_t fault_send(int fd,const void *p,size_t n,int flags){return fail_twice(&sends)?-1:send(fd,p,n,flags);}
static ssize_t fault_recv(int fd,void *p,size_t n,int flags){return fail_twice(&receives)?-1:recv(fd,p,n,flags);}
static ssize_t fault_read(int fd,void *p,size_t n){return fail_twice(&reads)?-1:read(fd,p,n);}
static int fault_select(int n,fd_set *r,fd_set *w,fd_set *x,struct timeval *tv){if(selects++==0){errno=EINTR;return -1;}return select(n,r,w,x,tv);}
int main(void){int pair[2],pipefd[2];char response[32],input[32];
    if(socketpair(AF_UNIX,SOCK_DGRAM,0,pair))return 10;
    ctrl=pair[0];fcntl(ctrl,F_SETFL,O_NONBLOCK);
    if(send(pair[1],"OK\n",3,0)!=3)return 11;
    if(!command("STATUS",response,sizeof(response))||strcmp(response,"OK\n"))return 12;
    if(sends<3||receives<3||selects<2)return 13;
    close(pair[0]);close(pair[1]);ctrl=-1;
    if(pipe(pipefd))return 14;
    if(write(pipefd[1],"hello",5)!=5)return 15;
    close(pipefd[1]);if(dup2(pipefd[0],0)<0)return 16;close(pipefd[0]);selects=0;
    if(read_request(input,sizeof(input))!=5||memcmp(input,"hello",5)||reads<3)return 17;
    return 0;
}
