#include "powerrequest.h"
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <stddef.h>
#include <string.h>
#if defined(__linux__)
#include <sys/syscall.h>
#endif
#if defined(__mips__) && defined(__linux__)
typedef char RequestStatSize[sizeof(struct stat)==144?1:-1];
typedef char RequestStatMode[offsetof(struct stat,st_mode)==20?1:-1];
typedef char RequestStatUid[offsetof(struct stat,st_uid)==28?1:-1];
extern "C" int __fxstat(int,int,struct stat *);
extern "C" int __fxstatat(int,int,const char *,struct stat *,int);
static int requestStat(int fd,struct stat *s){return __fxstat(3,fd,s);}
static int requestStatAt(int fd,const char *name,struct stat *s){return __fxstatat(3,fd,name,s,AT_SYMLINK_NOFOLLOW);}
#else
static int requestStat(int fd,struct stat *s){return ::fstat(fd,s);}
static int requestStatAt(int fd,const char *name,struct stat *s){return ::fstatat(fd,name,s,AT_SYMLINK_NOFOLLOW);}
#endif
#ifdef PANDANOTE_POWERREQUEST_TEST
extern "C" ssize_t powerRequestTestWrite(int,const void *,size_t);
extern "C" int powerRequestTestFsync(int);
extern "C" int powerRequestTestClose(int);
extern "C" int powerRequestTestRename(int,const char *,int,const char *);
#define requestWrite powerRequestTestWrite
#define requestSync powerRequestTestFsync
#define requestClose powerRequestTestClose
#define requestRename powerRequestTestRename
#else
static ssize_t requestWrite(int fd,const void *p,size_t n){return ::write(fd,p,n);}
static int requestSync(int fd){return ::fsync(fd);}
static int requestClose(int fd){return ::close(fd);}
static int requestRename(int a,const char *oldname,int b,const char *newname){
#if defined(__APPLE__)
 return ::renameatx_np(a,oldname,b,newname,RENAME_EXCL);
#elif defined(__linux__) && defined(SYS_renameat2)
 return int(::syscall(SYS_renameat2,a,oldname,b,newname,1)); // RENAME_NOREPLACE
#else
 (void)a;(void)oldname;(void)b;(void)newname;errno=ENOSYS;return -1;
#endif
}
#endif
namespace {
int privateDirectory(const char *raw){
 if(!raw){errno=EINVAL;return -1;}
 const size_t length=::strnlen(raw,4097);
 if(length<2||length>4096||raw[0]!='/'||raw[length-1]=='/'){errno=EINVAL;return -1;}
 // Open the first component directly, matching the retained QEMU sysroot
 // boundary. O_NOFOLLOW protects every ancestor, not only the private leaf.
 const char *part=raw+1;int fd=-1;
 for(;;){
  const char *end=::strchr(part,'/');const size_t size=end ? size_t(end-part) : ::strlen(part);
  if(!size||(size==1&&part[0]=='.')||(size==2&&part[0]=='.'&&part[1]=='.')){if(fd>=0)::close(fd);errno=EINVAL;return -1;}
  char name[4098];size_t prefix=fd<0?1:0;name[0]='/';::memcpy(name+prefix,part,size);name[size+prefix]=0;
  int next=fd<0?::open(name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC):
   ::openat(fd,name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
  if(fd>=0)::close(fd);
  fd=next;if(fd<0)return -1;
  if(!end)break;
  part=end+1;
 }
 struct stat st;
 if(requestStat(fd,&st)||!S_ISDIR(st.st_mode)||st.st_uid!=::geteuid()||(st.st_mode&07777)!=0700){::close(fd);errno=EACCES;return -1;}
 return fd;
}
}
static bool publishRequest(const char *directory,const char *finalName,const char *content){
 const int dir=privateDirectory(directory);if(dir<0)return false;
 struct stat st;
 if(!requestStatAt(dir,finalName,&st)||errno!=ENOENT){::close(dir);errno=EEXIST;return false;}
 char temporary[64];snprintf(temporary,sizeof(temporary),".%s-%ld.pending",finalName,long(::getpid()));
 int file=::openat(dir,temporary,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
 if(file<0){int saved=errno;::close(dir);errno=saved;return false;}
 bool ok=::fchmod(file,0600)==0;const size_t length=::strlen(content);size_t offset=0;
 while(ok&&offset<length){
  const ssize_t written=requestWrite(file,content+offset,length-offset);
  if(written<0&&errno==EINTR)continue;
  if(written<=0){ok=false;break;}offset+=size_t(written);
 }
 if(ok&&requestSync(file))ok=false;
 if(requestClose(file))ok=false;
 if(ok&&requestRename(dir,temporary,dir,finalName))ok=false;
 if(!ok){int saved=errno;::unlinkat(dir,temporary,0);::close(dir);errno=saved;return false;}
 // The service can consume the final name now. Never unlink it or report
 // "not published" after this point, including a directory-fsync failure.
 const int synced=requestSync(dir);const int saved=errno;::close(dir);if(synced)errno=saved;
 return true;
}

bool publishPowerOffRequest(const char *directory){return publishRequest(directory,"poweroff.request","poweroff-v1\n");}
namespace {
bool pairValid(const char *value){
 if(!value)return false;size_t n=::strnlen(value,49);if(n<3||n>48)return false;
 bool second=false,first=true;for(size_t i=0;i<n;++i){char c=value[i];if(c=='-'&&!second&&!first){second=true;first=true;continue;}if(c<'0'||c>'9'||(first&&c=='0'))return false;first=false;}return second&&!first;
}
bool privateText(const char *directory,const char *name,char *out,size_t capacity){
 int dir=privateDirectory(directory);if(dir<0)return false;
 int fd=::openat(dir,name,O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);::close(dir);if(fd<0)return false;
 struct stat s;if(requestStat(fd,&s)||!S_ISREG(s.st_mode)||s.st_uid!=::geteuid()||(s.st_mode&07777)!=0600||s.st_nlink!=1||s.st_size<=0||size_t(s.st_size)>=capacity){::close(fd);return false;}
 size_t at=0;while(at<capacity-1){ssize_t n=::read(fd,out+at,capacity-1-at);if(n<0&&errno==EINTR)continue;if(n<0){::close(fd);return false;}if(!n)break;at+=size_t(n);}::close(fd);if(at!=size_t(s.st_size)||at==capacity-1||::memchr(out,0,at))return false;out[at]=0;return true;
}
}
bool readSuspendGeneration(const char *directory,char generation[49]){
 char raw[128],gen[49],canonical[128];if(!generation||!privateText(directory,"suspend.ready",raw,sizeof(raw))||sscanf(raw,"suspend-v2 %48s",gen)!=1||!pairValid(gen))return false;
 snprintf(canonical,sizeof(canonical),"suspend-v2 %s\n",gen);if(strcmp(raw,canonical))return false;strcpy(generation,gen);return true;
}
bool publishSuspendRequest(const char *directory,const char *generation,const char *token){
 if(!pairValid(generation)||!pairValid(token))return false;
 char actual[49],raw[160];if(!readSuspendGeneration(directory,actual)||strcmp(actual,generation))return false;
 snprintf(raw,sizeof(raw),"suspend-v2 %s %s\n",generation,token);return publishRequest(directory,"suspend.request",raw);
}
SuspendReply readSuspendReply(const char *directory,const char *generation,const char *token){
 if(!pairValid(generation)||!pairValid(token))return NoSuspendReply;
 char raw[192],gen[49],id[49],result[16],canonical[192];if(!privateText(directory,"resume.status",raw,sizeof(raw))||sscanf(raw,"resume-v2 %48s %48s %15s",gen,id,result)!=3)return NoSuspendReply;
 snprintf(canonical,sizeof(canonical),"resume-v2 %s %s %s\n",gen,id,result);if(strcmp(raw,canonical)||strcmp(gen,generation)||strcmp(id,token))return NoSuspendReply;
 if(!strcmp(result,"resumed"))return SuspendResumed;
 if(!strcmp(result,"timer"))return SuspendTimerResumed;
 if(!strcmp(result,"busy")||!strcmp(result,"unsafe")||!strcmp(result,"failed"))return SuspendRejected;
 return NoSuspendReply;
}

bool cancelSuspendRequest(const char *directory,const char *leaseDirectory,const char *generation,const char *token){
 if(!pairValid(generation)||!pairValid(token))return false;
 int base=privateDirectory(leaseDirectory);if(base<0)return false;
 int lease=::openat(base,"normal-install.lock",O_RDWR|O_NOFOLLOW|O_CLOEXEC);::close(base);if(lease<0)return false;
 struct stat st;if(requestStat(lease,&st)||!S_ISREG(st.st_mode)||st.st_uid!=::geteuid()||(st.st_mode&07777)!=0600||st.st_nlink!=1||::flock(lease,LOCK_EX|LOCK_NB)){::close(lease);return false;}
 int dir=privateDirectory(directory);if(dir<0){::close(lease);return false;}
 char wake[96],ready[96],allow[96];snprintf(wake,sizeof wake,"suspend.wake-%s",token);snprintf(ready,sizeof ready,"suspend.input-ready-%s",token);snprintf(allow,sizeof allow,"suspend.input-allow-%s",token);
 const char *names[]={"suspend.request","suspend.active",wake,ready,allow};const char *wire[]={"suspend-v2","suspend-v2","wake-v2","input-ready-v2","input-allow-v2"};bool present[5]={false,false,false,false,false};bool safe=true;
 char expected[160];
 for(unsigned i=0;i<5&&safe;++i){
  snprintf(expected,sizeof expected,"%s %s %s\n",wire[i],generation,token);
  if(requestStatAt(dir,names[i],&st)){if(errno!=ENOENT)safe=false;continue;}
  char raw[160];if(!privateText(directory,names[i],raw,sizeof(raw))||strcmp(raw,expected)){safe=false;break;}present[i]=true;
 }
 if(safe)for(unsigned i=0;i<5;++i)if(present[i]&&::unlinkat(dir,names[i],0)&&errno!=ENOENT)safe=false;
 if(safe)::fsync(dir);
 ::close(dir);::close(lease);return safe;
}

namespace {
bool pendingSuspend(const char *directory,const char *generation,const char *token){
 if(!pairValid(generation)||!pairValid(token))return false;
 char actual[49],raw[160],expected[160];if(!readSuspendGeneration(directory,actual)||strcmp(actual,generation))return false;
 snprintf(expected,sizeof expected,"suspend-v2 %s %s\n",generation,token);
 return (privateText(directory,"suspend.active",raw,sizeof raw)&&!strcmp(raw,expected))||(privateText(directory,"suspend.request",raw,sizeof raw)&&!strcmp(raw,expected));
}
bool publishSuspendMarker(const char *directory,const char *generation,const char *token,const char *kind,const char *wire){
 char name[96],raw[160],previous[160];snprintf(name,sizeof name,"suspend.%s-%s",kind,token);snprintf(raw,sizeof raw,"%s %s %s\n",wire,generation,token);
 if(privateText(directory,name,previous,sizeof previous))return !strcmp(raw,previous);
 return publishRequest(directory,name,raw);
}
}
bool publishSuspendWakeIntent(const char *directory,const char *generation,const char *token){
 return pendingSuspend(directory,generation,token)&&publishSuspendMarker(directory,generation,token,"wake","wake-v2");
}
bool suspendInputReady(const char *directory,const char *generation,const char *token){
 if(!pendingSuspend(directory,generation,token))return false;
 char name[96],raw[160],expected[160];snprintf(name,sizeof name,"suspend.input-ready-%s",token);snprintf(expected,sizeof expected,"input-ready-v2 %s %s\n",generation,token);
 return privateText(directory,name,raw,sizeof raw)&&!strcmp(raw,expected);
}

bool acknowledgeSuspendInput(const char *directory,const char *generation,const char *token){return suspendInputReady(directory,generation,token)&&publishSuspendMarker(directory,generation,token,"input-allow","input-allow-v2");}
