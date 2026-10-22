#define _GNU_SOURCE
#include <linux/input.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <stdio.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
static volatile sig_atomic_t expired=0;
static void alarmed(int n){(void)n;expired=1;}
int main(void){
 for(int i=0;i<2;i++){
  char p[64],name[64];snprintf(p,sizeof p,"/dev/input/event%d",i);int fd=open(p,O_RDONLY|O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW);if(fd<0){printf("event%d open errno=%d\n",i,errno);continue;}
  memset(name,0,sizeof name);int n=ioctl(fd,EVIOCGNAME(sizeof name),name);printf("event%d name_result=%d name=%s\n",i,n,name);
  unsigned long keys[(KEY_MAX+8*sizeof(unsigned long))/(8*sizeof(unsigned long))];memset(keys,0,sizeof keys);errno=0;n=ioctl(fd,EVIOCGKEY(sizeof keys),keys);printf("event%d keys=%d errno=%d F11=%lu touch=%lu\n",i,n,errno,(keys[KEY_F11/(8*sizeof(unsigned long))]>>(KEY_F11%(8*sizeof(unsigned long))))&1,(keys[BTN_TOUCH/(8*sizeof(unsigned long))]>>(BTN_TOUCH%(8*sizeof(unsigned long))))&1);
  unsigned long absbits[(ABS_MAX+8*sizeof(unsigned long))/(8*sizeof(unsigned long))];memset(absbits,0,sizeof absbits);errno=0;n=ioctl(fd,EVIOCGBIT(EV_ABS,sizeof absbits),absbits);printf("event%d absbits=%d errno=%d SLOT=%lu TRACKING=%lu X=%lu Y=%lu\n",i,n,errno,(absbits[ABS_MT_SLOT/(8*sizeof(unsigned long))]>>(ABS_MT_SLOT%(8*sizeof(unsigned long))))&1,(absbits[ABS_MT_TRACKING_ID/(8*sizeof(unsigned long))]>>(ABS_MT_TRACKING_ID%(8*sizeof(unsigned long))))&1,(absbits[ABS_MT_POSITION_X/(8*sizeof(unsigned long))]>>(ABS_MT_POSITION_X%(8*sizeof(unsigned long))))&1,(absbits[ABS_MT_POSITION_Y/(8*sizeof(unsigned long))]>>(ABS_MT_POSITION_Y%(8*sizeof(unsigned long))))&1);
  struct input_absinfo abs;errno=0;n=ioctl(fd,EVIOCGABS(ABS_MT_SLOT),&abs);printf("event%d ABS_MT_SLOT=%d errno=%d",i,n,errno);if(n>=0)printf(" min=%d max=%d value=%d",abs.minimum,abs.maximum,abs.value);puts("");
  int slots[3]={ABS_MT_TRACKING_ID,-1,-1};errno=0;n=ioctl(fd,EVIOCGMTSLOTS(sizeof slots),slots);printf("event%d MTSLOTS=%d errno=%d slot0=%d slot1=%d\n",i,n,errno,slots[1],slots[2]);
  close(fd);
 }
 struct sigaction sa;memset(&sa,0,sizeof sa);sa.sa_handler=alarmed;sigemptyset(&sa.sa_mask);sigaction(SIGALRM,&sa,0);int fd=open("/sys/power/wakeup_count",O_RDONLY|O_CLOEXEC|O_NOFOLLOW);char b[64];alarm(3);errno=0;int n=fd>=0?read(fd,b,sizeof b-1):-1;int e=errno;alarm(0);if(n>0)b[n]=0;printf("WAKEUP_COUNT read=%d errno=%d expired=%d value=%s\n",n,e,expired,n>0?b:"");if(fd>=0)close(fd);
 return 0;
}
