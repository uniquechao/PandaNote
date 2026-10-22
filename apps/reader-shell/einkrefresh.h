#ifndef PANDANOTE_EINKREFRESH_H
#define PANDANOTE_EINKREFRESH_H
enum EinkRefreshResult { EinkRefreshOk, EinkRefreshUnavailable, EinkRefreshBusy, EinkRefreshArmFailed, EinkRefreshPanFailed, EinkRefreshRestoreFailed };
class EinkRefreshIo {
public:
 virtual ~EinkRefreshIo(){}
 virtual bool ready()=0; virtual void grab()=0; virtual void ungrab()=0;
 virtual bool readMode(int *)=0; virtual bool writeMode(int)=0; virtual bool pan()=0;
};
EinkRefreshResult performFullRefresh(EinkRefreshIo &);
EinkRefreshResult performDeviceFullRefresh();
#endif
