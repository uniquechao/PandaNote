#include "../battery.h"
#include <errno.h>
#include <stdio.h>
static int failures=0,checks=0;
#define CHECK(n,x) do{++checks;if(!(x)){++failures;fprintf(stderr,"FAIL %s line %d\n",n,__LINE__);}}while(0)
static unsigned char sample[4]={0,0,0,0};static int sampleCount=4,sampleError=0,chargingState=-1;
int batteryAdcRead(unsigned char *out,int *error){for(int i=0;i<4;++i)out[i]=sample[i];*error=sampleError;return sampleCount;}
int batteryChargingStatus(){return chargingState;}
static void adc(unsigned value){for(int i=0;i<4;++i)sample[i]=(value>>(8*i))&255;sampleCount=4;sampleError=0;}
int main(){
 BatteryReading empty;CHECK("default_unknown",empty.percent==-1&&empty.voltageMv==-1&&!empty.chargingKnown&&empty.source==BatteryUnavailable);
 adc(1300);BatteryReading b=batteryFromAdcBytes(sample,4);CHECK("little_endian_adc",b.adcMv==1300);CHECK("three_to_one_divider",b.voltageMv==3900);CHECK("uncalibrated_percent_unknown",b.percent==-1&&b.source==BatteryAdcVoltage);
 b=batteryFromAdcBytes(sample,4,true);CHECK("factory_estimate_explicit",b.percent==60&&b.source==BatteryFactoryEstimate);
 CHECK("factory_band_3400",factoryBatteryPercent(3400)==0);CHECK("factory_band_3401",factoryBatteryPercent(3401)==10);CHECK("factory_band_3420",factoryBatteryPercent(3420)==10);CHECK("factory_band_3421",factoryBatteryPercent(3421)==20);CHECK("factory_band_3549",factoryBatteryPercent(3549)==20);CHECK("factory_band_3550",factoryBatteryPercent(3550)==40);CHECK("factory_band_3799",factoryBatteryPercent(3799)==40);CHECK("factory_band_3800",factoryBatteryPercent(3800)==60);CHECK("factory_band_3949",factoryBatteryPercent(3949)==60);CHECK("factory_band_3950",factoryBatteryPercent(3950)==80);CHECK("factory_band_4099",factoryBatteryPercent(4099)==80);CHECK("factory_band_4100",factoryBatteryPercent(4100)==100);
 CHECK("implausible_voltage_no_percentage",factoryBatteryPercent(0)==-1&&factoryBatteryPercent(5400)==-1);
 CHECK("null_no_reading",batteryFromAdcBytes(0,4).source==BatteryUnavailable);for(unsigned n=0;n<4;++n)CHECK("partial_no_reading",batteryFromAdcBytes(sample,n).source==BatteryUnavailable);CHECK("extra_bytes_no_reading",batteryFromAdcBytes(sample,5).source==BatteryUnavailable);
 adc(1801);CHECK("over_vref_rejected",batteryFromAdcBytes(sample,4,true).source==BatteryUnavailable);adc(0xffffffffU);CHECK("driver_timeout_wrapping_rejected",batteryFromAdcBytes(sample,4,true).source==BatteryUnavailable);
 adc(0);b=batteryFromAdcBytes(sample,4,true);CHECK("zero_adc_not_full_battery",b.voltageMv==0&&b.percent==-1);adc(1800);b=batteryFromAdcBytes(sample,4,true);CHECK("vref_boundary_not_full_battery",b.voltageMv==5400&&b.percent==-1);
 adc(1300);chargingState=-1;b=readBattery(true);CHECK("adc_success_charge_unknown",b.voltageMv==3900&&b.percent==60&&!b.chargingKnown&&!b.charging);
 chargingState=1;b=readBattery(true);CHECK("explicit_charge_true",b.chargingKnown&&b.charging);chargingState=0;b=readBattery(true);CHECK("explicit_charge_false",b.chargingKnown&&!b.charging);chargingState=2;b=readBattery();CHECK("invalid_charge_unknown",!b.chargingKnown&&!b.charging);
 sampleCount=-1;sampleError=ETIMEDOUT;chargingState=-1;b=readBattery(true);CHECK("timeout_preserved",b.source==BatteryUnavailable&&b.percent==-1&&b.errorNumber==ETIMEDOUT);sampleCount=2;sampleError=0;b=readBattery(true);CHECK("partial_io_eio",b.source==BatteryUnavailable&&b.errorNumber==EIO);
 printf("%d checks, %d failures\n",checks,failures);return failures?1:0;
}
