#include "../content.h"
#include <QtCore/qcoreapplication.h>
#include <QtCore/qdir.h>
#include <QtCore/qfile.h>
#include <QtCore/qtextstream.h>
#include <QtCore/qthread.h>
#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
extern "C" {
#include "../third_party/sha256/sha256.h"
}

static int failures = 0, checks = 0;
#define CHECK(test, condition) do { ++checks; if (!(condition)) { fprintf(stderr,"FAIL %s line %d\n",test,__LINE__); ++failures; } } while(0)
static Content load(const QString &root, const char *name) {
    Content value; QString error;
    bool loaded=loadContent(root + "/" + name, &value, &error);
    CHECK(name, loaded);
    if(!loaded) { fprintf(stderr,"load error: %s\n",error.toUtf8().constData()); exit(1); }
    return value;
}
static QString ids(const QList<Event> &events) {
    QStringList values; for (int i=0;i<events.size();++i) values << events[i].id;
    return values.join(",");
}
static QByteArray hash(const QByteArray &data) {
    SHA256_CTX context; BYTE result[32]; sha256_init(&context);
    sha256_update(&context,reinterpret_cast<const BYTE *>(data.constData()),data.size());
    sha256_final(&context,result); return QByteArray(reinterpret_cast<const char *>(result),32).toHex();
}
int main(int argc, char **argv) {
    QCoreApplication app(argc,argv);
    if (argc != 2) return 64;
    QString root = QString::fromLocal8Bit(argv[1]); QString error;
    CHECK("sha256_empty_vector",hash(QByteArray())=="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    CHECK("sha256_abc_vector",hash("abc")=="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    CHECK("sha256_high_bit_vector",hash(QByteArray(1,char(0xff)))=="a8100ae6aa1940d0b663bb31cd466142ebbdbd5187131b92d93818987832eb89");
    CHECK("sha256_multiblock_vector",hash("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq")=="248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
    Content current = load(root,"valid");
    if (current.events.size()!=7) return 1;
    CHECK("valid_unicode_and_limits", current.version == "v1" && current.events.size() == 7);
    CHECK("unicode_comma_newline", current.events[2].summary == QString::fromUtf8("会议,中文\n第二行"));
    CHECK("empty_chinese_title", current.events[3].summary.isEmpty());
    CHECK("long_chinese_title", current.events[4].summary.size() == 1365);
    CHECK("max_200_events",load(root,"max-events").events.size()==200);
    CHECK("exact_text_4k",load(root,"max-text").events[0].summary.size()==4096);
    CHECK("null_output",!loadContent(root+"/valid",0,&error));
    Content value = current;
    CHECK("reject_truncated_package", !loadContent(root+"/truncated",&value,&error) && !error.isEmpty());
    CHECK("keep_previous_content_on_error", value.version == "v1" && value.schema==current.schema && value.generatedAt==current.generatedAt && value.displayTimezone==current.displayTimezone && value.localDays.size()==current.localDays.size() && value.events.size()==7 && value.events[2].summary==current.events[2].summary && value.events[2].end.epoch==current.events[2].end.epoch && value.background==current.background);
    CHECK("reject_unknown_schema", !loadContent(root+"/unknown-schema",&value,&error) && value.version=="v1");
    CHECK("select_five_upcoming_events", ids(selectUpcomingEvents(current,1792458000,QDate(2026,10,20))) == "cross,all-day,meeting,empty,long");
    CHECK("all_day_local_date_not_utc_date", ids(selectUpcomingEvents(current,1792427400,QDate(2026,10,20))) == "cross,all-day,past,meeting,empty");
    CHECK("fallback_next_future_event", ids(selectUpcomingEvents(load(root,"next-only"),1792504200,QDate(2026,10,20))) == "tomorrow");
    Content sparse=current;sparse.events.clear();sparse.events<<current.events[1]<<current.events[6];
    CHECK("fill_today_with_future_date",ids(selectUpcomingEvents(sparse,1792458000,QDate(2026,10,20)))=="all-day,tomorrow");
    CHECK("expired_events_excluded_even_when_fewer_than_five",ids(selectUpcomingEvents(current,1792504200,QDate(2026,10,20)))=="all-day,tomorrow");
    Content cancelled=load(root,"cancelled");
    CHECK("cancelled_snapshot_replaces", cancelled.version=="v2" && cancelled.events.isEmpty() && selectUpcomingEvents(cancelled,1792458000,QDate(2026,10,20)).isEmpty());
    CHECK("day_table_local_midnight", localDateAtEpoch(current,1792425600)==QDate(2026,10,20) && localDateAtEpoch(current,1792512000)==QDate(2026,10,21));
    Content dst=load(root,"dst");
    CHECK("dst_day_boundaries", localDateAtEpoch(dst,1793516400)==QDate(2026,11,1) && localDateAtEpoch(dst,1793606400)==QDate(2026,11,2));
    CHECK("no_utc_or_rtc_fallback", !localDateAtEpoch(current,0).isValid() && selectUpcomingEvents(current,0,QDate()).isEmpty());
    Content longRunning;
    const bool longLoaded=loadContent(root+"/long-running",&longRunning,&error);
    CHECK("accept_long_timed_original_endpoints",longLoaded && longRunning.events.size()==2 && longRunning.events[0].start.epoch==1790816400LL && longRunning.events[0].end.epoch==1792893600LL && longRunning.events[0].start.localDate==QDate(2026,10,1) && longRunning.events[0].end.localDate==QDate(2026,10,25));
    CHECK("accept_long_all_day_original_endpoints",longLoaded && longRunning.events.size()==2 && longRunning.events[1].allDay && longRunning.events[1].start.epoch==1790784000LL && longRunning.events[1].end.epoch==1792857600LL && longRunning.events[1].start.localDate==QDate(2026,10,1) && longRunning.events[1].end.localDate==QDate(2026,10,25));
    CHECK("select_long_events_ongoing",longLoaded && ids(selectUpcomingEvents(longRunning,1792458000,QDate(2026,10,20)))=="long-all-day,long-timed");
    CHECK("keep_long_event_day_table_bounded",longLoaded && longRunning.localDays.size()==9 && !localDateAtEpoch(longRunning,1790816400LL).isValid());
    Content longDst;
    const bool dstLoaded=loadContent(root+"/long-dst",&longDst,&error);
    CHECK("accept_long_dst_endpoints_outside_table",dstLoaded && longDst.events.size()==1 && longDst.events[0].start.epoch==1790870400LL && longDst.events[0].end.epoch==1795629600LL && longDst.events[0].start.localDate==QDate(2026,10,1) && longDst.events[0].end.localDate==QDate(2026,11,25) && longDst.events[0].start.utcOffsetSeconds==-25200 && longDst.events[0].end.utcOffsetSeconds==-28800);
    CHECK("select_long_dst_event_ongoing",dstLoaded && ids(selectUpcomingEvents(longDst,1793563200LL,QDate(2026,11,1)))=="long-dst");
    TimeAnchor clock; qint64 now=-1;
    CHECK("no_time_anchor", !clock.nowEpoch(&now) && now==-1);
    CHECK("reject_unreliable_time", !clock.establish(0) && !clock.nowEpoch(&now));
    CHECK("server_time_anchor", clock.establish(1792458000) && clock.nowEpoch(&now) && now>=1792458000 && now<=1792458001);
    usleep(1100000); CHECK("monotonic_clock_advances",clock.nowEpoch(&now) && now>=1792458001 && now<=1792458003);
    clock.invalidate(); CHECK("invalidate_time_anchor", !clock.nowEpoch(&now));
    const char *bad[]={"bad-base64","bad-utf8","too-long","too-many","bad-background","bad-path","bad-hash","missing-manifest","missing-background","extra-file","bad-date","bad-epoch","duplicate-id","bad-days","oversize-ini","symlink","corrupt-png","huge-png","extra-key","duplicate-key","malformed-manifest","bad-all-day","extra-section","duplicate-section","bad-offset-range","bad-offset-format","bad-offset-date","bad-offset-midnight","bad-offset-table-midnight"};
    for (unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);++i) {
        Content retained=current; CHECK(bad[i], !loadContent(root+"/"+bad[i],&retained,&error) && retained.version=="v1");
    }
    if(failures) return 1;
    printf("PASS content: package integrity, atomic retention, event selection, local dates, cache time (%d checks)\n",checks);
    return 0;
}
