#include "battery.h"
#include <errno.h>
#include <stdint.h>
int factoryBatteryPercent(int mv){
 // Single-cell sanity limits are a rejection gate, not calibration endpoints.
 if(mv<2700||mv>4500)return -1;
 // Exact retained getPercentByVolt() bands (libqtzlslib @0x76db8).
 if(mv<=3400)return 0;
 if(mv<=3420)return 10;
 if(mv<3550)return 20;
 if(mv<3800)return 40;
 if(mv<3950)return 60;
 if(mv<4100)return 80;
 return 100;
}
BatteryReading batteryFromAdcBytes(const unsigned char *bytes,unsigned length,bool factory){
 BatteryReading result;
 if(!bytes||length!=4){result.errorNumber=EIO;
 return result;}
 const uint32_t adc=uint32_t(bytes[0])|(uint32_t(bytes[1])<<8)|(uint32_t(bytes[2])<<16)|(uint32_t(bytes[3])<<24);
 // A driver timeout can wrap its negative raw result through unsigned scaling.
 if(adc>1800){result.errorNumber=ERANGE;
 return result;}
 result.adcMv=int(adc);result.voltageMv=int(adc)*3;result.source=BatteryAdcVoltage;
 if(factory){result.percent=factoryBatteryPercent(result.voltageMv);
 if(result.percent>=0)result.source=BatteryFactoryEstimate;else result.errorNumber=ERANGE;}
 return result;
}
BatteryReading readBattery(bool factory){
 unsigned char bytes[4]={0,0,0,0};int error=0;const int count=batteryAdcRead(bytes,&error);
 BatteryReading result;
 if(count==4)result=batteryFromAdcBytes(bytes,4,factory);else result.errorNumber=error?error:EIO;
 const int charging=batteryChargingStatus();result.chargingKnown=charging==0||charging==1;result.charging=result.chargingKnown&&charging==1;
 return result;
}
