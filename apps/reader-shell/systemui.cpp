#include "shell.h"
#include <QtGui/qpainter.h>
#include <QtGui/qpainterpath.h>
#include <QtGui/qfontmetrics.h>
#include <QtCore/qstringlist.h>

namespace {
QString uiText(const char *s) { return QString::fromUtf8(s); }
QFont uiFont(const QFont &base,int pixels,bool bold=false) {
    QFont f(base);f.setPixelSize(pixels);f.setBold(bold);return f;
}
QString uiWeekday(const QDate &date,bool shortName=false) {
    const char *full[]={"星期一","星期二","星期三","星期四","星期五","星期六","星期日"};
    const char *brief[]={"周一","周二","周三","周四","周五","周六","周日"};
    return date.isValid()?uiText(shortName?brief[date.dayOfWeek()-1]:full[date.dayOfWeek()-1]):QString();
}
void uiLine(QPainter &p,int y) {
    p.save();p.setPen(QPen(QColor(165,165,165),1));p.drawLine(24,y,456,y);p.restore();
}
void uiLabel(QPainter &p,const QRect &r,const QString &value,int flags=Qt::AlignLeft|Qt::AlignVCenter) {
    p.drawText(r,flags,value);
}
// Explicit line layout also handles long unspaced Chinese titles on Qt 4.
QStringList uiWrapped(const QString &raw,const QFont &font,int width,int limit) {
    QString value=raw.simplified();QStringList lines;QFontMetrics fm(font);
    while(!value.isEmpty() && lines.size()<limit) {
        int take=0;
        while(take<value.size() && fm.width(value.left(take+1))<=width)++take;
        take=qMax(1,take);
        if(take<value.size() && take>0 && value.at(take-1).isHighSurrogate())--take;
        take=qMax(1,take);
        if(lines.size()==limit-1 && take<value.size()) {
            lines.append(fm.elidedText(value,Qt::ElideRight,width));break;
        }
        lines.append(value.left(take));value=value.mid(take).trimmed();
    }
    if(lines.isEmpty())lines.append(QString());return lines;
}
int uiTitle(QPainter &p,const QFont &base,const QString &raw,int top,int maxLines,int pixels=32) {
    p.setFont(uiFont(base,pixels,true));
    QString value=raw.simplified();if(value.isEmpty())value=uiText("未命名日程");
    QStringList lines=uiWrapped(value,p.font(),432,maxLines);
    for(int i=0;i<lines.size();++i)uiLabel(p,QRect(24,top+i*44,432,44),lines[i]);
    return lines.size()*44;
}
QString uiClockAt(const EventTime &time) {
    // Manager endpoint offsets describe this exact instant, including DST.
    // Convert explicitly as UTC after applying that offset; never consult RTC.
    const qint64 local=time.epoch+time.utcOffsetSeconds;
    if(time.epoch>0&&local>=0&&local<=qint64(0xffffffffU))
        return QDateTime::fromTime_t(uint(local)).toUTC().toString("HH:mm");
    // Manually constructed fixtures may lack an epoch. Remove only an exact
    // matching endpoint-date prefix followed by whitespace, never arbitrary text.
    QString value=time.display.trimmed();
    if(time.localDate.isValid()) {
        const QString prefixes[]={time.localDate.toString("yyyy-MM-dd"),time.localDate.toString("MM-dd")};
        for(int i=0;i<2;++i)if(value.startsWith(prefixes[i])&&value.size()>prefixes[i].size()&&value.at(prefixes[i].size()).isSpace()) {
            value=value.mid(prefixes[i].size()).trimmed();break;
        }
    }
    return value;
}
QString uiWhen(const Event &event,const QDate &today) {
    QString when=event.allDay?uiText("全天"):uiClockAt(event.start);
    if(!event.allDay) {
        QString end=uiClockAt(event.end);
        if(!end.isEmpty()) {
            if(event.end.localDate.isValid()&&event.end.localDate!=event.start.localDate)
                end=event.end.localDate.toString("MM-dd")+" "+end;
            when+=uiText("—")+end;
        }
    }
    if(event.start.localDate!=today && event.start.localDate.isValid())
        when=event.start.localDate.toString(uiText("M月d日"))+"  "+when;
    if(event.allDay && event.end.localDate.isValid() && event.start.localDate.daysTo(event.end.localDate)>1)
        when+=uiText(" · 至 ")+event.end.localDate.addDays(-1).toString(uiText("M月d日"));
    return when;
}
void uiEventTime(QPainter &p,const QFont &base,const Event &event,const QDate &today,int top,int pixels=28) {
    p.setFont(uiFont(base,pixels));
    uiLabel(p,QRect(24,top,432,40),uiWhen(event,today));
}
void uiLocation(QPainter &p,const QFont &base,const Event &event,int top) {
    if(event.location.simplified().isEmpty())return;
    p.setFont(uiFont(base,24));
    uiLabel(p,QRect(24,top,432,32),QFontMetrics(p.font()).elidedText(event.location.simplified(),Qt::ElideRight,432));
}
// Five 96 px rows fit between the home summary and its fixed footer.
// A second title line takes priority over optional location metadata.
void uiCompactEvent(QPainter &p,const QFont &base,const Event &event,const QDate &today,int top) {
    p.save();p.setClipRect(QRect(24,top,432,92),Qt::IntersectClip);p.setPen(Qt::black);
    p.setFont(uiFont(base,22));uiLabel(p,QRect(24,top,432,26),uiWhen(event,today));
    p.setFont(uiFont(base,28,true));
    QString title=event.summary.simplified();if(title.isEmpty())title=uiText("未命名日程");
    QStringList lines=uiWrapped(title,p.font(),432,2);
    for(int line=0;line<lines.size();++line)uiLabel(p,QRect(24,top+26+line*32,432,32),lines[line]);
    if(lines.size()==1&&!event.location.simplified().isEmpty()) {
        p.setFont(uiFont(base,22));
        uiLabel(p,QRect(24,top+60,432,26),QFontMetrics(p.font()).elidedText(event.location.simplified(),Qt::ElideRight,432));
    }
    p.restore();
}
// The illustration is decorative only. Status and every event remain live UI.
void uiLandscapeBase(QPainter &p,const QImage &image){
    p.save();p.setClipRect(QRect(0,40,480,760),Qt::IntersectClip);p.fillRect(QRect(0,40,480,760),Qt::white);
    if(image.size()==QSize(480,800))p.drawImage(0,0,image);p.restore();
}
QString uiAgendaCaption(bool configured,bool trusted,bool stale,const QList<Event> &events,const QDate &date,int maximum){
    if(!configured)return uiText("等待日历同步");
    if(stale)return uiText("同步失败 · 缓存");
    if(!trusted)return uiText("缓存日程");
    for(int i=0;i<qMin(maximum,events.size());++i)if(events[i].start.localDate>date)return uiText("接下来安排");
    return uiText("今日安排");
}
void uiLandscapeHeader(QPainter &p,const QFont &base,const QDate &date,const QString &caption){
    p.setPen(Qt::black);p.setFont(uiFont(base,44));
    uiLabel(p,QRect(28,64,308,60),date.isValid()?date.toString(uiText("M月d日")):uiText("日程"));
    p.setFont(uiFont(base,24));uiLabel(p,QRect(30,132,96,32),uiWeekday(date));
    p.setFont(uiFont(base,18));p.setPen(QColor(64,64,64));uiLabel(p,QRect(128,134,208,28),caption);
}
void uiTimelineTime(QPainter &p,const QFont &base,const Event &event,const QDate &date,int top){
    int y=top;
    if(event.start.localDate.isValid()&&event.start.localDate!=date){
        p.setFont(uiFont(base,18));uiLabel(p,QRect(44,y,76,20),event.start.localDate.toString("MM-dd"));y+=20;
    }
    p.setFont(uiFont(base,22));
    const QString start=event.allDay?uiText("全天"):uiClockAt(event.start);
    uiLabel(p,QRect(44,y,76,24),start.isEmpty()?QString("--:--"):start);y+=24;
    if(event.allDay){
        if(event.start.localDate.isValid()&&event.end.localDate.isValid()&&event.start.localDate.daysTo(event.end.localDate)>1){
            p.setFont(uiFont(base,18));uiLabel(p,QRect(44,y,76,24),uiText("至")+event.end.localDate.addDays(-1).toString("MM-dd"));
        }
    }else{
        const QString end=uiClockAt(event.end);
        if(!end.isEmpty()){
            if(event.end.localDate.isValid()&&event.end.localDate!=event.start.localDate){
                p.setFont(uiFont(base,18));uiLabel(p,QRect(44,y,76,20),event.end.localDate.toString("MM-dd"));y+=20;
            }
            p.setFont(uiFont(base,22));uiLabel(p,QRect(44,y,76,24),QString("-")+end);
        }
    }
}
void uiTimelineEvents(QPainter &p,const QFont &base,const QList<Event> &events,const QDate &date,int maximum,int top,int step,int bottom){
    const int shown=qMin(maximum,events.size());if(!shown)return;
    p.save();p.setClipRect(QRect(24,top,312,bottom-top+1),Qt::IntersectClip);
    const int lineEnd=qMin(bottom,top+(shown-1)*step+qMin(step-4,88));
    p.setPen(QPen(QColor(88,88,88),1));p.drawLine(28,top+6,28,lineEnd);
    for(int i=0;i<shown;++i){
        const Event &event=events[i];const int y=top+i*step;
        p.setPen(Qt::NoPen);p.setBrush(QColor(48,48,48));p.drawEllipse(QPointF(28,y+12),3,3);
        p.save();p.setClipRect(QRect(40,y,296,step-4),Qt::IntersectClip);p.setPen(QColor(34,34,34));
        uiTimelineTime(p,base,event,date,y);
        QFont titleFont=uiFont(base,24);titleFont.setWeight(QFont::DemiBold);p.setFont(titleFont);
        QString title=event.summary.simplified();if(title.isEmpty())title=uiText("未命名日程");
        const QStringList lines=uiWrapped(title,p.font(),208,2);
        for(int line=0;line<lines.size();++line)uiLabel(p,QRect(128,y+line*32,208,32),lines[line]);
        if(!event.location.simplified().isEmpty()){
            p.setFont(uiFont(base,18));p.setPen(QColor(56,56,56));
            uiLabel(p,QRect(128,y+lines.size()*32,208,24),QFontMetrics(p.font()).elidedText(event.location.simplified(),Qt::ElideRight,208));
        }
        p.restore();
    }
    p.restore();
}
void uiLandscapeEmpty(QPainter &p,const QFont &base,bool configured,bool trusted,bool standby=false){
    p.setPen(QColor(34,34,34));p.setFont(uiFont(base,24));
    const QString message=!configured?uiText("尚未同步日历"):!trusted?uiText("缓存中暂无日程"):uiText("近期暂无日程");
    uiLabel(p,QRect(128,254,208,80),message,Qt::AlignLeft|Qt::AlignVCenter|Qt::TextWordWrap);
    p.setFont(uiFont(base,18));p.setPen(QColor(64,64,64));
    const QString hint=standby?uiText("短按电源键返回首页后同步"):!configured?uiText("下拉顶部连接网络并同步"):!trusted?uiText("同步后可确认当前时间与安排"):uiText("新的安排会在同步后显示");
    uiLabel(p,QRect(128,346,208,88),hint,Qt::AlignLeft|Qt::AlignTop|Qt::TextWordWrap);
}
enum UiIcon { CalendarIcon,BookIcon,NoteIcon,SlidersIcon,ChartIcon,WifiIcon,SyncIcon,RefreshIcon,GearIcon,GridIcon };
// Every icon is a 40 px vector glyph; callers scale the same stroke vocabulary.
void uiIcon(QPainter &p,UiIcon icon,const QRectF &box,const QColor &color=Qt::black) {
    p.save();p.setRenderHint(QPainter::Antialiasing,true);
    p.translate(box.left(),box.top());p.scale(box.width()/40.0,box.height()/40.0);
    p.setPen(QPen(color,2.8,Qt::SolidLine,Qt::RoundCap,Qt::RoundJoin));p.setBrush(Qt::NoBrush);
    QPainterPath a;
    if(icon==CalendarIcon) {
        p.drawRoundedRect(QRectF(5,8,30,28),1,1);p.drawLine(5,16,35,16);p.drawLine(12,3,12,12);p.drawLine(28,3,28,12);
        p.setPen(Qt::NoPen);p.setBrush(color);for(int row=0;row<2;++row)for(int col=0;col<2;++col)p.drawRect(QRectF(12+12*col,22+8*row,3,3));
    } else if(icon==BookIcon) {
        a.moveTo(20,10);a.cubicTo(14,6,8,5,3,6);a.lineTo(3,33);a.cubicTo(9,32,15,33,20,37);a.cubicTo(25,33,31,32,37,33);a.lineTo(37,6);a.cubicTo(32,5,26,6,20,10);a.lineTo(20,37);p.drawPath(a);
        p.drawLine(8,13,14,15);p.drawLine(26,15,32,13);
    } else if(icon==NoteIcon) {
        p.drawRoundedRect(QRectF(7,4,26,32),1,1);p.drawLine(12,13,28,13);p.drawLine(12,21,28,21);p.drawLine(12,29,21,29);
    } else if(icon==SlidersIcon) {
        p.drawLine(8,4,8,36);p.drawLine(20,4,20,36);p.drawLine(32,4,32,36);
        p.setBrush(color);p.drawEllipse(QPointF(8,12),3,3);p.drawEllipse(QPointF(20,28),3,3);p.drawEllipse(QPointF(32,17),3,3);
    } else if(icon==ChartIcon) {
        p.drawLine(4,4,4,36);p.drawLine(4,36,37,36);a.moveTo(11,28);a.lineTo(18,19);a.lineTo(25,23);a.lineTo(35,8);p.drawPath(a);
    } else if(icon==WifiIcon) {
        a.moveTo(4,12);a.cubicTo(13,4,27,4,36,12);a.moveTo(10,19);a.cubicTo(16,13,24,13,30,19);a.moveTo(16,26);a.cubicTo(18,24,22,24,24,26);p.drawPath(a);p.setPen(Qt::NoPen);p.setBrush(color);p.drawEllipse(QPointF(20,33),1.7,1.7);
    } else if(icon==SyncIcon) {
        a.moveTo(8,15);a.cubicTo(13,4,27,4,32,15);a.lineTo(36,9);a.moveTo(32,15);a.lineTo(26,14);
        a.moveTo(32,25);a.cubicTo(27,36,13,36,8,25);a.lineTo(4,31);a.moveTo(8,25);a.lineTo(14,26);p.drawPath(a);
    } else if(icon==RefreshIcon) {
        p.drawRoundedRect(QRectF(6,6,28,28),1,1);a.moveTo(24,13);a.cubicTo(13,8,10,26,21,27);a.cubicTo(25,27,27,24,27,22);a.moveTo(24,13);a.lineTo(24,19);a.moveTo(24,13);a.lineTo(18,13);p.drawPath(a);
    } else if(icon==GearIcon) {
        // Fixed outline avoids adding a libm dependency to the vendor ABI.
        static const float points[48][2]={
            {20.0,6.5},{22.22,3.15},{24.4,3.58},{26.51,4.29},{26.75,8.31},{28.22,9.29},
            {29.55,10.45},{33.49,9.65},{34.72,11.5},{35.71,13.49},{33.04,16.51},{33.38,18.24},
            {33.5,20.0},{36.85,22.22},{36.42,24.4},{35.71,26.51},{31.69,26.75},{30.71,28.22},
            {29.55,29.55},{30.35,33.49},{28.5,34.72},{26.51,35.71},{23.49,33.04},{21.76,33.38},
            {20.0,33.5},{17.78,36.85},{15.6,36.42},{13.49,35.71},{13.25,31.69},{11.78,30.71},
            {10.45,29.55},{6.51,30.35},{5.28,28.5},{4.29,26.51},{6.96,23.49},{6.62,21.76},
            {6.5,20.0},{3.15,17.78},{3.58,15.6},{4.29,13.49},{8.31,13.25},{9.29,11.78},
            {10.45,10.45},{9.65,6.51},{11.5,5.28},{13.49,4.29},{16.51,6.96},{18.24,6.62}
        };
        for(int i=0;i<48;++i) {
            const QPointF point(points[i][0],points[i][1]);
            if(i==0)a.moveTo(point);else a.lineTo(point);
        }
        a.closeSubpath();p.drawPath(a);p.drawEllipse(QPointF(20,20),5.3,5.3);
    } else {
        for(int row=0;row<2;++row)for(int col=0;col<2;++col)p.drawRoundedRect(QRectF(5+18*col,5+18*row,10,10),2,2);
    }
    p.restore();
}
void uiChevron(QPainter &p,const QPointF &center,bool up,int size,const QColor &color=Qt::black) {
    p.save();p.setRenderHint(QPainter::Antialiasing,true);p.setPen(QPen(color,1.6,Qt::SolidLine,Qt::RoundCap,Qt::RoundJoin));
    QPainterPath path;path.moveTo(center.x()-size/2.0,center.y()+(up?size/4.0:-size/4.0));path.lineTo(center.x(),center.y()+(up?-size/4.0:size/4.0));path.lineTo(center.x()+size/2.0,center.y()+(up?size/4.0:-size/4.0));p.drawPath(path);p.restore();
}
void uiTile(QPainter &p,const QFont &base,const QRect &rect,UiIcon icon,const QString &label,const QString &subtitle,bool active=false) {
    p.save();p.setPen(QPen(Qt::black,2,Qt::SolidLine));p.setBrush(active?QColor(187,187,187):Qt::white);p.drawRoundedRect(QRectF(rect).adjusted(.75,.75,-.75,-.75),16,16);
    QColor ink(34,34,34);uiIcon(p,icon,QRectF(rect.x()+16,rect.y()+30,28,28),ink);
    p.setPen(ink);p.setFont(uiFont(base,28,true));uiLabel(p,QRect(rect.x()+60,rect.y()+8,rect.width()-68,36),label);
    p.setFont(uiFont(base,24));uiLabel(p,QRect(rect.x()+60,rect.y()+48,rect.width()-68,32),subtitle);p.restore();
}
}

void ReaderShell::drawHome(QPainter &p) {
    p.save();uiLandscapeBase(p,landscapeBackground_);
    const QDate date=displayDate();qint64 now=0;
    const bool trusted=anchor_.nowEpoch(&now)&&localDateAtEpoch(content_,now).isValid();
    const QList<Event> events=homeEvents();
    p.save();p.setClipRect(QRect(0,40,350,656),Qt::IntersectClip);
    uiLandscapeHeader(p,font(),date,uiAgendaCaption(content_.schema==1,trusted,syncFailed_,events,date,5));
    if(events.isEmpty())uiLandscapeEmpty(p,font(),content_.schema==1,trusted);
    else uiTimelineEvents(p,font(),events,date,5,208,92,668);
    p.restore();
    uiIcon(p,SyncIcon,QRectF(28,741,22,22),QColor(64,64,64));p.setPen(QColor(56,56,56));p.setFont(uiFont(font(),18));
    uiLabel(p,QRect(60,724,220,56),compactSyncStatus(),Qt::AlignLeft|Qt::AlignVCenter|Qt::TextWordWrap);
    // Compact visual entry; the 112x56 touch target stays clear of sync.
    p.setPen(QPen(Qt::black,1,Qt::SolidLine));p.setBrush(Qt::white);p.drawRoundedRect(QRect(352,728,104,48),12,12);
    uiIcon(p,GridIcon,QRectF(368,742,20,20),QColor(34,34,34));p.setPen(QColor(34,34,34));p.setFont(uiFont(font(),22));uiLabel(p,QRect(396,738,48,28),uiText("应用"));p.restore();
}

void ReaderShell::drawPanel(QPainter &p) {
    p.save();p.fillRect(QRect(0,40,480,760),Qt::white);p.setPen(Qt::black);
    QPainterPath back;back.moveTo(44,66);back.lineTo(35,76);back.lineTo(44,86);p.setPen(QPen(Qt::black,1.8,Qt::SolidLine,Qt::RoundCap,Qt::RoundJoin));p.drawPath(back);
    p.setFont(uiFont(font(),32,true));uiLabel(p,QRect(80,52,248,52),uiText("应用"));p.setFont(uiFont(font(),24));uiLabel(p,QRect(360,60,96,40),uiText("5 项"),Qt::AlignRight|Qt::AlignVCenter);
    uiLabel(p,QRect(24,132,432,40),uiText("常用应用"));
    const char *labels[]={"日程","单词卡","阅读笔记","设备控制","信息看板"};
    for(int i=0;i<5;++i) {
        const int x=24+(i%2)*224,y=184+(i/2)*168;
        p.setPen(QPen(QColor(187,187,187),1));p.setBrush(QColor(204,204,204));p.drawRoundedRect(QRect(x+68,y+16,72,72),24,24);
        uiIcon(p,UiIcon(i),QRectF(x+84,y+32,40,40),QColor(34,34,34));
        p.setPen(Qt::black);p.setFont(uiFont(font(),28,true));uiLabel(p,QRect(x,y+104,208,40),uiText(labels[i]),Qt::AlignCenter);
    }
    p.restore();
}

void ReaderShell::drawStatusBar(QPainter &p) {
    p.save();p.setClipRect(QRect(0,0,480,40));p.fillRect(QRect(0,0,480,40),Qt::white);p.setPen(Qt::black);p.setFont(uiFont(font(),24,true));
    QString clock=displayClock();if(clock.size()!=5 || clock.at(2)!=QChar(':'))clock="--:--";
    uiLabel(p,QRect(24,3,144,32),clock);if(otaOffered_){p.setFont(uiFont(font(),15));uiLabel(p,QRect(172,6,46,28),uiText("更新"));}uiChevron(p,QPointF(240,19),false,10);
    uiIcon(p,WifiIcon,QRectF(328,8,24,24));
    if(!wifiLinked_) {p.setPen(QPen(Qt::black,1.5));p.drawLine(330,9,350,31);}
    p.setPen(QPen(Qt::black,1.5));p.setBrush(Qt::NoBrush);p.drawRoundedRect(QRectF(358,13,28,14),2,2);p.drawLine(389,17,389,23);
    const int percent=batteryPercent_<0?-1:qMin(100,batteryPercent_);
    if(percent>=0) {p.setPen(Qt::NoPen);p.setBrush(Qt::black);p.drawRect(QRectF(361,16,22*percent/100.0,8));}
    if(batteryCharging_) {
        QPainterPath bolt;bolt.moveTo(375,12);bolt.lineTo(369,21);bolt.lineTo(374,21);bolt.lineTo(370,29);
        p.setPen(QPen(Qt::white,4,Qt::SolidLine,Qt::RoundCap,Qt::RoundJoin));p.drawPath(bolt);p.setPen(QPen(Qt::black,1.5,Qt::SolidLine,Qt::RoundCap,Qt::RoundJoin));p.drawPath(bolt);
    }
    p.setPen(Qt::black);p.setFont(uiFont(font(),batteryEstimated_?20:24));uiLabel(p,QRect(392,3,64,32),percent<0?QString("--"):QString::number(percent)+"%",Qt::AlignRight|Qt::AlignVCenter);p.restore();
}

void ReaderShell::drawSystemPanel(QPainter &p) {
    p.save();p.setClipRect(QRect(0,40,480,360));p.fillRect(QRect(0,40,480,360),Qt::white);p.setPen(Qt::black);
    p.setFont(uiFont(font(),28,true));uiLabel(p,QRect(24,56,200,32),uiText("快捷控制"));
    const QDate date=displayDate();p.setFont(uiFont(font(),24));
    uiLabel(p,QRect(240,56,216,32),date.isValid()?date.toString(uiText("M月d日 "))+uiWeekday(date,true):uiText("日期待同步"),Qt::AlignRight|Qt::AlignVCenter);
    QString network=systemWifiStatus();if(wifiLinked_ && !radioReply_.wifiSsid.isEmpty())network=radioReply_.wifiSsid+uiText(" · ")+network;
    uiLabel(p,QRect(24,88,216,32),QFontMetrics(p.font()).elidedText(network,Qt::ElideRight,216));
    uiLabel(p,QRect(248,88,208,32),compactSyncStatus(),Qt::AlignRight|Qt::AlignVCenter);
    uiTile(p,font(),QRect(24,136,208,88),WifiIcon,QString("Wi-Fi"),systemWifiStatus(),wifiLinked_);
    QString sync=quickSyncPending_?uiText("同步中"):syncFailed_?uiText("同步失败"):content_.schema!=1?uiText("尚未同步"):uiText("点击同步");
    uiTile(p,font(),QRect(248,136,208,88),SyncIcon,uiText("同步内容"),sync);
    uiTile(p,font(),QRect(24,240,208,88),RefreshIcon,uiText("刷新屏幕"),uiText("清除残影"));
    uiTile(p,font(),QRect(248,240,208,88),GearIcon,uiText("系统设置"),uiText("更多选项"));
    p.setPen(Qt::black);p.setFont(uiFont(font(),24));
    if(!quickMessage_.isEmpty()) {
        // The action layer supplies a short complete result; never elide errors.
        uiLabel(p,QRect(24,336,432,32),quickMessage_,Qt::AlignCenter);uiChevron(p,QPointF(210,383),true,18);uiLabel(p,QRect(236,368,96,32),uiText("收起"));
    } else {uiChevron(p,QPointF(210,368),true,18);uiLabel(p,QRect(236,352,96,32),uiText("收起"));}
    p.setPen(QPen(Qt::black,1.5));p.drawLine(0,399,480,399);p.restore();
}

// Static, touch-locked agenda snapshot; only the caller decides when to paint.
void ReaderShell::drawStandbyAgenda(QPainter &p){
    p.save();uiLandscapeBase(p,landscapeBackground_);
    const QDate date=displayDate();qint64 now=0;const bool trusted=anchor_.nowEpoch(&now)&&localDateAtEpoch(content_,now).isValid();
    const QList<Event> events=homeEvents();
    p.save();p.setClipRect(QRect(0,40,350,656),Qt::IntersectClip);
    const QString caption=powerMessage_.isEmpty()?uiAgendaCaption(content_.schema==1,trusted,syncFailed_,events,date,3):QString();
    uiLandscapeHeader(p,font(),date,caption);
    if(powerMessage_.isEmpty()){
        p.setPen(QColor(64,64,64));p.setFont(uiFont(font(),16));uiLabel(p,QRect(128,174,208,24),compactSyncStatus());
    }else{
        p.setPen(Qt::black);p.setFont(uiFont(font(),22,true));uiLabel(p,QRect(28,164,308,52),powerMessage_,Qt::AlignLeft|Qt::AlignVCenter|Qt::TextWordWrap);
    }
    if(events.isEmpty())uiLandscapeEmpty(p,font(),content_.schema==1,trusted,true);
    else uiTimelineEvents(p,font(),events,date,3,222,116,570);
    p.restore();p.setPen(QColor(80,80,80));p.setFont(uiFont(font(),16));
    uiLabel(p,QRect(28,752,308,28),uiText("PandaNote · 待机"));p.restore();
}
