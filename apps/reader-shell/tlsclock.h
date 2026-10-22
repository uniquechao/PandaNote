#ifndef PANDANOTE_TLS_CLOCK_H
#define PANDANOTE_TLS_CLOCK_H
#include <stdint.h>
inline bool validTlsEpoch(int64_t e){return e>=946684800LL&&e<=2147483646LL;}
inline int64_t tlsInitialEpoch(bool domain,int64_t floor,int64_t realtime){if(!validTlsEpoch(floor))return 0;return domain&&validTlsEpoch(realtime)&&realtime>floor?realtime:floor;}
inline int64_t tlsAdvanceEpoch(int64_t epoch,int64_t anchorMs,int64_t nowMs){if(!validTlsEpoch(epoch)||anchorMs<0||nowMs<anchorMs)return 0;int64_t delta=(nowMs-anchorMs)/1000;return delta>2147483646LL-epoch?0:epoch+delta;}
int64_t tlsBootMs();int64_t tlsRealtimeEpoch();
#endif
