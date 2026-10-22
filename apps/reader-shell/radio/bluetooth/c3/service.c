#include "service.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#define OBJECTS "org.freedesktop.DBus.ObjectManager"
#define PROPS "org.freedesktop.DBus.Properties"
#define CHAR "org.bluez.GattCharacteristic1"
#define SERVICE "org.bluez.GattService1"
#define ADVERT "org.bluez.LEAdvertisement1"
#define AGENT "org.bluez.Agent1"
static uint64_t now_ms(void){struct timespec t;
 if(clock_gettime(CLOCK_MONOTONIC,&t))return 0;
 return (uint64_t)t.tv_sec*1000+(uint32_t)t.tv_nsec/1000000U;
 }
static DBusMessage *request(DBusConnection *bus,DBusMessage *m,int timeout){
 DBusPendingCall *pending=NULL;
 if(!dbus_connection_send_with_reply(bus,m,&pending,timeout)||!pending)return NULL;
 uint64_t end=now_ms()+(unsigned)timeout;
 while(now_ms()<end&&!dbus_pending_call_get_completed(pending))if(!dbus_connection_read_write_dispatch(bus,10))break;
 DBusMessage *r=NULL;
 if(dbus_pending_call_get_completed(pending))r=dbus_pending_call_steal_reply(pending);
 else dbus_pending_call_cancel(pending);
 dbus_pending_call_unref(pending);
 return r;
}
static DBusMessage *call(DBusConnection *bus,const char *dest,const char *path,const char *iface,const char *method,const char *signature,const void *arg){
 DBusMessage *m=dbus_message_new_method_call(dest,path,iface,method);
 if(!m)return NULL;
 dbus_message_set_auto_start(m,FALSE);
 if(signature&&signature[0]&&!dbus_message_append_args(m,signature[0],&arg,DBUS_TYPE_INVALID)){dbus_message_unref(m);
 return NULL;
 }
 /* Property/identity replies must not recursively dispatch while an exported
  * object handler is running. Registration uses request() separately because
  * BlueZ must call GetManagedObjects before returning from registration. */
 DBusError e;dbus_error_init(&e);
 DBusMessage *r=dbus_connection_send_with_reply_and_block(bus,m,500,&e);
 dbus_error_free(&e);
 dbus_message_unref(m);
 if(r&&(dbus_message_get_type(r)!=DBUS_MESSAGE_TYPE_METHOD_RETURN||!dbus_message_get_sender(r)||strcmp(dbus_message_get_sender(r),dest))){dbus_message_unref(r);
 r=NULL;
 }return r;
}
static int bound(struct c3_server *s){
 const char *name="org.bluez",*owner=NULL;
 DBusMessage *r=call(s->bus,"org.freedesktop.DBus","/org/freedesktop/DBus","org.freedesktop.DBus","GetNameOwner","s",name);
 if(!r)return 0;
 int ok=dbus_message_has_signature(r,"s")&&dbus_message_get_args(r,NULL,DBUS_TYPE_STRING,&owner,DBUS_TYPE_INVALID)&&strlen(owner)<sizeof s->owner&&owner[0]==':'&&dbus_validate_bus_name(owner,NULL);
 char copied[64];
 if(ok)strcpy(copied,owner);
 dbus_message_unref(r);
 if(!ok||(*s->owner&&strcmp(copied,s->owner)))return 0;
 r=call(s->bus,"org.freedesktop.DBus","/org/freedesktop/DBus","org.freedesktop.DBus","GetConnectionUnixProcessID","s",copied);
 dbus_uint32_t pid=0;
 ok=r&&dbus_message_has_signature(r,"u")&&dbus_message_get_args(r,NULL,DBUS_TYPE_UINT32,&pid,DBUS_TYPE_INVALID)&&pid==(unsigned)s->expected_pid;
 if(r)dbus_message_unref(r);
 if(ok)strcpy(s->owner,copied);
 return ok;
}
static int send_message(struct c3_server *s,DBusMessage *r){if(!r)return 0;
 int ok=dbus_connection_send(s->bus,r,NULL);
 dbus_message_unref(r);
 return ok;
 }
static int reject(struct c3_server *s,DBusMessage *m,const char *error){return send_message(s,dbus_message_new_error(m,error,"Request rejected"));
 }
static int done(struct c3_server *s,DBusMessage *m){return send_message(s,dbus_message_new_method_return(m));
 }
static int bytes(struct c3_server *s,DBusMessage *m,const unsigned char *p,size_t n){DBusMessage *r=dbus_message_new_method_return(m);
 if(!r)return 0;
 DBusMessageIter top,array;
 dbus_message_iter_init_append(r,&top);
 int ok=dbus_message_iter_open_container(&top,DBUS_TYPE_ARRAY,"y",&array)&&dbus_message_iter_append_fixed_array(&array,DBUS_TYPE_BYTE,&p,(int)n)&&dbus_message_iter_close_container(&top,&array);
 if(!ok){dbus_message_unref(r);
 return 0;
 }return send_message(s,r);
 }
static const char *uuid(const char *path){if(!strcmp(path,C3_SERVICE))return C3_SERVICE_UUID;
 if(!strcmp(path,C3_RX))return C3_RX_UUID;
 if(!strcmp(path,C3_ACK))return C3_ACK_UUID;
 if(!strcmp(path,C3_SESSION))return C3_SESSION_UUID;
 return NULL;
 }
static int strings(DBusMessageIter *out,const char **items,size_t n){DBusMessageIter a;
 if(!dbus_message_iter_open_container(out,DBUS_TYPE_ARRAY,"s",&a))return 0;
 for(size_t i=0; i<n; i++)if(!dbus_message_iter_append_basic(&a,DBUS_TYPE_STRING,&items[i]))return 0;
 return dbus_message_iter_close_container(out,&a);
 }
static int property(DBusMessageIter *out,const char *path,const char *key){
 const char *u=uuid(path),*value=NULL,*sig=NULL;
 int type=DBUS_TYPE_STRING;
 dbus_bool_t primary=TRUE;
 const char *flags[1];
 size_t count=0;
 if(!strcmp(key,"UUID")&&u){value=u;
 sig="s";
 }
 else if(!strcmp(path,C3_SERVICE)&&!strcmp(key,"Primary")){sig="b";
 type=DBUS_TYPE_BOOLEAN;
 }
 else if(u&&strcmp(path,C3_SERVICE)&&!strcmp(key,"Service")){value=C3_SERVICE;
 sig="o";
 type=DBUS_TYPE_OBJECT_PATH;
 }
 else if(u&&strcmp(path,C3_SERVICE)&&!strcmp(key,"Flags")){flags[0]=!strcmp(path,C3_RX)?"secure-write":"secure-read";
 count=1;
 sig="as";
 }
 else if(!strcmp(path,C3_ADV)&&!strcmp(key,"Type")){value="peripheral";
 sig="s";
 }
 else if(!strcmp(path,C3_ADV)&&!strcmp(key,"LocalName")){value="PandaNote966U2";
 sig="s";
 }
 else if(!strcmp(path,C3_ADV)&&!strcmp(key,"ServiceUUIDs")){flags[0]=C3_SERVICE_UUID;
 count=1;
 sig="as";
 }
 else return 0;
 DBusMessageIter variant;
 if(!dbus_message_iter_open_container(out,DBUS_TYPE_VARIANT,sig,&variant))return 0;
 int ok=count?strings(&variant,flags,count):(int)dbus_message_iter_append_basic(&variant,type,type==DBUS_TYPE_BOOLEAN?(const void *)&primary:(const void *)&value);
 return ok&&dbus_message_iter_close_container(out,&variant);
}
static int properties(DBusMessageIter *out,const char *path){
 DBusMessageIter array,entry;
 if(!dbus_message_iter_open_container(out,DBUS_TYPE_ARRAY,"{sv}",&array))return 0;
 const char *service[]={"UUID","Primary"},*characteristic[]={"UUID","Service","Flags"},*adv[]={"Type","LocalName","ServiceUUIDs"};
 const char **keys=!strcmp(path,C3_SERVICE)?service:!strcmp(path,C3_ADV)?adv:characteristic;
 size_t count=!strcmp(path,C3_SERVICE)?2:3;
 for(size_t i=0; i<count; i++)if(!dbus_message_iter_open_container(&array,DBUS_TYPE_DICT_ENTRY,NULL,&entry)||!dbus_message_iter_append_basic(&entry,DBUS_TYPE_STRING,&keys[i])||!property(&entry,path,keys[i])||!dbus_message_iter_close_container(&array,&entry))return 0;
 return dbus_message_iter_close_container(out,&array);
}
static int managed(struct c3_server *s,DBusMessage *m){
 DBusMessage *r=dbus_message_new_method_return(m);
 if(!r)return 0;
 DBusMessageIter top,objects;
 dbus_message_iter_init_append(r,&top);
 int ok=dbus_message_iter_open_container(&top,DBUS_TYPE_ARRAY,"{oa{sa{sv}}}",&objects);
 const char *paths[]={C3_SERVICE,C3_RX,C3_ACK,C3_SESSION};
 for(size_t i=0; ok&&i<4; i++){DBusMessageIter object,interfaces,interface;
 const char *iface=i?CHAR:SERVICE;
 ok=dbus_message_iter_open_container(&objects,DBUS_TYPE_DICT_ENTRY,NULL,&object)&&dbus_message_iter_append_basic(&object,DBUS_TYPE_OBJECT_PATH,&paths[i])&&dbus_message_iter_open_container(&object,DBUS_TYPE_ARRAY,"{sa{sv}}",&interfaces)&&dbus_message_iter_open_container(&interfaces,DBUS_TYPE_DICT_ENTRY,NULL,&interface)&&dbus_message_iter_append_basic(&interface,DBUS_TYPE_STRING,&iface)&&properties(&interface,paths[i])&&dbus_message_iter_close_container(&interfaces,&interface)&&dbus_message_iter_close_container(&object,&interfaces)&&dbus_message_iter_close_container(&objects,&object);
 }
 ok=ok&&dbus_message_iter_close_container(&top,&objects);
 if(!ok){dbus_message_unref(r);
 return 0;
 }return send_message(s,r);
}
struct peer {unsigned char address[6];
 int paired,bonded,connected;
 };
static int address(const char *v,unsigned char out[6]){
 if(strlen(v)!=17)return 0;
 for(unsigned i=0;i<17;i++){
  unsigned char c=(unsigned char)v[i];
  if(i%3==2){if(c!=':')return 0;}
  else if(!((c>='0'&&c<='9')||(c>='A'&&c<='F')||(c>='a'&&c<='f')))return 0;
 }
 unsigned values[6];
 if(sscanf(v,"%2x:%2x:%2x:%2x:%2x:%2x",&values[0],&values[1],&values[2],&values[3],&values[4],&values[5])!=6)return 0;
 for(unsigned i=0;i<6;i++)out[i]=(unsigned char)values[i];
 return 1;
}
static int device(struct c3_server *s,const char *path,struct peer *p){
 if(strncmp(path,"/org/bluez/hci0/dev_",20)||strlen(path)!=37)return 0;
 DBusMessage *r=call(s->bus,s->owner,path,PROPS,"GetAll","s","org.bluez.Device1");
 if(!r)return 0;
 memset(p,0,sizeof *p);
 if(!dbus_message_has_signature(r,"a{sv}")){dbus_message_unref(r);
 return 0;
 }unsigned seen=0,count=0;
 int ok=1;
 DBusMessageIter top,array;
 dbus_message_iter_init(r,&top);
 dbus_message_iter_recurse(&top,&array);
 while(ok&&dbus_message_iter_get_arg_type(&array)!=DBUS_TYPE_INVALID){if(++count>64){ok=0;
 break;
 }DBusMessageIter entry,value;
 const char *key;
 dbus_message_iter_recurse(&array,&entry);
 dbus_message_iter_get_basic(&entry,&key);
 dbus_message_iter_next(&entry);
 dbus_message_iter_recurse(&entry,&value);
 int type=dbus_message_iter_get_arg_type(&value);
 unsigned bit=0;
  if(!strcmp(key,"Address")){const char *v=NULL;
 bit=1;
 if(type!=DBUS_TYPE_STRING)ok=0;
 else{dbus_message_iter_get_basic(&value,&v);
 ok=address(v,p->address);
 }}
  else if(!strcmp(key,"Paired")||!strcmp(key,"Bonded")||!strcmp(key,"Connected")){dbus_bool_t v=FALSE;
 bit=!strcmp(key,"Paired")?2:!strcmp(key,"Bonded")?4:8;
 if(type!=DBUS_TYPE_BOOLEAN)ok=0;
 else{dbus_message_iter_get_basic(&value,&v);
 if(bit==2)p->paired=v;
 else if(bit==4)p->bonded=v;
 else p->connected=v;
 }}
  if(bit&&(seen&bit))ok=0;
 seen|=bit;
 dbus_message_iter_next(&array);
 }
 dbus_message_unref(r);
 return ok&&seen==15;
}
struct options {char device[128];
 unsigned mtu;
 };
static int options(DBusMessageIter *array,struct options *out,int write){
 DBusMessageIter entries;
 dbus_message_iter_recurse(array,&entries);
 memset(out,0,sizeof *out);
 out->mtu=23;
 unsigned seen=0,count=0;
 while(dbus_message_iter_get_arg_type(&entries)!=DBUS_TYPE_INVALID){if(++count>12)return 0;
 DBusMessageIter entry,value;
 const char *key;
 dbus_message_iter_recurse(&entries,&entry);
 dbus_message_iter_get_basic(&entry,&key);
 dbus_message_iter_next(&entry);
 dbus_message_iter_recurse(&entry,&value);
 int type=dbus_message_iter_get_arg_type(&value);
 unsigned bit=0;
  if(!strcmp(key,"device")){const char *v=NULL;
 bit=1;
 if(type!=DBUS_TYPE_OBJECT_PATH)return 0;
 dbus_message_iter_get_basic(&value,&v);
 if(strlen(v)>=sizeof out->device)return 0;
 strcpy(out->device,v);
 }
  else if(!strcmp(key,"link")){const char *v=NULL;
 bit=2;
 if(type!=DBUS_TYPE_STRING)return 0;
 dbus_message_iter_get_basic(&value,&v);
 if(strcmp(v,"LE"))return 0;
 }
  else if(!strcmp(key,"type")){const char *v=NULL;
 bit=4;
 if(type!=DBUS_TYPE_STRING||!write)return 0;
 dbus_message_iter_get_basic(&value,&v);
 if(strcmp(v,"request"))return 0;
 }
  else if(!strcmp(key,"offset")){dbus_uint16_t v;
 bit=8;
 if(type!=DBUS_TYPE_UINT16)return 0;
 dbus_message_iter_get_basic(&value,&v);
 if(v)return 0;
 }
  else if(!strcmp(key,"mtu")){dbus_uint16_t v;
 bit=16;
 if(type!=DBUS_TYPE_UINT16)return 0;
 dbus_message_iter_get_basic(&value,&v);
 if(v<23||v>517)return 0;
 out->mtu=v;
 }
  else if(!strcmp(key,"prepare-authorize")){dbus_bool_t v;
 bit=32;
 if(type!=DBUS_TYPE_BOOLEAN)return 0;
 dbus_message_iter_get_basic(&value,&v);
 if(v)return 0;
 }
  else return 0;
  if(seen&bit)return 0;
 seen|=bit;
 dbus_message_iter_next(&entries);
 }
 return (seen&3)==3&&(!write||(seen&4));
}
static int authorized(struct c3_server *s,const char *path,uint64_t now){
 struct peer p;
 if(strcmp(path,s->device)||!device(s,path,&p)||!p.connected||!p.paired||!p.bonded||memcmp(p.address,s->runtime->policy.peer,6)){c3_close(s->runtime);
 return 0;
 }
 if(!s->runtime->policy.active&&!bt_link_authorize(&s->runtime->policy,p.address,BT_LINK_BONDED|BT_LINK_ENCRYPTED|BT_LINK_MITM,now))return 0;
 return s->runtime->policy.active;
}
static DBusHandlerResult route(DBusConnection *connection,DBusMessage *m,void *data){
 (void)connection;
 struct c3_server *s=data;
 const char *sender=dbus_message_get_sender(m),*path=dbus_message_get_path(m);
 if(dbus_message_get_type(m)!=DBUS_MESSAGE_TYPE_METHOD_CALL)return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
 if(!sender||strcmp(sender,s->owner)||!bound(s)){c3_close(s->runtime);
 reject(s,m,"org.bluez.Error.NotAuthorized");
 return DBUS_HANDLER_RESULT_HANDLED;
 }
 uint64_t now=now_ms();
 c3_tick(s->runtime,now);
 if(!strcmp(path,C3_APP)&&dbus_message_is_method_call(m,OBJECTS,"GetManagedObjects")&&dbus_message_has_signature(m,"")){managed(s,m);
 return DBUS_HANDLER_RESULT_HANDLED;
 }
 if(dbus_message_is_method_call(m,PROPS,"GetAll")||dbus_message_is_method_call(m,PROPS,"Get")){
  const char *iface=NULL,*key=NULL;
 int get=dbus_message_is_method_call(m,PROPS,"Get");
 int ok=dbus_message_has_signature(m,get?"ss":"s")&&(get?dbus_message_get_args(m,NULL,DBUS_TYPE_STRING,&iface,DBUS_TYPE_STRING,&key,DBUS_TYPE_INVALID):dbus_message_get_args(m,NULL,DBUS_TYPE_STRING,&iface,DBUS_TYPE_INVALID));
  const char *expected=!strcmp(path,C3_SERVICE)?SERVICE:!strcmp(path,C3_ADV)?ADVERT:uuid(path)?CHAR:NULL;
  DBusMessage *r=ok&&expected&&!strcmp(iface,expected)?dbus_message_new_method_return(m):NULL;
 if(r){DBusMessageIter out;
 dbus_message_iter_init_append(r,&out);
 ok=get?property(&out,path,key):properties(&out,path);
 if(ok)send_message(s,r);
 else{dbus_message_unref(r);
 reject(s,m,"org.freedesktop.DBus.Error.InvalidArgs");
 }}else reject(s,m,"org.freedesktop.DBus.Error.InvalidArgs");
 return DBUS_HANDLER_RESULT_HANDLED;
 }
 if(!strcmp(path,C3_AGENT)){
  if(dbus_message_is_method_call(m,AGENT,"RequestConfirmation")&&dbus_message_has_signature(m,"ou")){
   const char *dev=NULL;
 dbus_uint32_t passkey;
 struct peer p;
 int ok=!s->confirmation&&dbus_message_get_args(m,NULL,DBUS_TYPE_OBJECT_PATH,&dev,DBUS_TYPE_UINT32,&passkey,DBUS_TYPE_INVALID)&&strlen(dev)<sizeof s->device&&device(s,dev,&p)&&c3_pair_request(s->runtime,p.address,passkey,now);
   if(ok){strcpy(s->device,dev);
 s->confirmation=dbus_message_ref(m);
 }else reject(s,m,"org.bluez.Error.Rejected");
  }else if((dbus_message_is_method_call(m,AGENT,"Cancel")||dbus_message_is_method_call(m,AGENT,"Release"))&&dbus_message_has_signature(m,"")){c3_close(s->runtime);
 if(s->confirmation){reject(s,s->confirmation,"org.bluez.Error.Canceled");
 dbus_message_unref(s->confirmation);
 s->confirmation=NULL;
 }done(s,m);
 }
  else reject(s,m,"org.bluez.Error.Rejected");
 return DBUS_HANDLER_RESULT_HANDLED;
 }
 int write=dbus_message_is_method_call(m,CHAR,"WriteValue"),read=dbus_message_is_method_call(m,CHAR,"ReadValue");
 if((write&&!strcmp(path,C3_RX))||(read&&(!strcmp(path,C3_ACK)||!strcmp(path,C3_SESSION)))){
  struct options opt;
 DBusMessageIter top,array;
 const unsigned char *wire=NULL;
 int length=0;
 int ok=dbus_message_has_signature(m,write?"aya{sv}":"a{sv}");
  if(ok){dbus_message_iter_init(m,&top);
 if(write){dbus_message_iter_recurse(&top,&array);
 if(dbus_message_iter_get_arg_type(&array)==DBUS_TYPE_BYTE)dbus_message_iter_get_fixed_array(&array,&wire,&length);
 dbus_message_iter_next(&top);
 ok=length>0&&length<=(int)(C3_RECORD_MAX+4);
 }if(ok)ok=options(&top,&opt,write)&&authorized(s,opt.device,now);
 }
  if(!ok){reject(s,m,"org.bluez.Error.NotAuthorized");
 return DBUS_HANDLER_RESULT_HANDLED;
 }
  if(write){(void)c3_fragment(s->runtime,wire,(size_t)length,opt.mtu,now);
 if(s->runtime->effect.kind==3||s->runtime->effect.kind==4||s->runtime->effect.kind==6)bt_effect_clear(&s->runtime->effect);
 done(s,m);
 }
  else if(!strcmp(path,C3_ACK))bytes(s,m,s->runtime->ack,C3_ACK_BYTES);
  else{unsigned char session[18]={1,(unsigned char)s->runtime->policy.grants};
 memcpy(session+2,s->runtime->policy.nonce,16);
 bytes(s,m,session,sizeof session);
 memset(session,0,sizeof session);
 }
  return DBUS_HANDLER_RESULT_HANDLED;
 }
 if(!strcmp(path,C3_ADV)&&dbus_message_is_method_call(m,ADVERT,"Release")&&dbus_message_has_signature(m,"")){s->registered&=~4U;
 done(s,m);
 return DBUS_HANDLER_RESULT_HANDLED;
 }
 reject(s,m,"org.freedesktop.DBus.Error.UnknownMethod");
 return DBUS_HANDLER_RESULT_HANDLED;
}
static DBusHandlerResult handler(DBusConnection *bus,DBusMessage *m,void *data){
 struct c3_server *s=data;
 if(s->handling){if(dbus_message_get_type(m)==DBUS_MESSAGE_TYPE_METHOD_CALL)reject(s,m,"org.bluez.Error.InProgress");
 return DBUS_HANDLER_RESULT_HANDLED;
 }
 s->handling=1;
 DBusHandlerResult result=route(bus,m,data);
 s->handling=0;
 return result;
}
int c3_server_export(struct c3_server *s,DBusConnection *bus,struct c3 *runtime,pid_t pid){
 memset(s,0,sizeof *s);
 if(!bus||!runtime||pid<=1)return -1;
 s->bus=bus;
 s->runtime=runtime;
 s->expected_pid=pid;
 dbus_connection_set_max_message_size(bus,32768);
 dbus_connection_set_max_received_size(bus,65536);
 if(!bound(s))return -1;
 static const DBusObjectPathVTable vtable={NULL,handler,NULL,NULL,NULL,NULL};
 if(!dbus_connection_register_fallback(bus,"/org/pandanote/Bluetooth",&vtable,s))return -1;
 s->exported=1;
 return 0;
}
static int registration(struct c3_server *s,unsigned bit,int enable){
 const char *path=bit==1?"/org/bluez":"/org/bluez/hci0",*iface=bit==1?"org.bluez.AgentManager1":bit==2?"org.bluez.GattManager1":"org.bluez.LEAdvertisingManager1",*object=bit==1?C3_AGENT:bit==2?C3_APP:C3_ADV;
 const char *method=bit==1?(enable?"RegisterAgent":"UnregisterAgent"):bit==2?(enable?"RegisterApplication":"UnregisterApplication"):(enable?"RegisterAdvertisement":"UnregisterAdvertisement");
 DBusMessage *m=dbus_message_new_method_call(s->owner,path,iface,method);
 if(!m)return -1;
 dbus_message_set_auto_start(m,FALSE);
 DBusMessageIter top,dict;
 dbus_message_iter_init_append(m,&top);
 int ok=dbus_message_iter_append_basic(&top,DBUS_TYPE_OBJECT_PATH,&object);
 if(enable){if(bit==1){const char *cap="DisplayYesNo";
 ok=ok&&dbus_message_iter_append_basic(&top,DBUS_TYPE_STRING,&cap);
 }else ok=ok&&dbus_message_iter_open_container(&top,DBUS_TYPE_ARRAY,"{sv}",&dict)&&dbus_message_iter_close_container(&top,&dict);
 }
 DBusMessage *r=ok?request(s->bus,m,1000):NULL;
 dbus_message_unref(m);
 ok=r&&dbus_message_get_type(r)==DBUS_MESSAGE_TYPE_METHOD_RETURN&&dbus_message_has_signature(r,"")&&dbus_message_get_sender(r)&&!strcmp(dbus_message_get_sender(r),s->owner);
 if(r)dbus_message_unref(r);
 return ok?0:-1;
}
int c3_server_register(struct c3_server *s){if(!s->exported||s->registered||!bound(s))return -1;
 for(unsigned bit=1; bit<=4; bit*=2){if(registration(s,bit,1)){(void)c3_server_close(s);
 return -1;
 }s->registered|=bit;
 }return 0;
 }
int c3_server_tick(struct c3_server *s,uint64_t now){
 if(!s->exported)return -1;
 c3_tick(s->runtime,now);
 if(s->confirmation&&!s->runtime->policy.pending){if(s->runtime->policy.approved)done(s,s->confirmation);
 else reject(s,s->confirmation,"org.bluez.Error.Rejected");
 dbus_message_unref(s->confirmation);
 s->confirmation=NULL;
 }
 if(now>=s->next_check){s->next_check=now+500;
 if(!bound(s)||(s->runtime->policy.active&&!authorized(s,s->device,now))){c3_close(s->runtime);
 return -1;
 }}
 return dbus_connection_read_write_dispatch(s->bus,10)?0:-1;
}
int c3_server_close(struct c3_server *s){
 int result=0;
 if(s->confirmation){reject(s,s->confirmation,"org.bluez.Error.Canceled");
 dbus_message_unref(s->confirmation);
 s->confirmation=NULL;
 }
 if(s->registered){if(!bound(s))result=-1;
 else for(unsigned bit=4; bit; bit/=2)if((s->registered&bit)&&registration(s,bit,0))result=-1;
 s->registered=0;
 }
 if(s->exported){if(!dbus_connection_unregister_object_path(s->bus,"/org/pandanote/Bluetooth"))result=-1;
 s->exported=0;
 }if(s->runtime)c3_close(s->runtime);
 return result;
}
