#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "session.h"
#include "inputs.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/statfs.h>
#include <sys/statvfs.h>
#include <unistd.h>
volatile sig_atomic_t c2_cancelled;
static void cancelled(int signal){(void)signal;c2_cancelled=1;}
static int regular(int fd,mode_t mode){struct stat s;return fd>=0&&!fstat(fd,&s)&&S_ISREG(s.st_mode)&&s.st_uid==0&&s.st_nlink==1&&(s.st_mode&07777)==mode;}
/* Walk from / without following any symlink. Ancestors must not be writable by
 * another UID, except the conventional sticky root-owned /tmp directory. */
static int inbox(const char *path){
 if(!path||path[0]!='/'||strlen(path)>240||!strcmp(path,"/")||!strncmp(path,C4_ROOT,strlen(C4_ROOT)))return -1;
 size_t length=strlen(path);if(length<=strlen(C4_ROOT)&&!strncmp(C4_ROOT,path,length)&&(C4_ROOT[length]==0||C4_ROOT[length]=='/'))return -1;
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
static int libraries(void){
 for(unsigned i=0;i<sizeof c4_libraries/sizeof c4_libraries[0];i++){
  const struct c4_library_pin *pin=&c4_libraries[i];struct stat file,alias;
  int fd=open(pin->file,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
  int bad=fd<0||fstat(fd,&file)||!S_ISREG(file.st_mode)||file.st_uid||file.st_mode&0022||c2_hash(fd,pin->sha,16777216)||stat(pin->alias,&alias)||alias.st_dev!=file.st_dev||alias.st_ino!=file.st_ino;
  if(fd>=0)close(fd);
  if(bad)return -1;
 }
 return 0;
}
static int remove_file(int,const char *,int);
static int config(int dir,const char *name,const char *text,const char *pin){
 int fd=c2_file(dir,name,1);if(fd<0)return -1;
 size_t size=strlen(text);ssize_t n=write(fd,text,size);
 if(n!=(ssize_t)size||c2_hash(fd,pin,4096)){(void)remove_file(dir,name,fd);close(fd);return -1;}return fd;
}
static int remove_file(int dir,const char *name,int fd){
 if(fd<0)return 0;
 struct stat held,path;
 if(fstat(fd,&held)||fstatat(dir,name,&path,AT_SYMLINK_NOFOLLOW)||!S_ISREG(path.st_mode)||held.st_dev!=path.st_dev||held.st_ino!=path.st_ino||path.st_uid||path.st_nlink!=1||(path.st_mode&07777)!=0600)return -1;
 return unlinkat(dir,name,0);
}
int main(int argc,char **argv){
 if(argc!=3||strcmp(argv[1],"--enable-private-session")){puts("C4 disabled; explicit --enable-private-session ABS_PRIVATE_INBOX required");return 2;}
 struct statfs fs;struct rlimit cpu;
 if(geteuid()!=0||statfs("/tmp",&fs)||fs.f_type!=0x01021994||getrlimit(RLIMIT_CPU,&cpu)||cpu.rlim_cur!=RLIM_INFINITY||cpu.rlim_max!=RLIM_INFINITY){puts("C4 precondition failed");return 3;}
 int content=inbox(argv[2]);if(content<0){puts("C4 private writable inbox rejected");return 3;}
 umask(077);struct sigaction action;memset(&action,0,sizeof action);action.sa_handler=cancelled;sigemptyset(&action.sa_mask);
 if(sigaction(SIGTERM,&action,NULL)||sigaction(SIGINT,&action,NULL)){close(content);return 3;}
 struct sigaction reap;memset(&reap,0,sizeof reap);reap.sa_handler=SIG_DFL;sigemptyset(&reap.sa_mask);if(sigaction(SIGCHLD,&reap,NULL)){close(content);return 3;}
 struct rlimit core={0,0},memory={12*1024*1024,64*1024*1024},stack={512*1024,512*1024};
 if(setrlimit(RLIMIT_CORE,&core)||setrlimit(RLIMIT_AS,&memory)||setrlimit(RLIMIT_STACK,&stack)){close(content);return 3;}
 int status=4,cleanup=0,owned=0;const char *stage="runtime";
 int tmp=-1,parent=-1,base=-1,lock=-1,run=-1,etc=-1,var=-1,lib=-1,state=-1,bin=-1,service=-1;
 int busfd=-1,daemonfd=-1,servicefd=-1,buslog=-1,daemonlog=-1,servicelog=-1,busconfig=-1,mainconfig=-1;
 struct c4_context context;memset(&context,0,sizeof context);struct c4_result result;memset(&result,0,sizeof result);
 tmp=open("/tmp",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);struct stat temporary;if(tmp<0||fstat(tmp,&temporary)||temporary.st_uid||((temporary.st_mode&0022)&&(temporary.st_mode&07777)!=01777))goto done;
 parent=c2_dir(tmp,"pandanote-connectivity");if(parent<0)goto done;base=c2_dir(parent,"bluetooth");if(base<0)goto done;
 lock=c2_file(base,"lifecycle.lock",1);if(lock<0)lock=c2_file(base,"lifecycle.lock",0);if(lock<0||c2_lock(lock))goto done;
 run=c2_dir(base,"run");etc=c2_dir(base,"etc");var=c2_dir(base,"var");bin=c2_dir(base,"bin");service=c2_dir(base,"service");
 if(run<0||etc<0||var<0||bin<0||service<0||c2_empty(run)||c2_empty(etc)||c2_empty(service))goto done;
 lib=c2_dir(var,"lib");if(lib<0)goto done;state=c2_dir(lib,"bluetooth");if(state<0||c2_empty(state))goto done;owned=1;
 context.bus_socket=(struct c4_socket){.directory=run,.name="bus",.path=C4_ROOT "/run/bus"};
 context.service_socket=(struct c4_socket){.directory=service,.name="local.sock",.path=C4_SOCKET};
 stage="input-digest";busfd=open("/usr/bin/dbus-daemon",O_RDONLY|O_NOFOLLOW|O_CLOEXEC);daemonfd=openat(bin,"bluetoothd",O_RDONLY|O_NOFOLLOW|O_CLOEXEC);servicefd=openat(bin,"pandanote-bt-service",O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
 struct stat c3;
 if(!regular(busfd,0755)||!regular(daemonfd,0700)||!regular(servicefd,0700)||fstat(servicefd,&c3)||c3.st_size!=C4_C3_BYTES||c2_hash(busfd,C2_BUS_SHA,2097152)||c2_hash(daemonfd,C2_DAEMON_SHA,1048576)||c2_hash(servicefd,C4_C3_SHA,C4_C3_BYTES)||libraries())goto done;
 busconfig=config(etc,"private-bus.conf",C2_BUS_CONFIG,C2_BUS_CONFIG_SHA);if(busconfig<0)goto done;
 mainconfig=config(etc,"main.conf",C2_MAIN_CONFIG,C2_MAIN_CONFIG_SHA);if(mainconfig<0)goto done;
 buslog=c2_file(run,"bus.log",1);daemonlog=c2_file(run,"daemon.log",1);servicelog=c2_file(run,"service.log",1);if(buslog<0||daemonlog<0||servicelog<0)goto done;
 char *env[]={"PATH=/usr/bin:/bin","HOME=" C4_ROOT,"XDG_CONFIG_HOME=" C4_ROOT "/etc","XDG_CACHE_HOME=" C4_ROOT "/var/lib/bluetooth","DBUS_SYSTEM_BUS_ADDRESS=unix:path=" C4_ROOT "/run/bus",NULL};
 char *bus_args[]={"dbus-daemon","--nofork","--nopidfile","--nosyslog","--config-file=" C4_ROOT "/etc/private-bus.conf",NULL};
 char *daemon_args[]={"bluetoothd","--nodetach","--configfile=" C4_ROOT "/etc/main.conf","--plugin=gap",NULL};
 char *service_args[]={"pandanote-bt-service","--serve-private",context.daemon_pid,C4_ROOT "/service",argv[2],NULL};
 struct c4_plan plan={.program={{busfd,buslog,bus_args,env,16,C4_SHORT_FILE_LIMIT,500},{daemonfd,daemonlog,daemon_args,env,24,C4_SHORT_FILE_LIMIT,1000},{servicefd,servicelog,service_args,env,16,C4_SERVICE_FILE_LIMIT,4000}},.stop=&c2_cancelled,.ready=c4_ready,.healthy=c4_healthy,.context=&context,.health_ms=1000};
 stage="owned-session";status=c4_run(&plan,&result);
 done:
 if(context.bus){dbus_connection_close(context.bus);dbus_connection_unref(context.bus);}
 if(result.started!=result.reaped)cleanup=1;
 if(owned&&!cleanup){
  if(c4_unlink_socket(&context.service_socket)||c4_unlink_socket(&context.bus_socket))cleanup=1;
  if(!cleanup){unsigned count=0,bytes=0;if(c2_erase(state,0,&count,&bytes))cleanup=1;count=bytes=0;if(c2_erase(service,0,&count,&bytes))cleanup=1;}
  if(!cleanup&&(remove_file(run,"service.log",servicelog)||remove_file(run,"daemon.log",daemonlog)||remove_file(run,"bus.log",buslog)||remove_file(etc,"main.conf",mainconfig)||remove_file(etc,"private-bus.conf",busconfig)))cleanup=1;
  if(c2_empty(run)||c2_empty(etc)||c2_empty(service)||c2_empty(state))cleanup=1;
 }
 int fds[]={servicelog,daemonlog,buslog,mainconfig,busconfig,servicefd,daemonfd,busfd,service,bin,state,lib,var,etc,run,lock,base,parent,tmp,content};
 for(unsigned i=0;i<sizeof fds/sizeof fds[0];i++)if(fds[i]>=0)close(fds[i]);
 if(cleanup)status=6;
 printf("{\"stage\":\"%s\",\"exit\":%d,\"ready_children\":%u,\"reaped_all\":%s,\"cleanup\":%s,\"phone_validated\":false}\n",stage,status,result.ready,result.started==result.reaped?"true":"false",cleanup?"false":"true");
 return status;
}
