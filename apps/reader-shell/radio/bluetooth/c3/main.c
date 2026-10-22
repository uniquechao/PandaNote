#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "service.h"
#include "ipc.h"
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
static volatile sig_atomic_t stopping;
static void stop(int signal){(void)signal;stopping=1;}
static unsigned char file_buffer[BT_FILE_MAX];
static uint64_t clock_ms(void){struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t))return 0;return (uint64_t)t.tv_sec*1000+(uint32_t)t.tv_nsec/1000000U;}
/* No symlink component, untrusted ancestor, dot or empty component. Roots must
 * already be provisioned by the supervisor; this CLI never creates directories. */
static int private_dir(const char *path){
 if(!path||path[0]!='/'||strlen(path)>255||path[1]==0)return -1;
 int current=open("/",O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(current<0)return -1;
 const char *part=path+1;char leaf[256];unsigned components=0;
 while(*part){const char *slash=strchr(part,'/');size_t n=slash?(size_t)(slash-part):strlen(part);if(!n||n>=sizeof leaf||++components>16)goto failed;memcpy(leaf,part,n);leaf[n]=0;if(!strcmp(leaf,".")||!strcmp(leaf,".."))goto failed;int next=openat(current,leaf,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(next<0)goto failed;struct stat s;int final=!slash;
  int special=components==1&&!strcmp(leaf,"tmp");
  if(fstat(next,&s)||!S_ISDIR(s.st_mode)||s.st_uid!=geteuid()||(final?(s.st_mode&07777)!=0700:((s.st_mode&0022)!=0&&!(special&&(s.st_mode&07777)==01777)))){close(next);goto failed;}
  close(current);current=next;if(final)return current;part=slash+1;if(!*part)goto failed;
 }
 failed:close(current);return -1;
}
static int limit(int key,rlim_t value){struct rlimit l={value,value};return setrlimit(key,&l);}
int main(int argc,char **argv){
 if(argc!=5||strcmp(argv[1],"--serve-private")){puts("Usage: pandanote-bt-service --serve-private owned-bluez-pid private-runtime-dir private-inbox-dir");return 2;}
 if(geteuid()!=0){puts("C3 requires owned root supervisor");return 3;}
 char *end=NULL;errno=0;long parsed=strtol(argv[2],&end,10);if(errno||!end||*end||parsed<2||parsed>INT_MAX)return 2;
 if(limit(RLIMIT_CORE,0)||limit(RLIMIT_AS,16*1024*1024)||limit(RLIMIT_STACK,512*1024)||limit(RLIMIT_FSIZE,BT_FILE_MAX))return 3;
 struct sigaction action;memset(&action,0,sizeof action);action.sa_handler=stop;sigemptyset(&action.sa_mask);if(sigaction(SIGTERM,&action,NULL)||sigaction(SIGINT,&action,NULL))return 3;
 int runtime=private_dir(argv[3]),inbox=private_dir(argv[4]);if(runtime<0||inbox<0){if(runtime>=0)close(runtime);if(inbox>=0)close(inbox);return 3;}
 struct c3 state;c3_init(&state,file_buffer,sizeof file_buffer,inbox);struct c3_ipc ipc;if(c3_ipc_open(&ipc,runtime,argv[3])){close(runtime);close(inbox);return 3;}
 DBusError error;dbus_error_init(&error);DBusConnection *bus=dbus_connection_open_private("unix:path=/tmp/pandanote-connectivity/bluetooth/run/bus",&error);dbus_error_free(&error);int result=4;struct c3_server server;memset(&server,0,sizeof server);
 if(bus){dbus_connection_set_exit_on_disconnect(bus,FALSE);dbus_connection_set_max_message_size(bus,32768);dbus_connection_set_max_received_size(bus,65536);dbus_error_init(&error);int registered=dbus_bus_register(bus,&error);dbus_error_free(&error);if(registered&&!c3_server_export(&server,bus,&state,(pid_t)parsed)&&!c3_server_register(&server)){
  result=0;while(!stopping){uint64_t now=clock_ms();if(!now||c3_ipc_poll(&ipc,&state,now)<0||c3_server_tick(&server,now)){result=4;break;}}
 }}
 if(c3_server_close(&server))result=5;
 if(bus){dbus_connection_close(bus);dbus_connection_unref(bus);}
 if(c3_ipc_close(&ipc))result=5;
 c3_close(&state);close(inbox);close(runtime);puts(result?"C3 stopped with an incomplete lifecycle":"C3 stopped and owned state closed");return result;
}
