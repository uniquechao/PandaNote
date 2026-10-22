/* Source-build adapter: no global /dev/log socket. Supervisor must provide a
 * private regular tmpfs stderr file. Per-message and process-total byte caps;
 * debug is not enabled. No credentials/file payload logging is introduced. */
#include <stdarg.h>
#include <stdio.h>
#include <unistd.h>
#include <errno.h>
#include <stddef.h>
static size_t remaining=8192;
void pandanote_private_openlog(const char *identity,int option,int facility){(void)identity;(void)option;(void)facility;}
void pandanote_private_closelog(void){}
void pandanote_private_vsyslog(int priority,const char *format,va_list args){
    char message[256];size_t n;int count;
    (void)priority;
    if(!remaining||!format)return;
    count=vsnprintf(message,sizeof(message)-1,format,args);
    if(count<0)return;
    n=(size_t)count;if(n>sizeof(message)-2)n=sizeof(message)-2;
    if(n+1>remaining)n=remaining-1;
    message[n++]='\n';remaining-=n;
    for(size_t offset=0;offset<n;){
        ssize_t done=write(STDERR_FILENO,message+offset,n-offset);
        if(done<0&&errno==EINTR)continue;
        if(done<=0)break;
        offset+=(size_t)done;
    }
}

void pandanote_private_syslog(int priority,const char *format,...){
    va_list args;va_start(args,format);pandanote_private_vsyslog(priority,format,args);va_end(args);
}
