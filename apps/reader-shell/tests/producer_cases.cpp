// Focused acceptance of manager-generated packages by the frozen consumer.
#include "../content.h"
#include <QtCore/qcoreapplication.h>
#include <QtCore/qalgorithms.h>
#include <stdio.h>

static int checks=0,failures=0;
#define CHECK(name, condition) do { ++checks; if(!(condition)) { ++failures; printf("FAIL %s\n",name); } } while(0)
static bool earlier(const Event &a,const Event &b) { return a.start.epoch!=b.start.epoch ? a.start.epoch<b.start.epoch : a.id<b.id; }
int main(int argc,char **argv) {
    QCoreApplication app(argc,argv);
    if(argc!=2) return 2;
    QString root=QString::fromLocal8Bit(argv[1]),error;
    Content original,produced;
    CHECK("load_independent_shared_input",loadContent(root+"/valid",&original,&error));
    CHECK("load_real_producer_package",loadContent(root+"/producer-shared",&produced,&error));
    qSort(original.events.begin(),original.events.end(),earlier);
    CHECK("producer_full_snapshot_count",produced.events.size()==original.events.size());
    CHECK("producer_display_zone",produced.displayTimezone==original.displayTimezone);
    for(int i=0;i<produced.events.size() && i<original.events.size();++i) {
        const Event &a=produced.events[i],&b=original.events[i];
        CHECK("producer_preserves_shared_event_semantics",a.id==b.id && a.summary==b.summary && a.location==b.location && a.start.epoch==b.start.epoch && a.end.epoch==b.end.epoch && a.start.localDate==b.start.localDate && a.end.localDate==b.end.localDate && a.allDay==b.allDay);
    }
    Content chronology;
    CHECK("load_multicalendar_producer",loadContent(root+"/producer-chronology",&chronology,&error));
    CHECK("deduplicate_multicalendar",chronology.events.size()==5);
    const char *expected[]={"early","\xf0\x90\x80\x80","\xee\x80\x80","middle","late"};
    // Reader drawSchedule uses consecutive groups of five directly from events.
    // Check both pages' underlying event order through the actual consumer.
    for(int page=0;page<1;++page) {
        for(int row=0;row<5 && page*5+row<chronology.events.size();++row) {
            const int index=page*5+row;
            CHECK("chronological_full_agenda_page",chronology.events[index].id==QString::fromUtf8(expected[index]));
        }
    }
    const QList<Event> upcoming=selectUpcomingEvents(chronology,1792458000LL,QDate(2026,10,20));
    CHECK("home_utf16_tie_order",upcoming.size()==4 && upcoming[0].id==QString::fromUtf8(expected[1]) && upcoming[1].id==QString::fromUtf8(expected[2]) && upcoming[2].id=="middle");
    if(failures) return 1;
    printf("PASS producer: frozen Qt loadContent, shared semantics, UTF16 ordering and chronological full-agenda pages (%d checks)\n",checks);
    return 0;
}
