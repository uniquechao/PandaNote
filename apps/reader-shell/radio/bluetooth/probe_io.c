#define _POSIX_C_SOURCE 200809L
#include "probe_io.h"
#include <time.h>
#include <poll.h>
#include <errno.h>
#include <sys/socket.h>
#include <fcntl.h>
int64_t bt_deadline(int milliseconds) {
    struct timespec ts;
    if(milliseconds<0||milliseconds>10000||clock_gettime(CLOCK_MONOTONIC,&ts))return -1;
    return (int64_t)ts.tv_sec*1000+ts.tv_nsec/1000000+milliseconds;
}
static int ready(int fd,short events,int64_t deadline) {
    struct pollfd p;int rc;int64_t now,left;
    for(;;) {
        now=bt_deadline(0);left=deadline-now;
        if(now<0||deadline<0||left<=0||left>10000)return -1;
        p.fd=fd;p.events=events;p.revents=0;
        rc=poll(&p,1,(int)left);
        if(rc<0&&errno==EINTR)continue;
        if(rc<=0||p.revents&(POLLERR|POLLHUP|POLLNVAL))return -1;
        if(p.revents&events)return 1;
    }
}
int bt_exchange(int fd,const unsigned char *request,size_t n,int64_t deadline,
                int (*parse)(const unsigned char *,size_t,void *),void *arg) {
    unsigned char reply[512];ssize_t count;int rc;
    if(fd<0||!request||!n||n>16||!parse)return -1;
    rc=fcntl(fd,F_GETFL);if(rc<0||!(rc&O_NONBLOCK))return -1;
    for(;;) {
        if(ready(fd,POLLOUT,deadline)<0)return -1;
        count=send(fd,request,n,0);
        if(count<0&&(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK))continue;
        if(count!=(ssize_t)n)return -1;
        break;
    }
    for(;;) {
        if(ready(fd,POLLIN,deadline)<0)return -1;
        count=recv(fd,reply,sizeof(reply),0);
        if(count<0&&(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK))continue;
        if(count<=0)return -1;
        rc=parse(reply,(size_t)count,arg);if(rc)return rc;
    }
}
