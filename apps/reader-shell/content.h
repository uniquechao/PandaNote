#ifndef PANDANOTE_READER_CONTENT_H
#define PANDANOTE_READER_CONTENT_H
#include <QtCore/qstring.h>
#include <QtCore/qlist.h>
#include <QtCore/qdatetime.h>
#include <QtCore/qelapsedtimer.h>

struct EventTime { qint64 epoch; QDate localDate; QString display; int utcOffsetSeconds; EventTime(): epoch(0), utcOffsetSeconds(0) {} };
struct Event { QString id, summary; EventTime start, end; bool allDay; QString location; Event(): allDay(false) {} };
struct LocalDay { QDate date; qint64 startEpoch, endEpoch; LocalDay(): startEpoch(0), endEpoch(0) {} };
struct Content {
    int schema; QString version; qint64 generatedAt; QString displayTimezone;
    QList<Event> events; QString background; QList<LocalDay> localDays;
    Content(): schema(0), generatedAt(0) {}
};
// The caller must supply an immutable staged directory. Updates are atomic to out.
bool loadContent(const QString &directory, Content *out, QString *error);
QDate localDateAtEpoch(const Content &content, qint64 epoch);
QList<Event> selectUpcomingEvents(const Content &content, qint64 nowEpoch, const QDate &localDate);
// Establish only from a fresh trusted server response, never cached generatedAt/RTC.
class TimeAnchor {
public:
    TimeAnchor(): serverEpoch_(0), bootAtMs_(-1) {}
    bool establish(qint64 serverEpoch);
    void invalidate();
    bool nowEpoch(qint64 *out) const;
private:
    qint64 serverEpoch_, bootAtMs_;
};
#endif
