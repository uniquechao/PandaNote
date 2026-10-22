// Production Linux evdev boundary. No key grabs, driver writes or power syscall.
#include "powerkeys.h"
#include <linux/input.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <limits>
#include <stddef.h>
#ifndef EVIOCSCLOCKID
#define EVIOCSCLOCKID _IOW('E',0xa0,int)
#endif
#if defined(__mips__)
// The retained 4.4 kernel exports the o32 timeval-based 16-byte event ABI.
typedef char PowerInputEventMustBe16Bytes[(sizeof(struct input_event)==16)?1:-1];
typedef char PowerInputEventTypeMustBeAt8[(offsetof(struct input_event,type)==8)?1:-1];
// Match LocalApps and the retained glibc 2.29 o32 version-3 stat converter.
typedef char PowerStatMustBe144Bytes[(sizeof(struct stat)==144)?1:-1];
typedef char PowerStatModeMustBeAt20[(offsetof(struct stat,st_mode)==20)?1:-1];
extern "C" int __fxstat(int,int,struct stat *);
#endif
namespace {
int oldFstat(int fd,struct stat *status){
#if defined(__mips__)
 return __fxstat(3,fd,status);
#else
 return ::fstat(fd,status);
#endif
}
const unsigned WordBits=sizeof(unsigned long)*8;
bool bit(const unsigned long *bits,unsigned index){return (bits[index/WordBits]&(1UL<<(index%WordBits)))!=0;}
int64_t milliseconds(int64_t seconds,int64_t micros){
 if(seconds<0||micros<0||micros>=1000000||seconds>(std::numeric_limits<int64_t>::max()-999)/1000)return -1;
 return seconds*1000+micros/1000;
}
}
int64_t powerKeyNowMs(){struct timespec now;if(::clock_gettime(CLOCK_MONOTONIC,&now)!=0)return -1;return milliseconds(now.tv_sec,now.tv_nsec/1000);}
void powerKeyClose(int fd){if(fd>=0)::close(fd);}
bool powerKeyHeld(int fd,bool *held){PowerKeyHeldState state;if(!held||!powerKeyHeld(fd,&state))return false;*held=state.power;return true;}
bool powerKeyHeld(int fd,PowerKeyHeldState *held){
 if(!held)return false;
 unsigned long keys[(KEY_MAX+WordBits)/WordBits];memset(keys,0,sizeof(keys));
 if(::ioctl(fd,EVIOCGKEY(sizeof(keys)),keys)<0)return false;
 held->power=bit(keys,PowerKeyF11);held->previous=bit(keys,PowerKeyPageUp);held->next=bit(keys,PowerKeyPageDown);return true;
}
int powerKeyOpenCandidate(int index,bool *held){PowerKeyHeldState state;if(!held)return -1;int fd=powerKeyOpenCandidate(index,&state);if(fd>=0)*held=state.power;return fd;}
int powerKeyOpenCandidate(int index,PowerKeyHeldState *held){
 if(index<0||index>15||!held)return -1;
 char path[32];snprintf(path,sizeof(path),"/dev/input/event%d",index);
 const int fd=::open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW);
 if(fd<0)return -1;
 struct stat status;char name[64];memset(name,0,sizeof(name));
 unsigned long types[(EV_MAX+WordBits)/WordBits],keys[(KEY_MAX+WordBits)/WordBits];memset(types,0,sizeof(types));memset(keys,0,sizeof(keys));
 const int clockId=CLOCK_MONOTONIC;
 // Only the exact board driver name already observed in retained evidence.
 if(oldFstat(fd,&status)!=0||!S_ISCHR(status.st_mode)||::ioctl(fd,EVIOCGNAME(sizeof(name)),name)<0||name[sizeof(name)-1]!=0||strcmp(name,"md-gpio-keys")!=0||
    ::ioctl(fd,EVIOCGBIT(0,sizeof(types)),types)<0||!bit(types,EV_KEY)||::ioctl(fd,EVIOCGBIT(EV_KEY,sizeof(keys)),keys)<0||!bit(keys,PowerKeyF11)||
    ::ioctl(fd,EVIOCSCLOCKID,&clockId)<0||!powerKeyHeld(fd,held)||powerKeyNowMs()<0){powerKeyClose(fd);return -1;}
 return fd;
}
namespace {
bool sameInputDevice(const struct stat &a,const struct stat &b){
 return S_ISCHR(a.st_mode)&&S_ISCHR(b.st_mode)&&a.st_dev==b.st_dev&&a.st_ino==b.st_ino&&a.st_rdev==b.st_rdev;
}
}
bool powerKeySnapshotHeld(int originalFd,bool *held){PowerKeyHeldState state;if(!held||!powerKeySnapshotHeld(originalFd,&state))return false;*held=state.power;return true;}
bool powerKeySnapshotHeld(int originalFd,PowerKeyHeldState *held){
 if(!held)return false;
 struct stat original;if(oldFstat(originalFd,&original)||!S_ISCHR(original.st_mode))return false;
 // Opening the device creates another evdev client. dup() would share the
 // original event queue, allowing GETKEY to erase an intervening complete tap.
 for(int index=0;index<16;++index){
  PowerKeyHeldState candidateHeld;int candidate=powerKeyOpenCandidate(index,&candidateHeld);if(candidate<0)continue;
  struct stat fresh,after;bool readOk=oldFstat(candidate,&fresh)==0&&oldFstat(originalFd,&after)==0;
  powerKeyClose(candidate);
  if(!readOk||!sameInputDevice(original,after))return false;
  if(sameInputDevice(original,fresh)){*held=candidateHeld;return true;}
 }
 return false;
}
int powerKeyReadEvents(int fd,PowerKeyEvent *events,unsigned capacity){
 if(!events||capacity==0||capacity>32)return -1;
 struct input_event raw[32];ssize_t bytes;
 do{bytes=::read(fd,raw,capacity*sizeof(raw[0]));}while(bytes<0&&errno==EINTR);
 if(bytes<0)return errno==EAGAIN||errno==EWOULDBLOCK?PowerReadAgain:-1;
 // Partial input records never carry a trusted key edge across calls.
 if(bytes==0||size_t(bytes)%sizeof(raw[0])!=0)return -1;
 const int count=int(bytes/sizeof(raw[0]));
 for(int i=0;i<count;++i){
  const int64_t stamp=milliseconds(raw[i].time.tv_sec,raw[i].time.tv_usec);if(stamp<0)return -1;
  events[i].type=raw[i].type;events[i].code=raw[i].code;events[i].value=raw[i].value;events[i].milliseconds=stamp;
 }
 return count;
}
