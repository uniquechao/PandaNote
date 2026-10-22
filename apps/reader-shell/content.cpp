#include "content.h"
#include <time.h>
#include <QtCore/qfile.h>
#include <QtCore/qfileinfo.h>
#include <QtCore/qdir.h>
#include <QtCore/qsettings.h>
#include <QtCore/qset.h>
#include <QtCore/qregexp.h>
#include <QtCore/qalgorithms.h>
#include <QtGui/qimage.h>
extern "C" {
#include "third_party/sha256/sha256.h"
}

typedef char ExpectedFloatQreal[sizeof(qreal)==4 ? 1 : -1];
typedef char ExpectedShaWord[sizeof(WORD)==4 ? 1 : -1];
namespace {
const qint64 MinEpoch=946684800LL, MaxEpoch=4133980800LL;
bool fail(QString *error,const QString &reason) { if(error) *error=reason; return false; }
QByteArray digest(const QByteArray &data) {
    SHA256_CTX context; BYTE hash[SHA256_BLOCK_SIZE]; sha256_init(&context);
    sha256_update(&context,reinterpret_cast<const BYTE *>(data.constData()),data.size());
    sha256_final(&context,hash);
    return QByteArray(reinterpret_cast<const char *>(hash),SHA256_BLOCK_SIZE).toHex();
}
bool readFile(const QString &path,int limit,QByteArray *data) {
    QFileInfo info(path); if(info.isSymLink() || !info.isFile() || info.size()>limit || info.size()<0) return false;
    QFile file(path); if(!file.open(QIODevice::ReadOnly)) return false;
    *data=file.read(limit+1);return data->size()==info.size() && data->size()<=limit && file.error()==QFile::NoError;
}
// QSettings is the decoder, but reject its permissive duplicate/escape grammar first.
bool iniKeys(const QByteArray &data,QSet<QString> *keys,QSet<QString> *sections) {
    if(data.contains('\0') || QString::fromUtf8(data.constData(),data.size()).toUtf8()!=data) return false;
    QString section;
    const QList<QByteArray> lines=data.split('\n');
    for(int i=0;i<lines.size();++i) {
        QByteArray raw=lines[i]; if(raw.endsWith('\r')) raw.chop(1);
        if(raw.isEmpty()) continue;
        const QString line=QString::fromLatin1(raw.constData(),raw.size());
        if(QRegExp("\\[[A-Za-z0-9]+\\]").exactMatch(line)) {
            section=line.mid(1,line.size()-2);
            if(sections->contains(section)) return false;
            sections->insert(section);continue;
        }
        const int equal=line.indexOf('=');
        if(section.isEmpty() || equal<1 || !QRegExp("[A-Za-z][A-Za-z0-9]*").exactMatch(line.left(equal))) return false;
        const QString key=section+"/"+line.left(equal);
        if(keys->contains(key)) return false;
        keys->insert(key);
        if(!QRegExp("[A-Za-z0-9+/=.-]*").exactMatch(line.mid(equal+1))) return false;
    }
    return true;
}
class Fields {
public:
    QSettings settings; QSet<QString> read; bool ok;
    explicit Fields(const QString &path): settings(path,QSettings::IniFormat),ok(true) { settings.setIniCodec("UTF-8"); }
    QString raw(const QString &key) {
        read.insert(key); if(!settings.contains(key)) {ok=false;return QString();}
        const QVariant value=settings.value(key);
        if(value.type()!=QVariant::String && value.type()!=QVariant::ByteArray) { ok=false;return QString(); }
        return value.toString();
    }
    qint64 number(const QString &key,qint64 min,qint64 max) {
        const QString text=raw(key); bool parsed=false; const qint64 n=text.toLongLong(&parsed);
        if(!QRegExp(min<0 ? "0|-?[1-9][0-9]*" : "0|[1-9][0-9]*").exactMatch(text) || !parsed || n<min || n>max) ok=false;
        return n;
    }
    QString text(const QString &key,bool empty=true,int limit=4096) {
        const QByteArray encoded=raw(key).toLatin1();
        if(encoded.size()>((limit+2)/3)*4 || encoded.size()%4 || !QRegExp("[A-Za-z0-9+/]*={0,2}").exactMatch(QString::fromLatin1(encoded))) {ok=false;return QString();}
        const QByteArray decoded=QByteArray::fromBase64(encoded);
        const QString value=QString::fromUtf8(decoded.constData(),decoded.size());
        if(decoded.toBase64()!=encoded || decoded.size()>limit || decoded.contains('\0') || value.toUtf8()!=decoded || (!empty && value.isEmpty())) ok=false;
        return value;
    }
    QDate date(const QString &key) {
        const QString value=raw(key); const QDate date=QDate::fromString(value,"yyyy-MM-dd");
        if(!date.isValid() || date.toString("yyyy-MM-dd")!=value) ok=false;
        return date;
    }
};
QDate dateForEndpoint(const Content &content,qint64 epoch) {
    QDate result=localDateAtEpoch(content,epoch);
    if(!result.isValid() && !content.localDays.isEmpty() && epoch==content.localDays.last().endEpoch) return content.localDays.last().date.addDays(1);
    return result;
}
bool validEndpoint(const Content &content,const EventTime &time) {
    // The manager supplies the offset at this exact endpoint, including DST.
    // This is integer Gregorian mapping, not an IANA or system-clock lookup.
    const qint64 localSeconds=time.epoch+time.utcOffsetSeconds;
    if(QDate(1970,1,1).addDays(localSeconds/86400)!=time.localDate) return false;
    const QDate tableDate=dateForEndpoint(content,time.epoch);
    if(tableDate.isValid() && tableDate!=time.localDate) return false;
    if(localSeconds%86400==0) {
        for(int i=0;i<content.localDays.size();++i) {
            const LocalDay &day=content.localDays[i];
            if(time.epoch>=day.startEpoch && time.epoch<day.endEpoch && time.epoch!=day.startEpoch) return false;
        }
    }
    return true;
}
bool atMidnight(const EventTime &time) {
    return (time.epoch+time.utcOffsetSeconds)%86400==0;
}
struct Earlier {
    qint64 now; explicit Earlier(qint64 value):now(value) {}
    bool operator()(const Event &a,const Event &b) const {
        bool activeA=a.start.epoch<=now && a.end.epoch>now;
        bool activeB=b.start.epoch<=now && b.end.epoch>now;
        if(activeA!=activeB) return activeA;
        if(a.start.epoch!=b.start.epoch) return a.start.epoch<b.start.epoch;
        return a.id<b.id;
    }
};
}

bool loadContent(const QString &directory,Content *out,QString *error) {
    if(!out) return fail(error,"missing output");
    QFileInfo directoryInfo(directory);QDir dir(directory);
    if(!directoryInfo.isDir() || directoryInfo.isSymLink()) return fail(error,"invalid package directory");
    const QStringList files=dir.entryList(QDir::AllEntries|QDir::Hidden|QDir::System|QDir::NoDotAndDotDot,QDir::Name);
    QStringList expected;expected<<"SHA256SUMS"<<"background.png"<<"content.ini";
    if(files!=expected) return fail(error,"package file set mismatch");
    QByteArray ini,image,manifest;
    if(!readFile(dir.filePath("content.ini"),131072,&ini) || !readFile(dir.filePath("background.png"),2097152,&image) || !readFile(dir.filePath("SHA256SUMS"),512,&manifest)) return fail(error,"package file missing, symlink, oversized or unreadable");
    QByteArray expectedManifest=digest(ini)+"  content.ini\n"+digest(image)+"  background.png\n";
    if(manifest!=expectedManifest) return fail(error,"SHA256 manifest mismatch");
    QSet<QString> keys,sections;
    if(!iniKeys(ini,&keys,&sections)) return fail(error,"invalid or duplicate INI fields");
    Fields fields(dir.filePath("content.ini"));Content content;
    content.schema=fields.number("content/schema",1,1);
    content.version=fields.text("content/version",false);
    content.generatedAt=fields.number("content/generatedAt",MinEpoch,MaxEpoch-1);
    content.displayTimezone=fields.text("content/displayTimezone",false,128);
    const QString background=fields.text("content/background",false);
    if(background!="background.png" || !QRegExp("[A-Za-z0-9_+./-]+").exactMatch(content.displayTimezone)) return fail(error,"invalid resource or timezone identifier");
    const int count=fields.number("events/count",0,200);
    const int days=fields.number("days/count",1,9);
    if(!fields.ok) return fail(error,"invalid schema or content header");
    for(int i=0;i<days;++i) {
        const QString prefix=QString("day%1/").arg(i,3,10,QChar('0'));LocalDay day;
        day.date=fields.date(prefix+"date");day.startEpoch=fields.number(prefix+"startEpoch",MinEpoch,MaxEpoch-1);day.endEpoch=fields.number(prefix+"endEpoch",MinEpoch,MaxEpoch-1);
        if(day.endEpoch-day.startEpoch<20*3600 || day.endEpoch-day.startEpoch>28*3600 || (i && (day.date!=content.localDays.last().date.addDays(1) || day.startEpoch!=content.localDays.last().endEpoch))) return fail(error,"noncontiguous local day table");
        content.localDays.append(day);
    }
    QSet<QString> ids;
    for(int i=0;i<count;++i) {
        const QString prefix=QString("event%1/").arg(i,3,10,QChar('0'));Event event;
        event.id=fields.text(prefix+"id",false);event.summary=fields.text(prefix+"summary");event.location=fields.text(prefix+"location");
        event.start.epoch=fields.number(prefix+"startEpoch",MinEpoch,MaxEpoch-1);event.end.epoch=fields.number(prefix+"endEpoch",MinEpoch,MaxEpoch-1);
        event.start.localDate=fields.date(prefix+"startDate");event.end.localDate=fields.date(prefix+"endDate");
        event.start.utcOffsetSeconds=fields.number(prefix+"startUtcOffsetSeconds",-50400,50400);event.end.utcOffsetSeconds=fields.number(prefix+"endUtcOffsetSeconds",-50400,50400);
        event.start.display=fields.text(prefix+"startDisplay",false);event.end.display=fields.text(prefix+"endDisplay");event.allDay=fields.number(prefix+"allDay",0,1)==1;
        if(!fields.ok || ids.contains(event.id) || event.end.epoch<=event.start.epoch || !validEndpoint(content,event.start) || !validEndpoint(content,event.end) || (event.allDay && (event.end.localDate<=event.start.localDate || !atMidnight(event.start) || !atMidnight(event.end)))) return fail(error,"invalid event");
        ids.insert(event.id);content.events.append(event);
    }
    // Complete key equality proves each required group exists. Counting unique
    // headers also catches empty extra groups without depending on permissive
    // QSettings section handling.
    if(!fields.ok || fields.settings.status()!=QSettings::NoError || fields.read!=keys || sections.size()!=3+days+count) return fail(error,"missing or unexpected INI fields");
    // Inspect dimensions before invoking a decoder, bounding decoded allocation.
    if(image.size()<33 || image.left(8)!=QByteArray("\x89PNG\r\n\x1a\n",8) || image.mid(8,8)!=QByteArray("\0\0\0\x0dIHDR",8) || image.mid(16,8)!=QByteArray("\0\0\x01\xe0\0\0\x03\x20",8)) return fail(error,"PNG must be 480x800");
    const QImage decoded=QImage::fromData(image,"PNG");
    if(decoded.isNull() || decoded.width()!=480 || decoded.height()!=800) return fail(error,"PNG decode failed");
    content.background=QFileInfo(dir.filePath(background)).canonicalFilePath();
    *out=content;if(error) error->clear();return true;
}

QDate localDateAtEpoch(const Content &content,qint64 epoch) {
    for(int i=0;i<content.localDays.size();++i) {
        const LocalDay &day=content.localDays[i];if(epoch>=day.startEpoch && epoch<day.endEpoch) return day.date;
    }
    return QDate();
}
QList<Event> selectUpcomingEvents(const Content &content,qint64 now,const QDate &today) {
    QList<Event> result;if(!today.isValid() || localDateAtEpoch(content,now)!=today) return result;
    for(int i=0;i<content.events.size();++i)
        if(content.events[i].end.epoch>now)result.append(content.events[i]);
    qSort(result.begin(),result.end(),Earlier(now));
    return result.mid(0,5);
}
// BOOTTIME includes Linux suspend, retaining only this process boot's authenticated epoch.
// Failure is not replaced with RTC, wall time or cached generatedAt.
static qint64 contentBootTimeMs() {
#ifndef CLOCK_BOOTTIME
#define CLOCK_BOOTTIME 7
#endif
    struct timespec value;
    if(::clock_gettime(clockid_t(CLOCK_BOOTTIME),&value)||value.tv_sec<0||value.tv_nsec<0||value.tv_nsec>=1000000000||qint64(value.tv_sec)>0x7fffffffffffffffLL/1000-1)return -1;
    return qint64(value.tv_sec)*1000+value.tv_nsec/1000000;
}
bool TimeAnchor::establish(qint64 epoch) {
    invalidate();if(epoch<MinEpoch||epoch>=MaxEpoch)return false;
    qint64 boot=contentBootTimeMs();if(boot<0)return false;
    serverEpoch_=epoch;bootAtMs_=boot;return true;
}
void TimeAnchor::invalidate() { serverEpoch_=0;bootAtMs_=-1; }
bool TimeAnchor::nowEpoch(qint64 *out) const {
    if(!out||bootAtMs_<0||serverEpoch_<MinEpoch||serverEpoch_>=MaxEpoch)return false;
    qint64 boot=contentBootTimeMs();if(boot<bootAtMs_)return false;
    qint64 delta=(boot-bootAtMs_)/1000;
    if(delta>=MaxEpoch-serverEpoch_)return false;
    *out=serverEpoch_+delta;return true;
}
