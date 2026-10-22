#include "navigation.h"
#include <QtCore/qrect.h>
QRect actionRect(Page page, Action action) {
    if(page==Home) {
        if(action==OpenPanel) return QRect(344,724,112,56);
        if(action==OpenSchedule) return QRect(24,176,432,504);
    } else {
        if(action==BackHome) return page==Panel ? QRect(8,44,64,64) : QRect(408,44,64,64);
        if(page!=Panel && action==BackToPanel) return QRect(8,44,64,64);
        if(page==Panel && action>=OpenSchedule && action<=OpenInfo) {
            int n=int(action)-int(OpenSchedule);
            return QRect(24+(n%2)*224,184+(n/2)*168,208,152);
        }
    }
    return QRect();
}
Page navigate(Page current, Action action) {
    if(action==OpenSystemControl) return Control;
    if(action==BackHome) return Home;
    if(current==Home && action==OpenPanel) return Panel;
    if(current==Home && action==OpenSchedule) return Schedule;
    if(current!=Home && current!=Panel && action==BackToPanel) return Panel;
    if(current==Panel && action>=OpenSchedule && action<=OpenInfo)
        return Page(int(Schedule)+int(action)-int(OpenSchedule));
    return current;
}
Action hitTest(Page page,int x,int y) {
    if(x<0 || x>=480 || y<0 || y>=800) return NoAction;
    for(int a=int(OpenPanel);a<=int(BackHome);++a)
        if(actionRect(page,Action(a)).contains(x,y)) return Action(a);
    return NoAction;
}
Page IdleNavigation::interact(Action action,qint64 monotonicMs) {
    lastInteraction_=monotonicMs;page_=navigate(page_,action);return page_;
}
Page IdleNavigation::expire(qint64 monotonicMs) {
    if(page_!=Home && monotonicMs-lastInteraction_>=60000) page_=Home;
    return page_;
}

Page IdleNavigation::restore(Page target,qint64 monotonicMs) {
    lastInteraction_=monotonicMs;page_=target;return page_;
}
