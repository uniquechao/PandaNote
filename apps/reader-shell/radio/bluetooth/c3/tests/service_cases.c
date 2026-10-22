/* Trusted own-code fixture includes private serializers; never a production main. */
#include "../service.c"
#include <assert.h>
static void option(DBusMessageIter *a,const char *key,int type,const void *value){DBusMessageIter e,v;char sig[2]={(char)type,0};assert(dbus_message_iter_open_container(a,DBUS_TYPE_DICT_ENTRY,NULL,&e));assert(dbus_message_iter_append_basic(&e,DBUS_TYPE_STRING,&key));assert(dbus_message_iter_open_container(&e,DBUS_TYPE_VARIANT,sig,&v));assert(dbus_message_iter_append_basic(&v,type,value));assert(dbus_message_iter_close_container(&e,&v));assert(dbus_message_iter_close_container(a,&e));}
static DBusMessage *opts(const char *link,const char *type,int duplicate){DBusMessage *m=dbus_message_new(DBUS_MESSAGE_TYPE_METHOD_RETURN);assert(m);DBusMessageIter top,a;dbus_message_iter_init_append(m,&top);assert(dbus_message_iter_open_container(&top,DBUS_TYPE_ARRAY,"{sv}",&a));const char *dev="/org/bluez/hci0/dev_01_02_03_04_05_06";option(&a,"device",DBUS_TYPE_OBJECT_PATH,&dev);option(&a,"link",DBUS_TYPE_STRING,&link);if(type)option(&a,"type",DBUS_TYPE_STRING,&type);if(duplicate)option(&a,"device",DBUS_TYPE_OBJECT_PATH,&dev);assert(dbus_message_iter_close_container(&top,&a));return m;}
int main(void){
 unsigned char mac[6];assert(address("01:02:03:04:05:06",mac)&&mac[0]==1&&mac[5]==6);assert(!address("01:02:03:04:05:GG",mac));assert(!address("01:02:03:04:05: 6",mac));
 const char *paths[]={C3_SERVICE,C3_RX,C3_ACK,C3_SESSION,C3_ADV};
 for(unsigned i=0;i<5;i++){DBusMessage *m=dbus_message_new(DBUS_MESSAGE_TYPE_METHOD_RETURN);assert(m);DBusMessageIter top;dbus_message_iter_init_append(m,&top);assert(properties(&top,paths[i]));assert(dbus_message_has_signature(m,"a{sv}"));char *wire=NULL;int size=0;assert(dbus_message_marshal(m,&wire,&size));if(i>0&&i<4){const char *wanted=i==1?"secure-write":"secure-read";int found=0;for(int x=0;x+(int)strlen(wanted)<size;x++)if(!memcmp(wire+x,wanted,strlen(wanted)))found=1;assert(found);}dbus_free(wire);dbus_message_unref(m);}
 const char *links[]={"LE","BR/EDR","LE","LE","LE"},*types[]={"request","request","command",NULL,"request"};
 for(int i=0;i<5;i++){DBusMessage *m=opts(links[i],types[i],i==4);DBusMessageIter top;struct options result;dbus_message_iter_init(m,&top);assert(options(&top,&result,1)==(i==0));dbus_message_unref(m);}
 puts("PASS actual libdbus variant serialization, secure flags, LE/request/duplicate option refusal");return 0;
}
