#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "inspect.h"
#include "inputs.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/statvfs.h>
#include <time.h>
#include <unistd.h>
#define ROOT "/tmp/pandanote-connectivity/bluetooth"
volatile sig_atomic_t c2_cancelled=0;
static void cancelled(int sig){(void)sig;c2_cancelled=1;}
static int regular(int fd,mode_t mode){struct stat s;return fd>=0&&!fstat(fd,&s)&&S_ISREG(s.st_mode)&&s.st_uid==0&&s.st_nlink==1&&(s.st_mode&07777)==mode;}
static int config(int dir,const char *name,const char *data,const char *pin){
 int fd=c2_file(dir,name,1);if(fd<0)return -1;
 size_t size=strlen(data);ssize_t count=write(fd,data,size);int ok=count==(ssize_t)size&&!c2_hash(fd,pin,4096);close(fd);
 if(!ok){unlinkat(dir,name,0);return -1;}return 0;
}
int main(int argc,char **argv){
 if(argc!=2||strcmp(argv[1],"--private-daemon-lifecycle-capabilities")){puts("C2 prepared only; reviewed runtime/resource/shared-radio preflight required");return 2;}
 /* This preparatory binary is not a replacement for the external storage/guard
  * and shared-radio preflight. No staging/UI/boot caller is installed by C2. */
 struct statfs fs;struct statvfs rootfs;
 if(geteuid()!=0||statfs("/tmp",&fs)||fs.f_type!=0x01021994||statvfs("/",&rootfs)||!(rootfs.f_flag&ST_RDONLY)){puts("C2 precondition failed");return 3;}
 umask(077);struct sigaction action;memset(&action,0,sizeof action);action.sa_handler=cancelled;sigemptyset(&action.sa_mask);
 if(sigaction(SIGTERM,&action,NULL)||sigaction(SIGINT,&action,NULL)||sigaction(SIGALRM,&action,NULL))return 3;
 struct rlimit no_core={0,0},memory={12*1024*1024,64*1024*1024},stack={512*1024,512*1024};
 if(setrlimit(RLIMIT_CORE,&no_core)||setrlimit(RLIMIT_AS,&memory)||setrlimit(RLIMIT_STACK,&stack))return 3;
 alarm(10);int status=4,cleanup=0,verified=0;const char *stage="runtime";
 int tmp=-1,parent=-1,base=-1,lock=-1,run=-1,etc=-1,var=-1,lib=-1,state=-1,bin=-1,busfd=-1,daemonfd=-1,buslog=-1,daemonlog=-1;
 int bus_config=0,main_config=0,socket_seen=0,state_owned=0;struct stat socket_stat;memset(&socket_stat,0,sizeof socket_stat);
 DBusConnection *connection=NULL;struct child bus={0},daemon={0};struct c2_capability cap={0};
 tmp=open("/tmp",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(tmp<0)goto done;
 parent=c2_dir(tmp,"pandanote-connectivity");if(parent<0)goto done;
 base=c2_dir(parent,"bluetooth");if(base<0)goto done;
 lock=c2_file(base,"lifecycle.lock",1);if(lock<0)lock=c2_file(base,"lifecycle.lock",0);
 if(lock<0||c2_lock(lock))goto done;
 run=c2_dir(base,"run");etc=c2_dir(base,"etc");var=c2_dir(base,"var");bin=c2_dir(base,"bin");
 if(run<0||etc<0||var<0||bin<0||c2_empty(run)||c2_empty(etc))goto done;
 lib=c2_dir(var,"lib");if(lib<0)goto done;state=c2_dir(lib,"bluetooth");if(state<0||c2_empty(state))goto done;state_owned=1;
 stage="input-digest";
 busfd=open("/usr/bin/dbus-daemon",O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
 daemonfd=openat(bin,"bluetoothd",O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
 if(!regular(busfd,0755)||!regular(daemonfd,0700)||c2_hash(busfd,C2_BUS_SHA,2097152)||c2_hash(daemonfd,C2_DAEMON_SHA,1048576))goto done;
 if(config(etc,"private-bus.conf",C2_BUS_CONFIG,C2_BUS_CONFIG_SHA))goto done;
 bus_config=1;
 if(config(etc,"main.conf",C2_MAIN_CONFIG,C2_MAIN_CONFIG_SHA))goto done;
 main_config=1;
 buslog=c2_file(run,"bus.log",1);daemonlog=c2_file(run,"daemon.log",1);if(buslog<0||daemonlog<0)goto done;
 char *env[]={"PATH=/usr/bin:/bin","HOME=" ROOT,"XDG_CONFIG_HOME=" ROOT "/etc","XDG_CACHE_HOME=" ROOT "/var/lib/bluetooth","DBUS_SYSTEM_BUS_ADDRESS=unix:path=" ROOT "/run/bus",NULL};
 char *bus_args[]={"dbus-daemon","--nofork","--nopidfile","--nosyslog","--config-file=" ROOT "/etc/private-bus.conf",NULL};
 char *daemon_args[]={"bluetoothd","--nodetach","--configfile=" ROOT "/etc/main.conf","--plugin=gap",NULL};
 stage="bus-start";if(c2_spawn(&bus,busfd,bus_args,env,buslog,16))goto done;
 int64_t end=c2_now()+3000;
 while(!c2_cancelled&&c2_now()<end&&c2_alive(&bus)==1){
  if(!lstat(ROOT "/run/bus",&socket_stat)){
   if(!S_ISSOCK(socket_stat.st_mode)||socket_stat.st_uid!=0)goto done;
   socket_seen=1;if(fchmodat(run,"bus",0600,0))goto done;
   if(lstat(ROOT "/run/bus",&socket_stat)||(socket_stat.st_mode&07777)!=0600)goto done;
   connection=c2_bus(end);break;
  }
  if(errno!=ENOENT)goto done;
  struct timespec pause_time={0,10000000};nanosleep(&pause_time,NULL);
 }
 if(!connection||c2_cancelled)goto done;
 stage="daemon-start";if(c2_spawn(&daemon,daemonfd,daemon_args,env,daemonlog,24))goto done;
 stage="capability";int inspect=c2_inspect(connection,&bus,&daemon,&cap,c2_now()+3000);
 if(inspect==0){status=0;verified=1;}else if(inspect==1){status=5;verified=1;}
 done:
 if(connection){dbus_connection_close(connection);dbus_connection_unref(connection);}
 int daemon_stop=c2_stop(&daemon);int bus_stop=c2_stop(&bus);
 if(daemon_stop||bus_stop)cleanup=1;
 /* No unlink while an owned process remains, or before this invocation owns a
  * socket. Existing/stale sockets fail startup; a PID file never authorizes it. */
 if(!cleanup){
  if(socket_seen){struct stat now;if(lstat(ROOT "/run/bus",&now)==0){if(now.st_dev!=socket_stat.st_dev||now.st_ino!=socket_stat.st_ino||!S_ISSOCK(now.st_mode)||unlinkat(run,"bus",0))cleanup=1;}else if(errno!=ENOENT)cleanup=1;}
  else if(bus.pid){struct stat s;if(!lstat(ROOT "/run/bus",&s))cleanup=1;else if(errno!=ENOENT)cleanup=1;}
  if(state_owned){unsigned count=0,bytes=0;if(c2_erase(state,0,&count,&bytes))cleanup=1;}
  if(buslog>=0&&unlinkat(run,"bus.log",0))cleanup=1;
  if(daemonlog>=0&&unlinkat(run,"daemon.log",0))cleanup=1;
  if(bus_config&&unlinkat(etc,"private-bus.conf",0))cleanup=1;
  if(main_config&&unlinkat(etc,"main.conf",0))cleanup=1;
 }
 int fds[]={daemonlog,buslog,daemonfd,busfd,bin,state,lib,var,etc,run,lock,base,parent,tmp};
 for(unsigned i=0;i<sizeof fds/sizeof fds[0];i++)if(fds[i]>=0)close(fds[i]);
 alarm(0);
 if(cleanup)status=6;else if(c2_cancelled)status=7;
 printf("{\"stage\":\"%s\",\"exit\":%d,\"adapter\":%s,\"gatt_manager\":%s,\"advertising_manager\":%s,\"cleanup\":%s,\"phone_ready\":false}\n",stage,status,verified?(cap.flags&1?"true":"false"):"null",verified?(cap.flags&2?"true":"false"):"null",verified?(cap.flags&4?"true":"false"):"null",cleanup?"false":"true");
 return status;
}
