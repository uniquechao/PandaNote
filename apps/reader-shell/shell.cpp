#include "shell.h"
#include "battery.h"
#include <stdio.h>
#include "build-support/qws-cursor.h"
#include <QtGui/qpainter.h>
#include <QtGui/qevent.h>
#include <QtGui/qapplication.h>
#include <QtGui/qcursor.h>
#include <QtGui/qfontdatabase.h>
#include <QtGui/qfontmetrics.h>
#include <QtCore/qcoreapplication.h>
#include <QtCore/qfileinfo.h>
#include <QtCore/qstringlist.h>
#include <QtCore/qdir.h>
#include <QtCore/qfile.h>
static QString text(const char *s) { return QString::fromUtf8(s); }
static QString localError(const QString &code){
 if(code=="workspace-unconfigured")return text("未配置可写工作目录");
 if(code=="workspace-limit-or-permissions")return text("目录权限已改变，或内容超过容量限制");
 if(code=="workspace-unsafe-file")return text("已有文件类型或权限不符合要求");
 if(code=="workspace-create")return text("无法创建保存文件，请检查空间与残留临时文件");
 if(code=="workspace-durability-uncertain")return text("新内容已替换，但未确认落盘；请保留草稿并重启检查");
 if(code=="workspace-write")return text("写入失败，原文件保留");
 if(code=="workspace-rename")return text("无法替换保存文件，原文件保留");
 if(code.startsWith("note")||code.startsWith("word"))return text("内容或数量超过限制，或记录已不存在");
 return text("无法打开安全的本地目录或数据文件");
}
static QString pageTitle(Page page) {
    const char *labels[]={"首页","应用","日程","单词卡","阅读笔记","设备设置","设备信息"};
    return text(labels[int(page)]);
}
static QFont typeface(const QFont &base,int pixels,bool bold=false) {
    QFont f(base);f.setPixelSize(pixels);f.setBold(bold);return f;
}
static QString weekday(const QDate &date) {
    const char *days[]={"星期一","星期二","星期三","星期四","星期五","星期六","星期日"};
    return date.isValid()?text(days[date.dayOfWeek()-1]):QString();
}
// Two bounded lines; no unbounded title can invade the following event.
static void titleLines(QPainter &p,const QRect &r,const QString &raw) {
    QString value=raw.simplified();if(value.isEmpty())value=text("未命名日程");
    QFontMetrics fm(p.font());int used=0;
    while(used<value.size() && fm.width(value.left(used+1))<=r.width())++used;
    if(used==0)used=1;
    p.drawText(QRect(r.x(),r.y(),r.width(),fm.height()+2),Qt::AlignLeft|Qt::AlignVCenter,value.left(used));
    if(used<value.size())p.drawText(QRect(r.x(),r.y()+fm.height()+2,r.width(),fm.height()+2),Qt::AlignLeft|Qt::AlignVCenter,fm.elidedText(value.mid(used),Qt::ElideRight,r.width()));
}
ReaderShell::ReaderShell(const Content &content,QWidget *parent,RadioClient *radio):QWidget(parent),otaTimer_(0),otaPaintCount_(0),otaLocked_(false),otaOffered_(false),otaDeferred_(false),otaPreparing_(false),otaSyncBusy_(false),otaProgress_(false),otaPressPrompt_(false),otaPrepareAt_(-1),standby_(false),shutdownPending_(false),touchGuardUntil_(0),wordIndex_(0),wordScroll_(0),localOffset_(0),noteOffset_(0),noteScroll_(0),wordBack_(false),wordList_(false),noteEditing_(false),noteDelete_(false),systemPanelOpen_(false),quickSyncPending_(false),pressSystem_(false),pressWasOpen_(false),systemReturnActive_(false),batteryCharging_(false),batteryEstimated_(false),batteryChargingKnown_(false),fullRefreshAllowedAt_(0),batteryPercent_(-1),batteryVoltageMv_(-1),systemReturnInput_(-1),systemReturnPage_(Home),fontReady_(false),syncFailed_(false),pressActive_(false),pressPage_(Home),idleTimer_(0),scheduleOffset_(0),press_(-1,-1),radio_(radio?radio:&ownedRadio_),wifiOffset_(0),wifiPressOffset_(0),wifiSwipe_(false),wifiListGesture_(false),wifiDialog_(false),wifiNetworkInfo_(false),wifiScanPending_(false),radioTimer_(0),wifiStatusTimer_(0),wifiStatusDeadline_(0),wifiLinked_(false),wifiSyncLinked_(false),settingsTab_(0),inputField_(-1),keyboardMode_(0),selectedWifi_(-1),selectedBluetooth_(-1),uppercase_(false) {
    if(QApplication::overrideCursor())QApplication::changeOverrideCursor(QCursor(Qt::BlankCursor));
    else QApplication::setOverrideCursor(QCursor(Qt::BlankCursor));
    // QApplication has initialized QWS; global visibility is independent of
    // the widget/desktop cursor shape selected by setOverrideCursor().
#if QT_VERSION < QT_VERSION_CHECK(5,0,0)
    if(QApplication::type()==QApplication::GuiServer)pandanoteQwsSetCursorVisible(false);
#endif
    setCursor(QCursor(Qt::BlankCursor));
    setFixedSize(480,800);setAttribute(Qt::WA_OpaquePaintEvent);setFocusPolicy(Qt::StrongFocus);
    QString assets=QCoreApplication::applicationDirPath()+"/assets/";
    int id=QFontDatabase::addApplicationFont(assets+"wqy-microhei.ttc");
    QStringList families=QFontDatabase::applicationFontFamilies(id);
    fontReady_=id>=0 && !families.isEmpty();
    QFont f(fontReady_?families.first():QString("sans"));f.setPixelSize(24);setFont(f);
    // Decode the immutable landscape once; status-only paints never enter body drawing.
    landscapeBackground_=QImage(assets+"landscape-background.png");
    if(landscapeBackground_.size()!=QSize(480,800))landscapeBackground_=QImage();
    defaultBackground_=QImage(assets+"neutral-background.png");
    if(defaultBackground_.size()!=QSize(480,800)) { defaultBackground_=QImage(480,800,QImage::Format_RGB32);defaultBackground_.fill(0xffededed); }
    monotonic_.start();setContent(content);
}
void ReaderShell::setContent(const Content &content) {
    if(content_.schema==content.schema && content_.version==content.version && content_.background==content.background && !background_.isNull())return;
    content_=content;syncFailed_=false;scheduleOffset_=0;
    if(quickSyncPending_&&(systemPanelOpen_||(page()!=Home&&page()!=Schedule)))quickMessage_=text("内容已更新，回首页显示");
    QImage image(content.background);
    background_=(image.size()==QSize(480,800))?image:defaultBackground_;
    refreshTime();if(page()==Home||page()==Schedule)update();
}
bool ReaderShell::setTrustedTime(qint64 serverEpoch) { bool ok=anchor_.establish(serverEpoch);refreshTime();return ok; }
void ReaderShell::clearTrustedTime() { anchor_.invalidate();refreshTime(); }
void ReaderShell::setSyncFailed(bool failed) { if(syncFailed_!=failed) { syncFailed_=failed;refreshTime(); } }
QDate ReaderShell::displayDate() const {
    qint64 now=0;if(anchor_.nowEpoch(&now)) { QDate date=localDateAtEpoch(content_,now);if(date.isValid())return date; }
    return localDateAtEpoch(content_,content_.generatedAt);
}
QString ReaderShell::displayStatus() const {
    if(content_.schema!=1)return text("尚未同步日历");
    qint64 now=0;bool trusted=anchor_.nowEpoch(&now) && localDateAtEpoch(content_,now).isValid();
    QString prefix=syncFailed_?text("日历数据已过期"):(!trusted?text("缓存时间"):text("日历已同步"));
    // Snapshot display time comes from manager day metadata, never the reader RTC.
    QString stamp=QDateTime::fromTime_t(uint(content_.generatedAt)).toUTC().toString("MM-dd HH:mm");
    return prefix+text(" · 上次同步 ")+stamp+" UTC";
}
QList<Event> ReaderShell::homeEvents() const {
    qint64 now=0;
    if(!anchor_.nowEpoch(&now) || !localDateAtEpoch(content_,now).isValid())now=content_.generatedAt;
    return selectUpcomingEvents(content_,now,localDateAtEpoch(content_,now));
}
QString ReaderShell::homeMessage() const {
    if(content_.schema!=1)return text("尚未同步日历");
    if(homeEvents().isEmpty()) {
        qint64 now=0;
        if(!anchor_.nowEpoch(&now) || !localDateAtEpoch(content_,now).isValid())return text("缓存中暂无日程");
        return text("今天暂无日程");
    }
    return QString();
}
QString ReaderShell::agendaFingerprint(int maximum) const {
    QStringList fields;fields<<QString::number(content_.schema)<<content_.version<<displayDate().toString(Qt::ISODate)<<displayStatus()<<compactSyncStatus()<<homeMessage()<<powerMessage_;
    qint64 now=0;if(!anchor_.nowEpoch(&now)||!localDateAtEpoch(content_,now).isValid())now=content_.generatedAt;
    QList<Event> events=homeEvents();
    for(int i=0;i<qMin(maximum,events.size());++i){const Event &e=events[i];
        fields<<e.id<<e.summary<<e.location<<QString::number(e.allDay)<<QString::number(e.start.epoch)<<QString::number(e.end.epoch)<<QString::number(e.start.utcOffsetSeconds)<<QString::number(e.end.utcOffsetSeconds)<<e.start.localDate.toString(Qt::ISODate)<<e.end.localDate.toString(Qt::ISODate)<<e.start.display<<e.end.display<<QString::number(e.start.epoch<=now);
    }
    QString value;for(int i=0;i<fields.size();++i)value+=QString::fromLatin1(fields[i].toUtf8().toBase64())+'|';return value;
}
QString ReaderShell::statusFingerprint() const {
    return displayClock()+'|'+QString::number(batteryPercent_)+'|'+QString::number(batteryCharging_)+'|'+QString::number(batteryEstimated_)+'|'+QString::number(wifiLinked_);
}
void ReaderShell::refreshTime() {
    if(!otaTimer_)otaInitialize();
    bool batteryChanged=refreshBattery();QString clock=displayClock();bool clockChanged=clock!=statusClock_;statusClock_=clock;
    QString fingerprint=agendaFingerprint(5);
    bool changed=fingerprint!=fingerprint_;fingerprint_=fingerprint;
    if(changed&&(page()==Home||page()==Schedule))update();
    else if(changed&&systemPanelOpen_)update(QRect(0,0,480,400));
    else if(clockChanged||batteryChanged)update(QRect(0,0,480,40));
}
void ReaderShell::refreshStandbySnapshot(){
    if(!standby_||shutdownPending_)return;
    refreshTime();const QString body=agendaFingerprint(3),status=statusFingerprint();
    QRegion damage;if(body!=standbyFingerprint_)damage+=QRect(0,40,480,760);
    if(status!=standbyStatusFingerprint_)damage+=QRect(0,0,480,40);
    if(damage.isEmpty())return;
    // No updates-enable transition: it schedules an implicit full-widget paint.
    // One explicit synchronous paint lets Runtime safely await the paint ACK.
    QWidget::repaint(damage);
    standbyFingerprint_=body;standbyStatusFingerprint_=status;
}

void ReaderShell::drawButton(QPainter &p,const QRect &rect,const QString &label) {
    p.fillRect(rect,Qt::white);p.setPen(QPen(QColor(153,153,153),1.5));p.drawRect(rect.adjusted(1,1,-1,-1));p.setPen(Qt::black);
    p.setFont(typeface(font(),23));p.drawText(rect,Qt::AlignCenter,QFontMetrics(p.font()).elidedText(label,Qt::ElideRight,qMax(0,rect.width()-12)));
}
void ReaderShell::drawEvent(QPainter &p,const Event &event,const QRect &rect,bool showDate) {
    p.save();p.setClipRect(rect);p.setPen(Qt::black);p.setFont(typeface(font(),22));
    QString when=event.allDay?text("全天"):QDateTime::fromTime_t(uint(event.start.epoch+event.start.utcOffsetSeconds)).toUTC().toString("HH:mm");
    if(!event.allDay){
        QString end=QDateTime::fromTime_t(uint(event.end.epoch+event.end.utcOffsetSeconds)).toUTC().toString("HH:mm");
        if(event.end.localDate!=event.start.localDate)end=event.end.localDate.toString("MM-dd")+" "+end;
        when+=text("—")+end;
    }
    if(showDate)when=event.start.localDate.toString("MM-dd")+"  "+when;
    p.drawText(QRect(rect.x(),rect.y(),rect.width(),26),Qt::AlignLeft|Qt::AlignVCenter,QFontMetrics(p.font()).elidedText(when,Qt::ElideRight,rect.width()));
    p.setFont(typeface(font(),26,true));titleLines(p,QRect(rect.x(),rect.y()+28,rect.width(),64),event.summary);
    if(!event.location.simplified().isEmpty() && QFontMetrics(p.font()).width(event.summary.simplified())<=rect.width()) {
        p.setFont(typeface(font(),20));p.drawText(QRect(rect.x(),rect.y()+64,rect.width(),26),Qt::AlignLeft|Qt::AlignVCenter,QFontMetrics(p.font()).elidedText(event.location.simplified(),Qt::ElideRight,rect.width()));
    }
    p.restore();
}
void ReaderShell::drawSchedule(QPainter &p) {
    if(content_.schema!=1 || content_.events.isEmpty()) { p.setFont(typeface(font(),25));p.drawText(QRect(24,212,432,180),Qt::AlignCenter|Qt::TextWordWrap,homeMessage());return; }
    int shown=qMin(5,content_.events.size()-scheduleOffset_);
    for(int i=0;i<shown;++i) {
        QRect rect(24,120+i*116,432,108);drawEvent(p,content_.events[scheduleOffset_+i],rect,true);
        p.setPen(QColor(180,180,180));p.drawLine(24,rect.bottom()+4,456,rect.bottom()+4);
    }
    p.setPen(Qt::black);p.setFont(typeface(font(),18));
    p.drawText(QRect(24,746,432,30),Qt::AlignCenter,text("上下滑动翻阅")+QString("  %1-%2 / %3").arg(scheduleOffset_+1).arg(scheduleOffset_+shown).arg(content_.events.size()));
}
void ReaderShell::drawPlaceholder(QPainter &p) {
    p.setFont(typeface(font(),29,true));p.drawText(QRect(24,302,432,60),Qt::AlignCenter,text("功能准备中"));
    p.setFont(typeface(font(),21));p.drawText(QRect(24,380,432,38),Qt::AlignCenter,text("可返回应用面板"));
}
void ReaderShell::paintEvent(QPaintEvent *event) {
    QPainter p(this);p.fillRect(rect(),Qt::white);p.setPen(Qt::black);
    const bool body=event->region().intersects(QRect(0,40,480,760));
    if(!body){drawStatusBar(p);p.end();return;}
    if(standby_||shutdownPending_){
        drawPowerScreen(p);drawStatusBar(p);const bool painted=p.end();
        if(painted&&standby_&&!shutdownPending_&&content_.schema==1)contentPainted(content_.version);
        return;
    }
    if(page()==Home)drawHome(p);
    else if(page()==Panel)drawPanel(p);
    else {
        p.setPen(QPen(Qt::black,2));
        p.drawLine(44,62,30,76);p.drawLine(30,76,44,90);
        p.drawRect(423,69,26,22);p.drawLine(420,70,436,57);p.drawLine(436,57,452,70);
        p.setFont(typeface(font(),32,true));p.drawText(QRect(80,54,320,44),Qt::AlignLeft|Qt::AlignVCenter,pageTitle(page()));
        if(page()==Schedule)drawSchedule(p);else if(page()==Control)drawSettings(p);else if(page()==Info)drawInformation(p);else if(page()==Words)drawWords(p);else if(page()==Notes)drawNotes(p);else drawPlaceholder(p);
    }
    drawStatusBar(p);if(systemPanelOpen_)drawSystemPanel(p);
    if(!powerMessage_.isEmpty()){p.fillRect(QRect(24,112,432,80),Qt::white);p.setFont(typeface(font(),24,true));p.drawText(QRect(24,112,432,80),Qt::AlignCenter|Qt::TextWordWrap,powerMessage_);}
    drawOta(p);
    bool painted=p.end();if(painted)++otaPaintCount_;
    if(painted&&!systemPanelOpen_&&content_.schema==1&&(page()==Home||page()==Schedule))contentPainted(content_.version);
}
void ReaderShell::resetIdle() {
    if(idleTimer_) { killTimer(idleTimer_);idleTimer_=0; }
    if(page()!=Home&&!systemPanelOpen_&&!standby_&&!shutdownPending_) { idleDeadline_=monotonicMs()+60000;idleTimer_=startTimer(60000); }
}
void ReaderShell::applyAction(Action action,const char *source,int x,int y) {
    if(systemReturnActive_&&page()==Control&&action==BackToPanel) {
        Page from=page();navigation_.restore(systemReturnPage_,monotonicMs());systemReturnActive_=false;
        clearSecrets();if(page()==Notes&&noteEditing_&&systemReturnInput_==4)inputField_=4;
        cancelGesture();watchWifiStatus();resetIdle();navigationChanged(from,page(),"system-return",x,y);update();return;
    }
    if(page()==Notes&&noteEditing_&&(action==BackHome||action==BackToPanel)){localMessage_=text("请先保存或取消草稿");update();return;}
    Page from=page();navigation_.interact(action,monotonicMs());resetIdle();
    if(from!=page()) { if(page()==Notes&&!noteDraft_.isEmpty()){noteEditing_=true;}if(from==Control){systemReturnActive_=false;systemReturnInput_=-1;}clearSecrets();cancelGesture();if(page()==Schedule)scheduleOffset_=0;watchWifiStatus(page()==Control&&settingsTab_==0);navigationChanged(from,page(),source,x,y);update(); }
}
void ReaderShell::cancelGesture() { pressActive_=false;pressSystem_=false;wifiListGesture_=false;wifiSwipe_=false;press_=QPoint(-1,-1); }
void ReaderShell::mousePressEvent(QMouseEvent *event) {
    if(otaInput()||otaLocked_){cancelGesture();event->accept();return;}
    if(standby_||shutdownPending_||monotonicMs()<touchGuardUntil_){cancelGesture();event->accept();return;}
    if(event->button()==Qt::LeftButton && rect().contains(event->pos())) {
        otaPressAttempt_=otaAttempt_;otaPressGeneration_=otaGeneration_;otaPressPrompt_=otaPromptVisible();
        press_=event->pos();pressPage_=page();pressActive_=true;wifiSwipe_=false;wifiPressOffset_=wifiOffset_;wifiListGesture_=page()==Control&&settingsTab_==0&&!wifiDialog_&&!wifiNetworkInfo_&&QRect(16,342,448,348).contains(press_);
        pressSystem_=systemPanelOpen_||event->y()<40;pressWasOpen_=systemPanelOpen_;
        if(pressSystem_){wifiListGesture_=false;navigation_.interact(NoAction,monotonicMs());resetIdle();}
        else applyAction(NoAction,"press",event->x(),event->y());
    }
    event->accept();
}
void ReaderShell::scrollSchedule(int amount) {
    applyAction(NoAction,"wheel",-1,-1);
    int offset=qBound(0,scheduleOffset_+amount,qMax(0,content_.events.size()-5));
    if(offset!=scheduleOffset_) { scheduleOffset_=offset;update(); }
}
int ReaderShell::wifiRowAt(const QPoint &pos)const{
 if(!QRect(16,342,448,348).contains(pos))return -1;
 int row=(pos.y()-342)/58,index=wifiOffset_+row;
 return index<radioReply_.wifi.size()&&QRect(16,342+row*58,448,52).contains(pos)?index:-1;
}
bool ReaderShell::scrollWifiList(const QPoint &pos){
 if(!wifiListGesture_)return false;
 int dy=press_.y()-pos.y();if(qMax(qAbs(dy),qAbs(press_.x()-pos.x()))>=24)wifiSwipe_=true;
 if(!wifiSwipe_)return false;
 int offset=qBound(0,wifiPressOffset_+(dy>=0?(dy+29)/58:(dy-29)/58),qMax(0,radioReply_.wifi.size()-6));
 if(offset!=wifiOffset_){wifiOffset_=offset;update();}return true;
}
void ReaderShell::mouseMoveEvent(QMouseEvent *event){
 if(standby_||shutdownPending_||monotonicMs()<touchGuardUntil_){cancelGesture();event->accept();return;}
 if(pressSystem_){event->accept();return;}
 if(pressActive_&&scrollWifiList(event->pos()))applyAction(NoAction,"touch-scroll",event->x(),event->y());
 event->accept();
}
void ReaderShell::mouseReleaseEvent(QMouseEvent *event) {
    if(otaLocked_){cancelGesture();event->accept();return;}
    if(standby_||shutdownPending_||monotonicMs()<touchGuardUntil_){cancelGesture();event->accept();return;}
    if(event->button()!=Qt::LeftButton)return;
    if(!pressActive_ || pressPage_!=page()) { cancelGesture();event->accept();return; }
    bool otaTouch=otaGesture(event->x(),event->y());
    if(otaPromptVisible()){if(otaTouch)otaTap(event->x(),event->y());cancelGesture();event->accept();return;}
    if(!pressSystem_&&otaTouch&&otaTap(event->x(),event->y())){cancelGesture();event->accept();return;}
    pressActive_=false;
    if(pressSystem_){
        int dx=event->x()-press_.x(),dy=event->y()-press_.y();
        bool tap=qMax(qAbs(dx),qAbs(dy))<16;
        if(rect().contains(event->pos())){
            if(!pressWasOpen_){if((dy>=48&&dy>=qAbs(dx))||(tap&&event->y()<40))setSystemPanel(true);}
            else if(press_.y()>=400){if(tap&&event->y()>=400)setSystemPanel(false);}
            else if(dy<=-48&&-dy>=qAbs(dx))setSystemPanel(false);
            else if(tap){
                if(press_.y()<40&&event->y()<40)setSystemPanel(false);
                else {int x=event->x(),y=event->y();
                    const QRect areas[]={QRect(24,136,208,88),QRect(248,136,208,88),QRect(24,240,208,88),QRect(248,240,208,88),QRect(0,336,480,64)};
                    for(int i=0;i<5;++i)if(areas[i].contains(press_)&&areas[i].contains(event->pos())){systemPanelTap(x,y);break;}
                }
            }
        }
        cancelGesture();event->accept();return;
    }
    if(wifiListGesture_){
     bool swiped=scrollWifiList(event->pos());int row=wifiRowAt(press_);
     applyAction(NoAction,"touch-list",event->x(),event->y());
     if(!swiped&&row>=0&&row==wifiRowAt(event->pos()))settingsTap(event->x(),event->y());
     cancelGesture();event->accept();return;
    }
    if(page()==Schedule && press_.y()>=120 && press_.y()<700 && event->y()>=120 && event->y()<700 && qAbs(event->y()-press_.y())>=40)scrollSchedule(event->y()<press_.y()?5:-5);
    else if(page()==Words&&!wordList_&&press_.y()>=235&&press_.y()<525&&qAbs(event->y()-press_.y())>=40)scrollLocal(event->y()<press_.y()?9:-9);
    else if((page()==Words&&wordList_||page()==Notes&&!noteEditing_&&noteId_.isEmpty()) && press_.y()>=190 && press_.y()<610 && qAbs(event->y()-press_.y())>=40)scrollLocal(event->y()<press_.y()?6:-6);
    else if((page()==Words||page()==Notes)&&hitTest(page(),event->x(),event->y())==NoAction){applyAction(NoAction,"local-app",event->x(),event->y());localTap(event->x(),event->y());}
    else if(page()==Control && hitTest(page(),event->x(),event->y())==NoAction) { applyAction(NoAction,"settings",event->x(),event->y());settingsTap(event->x(),event->y()); }
    else {
        Action released=hitTest(page(),event->x(),event->y());
        if(released!=hitTest(page(),press_.x(),press_.y()))released=NoAction;
        applyAction(released,"release",event->x(),event->y());
    }
    cancelGesture();event->accept();
}
void ReaderShell::wheelEvent(QWheelEvent *event) {
    if(otaLocked_){event->accept();return;}otaInput();
    if(standby_||shutdownPending_||monotonicMs()<touchGuardUntil_){event->accept();return;}
    if(systemPanelOpen_){event->accept();return;}
    if(page()==Schedule)scrollSchedule(event->delta()<0?5:-5);else if(page()==Words||page()==Notes)scrollLocal(event->delta()<0?6:-6);else applyAction(NoAction,"wheel",event->x(),event->y());
    event->accept();
}
void ReaderShell::timerEvent(QTimerEvent *event) {
    if(event->timerId()==otaTimer_){otaTick();return;}
    if(standby_||shutdownPending_)return;
    if(event->timerId()==bt_.timer){bluetoothTick();return;}
    if(event->timerId()==radioTimer_) { if(radio_->poll())finishRadio();return; }
    if(event->timerId()==wifiStatusTimer_) { requestWifiStatus();return; }
    if(event->timerId()!=idleTimer_) { QWidget::timerEvent(event);return; }
    if(noteEditing_||systemPanelOpen_){navigation_.interact(NoAction,monotonicMs());resetIdle();return;}
    Page from=page();navigation_.expire(monotonicMs());
    if(from!=page()) { systemReturnActive_=false;systemReturnInput_=-1;clearSecrets();cancelGesture();watchWifiStatus();navigationChanged(from,page(),"idle",-1,-1);resetIdle();update(); }
    // An early/coarse Qt timer cannot return home before the monotonic deadline.
    else { killTimer(idleTimer_);idleTimer_=startTimer(int(qMax(qint64(1),idleDeadline_-monotonicMs()))); }
}
void ReaderShell::navigationChanged(Page,Page,const char *,int,int) {}

qint64 ReaderShell::monotonicMs() const { return monotonic_.elapsed(); }
QString ReaderShell::displayClock()const{
 qint64 now=0;if(!anchor_.nowEpoch(&now))return QString();
 for(int i=0;i<content_.localDays.size();++i){const LocalDay &d=content_.localDays[i];if(now>=d.startEpoch&&now<d.endEpoch){if(d.endEpoch-d.startEpoch!=86400)return text("已校时");qint64 offset=qint64(QDate(1970,1,1).daysTo(d.date))*86400-d.startEpoch;return QDateTime::fromTime_t(uint(now+offset)).toUTC().toString("HH:mm");}}
 return QString();
}
QString ReaderShell::inputValue(int field)const{return field==0?inputSsid_:field==1?inputPassword_:field==2?inputEndpoint_:QString(inputToken_.size(),QChar('*'));}
QString &ReaderShell::editValue(){return inputField_==4?noteDraft_:inputField_==0?inputSsid_:inputField_==1?inputPassword_:inputField_==2?inputEndpoint_:inputToken_;}
void ReaderShell::beginInput(int field){inputField_=field;keyboardMode_=0;uppercase_=false;update();}
void ReaderShell::clearSecrets(){inputPassword_.fill(QChar(0));inputPassword_.clear();inputToken_.fill(QChar(0));inputToken_.clear();inputField_=-1;wifiDialog_=false;}
bool ReaderShell::configureSync(const QString &,const QByteArray &){return false;}
void ReaderShell::syncRequested(){}
void ReaderShell::contentPainted(const QString &){}
bool ReaderShell::startRadio(const QString &action,const QString &value,const QString &password){
 // A user action or background status must never replace an active request.
 if(radio_->busy())return false;
 bool ok=radio_->start(action,value,password);
 if(ok){radioAction_=action;if(!radioTimer_)radioTimer_=startTimer(100);}
 else {radioReply_.ok=false;radioReply_.code=radio_->reply().code;}
 if(action=="wifi-connect")wifiSaveCode_=ok?QString("pending"):radioReply_.code;
 if(action!="status")update();
 return ok;
}
void ReaderShell::watchWifiStatus(bool scan){
 if(wifiStatusTimer_){killTimer(wifiStatusTimer_);wifiStatusTimer_=0;}
 if(page()!=Control||settingsTab_!=0){wifiScanPending_=false;wifiNetworkInfo_=false;return;}
 if(scan){wifiScanPending_=true;wifiScanCode_="scanning";}
 // A bounded observation window; only explicit page entry/actions renew it.
 wifiStatusDeadline_=monotonicMs()+60000;wifiStatusTimer_=startTimer(2000);requestWifiStatus();
}
void ReaderShell::requestWifiStatus(){
 if(page()!=Control||settingsTab_!=0||monotonicMs()>=wifiStatusDeadline_){
  if(wifiStatusTimer_){killTimer(wifiStatusTimer_);wifiStatusTimer_=0;}return;
 }
 if(radio_->busy())return;
 if(wifiScanPending_){wifiScanPending_=false;if(!startRadio("wifi-scan"))wifiScanCode_="helper-failed";return;}
 if(!startRadio("status")){
  if(wifiStatusTimer_){killTimer(wifiStatusTimer_);wifiStatusTimer_=0;}
  update();
 }
}
void ReaderShell::refreshWifiScan(){wifiScanPending_=true;wifiScanCode_="scanning";watchWifiStatus();update();}
QString ReaderShell::networkStatusText()const{
 const QMap<QString,QString> &st=radioReply_.status;
 QMap<QString,QString> visible=st;const char *keys[]={"interface_name","interface_state","wifi_state","netmask","mac","gateway"};for(int i=0;i<6;++i)if(visible.value(keys[i]).isEmpty())visible[keys[i]]=text("未提供");
 QString missing=text("未提供"),ssid=radioReply_.wifiSsid.isEmpty()?(st.value("wifi_state")=="COMPLETED"?missing:text("未关联")):radioReply_.wifiSsid;
 return text("已关联网络：")+ssid+"\n"+text("IPv4：")+(st.value("ipv4").isEmpty()?text("未分配"):st.value("ipv4"))+"\n"+text("接口：")+visible.value("interface_name")+"\n"+text("接口状态：")+visible.value("interface_state")+"\n"+text("关联状态：")+visible.value("wifi_state")+"\n"+text("子网掩码：")+visible.value("netmask")+"\n"+text("MAC：")+visible.value("mac")+"\n"+text("网关：")+visible.value("gateway")+"\n\n"+wifiSaveFeedback();
}
QString ReaderShell::wifiSaveFeedback()const{
 if(wifiSaveCode_.isEmpty())return text("配置保存：未确认；请重新选择网络连接后查看结果。");
 if(wifiSaveCode_=="pending")return text("等待配置保存结果；连接状态单独验证。");
 if(wifiSaveCode_=="saved")return text("配置保存：已保存；")+(radioReply_.status.value("wifi_state")=="COMPLETED"&&!radioReply_.status.value("ipv4").isEmpty()?text("连接见上方实时状态。"):text("关联与 IP 尚未验证。"));
 if(wifiSaveCode_=="temporary")return text("本次仅临时连接；未启用配置保存。");
 if(wifiSaveCode_=="unconfirmed")return text("配置保存：未确认；请保留当前连接并检查保存结果。");
 if(wifiSaveCode_=="persistence_uncertain")return text("配置保存结果不确定（persistence_uncertain）；请勿重启。");
 if(wifiSaveCode_=="persistence_failed")return text("配置保存失败（persistence_failed）；当前连接可能仍然有效。");
 if(wifiSaveCode_=="persistence_unavailable")return text("配置保存不可用（persistence_unavailable）；连接请求未提交。");
 return text("连接请求失败：")+wifiSaveCode_+text("；配置保存未确认。");
}
QString ReaderShell::wifiFeedback()const{
 const QString state=radioReply_.status.value("wifi_state"),ip=radioReply_.status.value("ipv4");
 if(state=="COMPLETED")return (radioReply_.wifiSsid.isEmpty()?text("已关联"):text("已关联：")+radioReply_.wifiSsid)+(ip.isEmpty()?text(" · 等待 IPv4"):text(" · IPv4 ")+ip);
 if(!state.isEmpty())return text("无线状态：")+state;
 if(radioReply_.code=="association_requested")return text("已提交连接 · 等待关联与 IPv4");
 if(radioReply_.code=="disconnected")return text("已请求断开 · 等待实际状态");
 if(!radioReply_.ok&&!radioReply_.code.isEmpty())return text("无线操作失败：")+radioReply_.code;
 return text("等待实际无线状态");
}
void ReaderShell::finishRadio(){
 killTimer(radioTimer_);radioTimer_=0;
 RadioReply reply=radio_->reply();QString action=radioAction_;radioAction_.clear();
 // Fingerprint the displayed state, not helper activity, to avoid e-ink churn.
 bool oldLinked=wifiLinked_;
 QString before=radioReply_.code+"|"+wifiFeedback()+wifiSaveFeedback()+(wifiNetworkInfo_?networkStatusText():QString());
 bool listChanged=false;
 if(action=="status"){
  if(reply.ok){
   radioReply_.status=reply.status;radioReply_.wifiSsid=reply.wifiSsid;radioReply_.code=reply.code;radioReply_.ok=true;
   bool linked=reply.status.value("wifi_state")=="COMPLETED"&&!reply.status.value("ipv4").isEmpty();
   if(linked&&!wifiSyncLinked_)syncRequested();
   wifiSyncLinked_=linked;wifiLinked_=linked;
  }else{
   wifiLinked_=false;radioReply_.status.clear();radioReply_.wifiSsid.clear();radioReply_.code=reply.code;radioReply_.ok=false;
   if(wifiStatusTimer_){killTimer(wifiStatusTimer_);wifiStatusTimer_=0;}
  }
 }else{
  radioReply_.ok=reply.ok;radioReply_.code=reply.code;radioReply_.message=reply.message;
  if(action=="wifi-scan"){
   wifiScanCode_=reply.ok?(reply.wifi.isEmpty()?"empty":"cached"):reply.code;
   if(reply.ok){clearSecrets();cancelGesture();radioReply_.wifi=reply.wifi;wifiOffset_=0;selectedWifi_=-1;listChanged=true;}
   if(wifiStatusTimer_)requestWifiStatus();
  }
  if(action.startsWith("bluetooth")&&reply.ok){radioReply_.bluetooth=reply.bluetooth;listChanged=true;}
  if(action=="wifi-connect"){
   // Helper durability acknowledgement is separate from later link/IP polling.
   // No marker means the legacy helper used a volatile configuration.
   wifiSaveCode_=!reply.ok?reply.code:reply.status.value("saved_network")=="pending_authentication"?QString("saved"):reply.status.contains("saved_network")?QString("unconfirmed"):QString("temporary");
  }
  if(action=="wifi-connect"||action=="wifi-disconnect"){
   // Command acceptance is not a link observation; suppress any old IP display.
   wifiLinked_=false;radioReply_.status.clear();radioReply_.wifiSsid.clear();
   if(page()==Control&&settingsTab_==0)watchWifiStatus();
  }
 }
 if(page()==Control&&(action!="status"||listChanged||before!=radioReply_.code+"|"+wifiFeedback()+wifiSaveFeedback()+(wifiNetworkInfo_?networkStatusText():QString())))update();
 if(systemPanelOpen_&&(listChanged||before!=radioReply_.code+"|"+wifiFeedback()+wifiSaveFeedback()+(wifiNetworkInfo_?networkStatusText():QString())))update(QRect(0,0,480,400));
 else if(oldLinked!=wifiLinked_)update(QRect(0,0,480,40));
 if(action=="status"&&wifiScanPending_&&wifiStatusTimer_)requestWifiStatus();
}
void ReaderShell::drawSettings(QPainter &p){
 const char *tabs[]={"Wi-Fi","蓝牙","时间与日历"};for(int i=0;i<3;++i){QRect r(12+i*156,154,144,52);drawButton(p,r,text(tabs[i]));if(i==settingsTab_)p.fillRect(r.adjusted(4,44,-4,-3),Qt::black);}
 p.setFont(typeface(font(),17));QString status=settingsTab_==1?bluetoothStatusText():settingsTab_==0?wifiFeedback():((radio_->busy()&&radioAction_!="status")?text("操作中 · 可继续使用界面"):(radioReply_.code.isEmpty()?text("尚未读取无线状态"):radioReply_.code));p.drawText(QRect(16,214,448,32),Qt::AlignLeft|Qt::AlignVCenter,QFontMetrics(p.font()).elidedText(status,Qt::ElideRight,448));
 if(settingsTab_==0){
  if(wifiNetworkInfo_){
   drawButton(p,QRect(16,256,208,52),text("返回网络列表"));drawButton(p,QRect(256,256,208,52),text("刷新状态"));
   p.setFont(typeface(font(),18));p.drawText(QRect(24,330,432,326),Qt::TextWordWrap,networkStatusText());
   p.setFont(typeface(font(),17));p.drawText(QRect(24,662,432,120),Qt::TextWordWrap,text("日历同步（独立状态）\n")+connectionStatus_);return;
  }
  drawButton(p,QRect(16,256,104,52),text("刷新"));drawButton(p,QRect(136,256,208,52),text("查看网络状态"));drawButton(p,QRect(360,256,104,52),text("断开"));
  p.setFont(typeface(font(),15));QString scanLabel=wifiScanCode_=="scanning"?text("正在扫描 · 可继续使用界面"):wifiScanCode_=="empty"?text("未发现网络 · 结果可能来自缓存"):wifiScanCode_=="cached"?text("扫描结果 · 可能来自缓存"):wifiScanCode_=="helper-busy"?text("操作进行中，请稍后重试连接"):wifiScanCode_=="password-required"?text("所选网络需要密码，请重新选择输入"):wifiScanCode_.isEmpty()?text("尚未扫描"):text("扫描失败：")+wifiScanCode_;p.drawText(QRect(16,314,448,24),Qt::AlignVCenter,scanLabel);
  for(int i=0;i<qMin(6,radioReply_.wifi.size()-wifiOffset_);++i){int index=wifiOffset_+i;const WifiRow &r=radioReply_.wifi[index];p.setFont(typeface(font(),22));QRect row(16,342+i*58,448,52);p.fillRect(row,index==selectedWifi_?QColor(220,220,220):Qt::white);p.drawText(row,Qt::AlignLeft|Qt::AlignVCenter,QFontMetrics(p.font()).elidedText(r.ssid+"  "+r.security+" "+r.signal,Qt::ElideRight,448));}
  p.setFont(typeface(font(),16));p.drawText(QRect(16,694,448,24),Qt::AlignRight,radioReply_.wifi.isEmpty()?QString():text("上下滑动 ")+QString("%1-%2 / %3").arg(wifiOffset_+1).arg(qMin(wifiOffset_+6,radioReply_.wifi.size())).arg(radioReply_.wifi.size()));
  p.drawText(QRect(16,730,448,52),Qt::TextWordWrap,wifiSaveFeedback());
  if(wifiDialog_)drawWifiDialog(p);
 }else if(settingsTab_==1){drawBluetooth(p);
 }else{
  drawButton(p,QRect(16,256,448,54),inputEndpoint_.isEmpty()?text("输入 HTTPS 服务地址"):QFontMetrics(p.font()).elidedText(inputEndpoint_,Qt::ElideRight,430));
  drawButton(p,QRect(16,320,448,54),text("设备凭据：")+(inputToken_.isEmpty()?text("点击输入"):QString(qMin(20,inputToken_.size()),QChar('*'))));
  drawButton(p,QRect(16,388,208,52),text("应用配置"));drawButton(p,QRect(256,388,208,52),text("立即同步"));
  if(inputField_<0){p.setFont(typeface(font(),19));p.drawText(QRect(16,466,448,220),Qt::TextWordWrap,connectionStatus_+"\n\n"+text("自动校时来自新鲜认证响应，使用单调时钟。重启后先显示缓存时间。日历来源：Mac 日历。")+"\n\n"+text("HTTPS 地址使用 USB 预置证书、固定指纹和可信起始时间。握手与证书校验通过后才发送凭据。"));}
 }
 if(inputField_>=0&&!wifiDialog_)drawKeyboard(p);
}
void ReaderShell::drawWifiDialog(QPainter &p){
 p.fillRect(QRect(0,246,480,554),Qt::white);p.setFont(typeface(font(),22,true));p.drawText(QRect(24,252,432,64),Qt::TextWordWrap,inputSsid_);
 p.setFont(typeface(font(),17));p.drawText(QRect(24,318,432,28),Qt::AlignVCenter,wifiDialogSecurity_=="open"?text("开放网络 · 请确认连接"):text("输入此网络的密码"));
 if(wifiDialogSecurity_!="open")drawButton(p,QRect(16,350,448,48),text("密码：")+(inputPassword_.isEmpty()?text("点击输入"):inputValue(1)));
 drawButton(p,QRect(16,404,208,42),text("取消"));drawButton(p,QRect(256,404,208,42),text("确认连接"));if(inputField_>=0)drawKeyboard(p);
}
static QStringList wrappedText(const QString &body,const QFont &font,int width){
 QFontMetrics fm(font);QStringList out;QString line;
 for(int i=0;i<body.size();++i){QChar c=body[i];if(c=='\n'){out<<line;line.clear();continue;}QString next(c);if(c.unicode()>=0xd800&&c.unicode()<=0xdbff&&i+1<body.size()&&body[i+1].unicode()>=0xdc00&&body[i+1].unicode()<=0xdfff)next+=body[++i];if(!line.isEmpty()&&fm.width(line+next)>width){out<<line;line.clear();}line+=next;}out<<line;return out;
}
static int visibleRows(const QFont &font,int height){QFontMetrics fm(font);return qMax(1,1+(height-fm.height())/qMax(1,fm.lineSpacing()));}
QString ReaderShell::wordVisibleText()const{if(local_.words().isEmpty())return QString();const WordCard &w=local_.words()[wordIndex_];QFont f=typeface(font(),wordBack_?25:32,true);int rows=qMin(9,visibleRows(f,290));return QStringList(wrappedText(wordBack_?w.back:w.front,f,432).mid(wordScroll_,rows)).join("\n");}
QString ReaderShell::noteDraftVisibleText()const{QFont f=typeface(font(),20);QStringList lines=wrappedText(noteDraft_,f,428);return QStringList(lines.mid(qMax(0,lines.size()-visibleRows(f,90)))).join("\n");}
QString ReaderShell::noteVisibleText()const{for(int i=0;i<local_.notes().size();++i)if(local_.notes()[i].id==noteId_)return QStringList(wrappedText(local_.notes()[i].body,typeface(font(),20),432).mid(noteScroll_,14)).join("\n");return QString();}
bool ReaderShell::configureWorkspace(const QString &path){bool ok=local_.open(path);if(ok){wordIndex_=qBound(0,wordIndex_,qMax(0,local_.words().size()-1));localOffset_=0;noteOffset_=0;noteDraft_=local_.draft();noteEditing_=false;}localMessage_=ok?text("已打开本地工作目录"):text("工作目录不可用：")+localError(local_.error());update();return ok;}
QString ReaderShell::workspaceStatus()const{return local_.available()?text("本地写入目录：")+local_.directory()+text("\n持久磁盘挂载：未核验（由启动环境确认）"):text("未配置本地写入目录；请使用 --workspace-dir ABS\n当前不能保存单词进度或笔记。");}
void ReaderShell::drawInformation(QPainter &p){p.setFont(typeface(font(),17));QString version=content_.version.isEmpty()?text("尚无内容"):content_.version;p.drawText(QRect(24,163,432,430),Qt::TextWordWrap,text("PandaNote\n")+text("电量：")+(batteryPercent_<0?text("暂不可用"):(batteryEstimated_?text("约"):QString())+QString::number(batteryPercent_)+"%")+(batteryEstimated_?text("（电压估算）"):QString())+text("\n电池电压：")+(batteryVoltageMv_<0?text("暂不可用"):QString::number(batteryVoltageMv_/1000.0,'f',3)+" V")+text("\n充电状态：")+(!batteryChargingKnown_?text("暂不可用"):batteryCharging_?text("正在充电"):text("未充电"))+"\n"+displayStatus()+text("\n内容版本：")+version+"\n\n"+connectionStatus_+text("\n\n无线信息：到设备设置查看实时状态\n\n")+workspaceStatus()+text("\n\n短按电源键待机，再短按唤醒。长按约 3 秒关机。"));p.setFont(typeface(font(),18));p.drawText(QRect(24,608,432,84),Qt::TextWordWrap,text("当前程序：")+otaCurrent_+"\n"+otaMessage_);drawButton(p,QRect(24,704,432,56),otaProgress_?text("稍后更新"):otaOffered_?text("查看软件更新 ")+otaVersion_:text("检查软件更新"));}
void ReaderShell::drawWords(QPainter &p){
 drawButton(p,QRect(330,154,126,48),wordList_?text("学习"):text("列表"));p.setFont(typeface(font(),20));p.drawText(QRect(24,155,290,48),Qt::AlignVCenter,QString("%1 / %2").arg(local_.words().isEmpty()?0:wordIndex_+1).arg(local_.words().size()));
 if(local_.words().isEmpty()){p.drawText(QRect(24,240,432,260),Qt::TextWordWrap,text("没有单词卡。\n先配置本地工作目录，再用 local_apps_tool.py import-words 导入 UTF-8 TSV：每行 正面<TAB>背面。\n无预置示例数据。"));}
 else if(wordList_){for(int i=0;i<qMin(6,local_.words().size()-localOffset_);++i){const WordCard &w=local_.words()[localOffset_+i];drawButton(p,QRect(24,215+i*64,432,56),(w.known?text("✓ "):QString())+w.front);}p.setFont(typeface(font(),17));p.drawText(QRect(24,610,432,30),Qt::AlignCenter,text("上下滑动翻页"));}
 else {const WordCard &w=local_.words()[wordIndex_];p.setFont(typeface(font(),wordBack_?25:32,true));p.drawText(QRect(24,235,432,290),Qt::AlignCenter|Qt::TextWordWrap,wordVisibleText());drawButton(p,QRect(24,535,432,48),wordBack_?text("背面 · 上下滑动，点击翻回"):text("正面 · 上下滑动，点击翻面"));drawButton(p,QRect(24,590,204,52),text("认识"));drawButton(p,QRect(252,590,204,52),text("再学"));drawButton(p,QRect(24,654,432,52),text("下一张"));}
 p.setFont(typeface(font(),17));p.drawText(QRect(24,720,432,65),Qt::TextWordWrap,localMessage_.isEmpty()?workspaceStatus():localMessage_);
}
void ReaderShell::drawNotes(QPainter &p){
 p.setFont(typeface(font(),20));
 if(noteEditing_){p.drawText(QRect(24,154,432,32),Qt::AlignVCenter,text("编辑笔记 · ")+QString::number(noteDraft_.toUtf8().size())+" / 16384 B");p.setFont(typeface(font(),16));p.drawText(QRect(24,190,432,54),Qt::TextWordWrap,localMessage_);p.setFont(typeface(font(),20));QStringList draftLines=noteDraftVisibleText().split('\n');QFontMetrics draftMetrics(p.font());for(int row=0;row<draftLines.size();++row)p.drawText(24,250+draftMetrics.ascent()+row*draftMetrics.lineSpacing(),draftLines[row]);int caretX=24+draftMetrics.width(draftLines.last()),caretY=250+(draftLines.size()-1)*draftMetrics.lineSpacing();p.drawLine(caretX,caretY,caretX,caretY+draftMetrics.height()-1);drawButton(p,QRect(24,350,130,40),text("换行"));drawButton(p,QRect(170,350,286,40),text("继续输入"));drawButton(p,QRect(24,396,204,44),text("取消"));drawButton(p,QRect(252,396,204,44),text("保存"));if(inputField_==4)drawKeyboard(p);else{p.setFont(typeface(font(),18));p.drawText(QRect(24,460,432,160),Qt::TextWordWrap,localMessage_);}return;}
 if(noteDelete_){p.drawText(QRect(24,240,432,110),Qt::TextWordWrap,text("确定删除这条笔记？此操作需要再次确认。"));drawButton(p,QRect(24,396,204,44),text("取消"));drawButton(p,QRect(252,396,204,44),text("确认删除"));return;}
 if(!noteId_.isEmpty()){QString body;for(int i=0;i<local_.notes().size();++i)if(local_.notes()[i].id==noteId_)body=local_.notes()[i].body;p.drawText(QRect(24,170,432,400),Qt::TextWordWrap,noteVisibleText());drawButton(p,QRect(24,578,100,44),text("上页"));drawButton(p,QRect(140,578,100,44),text("下页"));drawButton(p,QRect(256,578,200,44),text("笔记列表"));drawButton(p,QRect(24,628,204,52),text("编辑"));drawButton(p,QRect(252,628,204,52),text("删除"));}
 else{if(local_.notes().isEmpty())p.drawText(QRect(24,210,432,180),Qt::TextWordWrap,text("还没有笔记。\n点新建开始输入；中文正文可通过导入工具导入并保留。"));for(int i=0;i<qMin(6,local_.notes().size()-noteOffset_);++i)drawButton(p,QRect(24,170+i*68,432,60),local_.notes()[noteOffset_+i].body.simplified().isEmpty()?text("空笔记"):local_.notes()[noteOffset_+i].body.simplified());drawButton(p,QRect(24,628,432,52),text("新建笔记"));}
 p.setFont(typeface(font(),17));p.drawText(QRect(24,700,432,88),Qt::TextWordWrap,localMessage_.isEmpty()?workspaceStatus():localMessage_);
}
bool ReaderShell::scrollLocal(int delta){
 if(!delta)return false;
 int *offset=0,amount=delta,limit=0;
 if(page()==Words&&wordList_){offset=&localOffset_;limit=qMax(0,local_.words().size()-6);}
 else if(page()==Words&&!local_.words().isEmpty()){
  QFont f=typeface(font(),wordBack_?25:32,true);int rows=qMin(9,visibleRows(f,290));const WordCard &w=local_.words()[wordIndex_];
  offset=&wordScroll_;amount=delta<0?-rows:rows;limit=qMax(0,wrappedText(wordBack_?w.back:w.front,f,432).size()-rows);
 }else if(page()==Notes&&!noteEditing_&&!noteDelete_){
  if(noteId_.isEmpty()){offset=&noteOffset_;limit=qMax(0,local_.notes().size()-6);}
  else{for(int i=0;i<local_.notes().size();++i)if(local_.notes()[i].id==noteId_){offset=&noteScroll_;amount=delta<0?-14:14;limit=qMax(0,wrappedText(local_.notes()[i].body,typeface(font(),20),432).size()-14);break;}}
 }
 if(!offset)return false;int next=qBound(0,*offset+amount,limit);if(next==*offset)return false;
 *offset=next;update();return true;
}

void ReaderShell::localTap(int x,int y){
 if(page()==Words){if(QRect(330,154,126,48).contains(x,y)){wordList_=!wordList_;update();return;}if(local_.words().isEmpty())return;if(wordList_){int i=(y-215)/64+localOffset_;if(y>=215&&y<599&&i<local_.words().size()){wordIndex_=i;wordBack_=false;wordScroll_=0;wordList_=false;}}
 else if(QRect(24,235,432,348).contains(x,y)){wordBack_=!wordBack_;wordScroll_=0;}
 else if(QRect(24,590,432,52).contains(x,y)){bool ok=local_.markWord(wordIndex_,x<240);localMessage_=ok?text("学习进度已保存"):text("保存失败：")+localError(local_.error());}
 else if(QRect(24,654,432,52).contains(x,y)){wordIndex_=(wordIndex_+1)%local_.words().size();wordBack_=false;wordScroll_=0;}update();return;}
 if(noteEditing_){if(QRect(24,396,204,44).contains(x,y)){if(local_.available()&&!local_.saveDraft(QString())){localMessage_=text("清理草稿失败，内容保留");update();return;}noteEditing_=false;inputField_=-1;noteDraft_.clear();localMessage_=text("已取消编辑");}
 else if(QRect(252,396,204,44).contains(x,y)){QString id;bool ok=local_.saveNote(noteId_,noteDraft_,&id);localMessage_=ok?text("笔记已保存"):text("保存失败，草稿保留：")+localError(local_.error());if(ok){noteId_=id;if(!local_.saveDraft(QString())){localMessage_=text("笔记已保存，草稿清理失败");update();return;}noteEditing_=false;inputField_=-1;noteDraft_.clear();noteId_.clear();noteOffset_=0;}}
 else if(QRect(24,350,130,40).contains(x,y)){if(noteDraft_.toUtf8().size()<16384)noteDraft_+='\n';}
 else if(QRect(170,350,286,40).contains(x,y))beginInput(4);
 else if(inputField_==4)keyboardTap(x,y);update();return;}
 if(noteDelete_){if(QRect(24,396,204,44).contains(x,y))noteDelete_=false;else if(QRect(252,396,204,44).contains(x,y)){bool ok=local_.deleteNote(noteId_);localMessage_=ok?text("笔记已删除"):text("删除失败：")+localError(local_.error());noteDelete_=false;if(ok){noteId_.clear();noteOffset_=0;}}update();return;}
 if(noteId_.isEmpty()){if(QRect(24,628,432,52).contains(x,y)){noteDraft_.clear();localMessage_.clear();localMessage_.clear();noteEditing_=true;beginInput(4);}
 else if(y>=170&&y<578){int i=noteOffset_+(y-170)/68;if(i<local_.notes().size()){noteId_=local_.notes()[i].id;noteScroll_=0;}}}
 else{if(QRect(24,628,204,52).contains(x,y)){for(int i=0;i<local_.notes().size();++i)if(local_.notes()[i].id==noteId_)noteDraft_=local_.notes()[i].body;localMessage_.clear();noteEditing_=true;beginInput(4);}
 else if(QRect(252,628,204,52).contains(x,y))noteDelete_=true;
 else if(QRect(256,578,200,44).contains(x,y))noteId_.clear();
 else if(QRect(24,578,216,44).contains(x,y)){int maxLines=0;for(int i=0;i<local_.notes().size();++i)if(local_.notes()[i].id==noteId_)maxLines=wrappedText(local_.notes()[i].body,typeface(font(),20),432).size();noteScroll_=qBound(0,noteScroll_+(x<132?-14:14),qMax(0,maxLines-14));}}
 update();
}
static QString keyboardChars(int mode,bool upper){QString s=mode==0?QString("qwertyuiopasdfghjklzxcvbnm"):mode==1?QString("1234567890!@#$%^&*()-_=+[]{};:,.?/"):QString("\\|`~'\"<>:");return upper?s.toUpper():s;}
void ReaderShell::drawKeyboard(QPainter &p){p.fillRect(QRect(0,450,480,350),Qt::white);p.setPen(Qt::black);p.setFont(typeface(font(),17));p.drawText(QRect(16,450,448,28),Qt::AlignVCenter,(inputField_==4?text("笔记输入 · ASCII 键盘，可保留中文"):text("屏幕输入 · 密码仅保留到提交/离开")));QString chars=keyboardChars(keyboardMode_,uppercase_);for(int i=0;i<chars.size();++i)drawButton(p,QRect(12+(i%10)*46,486+(i/10)*54,42,48),QString(chars[i]));const char *labels[]={"大小写","符号","空格","删除","完成"};for(int i=0;i<5;++i)drawButton(p,QRect(12+i*94,724,88,54),text(labels[i]));}
void ReaderShell::keyboardTap(int x,int y){QString chars=keyboardChars(keyboardMode_,uppercase_);for(int i=0;i<chars.size();++i)if(QRect(12+(i%10)*46,486+(i/10)*54,42,48).contains(x,y)){QString candidate=editValue()+chars[i];int limit=inputField_==0?32:inputField_==1?63:inputField_==2?128:inputField_==4?16384:512;if(candidate.toUtf8().size()<=limit)editValue()=candidate;update();return;}for(int i=0;i<5;++i)if(QRect(12+i*94,724,88,54).contains(x,y)){if(i==0)uppercase_=!uppercase_;else if(i==1)keyboardMode_=(keyboardMode_+1)%3;else if(i==2){int limit=inputField_==0?32:inputField_==1?63:inputField_==2?128:inputField_==4?16384:512;if(editValue().toUtf8().size()<limit)editValue()+=' ';}else if(i==3&&!editValue().isEmpty()){int count=1;int n=editValue().size();if(n>=2&&editValue()[n-1].unicode()>=0xdc00&&editValue()[n-1].unicode()<=0xdfff&&editValue()[n-2].unicode()>=0xd800&&editValue()[n-2].unicode()<=0xdbff)count=2;editValue().chop(count);}else if(i==4)inputField_=-1;update();return;}}
void ReaderShell::settingsTap(int x,int y){
 if(settingsTab_==0&&wifiDialog_){
  if(QRect(16,404,208,42).contains(x,y)){clearSecrets();update();return;}
  if(QRect(256,404,208,42).contains(x,y)){if(wifiDialogSecurity_!="open"&&inputPassword_.isEmpty()){clearSecrets();wifiScanCode_="password-required";update();return;}bool started=startRadio("wifi-connect",inputSsid_,inputPassword_);clearSecrets();if(!started)wifiScanCode_="helper-busy";update();return;}
  if(inputField_>=0){keyboardTap(x,y);return;}
  if(wifiDialogSecurity_!="open"&&QRect(16,350,448,48).contains(x,y))beginInput(1);return;
 }
 if(inputField_>=0){keyboardTap(x,y);return;}
 for(int i=0;i<3;++i)if(QRect(12+i*156,154,144,52).contains(x,y)){settingsTab_=i;clearSecrets();watchWifiStatus(i==0);update();return;}
 if(settingsTab_==0){
  if(wifiNetworkInfo_){if(QRect(16,256,208,52).contains(x,y)){wifiNetworkInfo_=false;update();}else if(QRect(256,256,208,52).contains(x,y))watchWifiStatus();return;}
  if(QRect(16,256,104,52).contains(x,y)){refreshWifiScan();return;}
  if(QRect(136,256,208,52).contains(x,y)){wifiNetworkInfo_=true;watchWifiStatus();update();return;}
  if(QRect(360,256,104,52).contains(x,y)){startRadio("wifi-disconnect");return;}
  int row=wifiRowAt(QPoint(x,y));if(row>=0&&!(radio_->busy()&&radioAction_=="wifi-scan")){
   if(radioReply_.wifi[row].security!="open"&&radioReply_.wifi[row].security!="wpa"&&radioReply_.wifi[row].security!="wpa2"){clearSecrets();wifiScanCode_="unsupported-security";update();return;}
   clearSecrets();selectedWifi_=row;inputSsid_=radioReply_.wifi[row].ssid;wifiDialogSecurity_=radioReply_.wifi[row].security;wifiDialog_=true;
   if(wifiDialogSecurity_!="open")beginInput(1);update();
  }
 }
 else if(settingsTab_==1)bluetoothTap(x,y);
 else{if(QRect(16,256,448,54).contains(x,y)){beginInput(2);return;}if(QRect(16,320,448,54).contains(x,y)){beginInput(3);return;}if(QRect(16,388,208,52).contains(x,y)){configureSync(inputEndpoint_,inputToken_.toLatin1());clearSecrets();update();}if(QRect(256,388,208,52).contains(x,y))syncRequested();}
}

// System drawer captures the entire input sequence; only release commits a change.
void ReaderShell::setSystemPanel(bool open){
 if(systemPanelOpen_==open)return;
 systemPanelOpen_=open;if(!quickSyncPending_)quickMessage_.clear();refreshBattery();resetIdle();
 if(open&&!radio_->busy())startRadio("status");
 update(QRect(0,0,480,400));
}
void ReaderShell::openSystemControl(){
 if(page()==Control){
  clearSecrets();cancelGesture();settingsTab_=0;setSystemPanel(false);
  navigation_.interact(NoAction,monotonicMs());resetIdle();watchWifiStatus(true);update();return;
 }
 systemReturnActive_=true;systemReturnPage_=page();systemReturnInput_=inputField_;
 settingsTab_=0;setSystemPanel(false);applyAction(OpenSystemControl,"system-settings",-1,-1);
}
void ReaderShell::systemPanelTap(int x,int y){
 if(QRect(0,336,480,64).contains(x,y)){setSystemPanel(false);return;}
 if(QRect(24,136,208,88).contains(x,y)||QRect(248,240,208,88).contains(x,y)){openSystemControl();return;}
 if(QRect(248,136,208,88).contains(x,y)){
  if(quickSyncPending_)return;
  quickMessage_=text("正在同步");setSyncActivity(true);syncRequested();return;
 }
 if(QRect(24,240,208,88).contains(x,y)){
  if(monotonicMs()<fullRefreshAllowedAt_)return;
  fullRefreshAllowedAt_=monotonicMs()+2000;
  EinkRefreshResult result=fullRefreshRequested();fullRefreshAllowedAt_=monotonicMs()+2000;
  quickMessage_=result==EinkRefreshOk?text("全刷已执行，已恢复局刷"):
   result==EinkRefreshUnavailable?text("当前环境不支持硬件全刷"):
   result==EinkRefreshBusy?text("刷新模式忙，请稍后再试"):
   result==EinkRefreshRestoreFailed?text("恢复局刷失败，请联系维护"):
   text("全刷请求失败，已恢复局刷");
  update(QRect(0,336,480,64));
 }
}
void ReaderShell::setSyncActivity(bool active){
 otaSyncBusy_=active;
 if(quickSyncPending_==active)return;quickSyncPending_=active;
 if(!active&&quickMessage_==text("正在同步"))quickMessage_=syncFailed_?text("同步失败，保留缓存"):text("同步请求已结束");
 if(systemPanelOpen_)update(QRect(0,40,480,360));
 if(page()==Home)update(QRect(24,696,432,104));
}
void ReaderShell::setConnectionStatus(const QString &status){
 if(connectionStatus_==status)return;connectionStatus_=status;QString old=quickMessage_;
 if(quickSyncPending_){
  if(status.contains(text("请先配置")))quickMessage_=text("请先配置同步");
  else if(syncFailed_)quickMessage_=text("同步失败，保留缓存");
 }
 if(page()==Control||page()==Info)update();
 else if(systemPanelOpen_&&old!=quickMessage_)update(QRect(0,40,480,360));
}
bool ReaderShell::refreshBattery(){
 const BatteryReading r=readBattery(true);const bool estimate=r.source==BatteryFactoryEstimate;
 bool changed=r.percent!=batteryPercent_||r.charging!=batteryCharging_||estimate!=batteryEstimated_||r.chargingKnown!=batteryChargingKnown_;
 batteryPercent_=r.percent;batteryVoltageMv_=r.voltageMv;batteryCharging_=r.charging;batteryEstimated_=estimate;batteryChargingKnown_=r.chargingKnown;return changed;
}
QString ReaderShell::compactSyncStatus()const{
 if(quickSyncPending_)return text("正在同步");
 if(content_.schema!=1)return text("尚未同步");
 if(syncFailed_)return text("同步失败 · 使用缓存");
 qint64 now=0;bool trusted=anchor_.nowEpoch(&now)&&localDateAtEpoch(content_,now).isValid();
 if(!trusted)return text("缓存内容");
 QString stamp;
 for(int i=0;i<content_.localDays.size();++i){const LocalDay &d=content_.localDays[i];
  if(content_.generatedAt>=d.startEpoch&&content_.generatedAt<d.endEpoch&&d.endEpoch-d.startEpoch==86400){
   qint64 offset=qint64(QDate(1970,1,1).daysTo(d.date))*86400-d.startEpoch;
   stamp=QDateTime::fromTime_t(uint(content_.generatedAt+offset)).toUTC().toString("HH:mm");break;
  }
 }
 return stamp.isEmpty()?text("内容已同步"):text("同步于 ")+stamp;
}
QString ReaderShell::systemWifiStatus()const{
 QString state=radioReply_.status.value("wifi_state");
 if(state=="COMPLETED")return radioReply_.status.value("ipv4").isEmpty()?text("获取地址"):text("已连接");
 if(state=="SCANNING")return text("扫描中");
 if(state=="ASSOCIATING"||state=="ASSOCIATED"||state=="4WAY_HANDSHAKE"||state=="GROUP_HANDSHAKE")return text("连接中");
 if(state=="DISCONNECTED"||state=="INACTIVE")return text("未连接");
 if(state=="INTERFACE_DISABLED")return text("已关闭");
 return text("状态未核验");
}

EinkRefreshResult ReaderShell::fullRefreshRequested(){
 QElapsedTimer elapsed;elapsed.start();EinkRefreshResult result=performDeviceFullRefresh();
 fprintf(stdout,"{\"event\":\"HARDWARE_FULL_REFRESH\",\"result\":%d,\"elapsed_ms\":%lld}\n",int(result),(long long)elapsed.elapsed());fflush(stdout);return result;
}

bool ReaderShell::persistPowerDraft(){
 bool ok=local_.available()?local_.saveDraft(noteDraft_):noteDraft_.isEmpty();
 if(!ok){powerMessage_=text("草稿保存失败，请先保存或取消");if(standby_)refreshStandbySnapshot();else update();}return ok;
}
void ReaderShell::drawPowerScreen(QPainter &p){
 if(!shutdownPending_){drawStandbyAgenda(p);return;}
 p.setPen(Qt::black);p.setFont(typeface(font(),24));p.drawText(QRect(40,100,400,48),Qt::AlignLeft|Qt::AlignVCenter,displayDate().isValid()?displayDate().toString("yyyy.MM.dd"):QString());
 p.drawLine(40,164,440,164);p.setFont(typeface(font(),40,true));
 p.drawText(QRect(40,280,400,120),Qt::AlignCenter|Qt::TextWordWrap,shutdownPending_?text("正在关机"):powerMessage_.isEmpty()?text("已待机"):powerMessage_);
 p.setFont(typeface(font(),24));p.drawText(QRect(40,428,400,100),Qt::AlignCenter|Qt::TextWordWrap,shutdownPending_?text("正在安全结束，请稍候"):text("短按电源键返回首页"));
 p.drawLine(40,668,440,668);p.setFont(typeface(font(),24));p.drawText(QRect(40,692,400,48),Qt::AlignCenter,text("PandaNote"));
}
void ReaderShell::shortPowerPress(){
 if(otaLocked_)return;otaInput();
 if(shutdownPending_)return;
 if(!standby_){
  if(!persistPowerDraft())return;
  cancelGesture();clearSecrets();systemPanelOpen_=false;standby_=true;powerMessage_.clear();resetIdle();standbyChanged(true);standbyFingerprint_.clear();standbyStatusFingerprint_.clear();refreshStandbySnapshot();
 }else{
  standby_=false;powerMessage_.clear();noteEditing_=false;clearSecrets();cancelGesture();systemPanelOpen_=false;systemReturnActive_=false;
  Page from=page();navigation_.restore(Home,monotonicMs());touchGuardUntil_=monotonicMs()+250;resetIdle();standbyChanged(false);update();if(from!=Home)navigationChanged(from,Home,"power-wake",-1,-1);
 }
}
void ReaderShell::longPowerPress(){
 if(otaLocked_)return;otaInput();
 if(shutdownPending_||!persistPowerDraft())return;
 shutdownPending_=true;standby_=false;powerMessage_.clear();cancelGesture();clearSecrets();systemPanelOpen_=false;resetIdle();standbyChanged(true);QWidget::repaint();
 if(!shutdownRequested()){shutdownPending_=false;standby_=true;powerMessage_=text("关机请求失败");standbyFingerprint_.clear();standbyStatusFingerprint_.clear();refreshStandbySnapshot();}
}
bool ReaderShell::shutdownRequested(){return false;}
void ReaderShell::standbyChanged(bool){}

void ReaderShell::systemStandbyCompleted(bool resumed){
 if(!standby_||shutdownPending_)return;
 shortPowerPress();
 if(!resumed){powerMessage_=text("系统待机未完成，请重试");update();}
}

bool ReaderShell::listNavigate(int direction){
 if(otaLocked_)return false;otaInput();
 if(direction!=-1&&direction!=1)return false;
 // A hardware key cancels any unfinished touch, even when this page cannot
 // scroll. Its later release must never activate a newly exposed row/button.
 cancelGesture();
 if(standby_||shutdownPending_||systemPanelOpen_||inputField_>=0||monotonicMs()<touchGuardUntil_)return false;
 if(page()==Schedule){int previous=scheduleOffset_;scrollSchedule(direction*5);return scheduleOffset_!=previous;}
 if(page()==Words||page()==Notes){
  if(page()==Notes&&(noteEditing_||noteDelete_))return false;
  applyAction(NoAction,"list-key",-1,-1);return scrollLocal(direction*6);
 }
 if(page()==Control&&settingsTab_==0&&!wifiDialog_&&!wifiNetworkInfo_){
  applyAction(NoAction,"list-key",-1,-1);
  int next=qBound(0,wifiOffset_+direction*6,qMax(0,radioReply_.wifi.size()-6));
  if(next==wifiOffset_)return false;wifiOffset_=next;update();return true;
 }
 return false;
}
