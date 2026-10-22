#include <syslog.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
void pandanote_private_openlog(const char *,int,int);
void pandanote_private_closelog(void);
void pandanote_private_syslog(int,const char *,...);
void pandanote_private_vsyslog(int,const char *,va_list);
static void emit(int level,const char *format,...){va_list ap;va_start(ap,format);pandanote_private_vsyslog(level,format,ap);va_end(ap);}
int main(void){char longmsg[1001];memset(longmsg,'a',1000);longmsg[1000]=0;pandanote_private_openlog("ignored",LOG_NDELAY,LOG_DAEMON);emit(LOG_ERR,"synthetic failure %d",7);pandanote_private_syslog(LOG_INFO,"direct diagnostic %d",8);for(int i=0;i<100;i++)emit(LOG_INFO,"%s",longmsg);pandanote_private_closelog();return 0;}
