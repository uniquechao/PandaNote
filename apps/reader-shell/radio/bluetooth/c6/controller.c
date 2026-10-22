#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "controller.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/sysmacros.h>
#include <time.h>
#include <unistd.h>
/* sysfs names/attributes are kernel-owned. Following hci0's sysfs symlink is
 * intentional; retain its dev/inode to detect replacement during this lease. */
/* Linux4.4 hci_sysfs.c puts hci0:HANDLE links in the same class; those
 * are connections on this controller, not a second unowned controller. */
int c6_class_entry(const char *name){
 if(!strcmp(name,"hci0"))return 1;
 if(strncmp(name,"hci0:",5)||!name[5])return -1;
 unsigned value=0,count=0;for(const char *p=name+5;*p;p++){if(*p<'0'||*p>'9'||++count>5)return -1;value=value*10+(unsigned)(*p-'0');}
 return value<=65535?0:-1;
}
static int only_hci0(int root){
 int fd=openat(root,".",O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(fd<0)return -1;DIR *dir=fdopendir(fd);if(!dir){close(fd);return -1;}
 int found=0,code=0;struct dirent *e;
 for(;;){errno=0;e=readdir(dir);if(!e){if(errno)code=-1;break;}if(!strcmp(e->d_name,".")||!strcmp(e->d_name,".."))continue;int kind=c6_class_entry(e->d_name);if(kind<0||(kind==1&&found++)){code=-1;break;}}
 closedir(dir);return code?code:found==1?0:-1;
}
static int attribute(int dir,const char *name,const char *expected){
 char text[80];int fd=openat(dir,name,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return -1;ssize_t n=read(fd,text,sizeof text);int error=errno;close(fd);errno=error;
 size_t size=strlen(expected);return n==(ssize_t)(size+1)&&!memcmp(text,expected,size)&&text[size]=='\n'?0:-1;
}
/* Exact factory name or the reviewed C4 main.conf alias after a clean restart.
 * The space in "PandaNote 966U2" is significant; no trimming/case folding/prefix match. */
int c6_initial_name(int dir){return attribute(dir,"name","AIC8820")&&attribute(dir,"name","PandaNote 966U2")?-1:0;}
static int owns_serial(pid_t pid){
 char path[80];snprintf(path,sizeof path,"/proc/%ld/fd",(long)pid);int fd=open(path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return -1;DIR *dir=fdopendir(fd);if(!dir){close(fd);return -1;}unsigned count=0;int found=0,code=0;struct dirent *e;
 for(;;){errno=0;e=readdir(dir);if(!e){if(errno)code=-1;break;}if(e->d_name[0]=='.')continue;if(++count>64){code=-1;break;}struct stat s;if(fstatat(fd,e->d_name,&s,0)){if(errno==ENOENT)continue;code=-1;break;}if(S_ISCHR(s.st_mode)&&major(s.st_rdev)==4&&minor(s.st_rdev)==67)found=1;}
 closedir(dir);return code?code:found?0:-1;
}
int c6_controller_healthy(void *data,struct child *transport){
 struct c6_controller *c=data;struct stat current;
 if(c->held<0||c2_alive(transport)!=1||only_hci0(c->directory)||fstatat(c->directory,"hci0",&current,0)||current.st_dev!=c->identity.st_dev||current.st_ino!=c->identity.st_ino||attribute(c->held,"address","a4:6b:40:56:8c:f9")||owns_serial(transport->pid))return -1;
 return 0;
}
int c6_controller_ready(void *data,struct child *transport,int64_t deadline){
 struct c6_controller *c=data;
 while(c2_now()<deadline&&c2_alive(transport)==1){
  if(!only_hci0(c->directory)){
   int fd=openat(c->directory,"hci0",O_RDONLY|O_DIRECTORY|O_CLOEXEC);struct stat s;
   if(fd>=0&&!fstat(fd,&s)&&!attribute(fd,"address","a4:6b:40:56:8c:f9")&&!c6_initial_name(fd)&&!owns_serial(transport->pid)){c->held=fd;c->identity=s;return 0;}
   if(fd>=0)close(fd);
  }
  struct timespec t={0,10000000};nanosleep(&t,NULL);
 }
 return -1;
}
