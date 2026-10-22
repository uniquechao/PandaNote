// Explicit development probe only; no framebuffer pixels or geometry changes.
#include "../einkrefresh.h"
#include <QtGui/qapplication.h>
#include <QtCore/qelapsedtimer.h>
#include <stdio.h>
int main(int argc,char **argv){QApplication app(argc,argv,QApplication::GuiClient);QElapsedTimer t;t.start();EinkRefreshResult r=performDeviceFullRefresh();printf("EINK_DEVICE_PROBE result=%d elapsed_ms=%lld\n",int(r),(long long)t.elapsed());return r==EinkRefreshOk?0:1;}
