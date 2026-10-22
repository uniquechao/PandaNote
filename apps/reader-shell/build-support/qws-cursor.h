#ifndef PANDANOTE_QWS_CURSOR_API_H
#define PANDANOTE_QWS_CURSOR_API_H
// Declaration-only adapter for public Qt 4.7.4 QWSServer static APIs.
// Retained Qt commit: 092cd760d5fddf9640a310214fe01929f0fff3a8.
// Original declarations: src/gui/embedded/qwindowsystem_qws.h:272,318-319.
// Exact exports verified in pinned stock libQtGui.so.4 SHA-256
// 66fdf97eafbdf6cae5f2a7810809989d521514200db1facfe8a429d7f64cf902.
// No QWSServer object, object layout, replacement implementation or SDK edit.
// GNU symbol aliases avoid inventing an incomplete QWSServer class definition
// when the retained minimal SDK cannot include its transitive QtCore aliases.
class QWSMouseHandler;
extern "C" void pandanoteQwsSetCursorVisible(bool)
    __asm__("_ZN9QWSServer16setCursorVisibleEb");
extern "C" bool pandanoteQwsIsCursorVisible()
    __asm__("_ZN9QWSServer15isCursorVisibleEv");
extern "C" QWSMouseHandler *pandanoteQwsMouseHandler()
    __asm__("_ZN9QWSServer12mouseHandlerEv");
#endif
