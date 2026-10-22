#include "capability.h"
#include <string.h>
int c2_interface(struct c2_capability *c,const char *path,const char *interface){
 if(++c->interfaces>256)return -1;
 if(strcmp(path,"/org/bluez/hci0"))return 0;
 if(!strcmp(interface,"org.bluez.Adapter1"))c->flags|=1;
 if(!strcmp(interface,"org.bluez.GattManager1"))c->flags|=2;
 if(!strcmp(interface,"org.bluez.LEAdvertisingManager1"))c->flags|=4;
 return 0;
}
int c2_owner(const char *before,const char *after,pid_t expected,unsigned actual){
 return before&&after&&before[0]==':'&&strlen(before)<64&&!strcmp(before,after)&&expected>0&&(unsigned)expected==actual;
}
