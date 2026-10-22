#ifndef PANDANOTE_BATTERY_H
#define PANDANOTE_BATTERY_H
// Native battery boundary; no Qt, RTC, GPIO writes or vendor executable.
enum BatterySource { BatteryUnavailable,BatteryAdcVoltage,BatteryFactoryEstimate };
struct BatteryReading {
 int adcMv,voltageMv,percent,errorNumber;bool chargingKnown,charging;BatterySource source;
 BatteryReading():adcMv(-1),voltageMv(-1),percent(-1),errorNumber(0),chargingKnown(false),charging(false),source(BatteryUnavailable){}
};
// Retained factory voltage bands are an estimate, never a calibrated fuel gauge.
int factoryBatteryPercent(int voltageMv);
BatteryReading batteryFromAdcBytes(const unsigned char *bytes,unsigned length,bool useFactoryCurve=false);
BatteryReading readBattery(bool useFactoryCurve=false);
// Production links battery_posix.cpp; host cases replace only these syscalls.
int batteryAdcRead(unsigned char bytes[4],int *errorNumber);
int batteryChargingStatus(); // -1 unknown, 0 explicitly not charging, 1 charging.
#endif
