// Explicit native smoke probe; temp request is not watched by system service.
#include "../powerkeys.h"
#include "../powerrequest.h"
#include <stdio.h>
#include <errno.h>
int main(){PowerKeys keys;bool opened=keys.open();errno=0;bool published=publishPowerOffRequest("/tmp/pandanote-ui-a-d67c4d10/power-request-probe");int error=errno;printf("POWER_DEVICE_PROBE open=%d available=%d publish=%d errno=%d\n",int(opened),int(keys.available()),int(published),error);return opened&&published?0:1;}
