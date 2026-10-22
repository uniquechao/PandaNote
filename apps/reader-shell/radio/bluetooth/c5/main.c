#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "runner.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#define ROOT "/tmp/pandanote-connectivity/bluetooth"
static volatile sig_atomic_t stopping;
static void stop(int signal){(void)signal;stopping=1;}
static int read_text(const char *path,char *text,size_t capacity){
 int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return -1;
 size_t used=0;for(;;){ssize_t n=read(fd,text+used,capacity-1-used);if(n<0&&errno==EINTR)continue;if(n<0){close(fd);return -1;}if(!n)break;used+=(size_t)n;if(used==capacity-1){close(fd);return -1;}}
 close(fd);text[used]=0;return 0;
}
static int module(const char *all,const char *name){size_t n=strlen(name);for(const char *p=all;p&&*p;p=strchr(p,'\n')){if(*p=='\n')p++;if(!strncmp(p,name,n)&&p[n]==' ')return 1;}return 0;}
static int pinned(const char *path,const char *digest,unsigned bytes,mode_t exact){
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
int main(int argc,char **argv){
 if(argc!=2||strcmp(argv[1],"--bounded-attach-only")){puts("C5 disabled; explicit --bounded-attach-only required; no power setup");return 2;}
 struct statfs fs;struct stat tty;char modules[4096],consoles[2048];
 if(geteuid()!=0||statfs("/tmp",&fs)||fs.f_type!=0x01021994||lstat("/dev/ttyS3",&tty)||!S_ISCHR(tty.st_mode)||tty.st_uid||(tty.st_mode&07777)!=0600||major(tty.st_rdev)!=4||minor(tty.st_rdev)!=67||read_text("/proc/modules",modules,sizeof modules)||!module(modules,"aic8800_bsp")||!module(modules,"aic8800_fdrv")||module(modules,"aic8800_btlpm")||read_text("/proc/consoles",consoles,sizeof consoles)||strstr(consoles,"ttyS3")||idle(tty.st_rdev)){puts("C5 attach preflight rejected; no serial opened");return 3;}
 int hci=open("/sys/class/bluetooth",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(hci<0||c2_empty(hci)){if(hci>=0)close(hci);puts("C5 requires no existing HCI");return 3;}close(hci);
 const char *paths[]={"/module_driver/aic8800_bsp.ko","/module_driver/aic8800_fdrv.ko","/lib/libc-2.29.so","/lib/ld-2.29.so"};
 const char *pins[]={"35e0cb9542b2d2e3d9e7889070e4c2659e7ade5c1ab159a9f5b34c0dfa232142","82bd636c3f6b91687ec92922bef48e4ae978a4ed9d558c502bd70a91297be1f2","fb2c85aa7e6933d9ce92530427b8272a9dbfad300696e995b542b93f5fb228b6","0c37c07942b176a223b5fd4e1bcd0b7e5ebdf6205bce727ee0f895dd22caf0e2"};
 unsigned sizes[]={129380,597424,0,0};
 for(unsigned i=0;i<4;i++){
  if(!sizes[i]){struct stat s;if(lstat(paths[i],&s)||!S_ISREG(s.st_mode)||s.st_size<=0||s.st_size>4194304)return 3;sizes[i]=(unsigned)s.st_size;}
  int fd=pinned(paths[i],pins[i],sizes[i],0);if(fd<0){puts("C5 input rejected");return 3;}
  if(i>=2){const char *alias=i==2?"/lib/libc.so.6":"/lib/ld-linux-mipsn8.so.1";struct stat direct,linked;if(fstat(fd,&direct)||stat(alias,&linked)||direct.st_dev!=linked.st_dev||direct.st_ino!=linked.st_ino){close(fd);return 3;}}
  close(fd);
 }
 int executable=pinned("/usr/bin/btattach","746dee0da16884400a32eb89f64df58378824927901e8afe65157d574722ea6f",47536,0755);if(executable<0)return 3;
 umask(077);struct sigaction action;memset(&action,0,sizeof action);action.sa_handler=stop;sigemptyset(&action.sa_mask);if(sigaction(SIGTERM,&action,NULL)||sigaction(SIGINT,&action,NULL)){close(executable);return 3;}action.sa_handler=SIG_DFL;if(sigaction(SIGCHLD,&action,NULL)){close(executable);return 3;}
 struct rlimit core={0,0},memory={12*1024*1024,64*1024*1024},stack={512*1024,512*1024};if(setrlimit(RLIMIT_CORE,&core)||setrlimit(RLIMIT_AS,&memory)||setrlimit(RLIMIT_STACK,&stack)){close(executable);return 3;}
 int code=4,tmp=-1,parent=-1,base=-1,lock=-1,dir=-1,log=-1;struct c5_result result;memset(&result,0,sizeof result);
 tmp=open("/tmp",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);struct stat temporary;if(tmp<0||fstat(tmp,&temporary)||temporary.st_uid||((temporary.st_mode&0022)&&(temporary.st_mode&07777)!=01777))goto done;
 parent=c2_dir(tmp,"pandanote-connectivity");if(parent<0)goto done;base=c2_dir(parent,"bluetooth");if(base<0)goto done;
 lock=c2_file(base,"transport.lock",1);if(lock<0)lock=c2_file(base,"transport.lock",0);if(lock<0||c2_lock(lock))goto done;dir=c2_dir(base,"attach");if(dir<0||c2_empty(dir))goto done;log=c2_file(dir,"attach.log",1);if(log<0)goto done;
 char *args[]={"btattach","-P","h4","-S","1500000","-B","/dev/ttyS3",NULL};char *env[]={"PATH=/usr/bin:/bin","HOME=" ROOT "/attach",NULL};struct c4_program program={executable,log,args,env,8,16384,500};
 code=c5_run(&program,&stopping,5000,&result);
 done:
 printf("{\"exit\":%d,\"owned_pid\":%ld,\"reaped\":%s,\"killed\":%s,\"elapsed_ms\":%d,\"controller_verified\":false,\"power_configured\":false}\n",code,(long)result.child.pid,result.reaped?"true":"false",result.killed?"true":"false",result.elapsed_ms);
 /* Keep private bounded logs for review. Never delete tty/HCI/sysfs state,
  * global process state, persistent content, locks or pre-existing artifacts. */
 int fds[]={log,dir,lock,base,parent,tmp,executable};for(unsigned i=0;i<sizeof fds/sizeof fds[0];i++)if(fds[i]>=0)close(fds[i]);return code;
}
