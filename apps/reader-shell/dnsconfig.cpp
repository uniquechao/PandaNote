#include "dnsconfig.h"
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <string.h>
#include <stddef.h>
#include <errno.h>
#if defined(__GLIBC__)
#include <resolv.h>
extern "C" int __res_init(void);
#if defined(__mips__)
typedef char DnsStateOptions[offsetof(struct __res_state,options)==8?1:-1];
typedef char DnsStateCount[offsetof(struct __res_state,nscount)==12?1:-1];
typedef char DnsStateServers[offsetof(struct __res_state,nsaddr_list)==16?1:-1];
#endif
#elif defined(PANDANOTE_DNSCONFIG_TEST)
extern "C" bool dnsConfigTestApply(const char [3][16],unsigned);
#endif
#if defined(__mips__) && defined(__linux__)
typedef char DnsStatSize[sizeof(struct stat)==144?1:-1];
extern "C" int __fxstat(int,int,struct stat *);
static int fileStat(int fd,struct stat *s){return __fxstat(3,fd,s);}
#else
static int fileStat(int fd,struct stat *s){return fstat(fd,s);}
#endif
static int openPrivate(const char *raw){
 if(!raw)return -1;size_t length=strnlen(raw,4097);if(length<2||length>4096||raw[0]!='/'||raw[length-1]=='/')return -1;
 const char *part=raw+1;int fd=-1;
 for(;;){const char *end=strchr(part,'/');size_t size=end?size_t(end-part):strlen(part);if(!size||(size==1&&part[0]=='.')||(size==2&&part[0]=='.'&&part[1]=='.')){if(fd>=0)close(fd);return -1;}
  char name[4098];size_t prefix=fd<0?1:0;name[0]='/';memcpy(name+prefix,part,size);name[size+prefix]=0;
  int next=fd<0?open(name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC):openat(fd,name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(fd>=0)close(fd);fd=next;if(fd<0)return -1;if(!end)break;part=end+1;
 }
 struct stat st;if(fileStat(fd,&st)||!S_ISDIR(st.st_mode)||st.st_uid!=geteuid()||(st.st_mode&07777)!=0700){close(fd);return -1;}return fd;
}
bool configureDhcpDns(const char *directory){
 int dir=openPrivate(directory);if(dir<0)return false;
 int fd=openat(dir,"resolv.conf",O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);close(dir);if(fd<0)return false;
 struct stat before,after;bool ok=!fileStat(fd,&before)&&S_ISREG(before.st_mode)&&before.st_uid==geteuid()&&(before.st_mode&07777)==0600&&before.st_nlink==1&&before.st_size>0&&before.st_size<=256;
 char raw[257];size_t used=0;
 while(ok&&used<sizeof raw){ssize_t n=read(fd,raw+used,sizeof raw-used);if(n<0&&errno==EINTR)continue;if(n<0){ok=false;break;}if(!n)break;used+=size_t(n);}
 ok=ok&&used==size_t(before.st_size)&&!fileStat(fd,&after)&&before.st_dev==after.st_dev&&before.st_ino==after.st_ino&&before.st_size==after.st_size&&before.st_uid==after.st_uid&&before.st_mode==after.st_mode&&after.st_nlink==1;
 if(close(fd))ok=false;if(!ok)return false;
 char servers[3][16];memset(servers,0,sizeof servers);unsigned count=0;size_t at=0;
 while(at<used){if(count==3||used-at<13||memcmp(raw+at,"nameserver ",11))return false;at+=11;size_t end=at;while(end<used&&raw[end]!='\n')end++;size_t n=end-at;if(end==used||n<7||n>15)return false;
  char ip[16],canonical[16];memcpy(ip,raw+at,n);ip[n]=0;struct in_addr value;
  if(inet_pton(AF_INET,ip,&value)!=1||!inet_ntop(AF_INET,&value,canonical,sizeof canonical)||strcmp(ip,canonical)||value.s_addr==INADDR_ANY)return false;
  for(unsigned i=0;i<count;i++)if(!strcmp(servers[i],ip))return false;strcpy(servers[count++],ip);at=end+1;
 }
 if(!count)return false;
#if defined(__GLIBC__)
 // Fresh exec, before Qt or NSS threads. glibc 2.29 exports these in libc.
 // RES_NORELOAD prevents /etc/resolv.conf from replacing the DHCP snapshot.
 if(__res_init())return false;res_state state=__res_state();if(!state)return false;
 state->options=RES_INIT|RES_RECURSE|RES_NOALIASES|RES_NORELOAD;
 state->retrans=2;state->retry=1;state->nscount=int(count);memset(state->nsaddr_list,0,sizeof state->nsaddr_list);
 for(unsigned i=0;i<count;i++){state->nsaddr_list[i].sin_family=AF_INET;state->nsaddr_list[i].sin_port=htons(53);if(inet_pton(AF_INET,servers[i],&state->nsaddr_list[i].sin_addr)!=1)return false;}
 return true;
#elif defined(PANDANOTE_DNSCONFIG_TEST)
 return dnsConfigTestApply(servers,count);
#else
 return false;
#endif
}
