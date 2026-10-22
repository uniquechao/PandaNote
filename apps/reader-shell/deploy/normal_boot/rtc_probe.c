/* Read-only RTC capability inventory: no alarm/clock writes, IRQ reads or mem. */
#define _GNU_SOURCE
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <sys/sysmacros.h>
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <linux/rtc.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <signal.h>
#include <limits.h>
#if defined(__mips__)
extern int __fxstat(int,int,struct stat*);
#define fstat(f,s) __fxstat(3,f,s)
typedef char StatABI[(sizeof(struct stat)==144)?1:-1];
typedef char RTCIRQABI[(sizeof(unsigned long)==4)?1:-1];
#endif
static void tmout(const struct rtc_time*t){printf("%04d-%02d-%02dT%02d:%02d:%02d",1900+t->tm_year,1+t->tm_mon,t->tm_mday,t->tm_hour,t->tm_min,t->tm_sec);}
static int same(const struct rtc_time*a,const struct rtc_time*b){return a->tm_sec==b->tm_sec&&a->tm_min==b->tm_min&&a->tm_hour==b->tm_hour&&a->tm_mday==b->tm_mday&&a->tm_mon==b->tm_mon&&a->tm_year==b->tm_year;}
static int alarm20(int fd,struct rtc_time now,struct rtc_wkalrm old){
 if(old.enabled){puts("alarm_probe=foreign_enabled_refused");return 2;}
 /* Calendar arithmetic only: timegm does not read or trust the OS clock. */
 struct tm utc;memset(&utc,0,sizeof utc);utc.tm_sec=now.tm_sec;utc.tm_min=now.tm_min;utc.tm_hour=now.tm_hour;utc.tm_mday=now.tm_mday;utc.tm_mon=now.tm_mon;utc.tm_year=now.tm_year;
 time_t stamp=timegm(&utc);if(stamp<0||stamp>INT_MAX-20){puts("alarm_probe=calendar_refused");return 2;}stamp+=20;struct tm target;if(!gmtime_r(&stamp,&target))return 2;
 unsigned long data;for(unsigned i=0;i<8;i++){ssize_t n=read(fd,&data,sizeof data);if(n<0&&(errno==EAGAIN||errno==EWOULDBLOCK))break;if(n!=(ssize_t)sizeof data||i==7)return 2;}
 struct rtc_wkalrm own,got;memset(&own,0,sizeof own);own.enabled=1;own.time.tm_sec=target.tm_sec;own.time.tm_min=target.tm_min;own.time.tm_hour=target.tm_hour;own.time.tm_mday=target.tm_mday;own.time.tm_mon=target.tm_mon;own.time.tm_year=target.tm_year;
 sigset_t mask,previous;sigemptyset(&mask);sigaddset(&mask,SIGTERM);sigaddset(&mask,SIGINT);sigaddset(&mask,SIGHUP);if(sigprocmask(SIG_BLOCK,&mask,&previous))return 2;
 int result=2;errno=0;int rc=ioctl(fd,RTC_WKALM_SET,&own);printf("alarm_set rc=%d errno=%d target=",rc,errno);tmout(&own.time);puts("");
 if(rc)goto cleanup;memset(&got,0,sizeof got);if(ioctl(fd,RTC_WKALM_RD,&got)||!got.enabled||!same(&got.time,&own.time)){puts("alarm_probe=readback_refused");goto cleanup;}
 struct pollfd p={fd,POLLIN,0};struct timespec before,after;clock_gettime(CLOCK_MONOTONIC,&before);rc=poll(&p,1,25000);clock_gettime(CLOCK_MONOTONIC,&after);printf("alarm_poll rc=%d revents=%u elapsed_ms=%lld\n",rc,(unsigned)p.revents,(long long)(after.tv_sec-before.tv_sec)*1000+(after.tv_nsec-before.tv_nsec)/1000000);
 if(rc==1&&(p.revents&POLLIN)){errno=0;ssize_t n=read(fd,&data,sizeof data);printf("alarm_irq bytes=%ld errno=%d data=%lu af=%u irqf=%u\n",(long)n,errno,n==(ssize_t)sizeof data?data:0UL,n==(ssize_t)sizeof data&&!!(data&RTC_AF),n==(ssize_t)sizeof data&&!!(data&RTC_IRQF));if(n==(ssize_t)sizeof data&&(data&(RTC_AF|RTC_IRQF))==(RTC_AF|RTC_IRQF))result=0;}
 memset(&got,0,sizeof got);rc=ioctl(fd,RTC_WKALM_RD,&got);printf("alarm_after rc=%d enabled=%u pending=%u\n",rc,got.enabled,got.pending);
 cleanup:memset(&got,0,sizeof got);if(ioctl(fd,RTC_WKALM_RD,&got)||!same(&got.time,&own.time)){puts("alarm_cleanup=foreign_or_unreadable_refused");result=2;}else{if(got.enabled){got.enabled=0;if(ioctl(fd,RTC_WKALM_SET,&got))result=2;}memset(&got,0,sizeof got);if(ioctl(fd,RTC_WKALM_RD,&got)||got.enabled||!same(&got.time,&own.time)){puts("alarm_cleanup=failed");result=2;}else puts("alarm_cleanup=owned_disabled");}
 sigprocmask(SIG_SETMASK,&previous,NULL);return result;
}
int main(int argc,char**argv){
 if(argc!=1&&(argc!=2||strcmp(argv[1],"--alarm-20")))return 90;
 if(geteuid()!=0)return 90;
 int fd=open("/dev/rtc0",O_RDONLY|O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC);struct stat st;
 if(fd<0){printf("open errno=%d\n",errno);return 1;}
 if(fstat(fd,&st)||!S_ISCHR(st.st_mode)||major(st.st_rdev)!=254||minor(st.st_rdev)!=0){close(fd);puts("device_identity=refused");return 1;}
 printf("rtc_probe_v1 irq_word_bytes=%u\n",(unsigned)sizeof(unsigned long));
 struct rtc_time now;memset(&now,0,sizeof now);errno=0;int rc=ioctl(fd,RTC_RD_TIME,&now),err=errno;printf("rd_time rc=%d errno=%d time=",rc,err);if(!rc)tmout(&now);puts("");if(rc){close(fd);return 1;}
 struct rtc_wkalrm alarm;memset(&alarm,0,sizeof alarm);errno=0;rc=ioctl(fd,RTC_WKALM_RD,&alarm);err=errno;printf("wkalm_rd rc=%d errno=%d enabled=%u pending=%u time=",rc,err,alarm.enabled,alarm.pending);if(!rc)tmout(&alarm.time);puts("");if(rc){close(fd);return 1;}
 struct pollfd p={fd,POLLIN,0};errno=0;rc=poll(&p,1,0);err=errno;printf("poll rc=%d errno=%d revents=%u\n",rc,err,(unsigned)p.revents);
 int result=argc==2?alarm20(fd,now,alarm):0;close(fd);return result;
}
