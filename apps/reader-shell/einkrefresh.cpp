#include "einkrefresh.h"
EinkRefreshResult performFullRefresh(EinkRefreshIo &io) {
 if(!io.ready())return EinkRefreshUnavailable;
 io.grab();
 int mode=-1;
 if(!io.readMode(&mode)){io.ungrab();return EinkRefreshUnavailable;}
 // This UI is monochrome. Never alter an in-flight or grayscale mode.
 if(mode!=0){io.ungrab();return EinkRefreshBusy;}
 EinkRefreshResult result=EinkRefreshArmFailed;int armed=-1;
 bool wrote=io.writeMode(1);
 if(wrote&&io.readMode(&armed)&&armed==1)result=io.pan()?EinkRefreshOk:EinkRefreshPanFailed;
 // A short/failed sysfs write may still change global mode: restore regardless.
 int restored=-1;bool reset=io.writeMode(0);
 if(!reset||!io.readMode(&restored)||restored!=0)result=EinkRefreshRestoreFailed;
 io.ungrab();return result;
}
