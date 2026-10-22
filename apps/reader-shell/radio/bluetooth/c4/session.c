#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "session.h"
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>
#define BUS "org.freedesktop.DBus"
static void wipe(void *data,size_t size){volatile unsigned char *p=data;while(size--)*p++=0;}
static DBusMessage *call(DBusConnection *bus,const char *method,const char *argument,int64_t deadline){
 DBusMessage *m=dbus_message_new_method_call(BUS,"/org/freedesktop/DBus",BUS,method);
 if(!m)return NULL;
 dbus_message_set_auto_start(m,FALSE);
 if(!dbus_message_append_args(m,DBUS_TYPE_STRING,&argument,DBUS_TYPE_INVALID)){dbus_message_unref(m);return NULL;}
 int left=(int)(deadline-c2_now());DBusPendingCall *pending=NULL;
 if(left<=0||!dbus_connection_send_with_reply(bus,m,&pending,left)||!pending){dbus_message_unref(m);return NULL;}
 dbus_message_unref(m);
 while(!c2_cancelled&&c2_now()<deadline&&!dbus_pending_call_get_completed(pending))if(!dbus_connection_read_write_dispatch(bus,10))break;
 DBusMessage *reply=NULL;
 if(dbus_pending_call_get_completed(pending))reply=dbus_pending_call_steal_reply(pending);else dbus_pending_call_cancel(pending);
 dbus_pending_call_unref(pending);
 if(reply&&(dbus_message_get_type(reply)!=DBUS_MESSAGE_TYPE_METHOD_RETURN||!dbus_message_has_sender(reply,BUS))){dbus_message_unref(reply);reply=NULL;}
 return reply;
}
static int owner(struct c4_context *context,pid_t expected){
 int64_t deadline=c2_now()+500;const char *value=NULL;
 DBusMessage *reply=call(context->bus,"GetNameOwner","org.bluez",deadline);
 int ok=reply&&dbus_message_has_signature(reply,"s")&&dbus_message_get_args(reply,NULL,DBUS_TYPE_STRING,&value,DBUS_TYPE_INVALID)&&value[0]==':'&&strlen(value)<sizeof context->owner&&dbus_validate_bus_name(value,NULL);
 char name[64];if(ok)strcpy(name,value);if(reply)dbus_message_unref(reply);
 if(!ok||(*context->owner&&strcmp(name,context->owner)))return -1;
 reply=call(context->bus,"GetConnectionUnixProcessID",name,deadline);dbus_uint32_t pid=0;
 ok=reply&&dbus_message_has_signature(reply,"u")&&dbus_message_get_args(reply,NULL,DBUS_TYPE_UINT32,&pid,DBUS_TYPE_INVALID)&&pid==(unsigned)expected;
 if(reply)dbus_message_unref(reply);
 if(!ok)return -1;
 strcpy(context->owner,name);return 0;
}
static int socket_ready(struct c4_socket *socket,int tighten){
 struct stat now;
 if(fstatat(socket->directory,socket->name,&now,AT_SYMLINK_NOFOLLOW)){return errno==ENOENT?0:-1;}
 if(!S_ISSOCK(now.st_mode)||now.st_uid!=geteuid())return -1;
 if(socket->seen&&(now.st_dev!=socket->identity.st_dev||now.st_ino!=socket->identity.st_ino))return -1;
 /* C3 owns its bind0700 -> validate -> chmod0600 -> listen sequence.
  * Observing that same inode must never alter its construction precondition. */
 mode_t mode=now.st_mode&07777;
 if(!tighten&&mode!=0700&&mode!=0600)return -1;
 if(!socket->seen){socket->identity=now;socket->seen=1;}
 if(!tighten)return mode==0600?1:0;
 if(fchmodat(socket->directory,socket->name,0600,0))return -1;
 struct stat checked;if(fstatat(socket->directory,socket->name,&checked,AT_SYMLINK_NOFOLLOW)||checked.st_dev!=now.st_dev||checked.st_ino!=now.st_ino||(checked.st_mode&07777)!=0600)return -1;
 return 1;
}
int c4_unlink_socket(struct c4_socket *socket){
 struct stat now;
 if(fstatat(socket->directory,socket->name,&now,AT_SYMLINK_NOFOLLOW))return errno==ENOENT?0:-1;
 if(!socket->seen||!S_ISSOCK(now.st_mode)||now.st_uid!=geteuid()||now.st_dev!=socket->identity.st_dev||now.st_ino!=socket->identity.st_ino)return -1;
 return unlinkat(socket->directory,socket->name,0);
}
static int wait_io(int fd,short event,int64_t deadline){
 while(!c2_cancelled){int left=(int)(deadline-c2_now());if(left<=0)return -1;struct pollfd p={fd,event,0};int result=poll(&p,1,left);if(result<0&&errno==EINTR)continue;return result>0?0:-1;}return -1;
}
static int transfer(int fd,unsigned char *bytes,size_t size,int writing,int64_t deadline){
 size_t offset=0;
 while(offset<size){if(wait_io(fd,writing?POLLOUT:POLLIN,deadline))return -1;ssize_t n=writing?send(fd,bytes+offset,size-offset,MSG_NOSIGNAL):recv(fd,bytes+offset,size-offset,0);if(n>0)offset+=(size_t)n;else if(n<0&&(errno==EINTR||errno==EAGAIN))continue;else return -1;}
 return 0;
}
static int service(struct c4_context *context,pid_t expected){
 if(socket_ready(&context->service_socket,0)!=1)return -1;
 int fd=socket(AF_UNIX,SOCK_STREAM|SOCK_NONBLOCK|SOCK_CLOEXEC,0);if(fd<0)return -1;
 int ok=0;int64_t deadline=c2_now()+300;struct sockaddr_un address;memset(&address,0,sizeof address);address.sun_family=AF_UNIX;strcpy(address.sun_path,C4_SOCKET);
 if(connect(fd,(struct sockaddr *)&address,sizeof address)&&errno!=EINPROGRESS)goto done;
 if(wait_io(fd,POLLOUT,deadline))goto done;
 int error=0;socklen_t size=sizeof error;if(getsockopt(fd,SOL_SOCKET,SO_ERROR,&error,&size)||error)goto done;
 struct ucred peer;size=sizeof peer;
 if(getsockopt(fd,SOL_SOCKET,SO_PEERCRED,&peer,&size)||size!=sizeof peer||peer.uid!=geteuid()||peer.pid!=expected)goto done;
 unsigned char request[24]={0},reply[48];memcpy(request,"OBT1",4);request[4]=2;
 if(transfer(fd,request,sizeof request,1,deadline)||transfer(fd,reply,sizeof reply,0,deadline)){wipe(reply,sizeof reply);goto done;}
 ok=!memcmp(reply,"OBT1",4)&&reply[4]==0&&!(reply[5]&~7)&&!(reply[6]&~5)&&reply[39]==0&&reply[46]==0&&reply[47]==0;
 wipe(reply,sizeof reply);
 if(ok){unsigned char extra;ok=!wait_io(fd,POLLIN,deadline)&&recv(fd,&extra,1,0)==0;}
 done:close(fd);return ok?0:-1;
}
int c4_ready(void *data,unsigned index,struct child child[3],int64_t deadline){
 struct c4_context *context=data;
 if(index==1){struct c2_capability capability={0};if(c2_inspect(context->bus,&child[0],&child[1],&capability,deadline)||owner(context,child[1].pid))return -1;snprintf(context->daemon_pid,sizeof context->daemon_pid,"%ld",(long)child[1].pid);return 0;}
 struct c4_socket *path=index==0?&context->bus_socket:&context->service_socket;
 while(!c2_cancelled&&c2_now()<deadline&&c2_alive(&child[index])==1){
  int ready=socket_ready(path,index==0);if(ready<0)return -1;
  if(ready==1){if(index==0){context->bus=c2_bus(deadline);if(!context->bus)return -1;int fd=-1;struct ucred peer;socklen_t length=sizeof peer;return dbus_connection_get_unix_fd(context->bus,&fd)&&!getsockopt(fd,SOL_SOCKET,SO_PEERCRED,&peer,&length)&&length==sizeof peer&&peer.uid==geteuid()&&peer.pid==child[0].pid?0:-1;}if(!service(context,child[2].pid))return 0;}
  struct timespec delay={0,10000000};nanosleep(&delay,NULL);
 }
 return -1;
}
int c4_healthy(void *data,struct child child[3]){
 struct c4_context *context=data;
 return !context->bus||owner(context,child[1].pid)||service(context,child[2].pid)?-1:0;
}
