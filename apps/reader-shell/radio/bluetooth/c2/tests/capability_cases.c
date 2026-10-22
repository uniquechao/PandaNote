#include "capability.h"
#include <assert.h>
int main(void){
 struct c2_capability c={0};
 assert(!c2_interface(&c,"/org/bluez/hci1","org.bluez.Adapter1")&&c.flags==0);
 assert(!c2_interface(&c,"/org/bluez/hci0","org.bluez.GattManager1")&&c.flags==2);
 assert(!c2_interface(&c,"/org/bluez/hci0","org.bluez.Adapter1")&&c.flags==3);
 assert(!c2_interface(&c,"/org/bluez/hci0","org.bluez.LEAdvertisingManager1")&&c.flags==7);
 assert(!c2_interface(&c,"/org/bluez/hci0/dev_X","org.bluez.Adapter1"));
 assert(c2_owner(":1.2",":1.2",123,123));
 assert(!c2_owner(":1.2",":1.3",123,123));assert(!c2_owner(":1.2",":1.2",123,124));
 assert(!c2_owner("org.bluez","org.bluez",123,123));assert(!c2_owner(":1.2",":1.2",0,0));
 for(int i=0;i<300;i++)if(c2_interface(&c,"/any","org.bluez.Device1")<0)return 0;
 return 1;
}
