#ifndef PANDANOTE_NAVIGATION_H
#define PANDANOTE_NAVIGATION_H
#include <QtCore/qglobal.h>
#include <QtCore/qrect.h>
enum Page { Home, Panel, Schedule, Words, Notes, Control, Info };
enum Action { NoAction, OpenPanel, OpenSchedule, OpenWords, OpenNotes, OpenControl, OpenInfo, BackToPanel, BackHome, OpenSystemControl };
Page navigate(Page current, Action action);
Action hitTest(Page page, int x, int y);
QRect actionRect(Page page, Action action);
class IdleNavigation {
public:
    IdleNavigation(): page_(Home), lastInteraction_(0) {}
    Page page() const { return page_; }
    Page interact(Action action, qint64 monotonicMs);
    Page expire(qint64 monotonicMs);
    Page restore(Page target, qint64 monotonicMs);
private:
    Page page_; qint64 lastInteraction_;
};
#endif
