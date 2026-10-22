/* C5 41c6c39 preflight copied without changing the frozen five-second tool.
 * Metadata/hash checks only; no serial FD opened here. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "preflight.h"
#include "../c2/core.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/statvfs.h>
#include <sys/sysmacros.h>
#include <unistd.h>
static int read_text(const char *path,char *text,size_t capacity){
 int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return -1;
 size_t used=0;for(;;){ssize_t n=read(fd,text+used,capacity-1-used);if(n<0&&errno==EINTR)continue;if(n<0){close(fd);return -1;}if(!n)break;used+=(size_t)n;if(used==capacity-1){close(fd);return -1;}}
 close(fd);text[used]=0;return 0;
}
static int module(const char *all,const char *name){size_t n=strlen(name);for(const char *p=all;p&&*p;p=strchr(p,'\n')){if(*p=='\n')p++;if(!strncmp(p,name,n)&&p[n]==' ')return 1;}return 0;}
int c6_pin(const char *path,const char *digest,unsigned bytes,unsigned exact){
 int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);struct stat s;
 if(fd<0||fstat(fd,&s)||!S_ISREG(s.st_mode)||s.st_uid||s.st_nlink!=1||s.st_size!=(off_t)bytes||(exact?(s.st_mode&07777)!=exact:(s.st_mode&0022)!=0)||c2_hash(fd,digest,bytes)){if(fd>=0)close(fd);return -1;}return fd;
}
static int idle(dev_t serial){
 DIR *proc=opendir("/proc");if(!proc)return -1;struct dirent *entry;unsigned processes=0,descriptors=0;int result=0;
 for(;;){errno=0;entry=readdir(proc);if(!entry){if(errno)result=-1;break;}if(entry->d_name[0]<'0'||entry->d_name[0]>'9')continue;char *end=NULL;strtol(entry->d_name,&end,10);if(!end||*end)continue;if(++processes>256){result=-1;break;}
  char path[80];int length=snprintf(path,sizeof path,"/proc/%s/fd",entry->d_name);if(length<0||(size_t)length>=sizeof path){result=-1;break;}int fd=open(path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(fd<0){if(errno==ENOENT||errno==ESRCH)continue;result=-1;break;}DIR *files=fdopendir(fd);if(!files){close(fd);result=-1;break;}struct dirent *file;
  for(;;){errno=0;file=readdir(files);if(!file){if(errno)result=-1;break;}if(file->d_name[0]=='.')continue;if(++descriptors>4096){result=-1;break;}struct stat s;if(fstatat(fd,file->d_name,&s,0)){if(errno==ENOENT||errno==ESRCH)continue;result=-1;break;}if(S_ISCHR(s.st_mode)&&s.st_rdev==serial){result=-1;break;}}
  closedir(files);if(result)break;
 }
 closedir(proc);return result;
}
int c6_preflight(void){
 struct statfs fs;struct stat tty;char modules[4096],consoles[2048];
 if(geteuid()!=0||statfs("/tmp",&fs)||fs.f_type!=0x01021994||lstat("/dev/ttyS3",&tty)||!S_ISCHR(tty.st_mode)||tty.st_uid||(tty.st_mode&07777)!=0600||major(tty.st_rdev)!=4||minor(tty.st_rdev)!=67||read_text("/proc/modules",modules,sizeof modules)||!module(modules,"aic8800_bsp")||!module(modules,"aic8800_fdrv")||module(modules,"aic8800_btlpm")||read_text("/proc/consoles",consoles,sizeof consoles)||strstr(consoles,"ttyS3")||idle(tty.st_rdev)){puts("C6 attach preflight rejected; no serial opened");return -1;}
 int hci=open("/sys/class/bluetooth",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(hci<0||c2_empty(hci)){if(hci>=0)close(hci);puts("C6 requires no existing HCI");return -1;}close(hci);
 const char *paths[]={"/module_driver/aic8800_bsp.ko","/module_driver/aic8800_fdrv.ko","/lib/libc-2.29.so","/lib/ld-2.29.so"};
 const char *pins[]={"35e0cb9542b2d2e3d9e7889070e4c2659e7ade5c1ab159a9f5b34c0dfa232142","82bd636c3f6b91687ec92922bef48e4ae978a4ed9d558c502bd70a91297be1f2","fb2c85aa7e6933d9ce92530427b8272a9dbfad300696e995b542b93f5fb228b6","0c37c07942b176a223b5fd4e1bcd0b7e5ebdf6205bce727ee0f895dd22caf0e2"};
 unsigned sizes[]={129380,597424,0,0};
 for(unsigned i=0;i<4;i++){
  if(!sizes[i]){struct stat s;if(lstat(paths[i],&s)||!S_ISREG(s.st_mode)||s.st_size<=0||s.st_size>4194304)return -1;sizes[i]=(unsigned)s.st_size;}
  int fd=c6_pin(paths[i],pins[i],sizes[i],0);if(fd<0){puts("C6 input rejected");return -1;}
  if(i>=2){const char *alias=i==2?"/lib/libc.so.6":"/lib/ld-linux-mipsn8.so.1";struct stat direct,linked;if(fstat(fd,&direct)||stat(alias,&linked)||direct.st_dev!=linked.st_dev||direct.st_ino!=linked.st_ino){close(fd);return -1;}}
  close(fd);
 }
 int executable=c6_pin("/usr/bin/btattach","746dee0da16884400a32eb89f64df58378824927901e8afe65157d574722ea6f",47536,0755);if(executable<0)return -1;
 return executable;
}

#define C6_ROOT "/tmp/pandanote-connectivity/bluetooth"
int c6_inbox(const char *path){
 if(!path||path[0]!='/'||strlen(path)>240||!strcmp(path,"/")||!strncmp(path,C6_ROOT,strlen(C6_ROOT)))return -1;
 size_t length=strlen(path);if(length<=strlen(C6_ROOT)&&!strncmp(C6_ROOT,path,length)&&(C6_ROOT[length]==0||C6_ROOT[length]=='/'))return -1;
 char copy[256];strcpy(copy,path);int fd=open("/",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return -1;
 char *part=copy+1;unsigned depth=0;
 while(*part){char *slash=strchr(part,'/');if(slash)*slash=0;
  if(!*part||!strcmp(part,".")||!strcmp(part,"..")||++depth>16){close(fd);return -1;}
  int next=openat(fd,part,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);close(fd);fd=next;
  struct stat s;if(fd<0||fstat(fd,&s)||s.st_uid!=0){if(fd>=0)close(fd);return -1;}
  int temporary=depth==1&&!strcmp(part,"tmp")&&(s.st_mode&07777)==01777;
  if((s.st_mode&0022)&&!temporary){close(fd);return -1;}
  if(!slash)break;
  part=slash+1;if(!*part){close(fd);return -1;}
 }
 struct stat s;struct statvfs fs;
 if(fstat(fd,&s)||(s.st_mode&07777)!=0700||fstatvfs(fd,&fs)||(fs.f_flag&ST_RDONLY)||!fs.f_frsize||fs.f_bavail<1048576/fs.f_frsize+1){close(fd);return -1;}
 return fd;
}
