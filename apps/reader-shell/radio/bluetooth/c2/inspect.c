#include "inspect.h"
#include <string.h>
#define BUS "org.freedesktop.DBus"
#define BUSPATH "/org/freedesktop/DBus"
static DBusMessage *call(DBusConnection *c,const char *dest,const char *path,const char *iface,const char *method,const char *arg,int64_t deadline){
 DBusMessage *m=dbus_message_new_method_call(dest,path,iface,method);DBusPendingCall *pending=NULL;
 if(!m)return NULL;
 dbus_message_set_auto_start(m,FALSE);
 if(arg&&!dbus_message_append_args(m,DBUS_TYPE_STRING,&arg,DBUS_TYPE_INVALID)){dbus_message_unref(m);return NULL;}
 int left=(int)(deadline-c2_now());
 if(left<=0||!dbus_connection_send_with_reply(c,m,&pending,left)||!pending){dbus_message_unref(m);return NULL;}
 dbus_message_unref(m);
 while(!c2_cancelled&&c2_now()<deadline&&!dbus_pending_call_get_completed(pending)){
  if(!dbus_connection_read_write_dispatch(c,10))break;
 }
 DBusMessage *reply=NULL;
 if(dbus_pending_call_get_completed(pending))reply=dbus_pending_call_steal_reply(pending);
 else dbus_pending_call_cancel(pending);
 dbus_pending_call_unref(pending);
 if(reply&&(dbus_message_get_type(reply)!=DBUS_MESSAGE_TYPE_METHOD_RETURN||!dbus_message_get_sender(reply)||strcmp(dbus_message_get_sender(reply),dest))){dbus_message_unref(reply);reply=NULL;}
 return reply;
}
DBusConnection *c2_bus(int64_t deadline){
 DBusError e;dbus_error_init(&e);
 DBusConnection *c=dbus_connection_open_private("unix:path=/tmp/pandanote-connectivity/bluetooth/run/bus",&e);
 dbus_error_free(&e);if(!c)return NULL;
 dbus_connection_set_exit_on_disconnect(c,FALSE);
 dbus_connection_set_max_message_size(c,32768);dbus_connection_set_max_received_size(c,65536);
 DBusMessage *r=call(c,BUS,BUSPATH,BUS,"Hello",NULL,deadline);const char *name=NULL;
 int ok=r&&dbus_message_has_signature(r,"s")&&dbus_message_get_args(r,NULL,DBUS_TYPE_STRING,&name,DBUS_TYPE_INVALID)&&name[0]==':'&&strlen(name)<64&&dbus_validate_bus_name(name,NULL)&&dbus_bus_set_unique_name(c,name);
 if(r)dbus_message_unref(r);
 if(!ok){dbus_connection_close(c);dbus_connection_unref(c);return NULL;}
 return c;
}
static int owner(DBusConnection *c,char out[64],unsigned *pid,int64_t end){
 DBusMessage *r=call(c,BUS,BUSPATH,BUS,"GetNameOwner","org.bluez",end);const char *value=NULL;
 if(!r)return -1;
 int ok=dbus_message_has_signature(r,"s")&&dbus_message_get_args(r,NULL,DBUS_TYPE_STRING,&value,DBUS_TYPE_INVALID)&&value[0]==':'&&strlen(value)<64&&dbus_validate_bus_name(value,NULL);
 if(ok)strcpy(out,value);
 dbus_message_unref(r);if(!ok)return -1;
 r=call(c,BUS,BUSPATH,BUS,"GetConnectionUnixProcessID",out,end);dbus_uint32_t number=0;
 ok=r&&dbus_message_has_signature(r,"u")&&dbus_message_get_args(r,NULL,DBUS_TYPE_UINT32,&number,DBUS_TYPE_INVALID);
 if(r)dbus_message_unref(r);
 *pid=number;return ok?0:-1;
}
static int objects(DBusMessage *r,struct c2_capability *cap){
 if(!dbus_message_has_signature(r,"a{oa{sa{sv}}}"))return -1;
 DBusMessageIter top,entries;dbus_message_iter_init(r,&top);dbus_message_iter_recurse(&top,&entries);
 while(dbus_message_iter_get_arg_type(&entries)!=DBUS_TYPE_INVALID){
  if(++cap->objects>64)return -1;
  DBusMessageIter entry,interfaces;const char *path=NULL;
  dbus_message_iter_recurse(&entries,&entry);dbus_message_iter_get_basic(&entry,&path);dbus_message_iter_next(&entry);dbus_message_iter_recurse(&entry,&interfaces);
  while(dbus_message_iter_get_arg_type(&interfaces)!=DBUS_TYPE_INVALID){
   DBusMessageIter interface;const char *name=NULL;
   dbus_message_iter_recurse(&interfaces,&interface);dbus_message_iter_get_basic(&interface,&name);
   if(c2_interface(cap,path,name))return -1;
   dbus_message_iter_next(&interfaces);
  }
  dbus_message_iter_next(&entries);
 }
 return 0;
}
int c2_inspect(DBusConnection *c,struct child *bus,struct child *daemon,struct c2_capability *cap,int64_t end){
 char before[64],after[64];unsigned pid=0;int found=0;
 while(!c2_cancelled&&c2_now()<end&&c2_alive(bus)==1&&c2_alive(daemon)==1){
  if(!owner(c,before,&pid,end)){found=1;break;}
  dbus_connection_read_write_dispatch(c,20);
 }
 if(!found||!c2_owner(before,before,daemon->pid,pid))return -1;
 DBusMessage *r=call(c,before,"/","org.freedesktop.DBus.ObjectManager","GetManagedObjects",NULL,end);
 if(!r)return -1;
 int parsed=objects(r,cap);dbus_message_unref(r);
 if(parsed||owner(c,after,&pid,end)||!c2_owner(before,after,daemon->pid,pid)||c2_alive(bus)!=1||c2_alive(daemon)!=1||c2_cancelled)return -1;
 return cap->flags==7?0:1; /* Presence is a capability snapshot, not phone readiness. */
}
