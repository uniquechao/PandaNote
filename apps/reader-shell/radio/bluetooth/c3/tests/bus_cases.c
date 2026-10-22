/* Own-code synthetic BlueZ peer; actual private D-Bus transport, never HCI. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "../service.c"
#include "../../../third_party/sha256/sha256.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <unistd.h>
#define DEV "/org/bluez/hci0/dev_01_02_03_04_05_06"
static DBusConnection *connect_bus(void){DBusError e;dbus_error_init(&e);DBusConnection *c=dbus_connection_open_private("unix:path=/tmp/pandanote-connectivity/bluetooth/run/bus",&e);assert(c);dbus_error_free(&e);dbus_connection_set_exit_on_disconnect(c,FALSE);dbus_error_init(&e);assert(dbus_bus_register(c,&e));dbus_error_free(&e);return c;}
static void finish(DBusConnection *c,DBusMessage *m){DBusMessage *r=dbus_message_new_method_return(m);assert(r&&dbus_connection_send(c,r,NULL));dbus_message_unref(r);}
static void peer_property(DBusMessageIter *a,const char *key,const char *string){DBusMessageIter entry,value;dbus_bool_t yes=TRUE;assert(dbus_message_iter_open_container(a,DBUS_TYPE_DICT_ENTRY,NULL,&entry));assert(dbus_message_iter_append_basic(&entry,DBUS_TYPE_STRING,&key));assert(dbus_message_iter_open_container(&entry,DBUS_TYPE_VARIANT,string?"s":"b",&value));assert(dbus_message_iter_append_basic(&value,string?DBUS_TYPE_STRING:DBUS_TYPE_BOOLEAN,string?(const void *)&string:(const void *)&yes));assert(dbus_message_iter_close_container(&entry,&value));assert(dbus_message_iter_close_container(a,&entry));}
static DBusHandlerResult peer_handler(DBusConnection *c,DBusMessage *m,void *data){
 const char *dest=data,*method=dbus_message_get_member(m),*path=dbus_message_get_path(m);if(dbus_message_get_type(m)!=DBUS_MESSAGE_TYPE_METHOD_CALL)return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
 if(!strcmp(path,DEV)&&dbus_message_is_method_call(m,PROPS,"GetAll")){
  DBusMessage *r=dbus_message_new_method_return(m);assert(r);DBusMessageIter top,a;dbus_message_iter_init_append(r,&top);assert(dbus_message_iter_open_container(&top,DBUS_TYPE_ARRAY,"{sv}",&a));peer_property(&a,"Address","01:02:03:04:05:06");peer_property(&a,"Paired",NULL);peer_property(&a,"Bonded",NULL);peer_property(&a,"Connected",NULL);assert(dbus_message_iter_close_container(&top,&a));assert(dbus_connection_send(c,r,NULL));dbus_message_unref(r);return DBUS_HANDLER_RESULT_HANDLED;
 }
 if(!strcmp(method,"RegisterApplication")){
  DBusMessage *r=call(c,dest,C3_APP,OBJECTS,"GetManagedObjects",NULL,NULL);assert(r&&dbus_message_has_signature(r,"a{oa{sa{sv}}}"));dbus_message_unref(r);finish(c,m);return DBUS_HANDLER_RESULT_HANDLED;
 }
 if(!strcmp(method,"RegisterAgent")||!strcmp(method,"RegisterAdvertisement")||!strncmp(method,"Unregister",10)){finish(c,m);return DBUS_HANDLER_RESULT_HANDLED;}
 return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
}
static void option_value(DBusMessageIter *a,const char *key,int type,const void *value){DBusMessageIter entry,v;char sig[2]={(char)type,0};assert(dbus_message_iter_open_container(a,DBUS_TYPE_DICT_ENTRY,NULL,&entry));assert(dbus_message_iter_append_basic(&entry,DBUS_TYPE_STRING,&key));assert(dbus_message_iter_open_container(&entry,DBUS_TYPE_VARIANT,sig,&v));assert(dbus_message_iter_append_basic(&v,type,value));assert(dbus_message_iter_close_container(&entry,&v));assert(dbus_message_iter_close_container(a,&entry));}
static DBusMessage *gatt(DBusConnection *c,const char *dest,const char *path,const unsigned char *wire,int size){
 DBusMessage *m=dbus_message_new_method_call(dest,path,CHAR,wire?"WriteValue":"ReadValue");assert(m);dbus_message_set_auto_start(m,FALSE);DBusMessageIter top,a;dbus_message_iter_init_append(m,&top);
 if(wire){assert(dbus_message_iter_open_container(&top,DBUS_TYPE_ARRAY,"y",&a));assert(dbus_message_iter_append_fixed_array(&a,DBUS_TYPE_BYTE,&wire,size));assert(dbus_message_iter_close_container(&top,&a));}
 assert(dbus_message_iter_open_container(&top,DBUS_TYPE_ARRAY,"{sv}",&a));const char *dev=DEV,*link="LE",*type="request";dbus_uint16_t mtu=23;option_value(&a,"device",DBUS_TYPE_OBJECT_PATH,&dev);option_value(&a,"link",DBUS_TYPE_STRING,&link);option_value(&a,"mtu",DBUS_TYPE_UINT16,&mtu);if(wire)option_value(&a,"type",DBUS_TYPE_STRING,&type);assert(dbus_message_iter_close_container(&top,&a));DBusMessage *r=request(c,m,1000);dbus_message_unref(m);return r;
}
static const unsigned char *reply_bytes(DBusMessage *r,int expected){assert(r&&dbus_message_get_type(r)==DBUS_MESSAGE_TYPE_METHOD_RETURN&&dbus_message_has_signature(r,"ay"));DBusMessageIter top,a;dbus_message_iter_init(r,&top);dbus_message_iter_recurse(&top,&a);const unsigned char *p=NULL;int length=0;dbus_message_iter_get_fixed_array(&a,&p,&length);assert(length==expected);return p;}
static void put_le32(unsigned char *p,unsigned n){for(unsigned i=0;i<4;i++)p[i]=(unsigned char)(n>>(i*8));}
static void send_record(DBusConnection *c,const char *dest,const unsigned char nonce[16],unsigned seq,unsigned opcode,const unsigned char *body,size_t size,unsigned id,unsigned expected){
 unsigned char record[C3_RECORD_MAX]={1,(unsigned char)opcode};put_le32(record+2,seq);memcpy(record+6,nonce,16);if(size)memcpy(record+22,body,size);size+=22;
 for(size_t offset=0;offset<size;){unsigned char fragment[20];size_t take=size-offset;if(take>16)take=16;fragment[0]=(offset?0:1)|(offset+take==size?2:0);fragment[1]=(unsigned char)id;fragment[2]=(unsigned char)offset;fragment[3]=0;memcpy(fragment+4,record+offset,take);DBusMessage *r=gatt(c,dest,C3_RX,fragment,(int)take+4);assert(r&&dbus_message_get_type(r)==DBUS_MESSAGE_TYPE_METHOD_RETURN);dbus_message_unref(r);r=gatt(c,dest,C3_ACK,NULL,0);const unsigned char *ack=reply_bytes(r,12);assert(ack[1]==(offset+take==size?expected:0));if(offset+take==size)assert(ack[8]==(expected==1?seq+1:seq));dbus_message_unref(r);offset+=take;}
}
static void peer_run(int from_parent,int to_parent){
 DBusConnection *c=connect_bus();DBusError error;dbus_error_init(&error);assert(dbus_bus_request_name(c,"org.bluez",DBUS_NAME_FLAG_DO_NOT_QUEUE,&error)==DBUS_REQUEST_NAME_REPLY_PRIMARY_OWNER);dbus_error_free(&error);assert(write(to_parent,"R",1)==1);char dest[64];assert(read(from_parent,dest,sizeof dest)==sizeof dest&&dest[0]==':');
 static const DBusObjectPathVTable vtable={NULL,peer_handler,NULL,NULL,NULL,NULL};assert(dbus_connection_register_fallback(c,"/org/bluez",&vtable,dest));assert(!fcntl(from_parent,F_SETFL,O_NONBLOCK));char command=0;
 uint64_t deadline=now_ms()+7000;while(now_ms()<deadline&&read(from_parent,&command,1)!=1)assert(dbus_connection_read_write_dispatch(c,10));assert(command=='T');
 DBusMessage *m=dbus_message_new_method_call(dest,C3_AGENT,AGENT,"RequestConfirmation");assert(m);const char *dev=DEV;dbus_uint32_t key=123456;assert(dbus_message_append_args(m,DBUS_TYPE_OBJECT_PATH,&dev,DBUS_TYPE_UINT32,&key,DBUS_TYPE_INVALID));DBusMessage *r=request(c,m,2000);dbus_message_unref(m);assert(r&&dbus_message_get_type(r)==DBUS_MESSAGE_TYPE_METHOD_RETURN&&dbus_message_has_signature(r,""));dbus_message_unref(r);
 r=gatt(c,dest,C3_SESSION,NULL,0);const unsigned char *session=reply_bytes(r,18);assert(session[0]==1&&session[1]==5);unsigned char nonce[16];memcpy(nonce,session+2,16);unsigned char record[23]={1,1,1,0,0,0};memcpy(record+6,nonce,16);record[22]=1;dbus_message_unref(r);
 unsigned char fragment[20]={1,7,0,0};memcpy(fragment+4,record,16);r=gatt(c,dest,C3_RX,fragment,20);assert(r&&dbus_message_get_type(r)==DBUS_MESSAGE_TYPE_METHOD_RETURN);dbus_message_unref(r);r=gatt(c,dest,C3_ACK,NULL,0);const unsigned char *ack=reply_bytes(r,12);assert(ack[1]==0&&ack[6]==16);dbus_message_unref(r);
 fragment[0]=2;fragment[2]=16;memcpy(fragment+4,record+16,7);for(int i=0;i<2;i++){r=gatt(c,dest,C3_RX,fragment,11);assert(r&&dbus_message_get_type(r)==DBUS_MESSAGE_TYPE_METHOD_RETURN);dbus_message_unref(r);r=gatt(c,dest,C3_ACK,NULL,0);ack=reply_bytes(r,12);assert(ack[1]==1&&ack[2]==1&&ack[8]==2);dbus_message_unref(r);}
 unsigned char body[64],hash[32];const unsigned char text[]="hello\n";SHA256_CTX sha;sha256_init(&sha);sha256_update(&sha,text,6);sha256_final(&sha,hash);body[0]=8;memcpy(body+1,"book.txt",8);put_le32(body+9,6);memcpy(body+13,hash,32);send_record(c,dest,nonce,2,3,body,45,8,1);put_le32(body,0);memcpy(body+4,text,6);send_record(c,dest,nonce,3,4,body,10,9,1);send_record(c,dest,nonce,4,5,NULL,0,10,1);send_record(c,dest,nonce,5,2,NULL,0,11,2);
 DBusConnection *impostor=connect_bus();r=gatt(impostor,dest,C3_SESSION,NULL,0);assert(r&&dbus_message_get_type(r)==DBUS_MESSAGE_TYPE_ERROR&&dbus_message_has_sender(r,dest));dbus_message_unref(r);dbus_connection_close(impostor);dbus_connection_unref(impostor);
 assert(write(to_parent,"D",1)==1);command=0;deadline=now_ms()+3000;while(now_ms()<deadline&&read(from_parent,&command,1)!=1)assert(dbus_connection_read_write_dispatch(c,10));assert(command=='Q');dbus_connection_close(c);dbus_connection_unref(c);close(from_parent);close(to_parent);_exit(0);
}
static unsigned char file_buffer[BT_FILE_MAX];
int main(int argc,char **argv){
 assert(argc==2);int dir=open(argv[1],O_RDONLY|O_DIRECTORY);assert(dir>=0);int to_child[2],from_child[2];assert(!pipe(to_child)&&!pipe(from_child));pid_t child=fork();assert(child>=0);
 if(!child){close(to_child[1]);close(from_child[0]);peer_run(to_child[0],from_child[1]);}
 close(to_child[0]);close(from_child[1]);char marker;assert(read(from_child[0],&marker,1)==1&&marker=='R');DBusConnection *c=connect_bus();const char *unique=dbus_bus_get_unique_name(c);char dest[64]={0};assert(unique&&strlen(unique)<sizeof dest);strcpy(dest,unique);assert(write(to_child[1],dest,sizeof dest)==sizeof dest);
 struct c3 state;c3_init(&state,file_buffer,sizeof file_buffer,dir);bt_pair_window(&state.policy,now_ms());struct c3_server server,bad;assert(c3_server_export(&bad,c,&state,child+1)==-1);assert(!c3_server_export(&server,c,&state,child));assert(!c3_server_register(&server));assert(server.registered==7);assert(write(to_child[1],"T",1)==1);assert(!fcntl(from_child[0],F_SETFL,O_NONBLOCK));unsigned effects=0,files=0;uint64_t deadline=now_ms()+6000;marker=0;
 while(now_ms()<deadline&&read(from_child[0],&marker,1)!=1){assert(!c3_server_tick(&server,now_ms()));if(state.policy.pending)assert(bt_pair_confirm(&state.policy,state.policy.peer,state.policy.nonce,1,5,now_ms()));struct bt_effect effect;if(c3_take_effect(&state,&effect)){if(effect.kind==1){assert(effect.control==1);effects++;}else{assert(effect.kind==5&&!strcmp(effect.filename,"book.txt")&&effect.file_bytes==6);files++;}}bt_effect_clear(&effect);}
 assert(marker=='D'&&effects==1&&files==1&&!state.policy.active);int book=openat(dir,"book.txt",O_RDONLY|O_NOFOLLOW);assert(book>=0);char content[6];assert(read(book,content,6)==6&&!memcmp(content,"hello\n",6));close(book);assert(!c3_server_close(&server));assert(write(to_child[1],"Q",1)==1);int status;assert(waitpid(child,&status,0)==child&&WIFEXITED(status)&&WEXITSTATUS(status)==0);dbus_connection_close(c);dbus_connection_unref(c);close(dir);close(to_child[1]);close(from_child[0]);puts("PASS real private D-Bus owner/PID, registration callback, Agent deferred approval, bonded peer session, MTU23 control/file bytes+SHA, duplicate ACK, provisioning/sender refusal; synthetic BlueZ only");return 0;
}
