// Root may run this only after verifying the retained ADC module and policy.
#include "../battery.h"
#include <stdio.h>
int main(){
 const BatteryReading r=readBattery(true);
 printf("battery adc_mv=%d voltage_mv=%d percent=%d charging_known=%d charging=%d source=%d error=%d\n",r.adcMv,r.voltageMv,r.percent,r.chargingKnown?1:0,r.charging?1:0,int(r.source),r.errorNumber);
 return r.voltageMv>=0&&r.errorNumber==0?0:1;
}
