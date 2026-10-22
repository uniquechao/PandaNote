/* Own NORMAL suspend boundary. No raw storage writes, debugfs, killall or reboot. */
#define _GNU_SOURCE
#define _DARWIN_C_SOURCE
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <signal.h>
#include <time.h>
#include "sha256.h"
#ifndef PANDANOTE_SUSPEND_FIXTURE
#include <linux/input.h>
#include <linux/rtc.h>
#include <sys/sysmacros.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#if defined(__mips__)
typedef char RTCIRQABI[(sizeof(unsigned long)==4)?1:-1];
typedef char InputEventABI[(sizeof(struct input_event)==16&&offsetof(struct input_event,type)==8)?1:-1];
typedef char StatABI[(sizeof(struct stat)==144&&offsetof(struct stat,st_mode)==20)?1:-1];
#endif
#endif
#if defined(__mips__) && defined(__linux__)
extern int __fxstat(int,int,struct stat*);extern int __lxstat(int,const char*,struct stat*);extern int __fxstatat(int,int,const char*,struct stat*,int);
#define fstat(f,s) __fxstat(3,f,s)
#define lstat(p,s) __lxstat(3,p,s)
#define fstatat(f,p,s,a) __fxstatat(3,f,p,s,a)
#endif
#define RUN "/run/pandanote-normal"
#define WPA_SHA "628778a588da366c5790c928c172fb56463ab60d65222641ac9ad6cc5377e385"
#define BB_SHA "38081195a5342faafac704f96bec8fb5b4de7a706f74dab88e5c184374f9a593"
#define WAKE_PATH "/sys/devices/platform/md-gpio-keys/power/wakeup"
static int dirfd_=-1;static long service_owner=-1;static volatile sig_atomic_t expired;
static void timedout(int sig){(void)sig;expired=1;}
static const char*path(const char*p){
#ifdef PANDANOTE_SUSPEND_FIXTURE
 static char names[8][4096];static unsigned n;const char*base=getenv("PANDANOTE_SUSPEND_FIXTURE_ROOT");if(!base||*base!='/')exit(90);n=(n+1)%8;if(snprintf(names[n],sizeof names[n],"%s%s",base,p)>=(int)sizeof names[n])exit(90);return names[n];
#else
 return p;
#endif
}
static long parent(void){
#ifdef PANDANOTE_SUSPEND_FIXTURE
 const char*p=getenv("PANDANOTE_SUSPEND_FIXTURE_PARENT");return p?atol(p):-1;
#else
 return (long)getppid();
#endif
}
static int bytes(const char*p,char*b,size_t cap){int f=open(path(p),O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(f<0)return -1;size_t at=0;for(;;){ssize_t n=read(f,b+at,cap-1-at);if(n<0&&errno==EINTR&&!expired)continue;if(n<0){close(f);return -1;}if(!n)break;at+=(size_t)n;if(at==cap-1){close(f);return -1;}}close(f);b[at]=0;return (int)at;}
static int private_open(const char*name,int optional){struct stat s;int f=openat(dirfd_,name,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(f<0)return optional&&errno==ENOENT?-2:-1;if(fstat(f,&s)||!S_ISREG(s.st_mode)||s.st_uid!=geteuid()||s.st_nlink!=1||(s.st_mode&07777)!=0600){close(f);return -1;}return f;}
static int private_read(const char*name,char*b,size_t cap,int optional){int f=private_open(name,optional);if(f<0)return f;size_t at=0;for(;;){ssize_t n=read(f,b+at,cap-1-at);if(n<0&&errno==EINTR)continue;if(n<0){close(f);return -1;}if(!n)break;at+=(size_t)n;if(at==cap-1){close(f);return -1;}}close(f);if(memchr(b,0,at))return -1;b[at]=0;return (int)at;}
static int writeall(int fd,const void*p,size_t n){const char*b=p;while(n){ssize_t x=write(fd,b,n);if(x<0&&errno==EINTR&&!expired)continue;if(x<=0)return -1;b+=x;n-=x;}return 0;}
static int exclusive_rename(const char*a,const char*b){
#if defined(__APPLE__)
 return renameatx_np(dirfd_,a,dirfd_,b,RENAME_EXCL);
#else
 return (int)syscall(SYS_renameat2,dirfd_,a,dirfd_,b,1);
#endif
}
static int atomic(const char*name,const char*data,int exclusive){char tmp[100];struct stat s;if(snprintf(tmp,sizeof tmp,".%s-%ld.pending",name,(long)getpid())>=(int)sizeof tmp)return -1;
 if(!fstatat(dirfd_,name,&s,AT_SYMLINK_NOFOLLOW)){if(exclusive||!S_ISREG(s.st_mode)||s.st_uid!=geteuid()||s.st_nlink!=1||(s.st_mode&07777)!=0600)return -1;}else if(errno!=ENOENT)return -1;
 int f=openat(dirfd_,tmp,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);if(f<0)return -1;int r=writeall(f,data,strlen(data))||fchmod(f,0600)||fsync(f);if(close(f))r=-1;if(!r)r=exclusive?exclusive_rename(tmp,name):renameat(dirfd_,tmp,dirfd_,name);if(r){unlinkat(dirfd_,tmp,0);return -1;}return fsync(dirfd_);
}
static int remove_private(const char*name){int f=private_open(name,1);if(f==-2)return 0;if(f<0)return -1;close(f);return unlinkat(dirfd_,name,0)||fsync(dirfd_)?-1:0;}
static int pair(const char*s,long*pid,unsigned long long*other){char*e;errno=0;unsigned long p=strtoul(s,&e,10);if(errno||p<2||p>4194304||e==s||*e!='-'||s[0]<'1'||s[0]>'9')return -1;const char*t=e+1;if(!*t||*t=='0')return -1;errno=0;unsigned long long v=strtoull(t,&e,10);if(errno||!v||*e||strlen(s)>48)return -1;for(const char*q=t;*q;q++)if(*q<'0'||*q>'9')return -1;*pid=(long)p;*other=v;return 0;}
struct process{long pid,ppid,pgid,sid;unsigned long long start;char state;};
static int proc(long pid,struct process*p){char filename[100],b[4096],*tail,*save,*t,*e;snprintf(filename,sizeof filename,"/proc/%ld/stat",pid);int got=bytes(filename,b,sizeof b);if(got<0)return errno==ENOENT?10:-1;long reported;if(sscanf(b,"%ld",&reported)!=1||reported!=pid)return -1;tail=strrchr(b,')');if(!tail)return -1;memset(p,0,sizeof *p);p->pid=pid;unsigned i=0;
 for(t=strtok_r(tail+1," \n",&save);t;t=strtok_r(NULL," \n",&save),i++){if(i==0){if(strlen(t)!=1)return -1;p->state=*t;}else if(i<=3){errno=0;long v=strtol(t,&e,10);if(errno||*e||v<0)return -1;if(i==1)p->ppid=v;else if(i==2)p->pgid=v;else p->sid=v;}else if(i==19){errno=0;p->start=strtoull(t,&e,10);if(errno||*e||*t=='-'||!p->start)return -1;break;}}
 return i!=19?-1:(p->state=='Z'||p->state=='X')?10:0;
}
static int generation(const char*g){long pid;unsigned long long start;struct process p;if(pair(g,&pid,&start)||proc(pid,&p)||p.ppid!=1||p.start!=start)return -1;service_owner=pid;return 0;}
static int client(const char*token,long supervisor,const char*release){long pid;unsigned long long counter;struct process p,s;char exe[512],name[96],want[256];
 if(pair(token,&pid,&counter)||strlen(release)!=90||strncmp(release,"/user/pandanote/apps/releases/",26))return -1;
 for(const char*q=release+26;*q;q++)if(!((*q>='a'&&*q<='f')||(*q>='0'&&*q<='9')))return -1;
 if(proc(supervisor,&s)||s.ppid!=service_owner||s.pgid!=supervisor||s.sid!=supervisor||proc(pid,&p)||p.ppid!=supervisor||p.pgid!=supervisor||p.sid!=supervisor||strchr("Tt",p.state))return -1;
 snprintf(name,sizeof name,"/proc/%ld/exe",pid);ssize_t n=readlink(path(name),exe,sizeof exe-1);if(n<0||(size_t)n>=sizeof exe-1)return -1;exe[n]=0;snprintf(want,sizeof want,"%s/reader-shell.mipsel",release);return strcmp(exe,want)?-1:0;
}
static int request_parse(const char*b,char*g,char*t){char extra;long pid;unsigned long long value;if(sscanf(b,"suspend-v2 %48s %48s %c",g,t,&extra)!=2||pair(g,&pid,&value)||pair(t,&pid,&value))return -1;char canonical[128];snprintf(canonical,sizeof canonical,"suspend-v2 %s %s\n",g,t);return strcmp(canonical,b)?-1:0;}
static int terminal(const char*r){return !strcmp(r,"resumed")||!strcmp(r,"timer")||!strcmp(r,"busy")||!strcmp(r,"unsafe")||!strcmp(r,"failed");}
static int status_matches(const char*g,const char*t){char b[256],a[49],z[49],result[16],extra;if(private_read("resume.status",b,sizeof b,1)<0)return 0;if(sscanf(b,"resume-v2 %48s %48s %15s %c",a,z,result,&extra)!=3)return 0;char canonical[160];snprintf(canonical,sizeof canonical,"resume-v2 %s %s %s\n",a,z,result);return !strcmp(b,canonical)&&!strcmp(a,g)&&!strcmp(z,t)&&terminal(result);}
/* Token-scoped files make a delayed old UI writer harmless to the next cycle.
 * The caller holds the installation lease except the UI's exclusive intent
 * publication. Only exact private bodies may be consumed or cleaned. */
static int input_marker_name(char*out,size_t cap,const char*kind,const char*t){long pid;unsigned long long value;if(pair(t,&pid,&value))return -1;int n=snprintf(out,cap,"suspend.%s-%s",kind,t);return n<0||(size_t)n>=cap?-1:0;}
static int input_marker(const char*g,const char*t,const char*kind,const char*wire){char name[96],b[160],want[160];if(input_marker_name(name,sizeof name,kind,t))return -1;int n=private_read(name,b,sizeof b,1);if(n==-2)return 0;if(n<0)return -1;snprintf(want,sizeof want,"%s %s %s\n",wire,g,t);return strcmp(b,want)?-1:1;}
static int input_marker_publish(const char*g,const char*t,const char*kind,const char*wire){char name[96],b[160];if(input_marker_name(name,sizeof name,kind,t))return -1;snprintf(b,sizeof b,"%s %s %s\n",wire,g,t);return atomic(name,b,1);}
static int input_markers_clean(const char*g,const char*t){const char*kind[]={"wake","input-ready","input-allow"};const char*wire[]={"wake-v2","input-ready-v2","input-allow-v2"};for(unsigned i=0;i<3;i++){int r=input_marker(g,t,kind[i],wire[i]);char name[96];if(r<0||input_marker_name(name,sizeof name,kind[i],t))return -1;if(r&&remove_private(name))return -1;}return 0;}
static int wake_pending(const char*g,const char*t){return input_marker(g,t,"wake","wake-v2")!=0;}
static int completed_input_cleanup(void){char b[256],g[49],t[49],result[16],extra;long pid;unsigned long long value;int n=private_read("resume.status",b,sizeof b,1);if(n==-2)return 0;if(n<0||sscanf(b,"resume-v2 %48s %48s %15s %c",g,t,result,&extra)!=3||pair(g,&pid,&value)||pair(t,&pid,&value)||!status_matches(g,t))return 0;return input_markers_clean(g,t);}

static int finish(const char*g,const char*t,const char*r){char b[256],a[49],z[49],out[160];long n;unsigned long long v;if(pair(g,&n,&v)||pair(t,&n,&v)||!terminal(r))return -1;int exists=private_read("suspend.active",b,sizeof b,1);if(exists==-2)return status_matches(g,t)?input_markers_clean(g,t):-1;if(exists<0||request_parse(b,a,z)||strcmp(a,g)||strcmp(z,t))return -1;snprintf(out,sizeof out,"resume-v2 %s %s %s\n",g,t,r);if(atomic("resume.status",out,0))return -1;return input_markers_clean(g,t)||remove_private("suspend.entered")||remove_private("suspend.active")?-1:0;}
static int active_check(const char*g,const char*t,long supervisor,const char*release){char b[256],a[49],z[49];return wake_pending(g,t)||generation(g)||client(t,supervisor,release)||private_read("suspend.active",b,sizeof b,0)<0||request_parse(b,a,z)||strcmp(g,a)||strcmp(t,z)?-1:0;}
/* Called only while the service holds the installation/cancellation lease.
 * Missing active is a completed UI cancellation, not permission to trust a
 * malformed or differently owned marker. Remove only this token's entry latch. */
static int reconcile(const char*g,const char*t){char b[256],a[49],z[49];int n=private_read("suspend.active",b,sizeof b,1);if(n>=0)return request_parse(b,a,z)||strcmp(g,a)||strcmp(t,z)?12:0;if(n!=-2)return 12;n=private_read("suspend.entered",b,sizeof b,1);if(n!=-2){if(n<0||request_parse(b,a,z)||strcmp(g,a)||strcmp(t,z)||remove_private("suspend.entered"))return 12;}return input_markers_clean(g,t)?12:10;}
static int claim(const char*g,long supervisor,const char*release){char b[256],a[49],t[49];if(completed_input_cleanup())return 12;int n=private_read("suspend.request",b,sizeof b,1);if(n==-2)return 10;if(n<0||request_parse(b,a,t))return 12;
 struct stat s;if(!fstatat(dirfd_,"suspend.active",&s,AT_SYMLINK_NOFOLLOW)||errno!=ENOENT)return 12;
 if(exclusive_rename("suspend.request","suspend.active")||fsync(dirfd_))return 12;
 if(status_matches(a,t)){if(remove_private("suspend.active"))return 12;return 10;}
 if(strcmp(g,a)||generation(g)||client(t,supervisor,release)){if(finish(a,t,"unsafe"))return 12;return 10;}
 printf("%s\n",t);return 0;
}
#ifdef PANDANOTE_SUSPEND_FIXTURE
static int flag(const char*n){char p[100],b[16];snprintf(p,sizeof p,"/.fixture/%s",n);return bytes(p,b,sizeof b)<0||strcmp(b,"0\n");}
static int input_open(int fds[2]){fds[0]=fds[1]=-1;return 0;}
static int input_idle(int fds[2],int final){(void)fds;return flag("key_down")||flag("touch_down")||(final&&flag("input_activity"))?-1:0;}
#else
static int input_open(int fds[2]){fds[0]=fds[1]=-1;for(unsigned i=0;i<16;i++){char p[48],name[64];snprintf(p,sizeof p,"/dev/input/event%u",i);int f=open(p,O_RDONLY|O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC);if(f<0)continue;struct stat s;memset(name,0,sizeof name);if(fstat(f,&s)||!S_ISCHR(s.st_mode)||ioctl(f,EVIOCGNAME(sizeof name),name)<0||name[63]){close(f);continue;}int role=!strcmp(name,"md-gpio-keys")?0:!strcmp(name,"fts_ts")?1:-1;if(role<0){close(f);continue;}if(fds[role]>=0){close(f);return -1;}fds[role]=f;}return fds[0]<0||fds[1]<0?-1:0;}
/* Baseline only, before fresh ready: GETKEY flushes queued EV_KEY on this
 * client's FD in the pinned Linux 4.4 evdev. After ready every final check is
 * read-only on the same FDs; snapshots must never erase a complete late tap. */
static int input_idle(int fds[2],int final){unsigned long keys[(KEY_MAX+sizeof(unsigned long)*8)/(sizeof(unsigned long)*8)];for(unsigned role=0;role<2;role++){if(!final){memset(keys,0,sizeof keys);if(ioctl(fds[role],EVIOCGKEY(sizeof keys),keys)<0)return -1;unsigned key=role?BTN_TOUCH:KEY_F11;if(keys[key/(8*sizeof(unsigned long))]&(1UL<<(key%(8*sizeof(unsigned long)))))return -1;
 if(role){
  /* This pinned fts_ts uses Type A: its per-contact tracking value is not
   * cleared to -1 on release. Only an advertised SLOT bit selects Type B;
   * EVIOCGABS may succeed with zero defaults for an unsupported axis. */
  unsigned long abs[(ABS_MAX+sizeof(unsigned long)*8)/(sizeof(unsigned long)*8)];memset(abs,0,sizeof abs);memset(keys,0,sizeof keys);
  if(ioctl(fds[role],EVIOCGBIT(EV_ABS,sizeof abs),abs)<0||ioctl(fds[role],EVIOCGBIT(EV_KEY,sizeof keys),keys)<0)return -1;
  unsigned required[]={ABS_MT_TRACKING_ID,ABS_MT_POSITION_X,ABS_MT_POSITION_Y};
  if(!(keys[BTN_TOUCH/(8*sizeof(unsigned long))]&(1UL<<(BTN_TOUCH%(8*sizeof(unsigned long))))))return -1;
  for(unsigned i=0;i<sizeof required/sizeof required[0];i++)if(!(abs[required[i]/(8*sizeof(unsigned long))]&(1UL<<(required[i]%(8*sizeof(unsigned long))))))return -1;
  if(abs[ABS_MT_SLOT/(8*sizeof(unsigned long))]&(1UL<<(ABS_MT_SLOT%(8*sizeof(unsigned long))))){
   struct input_absinfo slot;memset(&slot,0,sizeof slot);if(ioctl(fds[role],EVIOCGABS(ABS_MT_SLOT),&slot)<0||slot.minimum!=0||slot.maximum<0||slot.maximum>=16||slot.value<0||slot.value>slot.maximum)return -1;
   int32_t slots[17];for(unsigned i=0;i<17;i++)slots[i]=-1;slots[0]=ABS_MT_TRACKING_ID;
   if(ioctl(fds[role],EVIOCGMTSLOTS((slot.maximum+2)*sizeof slots[0]),slots)<0)return -1;
   for(int i=1;i<=slot.maximum+1;i++)if(slots[i]!=-1)return -1;
  }
 }
 }
 unsigned total=0;for(;;){struct input_event events[32];ssize_t n=read(fds[role],events,sizeof events);if(n<0&&(errno==EAGAIN||errno==EWOULDBLOCK))break;if(n<0&&errno==EINTR)continue;if(n<=0||n%sizeof events[0]||total+(unsigned)n/sizeof events[0]>2048)return -1;total+=(unsigned)n/sizeof events[0];for(unsigned i=0;i<(unsigned)n/sizeof events[0];i++)if(final&&(events[i].type==EV_KEY||events[i].type==EV_ABS||events[i].code==SYN_DROPPED))return -1;}}
 return 0;}
#endif
static int platform(int fds[2]){char b[256];if(bytes(WAKE_PATH,b,sizeof b)<0||strcmp(b,"enabled\n")||bytes("/sys/power/state",b,sizeof b)<0)return -1;int found=0;char*save,*t;for(t=strtok_r(b," \n",&save);t;t=strtok_r(NULL," \n",&save))if(!strcmp(t,"mem"))found=1;return !found||input_open(fds)?-1:0;}
static void input_close(int fds[2]){for(unsigned i=0;i<2;i++)if(fds[i]>=0)close(fds[i]);}
#ifndef CLOCK_BOOTTIME
#define CLOCK_BOOTTIME 7
#endif
#ifdef PANDANOTE_SUSPEND_FIXTURE
static int64_t fixture_boot_delta;
#endif
static int64_t clockms(int which){struct timespec now;
#ifdef PANDANOTE_SUSPEND_FIXTURE
 int isboot=which==CLOCK_BOOTTIME;which=CLOCK_MONOTONIC;
#endif
 if(clock_gettime(which,&now)||now.tv_sec<0||now.tv_nsec<0||now.tv_nsec>=1000000000)return -1;int64_t value=(int64_t)now.tv_sec*1000+now.tv_nsec/1000000;
#ifdef PANDANOTE_SUSPEND_FIXTURE
 if(isboot)value=fixture_boot_delta;
#endif
 return value;}
/* RTC calendar arithmetic never consults CLOCK_REALTIME or the OS timezone. */
#ifdef PANDANOTE_SUSPEND_FIXTURE
#define RTC_AF 0x20
#define RTC_IRQF 0x80
#endif
#define RTC_INTERVAL_SECONDS 1800
/* RD_TIME is whole seconds: its sample may precede the true time by <1s.
 * This lower bound is auxiliary only; an owned target and same-fd AF are
 * mandatory. Elapsed time alone never establishes the wake cause. */
#define RTC_MIN_ELAPSED_MS 1799000
struct rtc_alarm_value{int enabled,pending;int64_t when;};
struct rtc_owner{int fd,created,returned;int64_t target,boot;char record[160];};
#ifdef PANDANOTE_SUSPEND_FIXTURE
static int fixture_number(const char*n,int64_t*out){char p[100],b[80],*e;snprintf(p,sizeof p,"/.fixture/%s",n);int got=bytes(p,b,sizeof b);if(got<2)return -1;errno=0;long long v=strtoll(b,&e,10);if(errno||v<0||strcmp(e,"\n"))return -1;*out=v;return 0;}
static int rtc_device(void){char b[100];return bytes("/sys/class/rtc/rtc0/name",b,sizeof b)<0||strcmp(b,"10003000.rtc\n")||bytes("/sys/devices/platform/apb/10003000.rtc/power/wakeup",b,sizeof b)<0||strcmp(b,"enabled\n")?-1:open(path("/.fixture/rtc.now"),O_RDONLY|O_NOFOLLOW|O_CLOEXEC);}
static int rtc_now(int fd,int64_t*out){(void)fd;return fixture_number("rtc.now",out);}
static int rtc_alarm_get(int fd,struct rtc_alarm_value*a){(void)fd;char b[128],canonical[128],extra;long long when;if(bytes("/.fixture/rtc.alarm",b,sizeof b)<0||sscanf(b,"%d %d %lld %c",&a->enabled,&a->pending,&when,&extra)!=3||when<0||a->enabled<0||a->enabled>1||a->pending<0||a->pending>1)return -1;snprintf(canonical,sizeof canonical,"%d %d %lld\n",a->enabled,a->pending,when);if(strcmp(b,canonical))return -1;a->when=when;return 0;}
static int fixture_write(const char*p,const char*b,int append){int f=open(path(p),O_WRONLY|O_CREAT|O_NOFOLLOW|O_CLOEXEC|(append?O_APPEND:O_TRUNC),0600);if(f<0)return -1;int r=writeall(f,b,strlen(b));close(f);return r;}
static int rtc_alarm_set(int fd,const struct rtc_alarm_value*a){(void)fd;char b[128];int64_t mismatch=0,fail=0;if(fixture_number("rtc.set-mismatch",&mismatch)||fixture_number("rtc.fail-cleanup",&fail))return -1;if(!a->enabled&&fail)return -1;snprintf(b,sizeof b,"%d 0 %lld\n",a->enabled,(long long)(a->when+(a->enabled&&mismatch?1:0)));if(fixture_write("/.fixture/rtc.alarm",b,0))return -1;snprintf(b,sizeof b,"%s %lld\n",a->enabled?"arm":"disable",(long long)a->when);return fixture_write("/.fixture/rtc.trace",b,1);}
static int rtc_irq(struct rtc_owner*c,unsigned long*flags){int64_t n=0;if(!c->returned){*flags=0;return 0;}if(fixture_number("rtc.irq",&n)||n>0xffffffffLL)return -1;*flags=(unsigned long)n;return 0;}
static void rtc_after_mem(struct rtc_owner*c){char b[128];int64_t n;if(!fixture_number("rtc.after",&n)){snprintf(b,sizeof b,"%lld\n",(long long)n);fixture_write("/.fixture/rtc.now",b,0);}if(!fixture_number("rtc.elapsed",&n))fixture_boot_delta=n;if(bytes("/.fixture/rtc.external",b,sizeof b)>=0)fixture_write("/.fixture/rtc.alarm",b,0);c->returned=1;}
#else
static int leap(int y){return y%4==0&&(y%100!=0||y%400==0);}
static int month_days(int y,int m){static const unsigned char d[]={31,28,31,30,31,30,31,31,30,31,30,31};return d[m]+(m==1&&leap(y));}
static int rtc_epoch(const struct rtc_time*t,int64_t*out){int y=t->tm_year+1900,m=t->tm_mon;if(y<1970||y>2099||m<0||m>11||t->tm_mday<1||t->tm_mday>month_days(y,m)||t->tm_hour<0||t->tm_hour>23||t->tm_min<0||t->tm_min>59||t->tm_sec<0||t->tm_sec>59)return -1;int64_t days=0;for(int i=1970;i<y;i++)days+=365+leap(i);for(int i=0;i<m;i++)days+=month_days(y,i);*out=((days+t->tm_mday-1)*24+t->tm_hour)*3600+t->tm_min*60+t->tm_sec;return 0;}
static int rtc_calendar(int64_t epoch,struct rtc_time*t){if(epoch<0||epoch>4102444799LL)return -1;uint32_t value=(uint32_t)epoch;int days=(int)(value/86400),y=1970,m=0;while(y<=2099&&days>=365+leap(y)){days-=365+leap(y);y++;}if(y>2099)return -1;while(m<11&&days>=month_days(y,m)){days-=month_days(y,m);m++;}memset(t,0,sizeof *t);t->tm_year=y-1900;t->tm_mon=m;t->tm_mday=(int)days+1;t->tm_hour=(int)(value%86400/3600);t->tm_min=(int)(value%3600/60);t->tm_sec=(int)(value%60);return 0;}
static int rtc_device(void){char b[100];if(bytes("/sys/class/rtc/rtc0/name",b,sizeof b)<0||strcmp(b,"10003000.rtc\n")||bytes("/sys/devices/platform/apb/10003000.rtc/power/wakeup",b,sizeof b)<0||strcmp(b,"enabled\n"))return -1;int f=open("/dev/rtc0",O_RDONLY|O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC);struct stat s;if(f<0)return -1;if(fstat(f,&s)||!S_ISCHR(s.st_mode)||major(s.st_rdev)!=254||minor(s.st_rdev)!=0){close(f);return -1;}return f;}
static int rtc_now(int fd,int64_t*out){struct rtc_time t;memset(&t,0,sizeof t);return ioctl(fd,RTC_RD_TIME,&t)||rtc_epoch(&t,out)?-1:0;}
static int rtc_alarm_get(int fd,struct rtc_alarm_value*a){struct rtc_wkalrm raw;memset(&raw,0,sizeof raw);if(ioctl(fd,RTC_WKALM_RD,&raw)||raw.enabled>1||raw.pending>1||rtc_epoch(&raw.time,&a->when))return -1;a->enabled=raw.enabled;a->pending=raw.pending;return 0;}
static int rtc_alarm_set(int fd,const struct rtc_alarm_value*a){struct rtc_wkalrm raw;memset(&raw,0,sizeof raw);raw.enabled=a->enabled;if(rtc_calendar(a->when,&raw.time))return -1;return ioctl(fd,RTC_WKALM_SET,&raw);}
static int rtc_irq(struct rtc_owner*c,unsigned long*flags){*flags=0;for(unsigned i=0;i<8;i++){unsigned long word=0;ssize_t n=read(c->fd,&word,sizeof word);if(n<0&&(errno==EAGAIN||errno==EWOULDBLOCK))return 0;if(n<0&&errno==EINTR)continue;if(n!=(ssize_t)sizeof word)return -1;*flags|=word;}return -1;}
static void rtc_after_mem(struct rtc_owner*c){c->returned=1;}
#endif
static int rtc_capable(void){int f=rtc_device();int64_t now;struct rtc_alarm_value a;if(f<0)return -1;int r=rtc_now(f,&now)||now<0||now>4102444799LL-RTC_INTERVAL_SECONDS||rtc_alarm_get(f,&a);close(f);return r?-1:0;}
static int rtc_owned(struct rtc_owner*c,int require_enabled){char b[160];struct rtc_alarm_value a;return private_read("suspend.rtc",b,sizeof b,0)<0||strcmp(b,c->record)||rtc_alarm_get(c->fd,&a)||a.when!=c->target||(require_enabled&&!a.enabled)?-1:0;}
static int rtc_cleanup(struct rtc_owner*c){int r=0;if(c->fd<0)return 0;if(c->created){struct rtc_alarm_value a;if(rtc_owned(c,0)||rtc_alarm_get(c->fd,&a))r=-1;else{if(a.enabled){a.enabled=0;a.pending=0;if(rtc_alarm_set(c->fd,&a))r=-1;}if(!r&&(rtc_alarm_get(c->fd,&a)||a.enabled||a.when!=c->target))r=-1;if(!r&&remove_private("suspend.rtc"))r=-1;}}close(c->fd);c->fd=-1;return r;}
static int rtc_arm(const char*g,const char*t,struct rtc_owner*c){int64_t now;struct rtc_alarm_value a;c->fd=rtc_device();if(c->fd<0||rtc_now(c->fd,&now)||now<0||now>4102444799LL-RTC_INTERVAL_SECONDS||rtc_alarm_get(c->fd,&a)||a.enabled)return 22;unsigned long stale;if(rtc_irq(c,&stale))return 22;c->target=now+RTC_INTERVAL_SECONDS;c->boot=clockms(CLOCK_BOOTTIME);if(c->boot<0)return 22;snprintf(c->record,sizeof c->record,"rtc-owner-v2 %s %s %lld\n",g,t,(long long)c->target);if(atomic("suspend.rtc",c->record,1))return 22;c->created=1;a.enabled=1;a.pending=0;a.when=c->target;if(rtc_alarm_set(c->fd,&a)||rtc_owned(c,1))return 23;return 0;}
static int rtc_timer(struct rtc_owner*c,int fds[2]){unsigned long irq=0;int64_t now,boot=clockms(CLOCK_BOOTTIME);if(rtc_owned(c,0)||rtc_irq(c,&irq)||rtc_now(c->fd,&now)||now<c->target||boot<c->boot||boot-c->boot<RTC_MIN_ELAPSED_MS||(irq&(RTC_AF|RTC_IRQF))!=(RTC_AF|RTC_IRQF)||input_idle(fds,1))return 0;
#ifdef PANDANOTE_SUSPEND_FIXTURE
 int64_t activity=1;if(fixture_number("rtc.post-input",&activity)||activity)return 0;
#endif
 return 1;}

/* FDs open before ready and remain open through mem. The UI must drain its
 * older key FD once after seeing this freshly created ready marker. Thus an
 * early press/release cannot disappear in the radio-off gap, even if Qt was
 * not scheduled there. New events are caught by our retained FD and then by
 * the wakeup_count kernel handshake. A delayed/missing UI never grants sleep. */
static int input_handoff(const char*g,const char*t,int fds[2]){
 char name[96],b[160];
 if(wake_pending(g,t)||input_marker_name(name,sizeof name,"input-allow",t)||private_read(name,b,sizeof b,1)!=-2||input_marker_publish(g,t,"input-ready","input-ready-v2"))return -1;
#ifdef PANDANOTE_SUSPEND_FIXTURE
 if(flag("input.auto-allow")){if(input_marker_publish(g,t,"input-allow","input-allow-v2"))return -1;}
#endif
 int64_t begin=clockms(CLOCK_MONOTONIC);if(begin<0)return -1;
 for(unsigned i=0;i<60;i++){
  int64_t now=clockms(CLOCK_MONOTONIC);if(now<begin||now-begin>=3000||wake_pending(g,t)||input_idle(fds,1))return -1;
  int r=input_marker(g,t,"input-allow","input-allow-v2");if(r<0)return -1;if(r==1)return 0;
  usleep(50000);
 }
 return -1;
}

static void diagnostic(const char*g,const char*t,int result,int64_t mono,int64_t boot){int64_t ma=clockms(CLOCK_MONOTONIC),ba=clockms(CLOCK_BOOTTIME);if(mono<0||boot<0||ma<mono||ba<boot)return;int64_t md=ma-mono,bd=ba-boot,sleep=bd>md?bd-md:0;char b[256];snprintf(b,sizeof b,"suspend-last-v1 %s %s %s mono_ms=%lld boot_ms=%lld slept_ms=%lld\n",g,t,result==24?"timer":result==0?"resumed":result==22?"unsafe":"failed",(long long)md,(long long)bd,(long long)sleep);(void)atomic("suspend.last",b,0);}
static int kernel_mem(const char*g,const char*t,long supervisor,const char*release){char b[256],a[49],z[49];int fds[2]={-1,-1},result=22,fd=-1;struct stat st;int64_t mono=-1,boot=-1;struct rtc_owner rtc;memset(&rtc,0,sizeof rtc);rtc.fd=-1;
 if(wake_pending(g,t)||generation(g)||client(t,supervisor,release)||private_read("suspend.active",b,sizeof b,0)<0||request_parse(b,a,z)||strcmp(g,a)||strcmp(t,z)||platform(fds)||input_idle(fds,0))goto out;
 if(!lstat(path("/sys/module/aic8800_fdrv"),&st)||errno!=ENOENT)goto out;
 if(!lstat(path("/sys/class/net/wlan0"),&st)||errno!=ENOENT)goto out;
 if(!fstatat(dirfd_,"poweroff.request",&st,AT_SYMLINK_NOFOLLOW)||errno!=ENOENT)goto out;
 if(atomic("suspend.entered",b,1)||input_handoff(g,t,fds))goto out;
 result=rtc_arm(g,t,&rtc);if(result)goto out;result=22;if(wake_pending(g,t))goto out;
#ifdef PANDANOTE_SUSPEND_FIXTURE
 if(flag("changed_wakeup"))goto out;
#endif
 expired=0;struct sigaction sa,old;memset(&sa,0,sizeof sa);sa.sa_handler=timedout;sigemptyset(&sa.sa_mask);if(sigaction(SIGALRM,&sa,&old)){result=23;goto out;}alarm(3);int n=bytes("/sys/power/wakeup_count",b,sizeof b);alarm(0);sigaction(SIGALRM,&old,NULL);if(expired||n<2||n>21)goto out;for(int i=0;i<n-1;i++)if(b[i]<'0'||b[i]>'9')goto out;if(b[n-1]!='\n'||input_idle(fds,1)||wake_pending(g,t))goto out;
 if(!fstatat(dirfd_,"poweroff.request",&st,AT_SYMLINK_NOFOLLOW)||errno!=ENOENT)goto out;
 fd=open(path("/sys/power/wakeup_count"),O_WRONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0||writeall(fd,b,(size_t)n))goto out;close(fd);fd=-1;
#ifdef PANDANOTE_SUSPEND_FIXTURE
 if(flag("fail_mem")){result=23;goto out;}
#endif
 if(!fstatat(dirfd_,"poweroff.request",&st,AT_SYMLINK_NOFOLLOW)||errno!=ENOENT)goto out;
 if(rtc_owned(&rtc,1)||wake_pending(g,t)||input_idle(fds,1))goto out;
 fd=open(path("/sys/power/state"),O_WRONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0){result=23;goto out;}mono=clockms(CLOCK_MONOTONIC);boot=clockms(CLOCK_BOOTTIME);result=writeall(fd,"mem\n",4)?(errno==EBUSY||errno==EAGAIN?22:23):0;if(!result){rtc_after_mem(&rtc);if(!wake_pending(g,t)&&rtc_timer(&rtc,fds))result=24;}
 out:if(fd>=0)close(fd);if(rtc_cleanup(&rtc))result=23;diagnostic(g,t,result,mono,boot);input_close(fds);return result;
}
/* Radio proof: exact initial argv/exe/session/starttime, captured before sleep. */
struct owned{struct process p;char exe[65],cmd[65];};
static const char wpa_cmd[]="/usr/sbin/wpa_supplicant\0-i\0wlan0\0-D\0wext\0-c\0/tmp/pandanote-connectivity/wpa.conf\0";
static const char dhcp_cmd[]="/sbin/udhcpc\0-f\0-i\0wlan0\0-s\0/tmp/pandanote-connectivity/dhcp.sh\0-p\0/tmp/pandanote-connectivity/dhcp.pid\0-t\0" "3\0-T\0" "3\0-A\0" "5\0";
static void hexdata(const void*p,size_t n,char out[65]){SHA256_CTX c;unsigned char h[32];sha256_init(&c);sha256_update(&c,p,n);sha256_final(&c,h);for(unsigned i=0;i<32;i++)sprintf(out+2*i,"%02x",h[i]);out[64]=0;}
static int exehash(long pid,char out[65]){
#ifdef PANDANOTE_SUSPEND_FIXTURE
 char p[100];snprintf(p,sizeof p,"/.fixture/exe-sha.%ld",pid);char b[80];if(bytes(p,b,sizeof b)!=65||b[64]!='\n')return -1;memcpy(out,b,64);out[64]=0;return 0;
#else
 char p[100];snprintf(p,sizeof p,"/proc/%ld/exe",pid);int f=open(p,O_RDONLY|O_CLOEXEC);if(f<0)return -1;unsigned char b[8192],h[32];SHA256_CTX c;sha256_init(&c);ssize_t n;while((n=read(f,b,sizeof b))>0)sha256_update(&c,b,n);close(f);if(n<0)return -1;sha256_final(&c,h);for(unsigned i=0;i<32;i++)sprintf(out+2*i,"%02x",h[i]);out[64]=0;return 0;
#endif
}
/* Scheduling state is not identity. Re-read the stable tuple after every
 * multi-file proof; an exit is distinct from a live unreadable/foreign PID. */
static int process_same(const struct process*a,const struct process*b){return a->pid==b->pid&&a->ppid==b->ppid&&a->pgid==b->pgid&&a->sid==b->sid&&a->start==b->start;}
static int radio_snapshot(const struct process*before,int result,const struct process*after){
 if(result==10)return !after->start||process_same(before,after)?10:-1;
 return result||!process_same(before,after)||strchr("Tt",after->state)?-1:0;
}
static int radio_vanished(const struct process*before){
 int64_t start=clockms(CLOCK_MONOTONIC);if(start<0)return -1;
 for(unsigned i=0;i<=10;i++){
  struct process after;memset(&after,0,sizeof after);int r=proc(before->pid,&after),state=radio_snapshot(before,r,&after);
  if(state==10)return 10;if(state)return -1;
  /* Linux may clear exe/cmdline before publishing Z. Wait only for this
   * unchanged identity to exit; unreadable live metadata is never proof. */
  int64_t now=clockms(CLOCK_MONOTONIC);if(now<start||now-start>=100||i==10)return -1;
  unsigned remain=(unsigned)(100-(now-start));usleep((remain<10?remain:10)*1000);
 }
 return -1;
}
static int radio_read(unsigned role,long pid,struct owned*o){char p[100],exe[256],cmd[1024];struct process after;memset(o,0,sizeof *o);int r=proc(pid,&o->p);if(r)return r;if(o->p.pgid!=pid||o->p.sid!=pid||(o->p.ppid!=1&&o->p.ppid!=parent())||strchr("Tt",o->p.state))return -1;
 snprintf(p,sizeof p,"/proc/%ld/exe",pid);ssize_t n=readlink(path(p),exe,sizeof exe-1);if(n<0)return radio_vanished(&o->p);if((size_t)n>=sizeof exe-1)return -1;exe[n]=0;if(strcmp(exe,role?"/bin/busybox":"/usr/sbin/wpa_supplicant"))return -1;
 if(exehash(pid,o->exe))return radio_vanished(&o->p);if(strcmp(o->exe,role?BB_SHA:WPA_SHA))return -1;
 snprintf(p,sizeof p,"/proc/%ld/cmdline",pid);int f=open(path(p),O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(f<0)return radio_vanished(&o->p);n=read(f,cmd,sizeof cmd);close(f);size_t expected=role?sizeof dhcp_cmd-1:sizeof wpa_cmd-1;const char*want=role?dhcp_cmd:wpa_cmd;if(n!=(ssize_t)expected||memcmp(cmd,want,expected))return radio_vanished(&o->p);hexdata(cmd,(size_t)n,o->cmd);
 memset(&after,0,sizeof after);r=proc(pid,&after);return radio_snapshot(&o->p,r,&after);
}
static int radio_load(struct owned o[2]){char b[1024],*save,*line,extra;int n=private_read("radio.owned",b,sizeof b,1);if(n<0)return n;unsigned i=0;for(line=strtok_r(b,"\n",&save);line;line=strtok_r(NULL,"\n",&save),i++){if(i>=2)return -1;struct process*p=&o[i].p;memset(&o[i],0,sizeof o[i]);if(sscanf(line,"%ld %ld %ld %ld %llu %64s %64s %c",&p->pid,&p->ppid,&p->pgid,&p->sid,&p->start,o[i].exe,o[i].cmd,&extra)!=7||p->pid<2||p->pid>4194304||p->pgid!=p->pid||p->sid!=p->pid||!p->start||strlen(o[i].exe)!=64||strlen(o[i].cmd)!=64)return -1;}return i==2&&o[0].p.pid!=o[1].p.pid?0:-1;}
static int radio_check(unsigned i,const struct owned*want){struct owned got;int r=radio_read(i,want->p.pid,&got);if(r==10)return got.p.start&&!process_same(&got.p,&want->p)?-1:10;if(r)return r;return !process_same(&got.p,&want->p)||strcmp(got.exe,want->exe)||strcmp(got.cmd,want->cmd)?-1:0;}
static int radio_state(struct owned o[2]){int a=radio_check(0,&o[0]),b=radio_check(1,&o[1]);if(a==0&&b==0)return 0;if(a==10&&b==10)return 10;if((a==0||a==10)&&(b==0||b==10))return 11;return 12;}
static long pidfile(const char*p){char b[32],*e;int n=bytes(p,b,sizeof b);if(n<2)return -1;struct stat s;if(lstat(path(p),&s)||!S_ISREG(s.st_mode)||s.st_uid!=geteuid()||s.st_nlink!=1||(s.st_mode&07777)!=0600)return -1;errno=0;long pid=strtol(b,&e,10);return errno||pid<2||pid>4194304||strcmp(e,"\n")?-1:pid;}
static int radio_capture(void){struct owned old[2],o[2];int r=radio_load(old);if(r!=-2&&(r||radio_state(old)!=10))return -1;long w=pidfile("/tmp/pandanote-connectivity/wpa.pid"),d=pidfile("/tmp/pandanote-connectivity/udhcpc.pid");if(w==d||radio_read(0,w,&o[0])||radio_read(1,d,&o[1]))return -1;char b[512];size_t at=0;for(unsigned i=0;i<2;i++){struct process*p=&o[i].p;at+=(size_t)snprintf(b+at,sizeof b-at,"%ld %ld %ld %ld %llu %s %s\n",p->pid,p->ppid,p->pgid,p->sid,p->start,o[i].exe,o[i].cmd);}return atomic("radio.owned",b,0);}
static int radio_signal(long pid){
#ifdef PANDANOTE_SUSPEND_FIXTURE
 int f=open(path("/.fixture/signals"),O_WRONLY|O_CREAT|O_APPEND,0600);char b[40];snprintf(b,sizeof b,"%ld\n",pid);if(f<0||writeall(f,b,strlen(b)))return -1;close(f);char p[100];snprintf(p,sizeof p,"/.fixture/ignore.%ld",pid);struct stat s;if(!lstat(path(p),&s))return 0;snprintf(p,sizeof p,"/proc/%ld/stat",pid);return unlink(path(p));
#else
 return kill((pid_t)pid,SIGTERM);
#endif
}
static int radio_stop(struct owned o[2]){int initial=radio_state(o);if(initial==10)return 0;if(initial!=0&&initial!=11)return -1;for(int i=1;i>=0;i--){int state=radio_check((unsigned)i,&o[i]);if(state==10)continue;if(state||radio_signal(o[i].p.pid))return -1;}for(unsigned i=0;i<50;i++){int state=radio_state(o);if(state==10)return 0;if(state==12)return -1;
#ifdef PANDANOTE_SUSPEND_FIXTURE
 usleep(1000);
#else
 usleep(100000);
#endif
 }return -1;}
static int radio_clean(struct owned o[2]){if(radio_state(o)!=10)return -1;const char*files[]={"/tmp/pandanote-connectivity/wpa.pid","/tmp/pandanote-connectivity/udhcpc.pid","/tmp/pandanote-connectivity/dhcp.pid"};for(unsigned i=0;i<3;i++){struct stat s;if(lstat(path(files[i]),&s)){if(errno==ENOENT)continue;return -1;}long pid=pidfile(files[i]);if(pid!=o[i?1:0].p.pid)return -1;if(unlink(path(files[i])))return -1;}
 const char*socket="/tmp/pandanote-connectivity/wpa/wlan0";struct stat s;if(!lstat(path(socket),&s)){if(!S_ISSOCK(s.st_mode)||s.st_uid!=geteuid()||s.st_nlink!=1||unlink(path(socket)))return -1;}else if(errno!=ENOENT)return -1;return 0;}
int main(int argc,char**argv){
#ifndef PANDANOTE_SUSPEND_FIXTURE
 if(geteuid()!=0)return 90;
#endif
 umask(077);dirfd_=open(path(RUN),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);struct stat s;if(dirfd_<0||fstat(dirfd_,&s)||s.st_uid!=geteuid()||(s.st_mode&07777)!=0700)return 90;int r=12;
 if((argc==2||argc==3)&&!strcmp(argv[1],"generation")){struct process p;long pid=argc==3?atol(argv[2]):parent();if(!proc(pid,&p)&&p.ppid==1){printf("%ld-%llu\n",pid,p.start);r=0;}}
 else if(argc==3&&!strcmp(argv[1],"setup")){int fds[2]={-1,-1};if(!generation(argv[2])&&!platform(fds)&&!rtc_capable()){char b[100];snprintf(b,sizeof b,"suspend-v2 %s\n",argv[2]);r=atomic("suspend.ready",b,0)?12:0;}input_close(fds);}
 else if(argc==5&&!strcmp(argv[1],"claim"))r=claim(argv[2],atol(argv[3]),argv[4]);
 else if(argc==4&&!strcmp(argv[1],"reconcile"))r=reconcile(argv[2],argv[3]);
 else if(argc==3&&!strcmp(argv[1],"abort")){char b[256],g[49],t[49];int n=private_read("suspend.active",b,sizeof b,1);if(n==-2)r=0;else if(n>=0&&!request_parse(b,g,t)&&!strcmp(g,argv[2]))r=finish(g,t,"failed")?12:0;}
 else if(argc==5&&!strcmp(argv[1],"finish"))r=finish(argv[2],argv[3],argv[4])?12:0;
 else if(argc==6&&!strcmp(argv[1],"check"))r=active_check(argv[2],argv[3],atol(argv[4]),argv[5])?12:0;
 else if(argc==6&&!strcmp(argv[1],"mem"))r=kernel_mem(argv[2],argv[3],atol(argv[4]),argv[5]);
 else if(argc==2&&!strcmp(argv[1],"radio-capture"))r=radio_capture()?12:0;
 else if(argc==2){struct owned o[2];if(!radio_load(o)){if(!strcmp(argv[1],"radio-state"))r=radio_state(o);else if(!strcmp(argv[1],"radio-stop"))r=radio_stop(o)?12:0;else if(!strcmp(argv[1],"radio-clean"))r=radio_clean(o)?12:0;}}
 close(dirfd_);return r;
}
