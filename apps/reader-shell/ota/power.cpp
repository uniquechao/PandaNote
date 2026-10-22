#include "core.h"
#include "../battery.h"
#include <sys/stat.h>
namespace Ota {
bool safePower(){BatteryReading b=readBattery(true);return b.voltageMv>=3900&&b.percent>=60&&b.chargingKnown&&b.charging;}
}
