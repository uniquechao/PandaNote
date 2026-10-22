#include "battery.h"
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/ioctl.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <signal.h>
#include <time.h>
#include <errno.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#if defined(__mips__)
typedef char BatteryStatSize[(sizeof(struct stat)==144)?1:-1];
typedef char BatteryStatModeOffset[(offsetof(struct stat,st_mode)==20)?1:-1];
extern "C" int __fxstat(int,int,struct stat *);
#endif
#ifdef PANDANOTE_BATTERY_POSIX_FIXTURE
extern void batteryFixtureSample(unsigned char *,int *,int *);
#endif
namespace {
int oldFstat(int fd,struct stat *s){
#if defined(__mips__)
 return __fxstat(3,fd,s);
#else
 return ::fstat(fd,s);
#endif
}
int64_t nowMs(){struct timespec t;
 if(::clock_gettime(CLOCK_MONOTONIC,&t)!=0)return -1;
 return int64_t(t.tv_sec)*1000+t.tv_nsec/1000000;}
// Called serially on the GUI thread. Never replace a not-yet-reaped owned PID.
pid_t pendingChild=-1;
void collect(pid_t child,bool stop){
 if(child<=0)return;
 if(stop)::kill(child,SIGKILL);
 int status=0;pid_t done=::waitpid(child,&status,WNOHANG);
 if(done==child||(done<0&&errno==ECHILD))pendingChild=-1;else pendingChild=child;
}
struct SampleMessage { int count,error;unsigned char bytes[4]; };
void worker(int output){
 SampleMessage result;result.count=-1;result.error=0;memset(result.bytes,0,4);
#ifdef PANDANOTE_BATTERY_POSIX_FIXTURE
 ::batteryFixtureSample(result.bytes,&result.count,&result.error);
#else
 int fd=::open("/dev/jz_adc_aux_1",O_RDONLY|O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW);
 if(fd<0)result.error=errno;
 else {
  struct stat s;
  // This query returns the reference mV as ioctl's integer result, not *arg.
  if(oldFstat(fd,&s)!=0)result.error=errno;
  else if(!S_ISCHR(s.st_mode))result.error=ENODEV;
  else {const int vref=::ioctl(fd,_IOWR('A',44,int),0);
 if(vref!=1800)result.error=vref<0?errno:ERANGE;
   else {ssize_t count;do{count=::read(fd,result.bytes,4);}while(count<0&&errno==EINTR);result.count=int(count);
 if(count!=4)result.error=count<0?errno:EIO;}
  }
  if(::close(fd)!=0&&!result.error){result.error=errno;result.count=-1;}
 }
#endif
 const unsigned char *data=reinterpret_cast<const unsigned char *>(&result);unsigned written=0;
 while(written<sizeof(result)){ssize_t n=::write(output,data+written,sizeof(result)-written);
 if(n<0&&errno==EINTR)continue;
 if(n<=0)break;
 written+=unsigned(n);}
 ::close(output);::_exit(0);
}
bool readText(const char *path,char *value,unsigned capacity){
 int fd=::open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW);
 if(fd<0)return false;
 struct stat s;
 bool ok=oldFstat(fd,&s)==0&&S_ISREG(s.st_mode);ssize_t n=-1;
 if(ok){do{n=::read(fd,value,capacity-1);}while(n<0&&errno==EINTR);ok=n>0&&unsigned(n)<capacity-1;}
 if(::close(fd)!=0)ok=false;
 if(!ok)return false;
 value[n]=0;while(n>0&&(value[n-1]=='\n'||value[n-1]=='\r'||value[n-1]==' '||value[n-1]=='\t'))value[--n]=0;
 return true;
}
}
int batteryAdcRead(unsigned char bytes[4],int *error){
 if(error)*error=0;
 if(!bytes||!error)return -1;
 if(pendingChild>0){collect(pendingChild,false);
 if(pendingChild>0){*error=EBUSY;
 return -1;}}
 const int64_t started=nowMs();
 if(started<0){*error=EIO;
 return -1;}
 int pipeFd[2];
 if(::pipe(pipeFd)!=0){*error=errno;
 return -1;}
 if(::fcntl(pipeFd[0],F_SETFD,FD_CLOEXEC)<0||::fcntl(pipeFd[1],F_SETFD,FD_CLOEXEC)<0||::fcntl(pipeFd[0],F_SETFL,O_NONBLOCK)<0){*error=errno;::close(pipeFd[0]);::close(pipeFd[1]);
 return -1;}
 const pid_t child=::fork();
 if(child<0){*error=errno;::close(pipeFd[0]);::close(pipeFd[1]);
 return -1;}
 if(child==0){::close(pipeFd[0]);worker(pipeFd[1]);}
 ::close(pipeFd[1]);SampleMessage result;unsigned received=0;bool complete=false;const int64_t deadline=started+250;
 while(!complete){
  const int64_t current=nowMs();
 if(current<0){*error=EIO;break;}if(current>=deadline){*error=ETIMEDOUT;break;}
  struct pollfd item;item.fd=pipeFd[0];item.events=POLLIN;item.revents=0;
  const int ready=::poll(&item,1,int(deadline-current));
 if(ready<0){if(errno==EINTR)continue;*error=errno;break;}if(ready==0){*error=ETIMEDOUT;break;}
  const ssize_t count=::read(pipeFd[0],reinterpret_cast<unsigned char *>(&result)+received,sizeof(result)-received);
  if(count<0&&(errno==EINTR||errno==EAGAIN))continue;
 if(count<=0){*error=count<0?errno:EIO;break;}
  received+=unsigned(count);complete=received==sizeof(result);
 }
 ::close(pipeFd[0]);collect(child,!complete);
 if(!complete)return -1;
 if(result.count!=4||result.error){*error=result.error?result.error:EIO;
 return -1;}
 memcpy(bytes,result.bytes,4);
 return 4;
}
int batteryChargingStatus(){
 // USB presence is not charging evidence. No GPIO export/direction/value writes.
 const char *roots[]={"/sys/class/power_supply/battery/","/sys/class/power_supply/Battery/"};
 for(unsigned i=0;i<2;++i){char path[96],type[32],status[32];const size_t n=strlen(roots[i]);memcpy(path,roots[i],n);strcpy(path+n,"type");
 if(!readText(path,type,sizeof(type))||strcmp(type,"Battery"))continue;
  strcpy(path+n,"status");
 if(!readText(path,status,sizeof(status)))continue;
  if(!strcmp(status,"Charging"))return 1;
  if(!strcmp(status,"Discharging")||!strcmp(status,"Not charging")||!strcmp(status,"Full"))return 0;
 }
 return -1;
}
