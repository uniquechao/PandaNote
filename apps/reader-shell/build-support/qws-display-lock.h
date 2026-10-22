#ifndef PANDANOTE_QWS_DISPLAY_LOCK_API_H
#define PANDANOTE_QWS_DISPLAY_LOCK_API_H
// Declaration-only adapter for Qt 4.7.4 QWSDisplay static APIs.
// src/gui/kernel/qapplication_qws.cpp:1323-1330, retained commit 092cd760d5fddf9640a310214fe01929f0fff3a8.
// Write lock serializes against the QWS framebuffer compositing lock.
extern "C" bool pandanoteQwsDisplayGrabbed() __asm__("_ZN10QWSDisplay7grabbedEv");
extern "C" void pandanoteQwsGrabDisplay(bool) __asm__("_ZN10QWSDisplay4grabEb");
extern "C" void pandanoteQwsUngrabDisplay() __asm__("_ZN10QWSDisplay6ungrabEv");
#endif
