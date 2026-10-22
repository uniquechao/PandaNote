// Disposable offline GUI harness. All input below is SIMULATED, never physical.
#include "../shell.h"
#include <QtGui/qapplication.h>
#include <QtGui/qevent.h>
#include <QtGui/qfontmetrics.h>
#include <QtGui/qimage.h>
#include <QtGui/qpainter.h>
#include <QtGui/qwindowsurface_p.h>
#include <QtGui/qcursor.h>
#include <QtCore/qdir.h>
#include <QtCore/qfile.h>
#include <QtCore/qabstracteventdispatcher.h>
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <linux/input.h>
#include "../build-support/qws-cursor.h"
static int failures=0,checks=0;
#define CHECK(name,condition) do { ++checks; if(!(condition)) { fprintf(stderr,"FAIL %s line %d\n",name,__LINE__); ++failures; } } while(0)
// Transport double only: the real widget owns scheduling, merge, display and sync.
class FixtureRadio:public RadioClient {
public:
    FixtureRadio():running(false),ready(false),overlaps(0),secretOnStatus(false),passwordBytes(-1){}
    QStringList actions;bool running,ready;int overlaps;bool secretOnStatus;RadioReply result;QString connectedSsid;int passwordBytes;
    bool start(const QString &action,const QString &value=QString(),const QString &password=QString()) {
        if(running){++overlaps;return false;}
        actions<<action;if(action=="wifi-connect"){connectedSsid=value;passwordBytes=password.toUtf8().size();}if(action=="status"&&(!value.isEmpty()||!password.isEmpty()))secretOnStatus=true;
        running=true;ready=false;return true;
    }
    bool poll(){if(!ready)return false;ready=false;running=false;return true;}
    bool busy()const{return running;}
    RadioReply reply()const{return result;}
    void finish(const RadioReply &r){result=r;ready=true;}
};
class ObservedShell:public ReaderShell {
public:
    ObservedShell(const Content &c,RadioClient *radio=0):ReaderShell(c,0,radio),changes(0),now(0),paintAcks(0),syncs(0),paints(0),fullRefreshes(0),fullResult(EinkRefreshOk),shutdowns(0),shutdownOk(true),batteryDirty(false),ackWhilePainting(false) {setWindowFlags(Qt::FramelessWindowHint);}
    int fullRefreshes;EinkRefreshResult fullResult;int shutdowns;bool shutdownOk,batteryDirty,ackWhilePainting;QString ackVersion;
    int changes;QByteArray source;qint64 now;int paintAcks,syncs,paints;QRegion paintedRegion;QPoint lastMousePress,lastMouseRelease;
    void syncRequested(){++syncs;}
    void fireRadio(bool statusTick=false){
        QList<QAbstractEventDispatcher::TimerInfo> timers=QAbstractEventDispatcher::instance()->registeredTimers(this);
        for(int i=0;i<timers.size();++i)if(timers[i].second==(statusTick?2000:100)){QTimerEvent event(timers[i].first);QApplication::sendEvent(this,&event);}
    }
    void fireBluetooth(){QList<QAbstractEventDispatcher::TimerInfo> ts=QAbstractEventDispatcher::instance()->registeredTimers(this);for(int i=0;i<ts.size();++i)if(ts[i].second==25){QTimerEvent e(ts[i].first);QApplication::sendEvent(this,&e);}}
    int fastTimers(){int count=0;QList<QAbstractEventDispatcher::TimerInfo> ts=QAbstractEventDispatcher::instance()->registeredTimers(this);for(int i=0;i<ts.size();++i)if(ts[i].second<=2000)++count;return count;}
    void contentPainted(const QString &version) { ++paintAcks;ackVersion=version;ackWhilePainting=ackWhilePainting||paintingActive(); }
    void fireIdle() {
        QList<QAbstractEventDispatcher::TimerInfo> timers=QAbstractEventDispatcher::instance()->registeredTimers(this);
        CHECK("gui_one_idle_timer",timers.size()==1);
        if(timers.size()!=1)return;
        QTimerEvent event(timers[0].first);QApplication::sendEvent(this,&event);
    }
protected:
    void paintEvent(QPaintEvent *e){++paints;paintedRegion+=e->region();ReaderShell::paintEvent(e);}
    void mousePressEvent(QMouseEvent *e){lastMousePress=e->pos();ReaderShell::mousePressEvent(e);}
    void mouseReleaseEvent(QMouseEvent *e){lastMouseRelease=e->pos();ReaderShell::mouseReleaseEvent(e);}
    bool refreshBattery(){if(batteryDirty){batteryDirty=false;return true;}return ReaderShell::refreshBattery();}
    EinkRefreshResult fullRefreshRequested(){++fullRefreshes;return fullResult;}
    bool shutdownRequested(){++shutdowns;return shutdownOk;}
    qint64 monotonicMs() const { return now; }
    void navigationChanged(Page,Page,const char *reason,int,int) { ++changes;source=reason; }
};
static void send(ReaderShell &shell,QEvent::Type type,int x,int y) {
    QMouseEvent event(type,QPoint(x,y),Qt::LeftButton,Qt::LeftButton,Qt::NoModifier);
    QApplication::sendEvent(&shell,&event);
}
static void settleEvents(){QElapsedTimer t;t.start();while(t.elapsed()<60){QApplication::processEvents();::usleep(1000);}}
static void tap(ReaderShell &shell,int x,int y) { send(shell,QEvent::MouseButtonPress,x,y);send(shell,QEvent::MouseButtonRelease,x,y); }
static void drag(ReaderShell &shell,int y0,int y1) {send(shell,QEvent::MouseButtonPress,240,y0);send(shell,QEvent::MouseMove,240,y1);send(shell,QEvent::MouseButtonRelease,240,y1);}
static void pumpBluetooth(ObservedShell &shell,int ticks=100){for(int i=0;i<ticks;++i){shell.now+=25;shell.fireBluetooth();QApplication::processEvents();::usleep(1000);}}
static RadioReply actualStatus(){RadioReply r;r.ok=true;r.code="status";r.status["wifi_state"]="DISCONNECTED";r.status["ipv4"]="";r.status["address_state"]="none";r.status["application_reachable"]="unverified";r.status["bt_state"]="unverified";return r;}
static RadioReply scanned(int count){RadioReply r;r.ok=true;r.code="scan_requested";r.status["scan_freshness"]="unverified";for(int i=0;i<count;++i){WifiRow row;row.ssid=i==0?QString::fromUtf8("中文测试网络"):QString("Fixture AP %1").arg(i);row.signal="-42";row.security="wpa2";r.wifi<<row;}return r;}
// Actual enabled QWS LinuxInput path, fed synthetic kernel-shaped events only.
static void fifoTouch(int x,int y,bool pressed){
 int fd=::open("/tmp/pandanote-qws-input",O_WRONLY|O_NONBLOCK);CHECK("offline_input_fifo_open",fd>=0);if(fd<0)return;
 struct input_event events[4];memset(events,0,sizeof(events));
 events[0].type=EV_ABS;events[0].code=ABS_X;events[0].value=x;
 events[1].type=EV_ABS;events[1].code=ABS_Y;events[1].value=y;
 events[2].type=EV_KEY;events[2].code=BTN_TOUCH;events[2].value=pressed?1:0;
 events[3].type=EV_SYN;events[3].code=SYN_REPORT;
 CHECK("offline_input_fifo_write",::write(fd,events,sizeof(events))==int(sizeof(events)));::close(fd);
 QElapsedTimer deadline;deadline.start();while(deadline.elapsed()<40)QApplication::processEvents();
}
static QImage frame(ReaderShell &shell,const char *name) {
    QImage image(480,800,QImage::Format_RGB32);image.fill(0xffffffff);
    QPainter painter(&image);shell.render(&painter);painter.end();
    CHECK("actual_qt_frame_480x800",image.save(QString("/tmp/")+name+".png"));return image;
}
int main(int argc,char **argv) {
    QApplication app(argc,argv,QApplication::GuiServer);
    Content content;QString error;
    CHECK("load_gui_fixture",loadContent("/content-test/fixtures/valid",&content,&error));
    CHECK("qws_server_initial_cursor_visible",pandanoteQwsIsCursorVisible());
    FixtureRadio initialRadio;ObservedShell shell(content,&initialRadio);shell.show();app.processEvents();
    CHECK("qws_server_cursor_really_hidden",!pandanoteQwsIsCursorVisible());
    CHECK("qws_linux_input_handler_remains_enabled",pandanoteQwsMouseHandler()!=0);
    // Compare actual Qt-composited pixels with the packaged PNG, independently
    // of product drawing helpers. This region is reserved landscape on both
    // pages, below text and above their distinct footers.
    const QRect landscapeRegion(360,500,96,190);
    QImage landscapeAsset(QApplication::applicationDirPath()+"/assets/landscape-background.png");
    CHECK("landscape_asset_is_packaged_480x800",!landscapeAsset.isNull()&&landscapeAsset.size()==QSize(480,800));
    QImage referenceLandscape(480,800,QImage::Format_RGB32);referenceLandscape.fill(0xffffffff);
    {QPainter referencePainter(&referenceLandscape);referencePainter.drawImage(QPoint(0,0),landscapeAsset);}
    Content landscapeContent=content;landscapeContent.version="landscape-synthetic";landscapeContent.events.clear();
    ObservedShell landscapeUi(landscapeContent);landscapeUi.setTrustedTime(1792458000);
    QImage landscapeHome=frame(landscapeUi,"landscape-home-shared-asset");
    landscapeUi.shortPowerPress();QImage landscapeStandby=frame(landscapeUi,"landscape-standby-shared-asset");
    const QImage referencePatch=referenceLandscape.copy(landscapeRegion);
    const QImage homeLandscapePatch=landscapeHome.copy(landscapeRegion),standbyLandscapePatch=landscapeStandby.copy(landscapeRegion);
    int referenceInk=0;for(int y=0;y<referencePatch.height();++y)for(int x=0;x<referencePatch.width();++x)if(qRed(referencePatch.pixel(x,y))<245||qGreen(referencePatch.pixel(x,y))<245||qBlue(referencePatch.pixel(x,y))<245)++referenceInk;
    CHECK("landscape_reference_region_has_visible_ink",referenceInk>64);
    CHECK("home_really_draws_packaged_landscape",!landscapeAsset.isNull()&&homeLandscapePatch==referencePatch);
    CHECK("standby_really_draws_packaged_landscape",!landscapeAsset.isNull()&&standbyLandscapePatch==referencePatch);
    CHECK("home_and_standby_preserve_same_landscape_pixels",homeLandscapePatch==standbyLandscapePatch);
    // LinuxInput consumes global screen coordinates. The offline QWS window
    // decoration offsets its client (observed +4,+57), so map the intended
    // client hit point rather than treating raw screen coordinates as local.
    tap(shell,376,744);
    const QPoint nativeScheduleTap=shell.mapToGlobal(QPoint(120,200));
    CHECK("qws_raw_fixture_point_inside_offline_screen",QRect(0,0,800,480).contains(nativeScheduleTap));
    fifoTouch(nativeScheduleTap.x(),nativeScheduleTap.y(),true);
    CHECK("qws_input_press_delivers_intended_client_point",shell.lastMousePress==QPoint(120,200));
    CHECK("qws_input_press_does_not_navigate",shell.page()==Panel);
    fifoTouch(nativeScheduleTap.x(),nativeScheduleTap.y(),false);
    CHECK("qws_input_release_delivers_same_client_point",shell.lastMouseRelease==QPoint(120,200));
    CHECK("qws_input_release_still_navigates",shell.page()==Schedule);
    CHECK("qws_cursor_stays_hidden_after_input",!pandanoteQwsIsCursorVisible());
    tap(shell,440,76);CHECK("qws_input_fixture_returns_home",shell.page()==Home);
    shell.changes=0;
    CHECK("font_dependency_loaded",shell.fontReady());
    CHECK("cached_time_never_claims_today",shell.displayStatus().contains(QString::fromUtf8("缓存时间")));
    CHECK("cached_date_not_rtc",shell.displayDate()==QDate(2026,10,20));frame(shell,"home-cached");
    CHECK("trusted_time_is_explicit",shell.setTrustedTime(1792458000));
    CHECK("trusted_today_date",shell.displayDate()==QDate(2026,10,20));frame(shell,"home-current");
    CHECK("last_success_exact_timestamp",shell.displayStatus().contains("UTC"));
    shell.setTrustedTime(1794000000);
    CHECK("outside_day_table_cached_date",shell.displayDate()==QDate(2026,10,20));
    CHECK("outside_day_table_cached_status",shell.displayStatus().contains(QString::fromUtf8("缓存时间")));
    shell.setTrustedTime(1792458000);
    send(shell,QEvent::MouseButtonPress,376,744);
    CHECK("press_does_not_navigate",shell.page()==Home);
    send(shell,QEvent::MouseButtonRelease,376,744);
    CHECK("release_navigates_once",shell.page()==Panel && shell.changes==1 && shell.source=="release");int beforePanelPaint=shell.paintAcks;frame(shell,"panel");CHECK("panel_paint_does_not_ack_calendar",shell.paintAcks==beforePanelPaint);
    const char *names[]={"schedule","words","notes","control","info"};
    const int xs[]={120,360,120,360,120},ys[]={200,200,380,380,560};
    for(int i=0;i<5;++i) { tap(shell,xs[i],ys[i]);CHECK("gui_five_entries_open",shell.page()==Page(int(Schedule)+i));frame(shell,names[i]);tap(shell,40,76);CHECK("gui_five_entries_return",shell.page()==Panel); }
    if(initialRadio.busy()){initialRadio.finish(actualStatus());shell.fireRadio();}
    // Native settings and on-screen keyboard, real Qt handlers, simulated input.
    tap(shell,360,380);CHECK("native_settings_open",shell.page()==Control);frame(shell,"settings-wifi");
    CHECK("blank_cursor_override_is_only_a_shape_hint",QApplication::overrideCursor()&&QApplication::overrideCursor()->shape()==Qt::BlankCursor);
    RadioReply initialScan=scanned(1);initialRadio.finish(initialScan);shell.fireRadio();initialRadio.finish(actualStatus());shell.fireRadio();
    CHECK("list_first_has_no_credential_editor",!shell.inputActive());tap(shell,80,366);CHECK("row_opens_password_dialog",shell.inputActive()&&shell.inputValue(0)==QString::fromUtf8("中文测试网络"));
    for(int key=0;key<80;++key)tap(shell,32,505);CHECK("password_bound_and_plaintext_by_default",shell.inputValue(1)==QString(63,QChar('q')));QImage longPlain=frame(shell,"settings-keyboard");int plainOverflow=0;for(int y=350;y<398;++y)for(int x=0;x<15;++x)if(qRed(longPlain.pixel(x,y))<128||qRed(longPlain.pixel(479-x,y))<128)++plainOverflow;CHECK("long_plaintext_password_fits_field",plainOverflow==0);
    tap(shell,90,425);CHECK("cancel_dialog_erases_password",!shell.inputActive()&&shell.inputValue(1).isEmpty());tap(shell,80,366);tap(shell,32,505);
    tap(shell,40,76);CHECK("leaving_dialog_clears_secret",shell.page()==Panel&&shell.inputValue(1).isEmpty());
    tap(shell,360,380);tap(shell,230,180);frame(shell,"settings-bluetooth");
    tap(shell,385,180);frame(shell,"settings-sync");tap(shell,40,76);tap(shell,120,560);frame(shell,"device-info");tap(shell,40,76);
    tap(shell,40,76);CHECK("gui_return_home",shell.page()==Home);
    Content next;CHECK("load_next_event_fixture",loadContent("/content-test/fixtures/next-only",&next,&error));shell.setContent(next);shell.setTrustedTime(1792504200);QImage nextFrame=frame(shell,"home-next-event");
    CHECK("home_location_fixture_present",next.events.size()==1&&!next.events[0].location.isEmpty());
    Content nextWithoutLocation=next;nextWithoutLocation.version=next.version+"-without-location";if(!nextWithoutLocation.events.isEmpty())nextWithoutLocation.events[0].location.clear();shell.setContent(nextWithoutLocation);
    QImage nextWithoutLocationFrame=frame(shell,"home-next-event-without-location");
    int locationOnlyInk=0;for(int y=208;y<300;++y)for(int x=128;x<336;++x)if(qRed(nextFrame.pixel(x,y))<128&&qRed(nextWithoutLocationFrame.pixel(x,y))>=128)++locationOnlyInk;
    CHECK("home_location_when_space_allows",locationOnlyInk>10);
    CHECK("home_location_is_independent_of_event_title",nextFrame.copy(128,208,208,32)==nextWithoutLocationFrame.copy(128,208,208,32));
    CHECK("home_location_keeps_event_time_column",nextFrame.copy(44,208,76,92)==nextWithoutLocationFrame.copy(44,208,76,92));
    shell.setContent(content);shell.setTrustedTime(1792458000);
    Content defaultContent=content;defaultContent.version="default-bg";defaultContent.background.clear();shell.setContent(defaultContent);frame(shell,"home-default-background");
    Content empty=content;empty.version="empty";empty.events.clear();shell.setContent(empty);
    CHECK("no_events_distinct_copy",shell.homeMessage()==QString::fromUtf8("今天暂无日程"));frame(shell,"home-empty");
    shell.setSyncFailed(true);CHECK("stale_status",shell.displayStatus().contains(QString::fromUtf8("已过期")));frame(shell,"home-stale");
    Content absent;shell.setContent(absent);CHECK("never_synced_copy",shell.homeMessage()==QString::fromUtf8("尚未同步日历"));frame(shell,"home-never-synced");
    content.version="long-title";content.events[0].summary=QString(1365,QChar(0x65e5));shell.setContent(content);shell.setTrustedTime(1792458000);frame(shell,"home-long-title");
    QFontMetrics metrics(shell.font());QString chinese=QString::fromUtf8("应用首页返回日程单词卡阅读笔记设备控制信息看板功能准备中今天暂无尚未同步历缓存时间上次数据已过期年月星期全天会议室工作安排");
    for(int i=0;i<chinese.size();++i) CHECK("chinese_glyph_coverage",metrics.inFont(chinese[i]));
    tap(shell,376,744);tap(shell,120,200);
    send(shell,QEvent::MouseButtonPress,240,600);send(shell,QEvent::MouseButtonRelease,240,200);
    CHECK("schedule_swipe_keeps_page",shell.page()==Schedule);frame(shell,"schedule-scrolled");
    tap(shell,440,76);
    shell.clearTrustedTime();CHECK("invalidated_time_cached",shell.displayStatus().contains(QString::fromUtf8("缓存时间")));
    // Latest requested list -> modal -> explicit confirmation, plus real status lifecycle.
    FixtureRadio radio;ObservedShell wifi(content,&radio);wifi.show();tap(wifi,376,744);tap(wifi,360,380);
    CHECK("wifi_entry_scans_once_asynchronously",radio.actions.size()==1&&radio.actions.last()=="wifi-scan");
    RadioReply disconnected=actualStatus(),scan=scanned(64);radio.finish(scan);wifi.fireRadio();
    CHECK("scan_completion_requests_actual_status",radio.actions.last()=="status");radio.finish(disconnected);wifi.fireRadio();
    CHECK("default_list_does_not_prompt_for_password",!wifi.inputActive());
    tap(wifi,80,366);CHECK("exact_chinese_network_dialog",wifi.inputActive()&&wifi.inputValue(0)==QString::fromUtf8("中文测试网络"));
    int beforeCancel=radio.actions.size();tap(wifi,32,505);CHECK("dialog_password_plaintext",wifi.inputValue(1)=="q");frame(wifi,"wifi-password-dialog");tap(wifi,90,425);
    CHECK("cancel_never_connects_or_retains_secret",radio.actions.size()==beforeCancel&&wifi.inputValue(1).isEmpty()&&!wifi.inputActive());
    tap(wifi,80,366);for(int i=0;i<8;++i)tap(wifi,32,505);tap(wifi,360,425);
    CHECK("explicit_confirm_connects_exact_selected_network",radio.actions.last()=="wifi-connect"&&radio.connectedSsid==QString::fromUtf8("中文测试网络")&&radio.passwordBytes==8&&wifi.inputValue(1).isEmpty());
    CHECK("connect_does_not_claim_link_or_sync",wifi.syncs==0);
    RadioReply requested;requested.ok=true;requested.code="association_requested";radio.finish(requested);wifi.fireRadio();
    CHECK("connect_completion_requests_status",radio.actions.last()=="status"&&radio.overlaps==0);
    RadioReply associated=disconnected;associated.status["wifi_state"]="COMPLETED";radio.finish(associated);wifi.fireRadio();CHECK("association_without_ip_never_syncs",wifi.syncs==0);frame(wifi,"wifi-associated");
    wifi.now=2000;wifi.fireRadio(true);RadioReply connected=associated;connected.status["ipv4"]="192.0.2.7";connected.status["address_state"]="assigned";connected.wifiSsid="Fixture Associated";connected.status["wifi_ssid64"]="Rml4dHVyZSBBc3NvY2lhdGVk";connected.status["interface_name"]="wlan0";connected.status["interface_state"]="up";connected.status["netmask"]="255.255.255.0";connected.status["mac"]="02:00:5e:00:53:01";connected.status["gateway"]="192.0.2.1";radio.finish(connected);wifi.fireRadio();
    CHECK("fresh_completed_ip_syncs_once",wifi.syncs==1&&!radio.secretOnStatus);
    tap(wifi,240,280);CHECK("network_details_requests_read_only_status",radio.actions.last()=="status");radio.finish(connected);wifi.fireRadio();
    QString detail=wifi.networkStatusText();CHECK("network_details_uses_actual_associated_ssid",detail.contains("Fixture Associated")&&!detail.contains(QString::fromUtf8("中文测试网络")));CHECK("network_details_contains_actual_interface_fields",detail.contains("192.0.2.7")&&detail.contains("wlan0")&&detail.contains("255.255.255.0")&&detail.contains("02:00:5e:00:53:01")&&detail.contains("192.0.2.1"));frame(wifi,"wifi-network-status");
    int beforeDetail=radio.actions.size();tap(wifi,360,280);CHECK("network_details_refresh_does_not_connect_or_scan",radio.actions.size()==beforeDetail+1&&radio.actions.last()=="status");radio.finish(connected);wifi.fireRadio();tap(wifi,100,280);

    app.processEvents();int paints=wifi.paints;wifi.now=4000;wifi.fireRadio(true);radio.finish(connected);wifi.fireRadio();app.processEvents();CHECK("unchanged_status_neither_syncs_nor_repaints",wifi.syncs==1&&wifi.paints==paints);
    wifi.now=5000;wifi.fireRadio(true);RadioReply detailOnly=connected;detailOnly.status["gateway"]="192.0.2.254";radio.finish(detailOnly);wifi.fireRadio();app.processEvents();CHECK("invisible_network_detail_change_does_not_repaint_list",wifi.paints==paints);
    // Every retained result is reachable, and a swipe consumes its release.
    QString lastSelection=wifi.inputValue(0);int beforeSwipe=radio.actions.size();drag(wifi,600,252);
    CHECK("finger_swipe_never_selects_or_connects",wifi.inputValue(0)==lastSelection&&!wifi.inputActive()&&radio.actions.size()==beforeSwipe);
    tap(wifi,80,366);CHECK("scrolled_row_hit_uses_actual_offset",wifi.inputValue(0)=="Fixture AP 6"&&wifi.inputActive());tap(wifi,90,425);
    QImage scrolled=frame(wifi,"wifi-list-scrolled");wifi.now=6000;wifi.fireRadio(true);radio.finish(connected);wifi.fireRadio();QImage retained=frame(wifi,"wifi-list-status-retained");CHECK("status_preserves_scrolled_results",scrolled.copy(16,342,448,348)==retained.copy(16,342,448,348));
    drag(wifi,400,6000);tap(wifi,80,366);CHECK("finger_scroll_clamps_at_first_row",wifi.inputValue(0)==QString::fromUtf8("中文测试网络"));tap(wifi,90,425);
    for(int first=0;first<=60;first+=6){tap(wifi,80,366);int visible=qMin(first,58);QString want=visible?QString("Fixture AP %1").arg(visible):QString::fromUtf8("中文测试网络");CHECK("all_retained_first_rows_reachable",wifi.inputValue(0)==want);tap(wifi,90,425);int last=qMin(visible+5,63);tap(wifi,80,366+(last-visible)*58);CHECK("all_retained_last_rows_reachable",wifi.inputValue(0)==QString("Fixture AP %1").arg(last));tap(wifi,90,425);if(first<60)drag(wifi,600,252);}
    drag(wifi,600,-6000);tap(wifi,80,656);CHECK("finger_scroll_clamps_at_last_row",wifi.inputValue(0)=="Fixture AP 63");tap(wifi,90,425);frame(wifi,"wifi-list-bottom");
    QString selected=wifi.inputValue(0);tap(wifi,80,398);CHECK("row_gap_does_not_open_dialog",!wifi.inputActive()&&wifi.inputValue(0)==selected);
    // A scan result replacement invalidates a previously pressed row.
    tap(wifi,65,280);send(wifi,QEvent::MouseButtonPress,80,366);RadioReply replacement=scanned(1);replacement.wifi[0].ssid="Fixture Open";replacement.wifi[0].security="open";radio.finish(replacement);wifi.fireRadio();send(wifi,QEvent::MouseButtonRelease,80,366);CHECK("replaced_scan_cannot_select_stale_row",!wifi.inputActive()&&wifi.inputValue(1).isEmpty()&&wifi.inputValue(0)==selected);radio.finish(connected);wifi.fireRadio();
    int beforeOpen=radio.actions.size();tap(wifi,80,366);CHECK("open_network_requires_explicit_confirmation",radio.actions.size()==beforeOpen&&!wifi.inputActive());frame(wifi,"wifi-open-dialog");tap(wifi,360,425);CHECK("open_network_confirm_has_no_password",radio.actions.last()=="wifi-connect"&&radio.connectedSsid=="Fixture Open"&&radio.passwordBytes==0);
    radio.finish(requested);wifi.fireRadio();radio.finish(connected);wifi.fireRadio();
    tap(wifi,410,280);radio.finish(requested);wifi.fireRadio();CHECK("disconnect_requests_actual_status",radio.actions.last()=="status");radio.finish(disconnected);wifi.fireRadio();
    wifi.now=8000;wifi.fireRadio(true);RadioReply failed;failed.code="helper-failed";radio.finish(failed);wifi.fireRadio();int afterError=radio.actions.size();wifi.now=10000;wifi.fireRadio(true);CHECK("status_failure_stops_automatic_retry",radio.actions.size()==afterError&&wifi.fastTimers()==0);
    tap(wifi,230,180);tap(wifi,65,180);CHECK("returning_wifi_starts_one_new_scan",radio.actions.last()=="wifi-scan");radio.finish(replacement);wifi.fireRadio();radio.finish(connected);wifi.fireRadio();
    int beforeTab=radio.actions.size();tap(wifi,230,180);wifi.now=12000;wifi.fireRadio(true);CHECK("leaving_wifi_tab_stops_status",radio.actions.size()==beforeTab&&wifi.fastTimers()==0);
    tap(wifi,65,180);radio.finish(replacement);wifi.fireRadio();radio.finish(connected);wifi.fireRadio();CHECK("same_link_does_not_resync_after_tab_return",wifi.syncs==2);
    wifi.now=14000;wifi.fireRadio(true);int beforeBusy=radio.actions.size();tap(wifi,65,280);CHECK("background_status_cannot_overlap_refresh",radio.actions.size()==beforeBusy&&radio.overlaps==0);radio.finish(connected);wifi.fireRadio();radio.finish(replacement);wifi.fireRadio();radio.finish(connected);wifi.fireRadio();
    int beforeLeave=radio.actions.size();tap(wifi,40,76);wifi.now=16000;wifi.fireRadio(true);CHECK("leaving_settings_stops_status",radio.actions.size()==beforeLeave&&wifi.fastTimers()==0);
    tap(wifi,360,380);radio.finish(replacement);wifi.fireRadio();radio.finish(connected);wifi.fireRadio();int beforeExpiry=radio.actions.size();wifi.now=76000;wifi.fireRadio(true);CHECK("status_lifetime_is_bounded",radio.actions.size()==beforeExpiry&&wifi.fastTimers()==0);wifi.fireIdle();CHECK("status_refresh_does_not_reset_idle",wifi.page()==Home);
    tap(wifi,376,744);tap(wifi,360,380);tap(wifi,385,180);int beforeManual=wifi.syncs;tap(wifi,360,410);CHECK("manual_calendar_sync_remains_available",wifi.syncs==beforeManual+1);int beforeLate=radio.actions.size();radio.finish(disconnected);wifi.fireRadio();wifi.now=78000;wifi.fireRadio(true);CHECK("late_status_after_tab_exit_does_not_restart_polling",radio.actions.size()==beforeLate&&wifi.fastTimers()==0);
    // Parse real helper-shaped repeated APs before exercising actual row hit handlers.
    QByteArray groupedRaw="[reply]\nschema=1\nok=1\ncode=scan_requested\nmessage64=\n";
    for(int i=0;i<64;++i)groupedRaw+="[wifi"+QByteArray::number(i)+"]\nssid64="+QString("Grouped Fixture %1").arg(i/2).toUtf8().toBase64()+"\nsignal="+QByteArray::number(i%2?-30:-80)+"\nsecurity="+(i%2?"wpa":"wpa2")+"\n";
    RadioReply grouped;CHECK("gui_grouped_scan_fixture",parseRadioReply(groupedRaw,&grouped,&error)&&grouped.wifi.size()==32);
    FixtureRadio groupRadio;ObservedShell groupWifi(content,&groupRadio);tap(groupWifi,376,744);tap(groupWifi,360,380);groupRadio.finish(grouped);groupWifi.fireRadio();groupRadio.finish(actualStatus());groupWifi.fireRadio();
    tap(groupWifi,80,366);CHECK("grouped_first_row_selects_exact_ssid",groupWifi.inputValue(0)=="Grouped Fixture 0"&&groupWifi.inputActive());tap(groupWifi,90,425);drag(groupWifi,600,252);tap(groupWifi,80,366);CHECK("grouped_scroll_offset_hits_correct_network",groupWifi.inputValue(0)=="Grouped Fixture 6");tap(groupWifi,90,425);drag(groupWifi,600,-6000);tap(groupWifi,80,656);CHECK("grouped_scroll_clamps_to_last_group",groupWifi.inputValue(0)=="Grouped Fixture 31");tap(groupWifi,90,425);frame(groupWifi,"wifi-grouped-results");
    QByteArray mixedRaw="[reply]\nschema=1\nok=1\ncode=scan_requested\nmessage64=\n";const char *mixedSecurity[]={"wpa2","open","unsupported"};for(int i=0;i<3;++i)mixedRaw+="[wifi"+QByteArray::number(i)+"]\nssid64=Rml4dHVyZSBNaXhlZA==\nsignal=-30\nsecurity="+QByteArray(mixedSecurity[i])+"\n";
    RadioReply mixed;CHECK("gui_same_ssid_security_fixture",parseRadioReply(mixedRaw,&mixed,&error)&&mixed.wifi.size()==3);tap(groupWifi,65,280);groupRadio.finish(mixed);groupWifi.fireRadio();groupRadio.finish(actualStatus());groupWifi.fireRadio();frame(groupWifi,"wifi-grouped-security-families");
    int beforeProtected=groupRadio.actions.size();tap(groupWifi,80,366);CHECK("protected_group_opens_password_dialog",groupWifi.inputActive());tap(groupWifi,360,425);CHECK("empty_protected_password_cannot_connect_same_ssid_open",groupRadio.actions.size()==beforeProtected&&groupWifi.inputValue(1).isEmpty());
    tap(groupWifi,80,424);CHECK("separate_open_group_needs_no_password",!groupWifi.inputActive()&&groupRadio.actions.size()==beforeProtected);tap(groupWifi,360,425);CHECK("only_explicit_open_group_submits_empty_password",groupRadio.actions.last()=="wifi-connect"&&groupRadio.connectedSsid=="Fixture Mixed"&&groupRadio.passwordBytes==0);groupRadio.finish(requested);groupWifi.fireRadio();groupRadio.finish(actualStatus());groupWifi.fireRadio();tap(groupWifi,80,482);CHECK("unsupported_group_never_prompts_or_connects",!groupWifi.inputActive()&&groupRadio.actions.last()=="status");tap(groupWifi,90,425);
    FixtureRadio busyRadio;ObservedShell busyWifi(content,&busyRadio);tap(busyWifi,376,744);tap(busyWifi,360,380);busyRadio.finish(scanned(1));busyWifi.fireRadio();tap(busyWifi,80,366);for(int i=0;i<8;++i)tap(busyWifi,32,505);tap(busyWifi,360,425);CHECK("busy_submit_erases_password_without_queued_connect",busyWifi.inputValue(1).isEmpty()&&!busyWifi.inputActive()&&busyRadio.actions.last()=="status");
    CHECK("old_helper_network_fields_have_truthful_fallback",busyWifi.networkStatusText().contains(QString::fromUtf8("未提供"))&&!busyWifi.networkStatusText().contains(QString::fromUtf8("中文测试网络")));
    // Saving a profile is independent of subsequent association/IP observations.
    // A successful status or scan must not erase a failed durable-save result.
    FixtureRadio saveRadio;ObservedShell saveWifi(content,&saveRadio);tap(saveWifi,376,744);tap(saveWifi,360,380);
    saveRadio.finish(scanned(1));saveWifi.fireRadio();saveRadio.finish(connected);saveWifi.fireRadio();
    CHECK("profile_initial_state_is_unconfirmed",saveWifi.networkStatusText().contains(QString::fromUtf8("配置保存：未确认")));
    const char *saveErrors[]={"persistence_failed","persistence_uncertain","persistence_unavailable","control-unavailable"};
    for(int i=0;i<4;++i){
      tap(saveWifi,80,366);for(int k=0;k<8;++k)tap(saveWifi,32,505);tap(saveWifi,360,425);
      CHECK("new_connect_clears_old_save_result",saveWifi.networkStatusText().contains(QString::fromUtf8("等待配置保存结果"))&&!saveWifi.networkStatusText().contains(saveErrors[i]));
      RadioReply failed;failed.ok=false;failed.code=saveErrors[i];saveRadio.finish(failed);saveWifi.fireRadio();
      CHECK("save_error_visible_before_status",saveWifi.networkStatusText().contains(saveErrors[i]));
      saveRadio.finish(connected);saveWifi.fireRadio();
      CHECK("live_ip_does_not_hide_save_error",saveWifi.networkStatusText().contains(saveErrors[i])&&saveWifi.networkStatusText().contains("192.0.2.7"));
      tap(saveWifi,65,280);saveRadio.finish(scanned(1));saveWifi.fireRadio();saveRadio.finish(connected);saveWifi.fireRadio();
      CHECK("rescan_does_not_hide_save_error",saveWifi.networkStatusText().contains(saveErrors[i]));
    }
    tap(saveWifi,80,366);for(int k=0;k<8;++k)tap(saveWifi,32,505);tap(saveWifi,360,425);
    RadioReply saved;CHECK("durable_save_helper_reply_parses",parseRadioReply("[reply]\nschema=1\nok=1\ncode=association_requested\nmessage64=\n[status]\nsaved_network=pending_authentication\n",&saved,&error));
    saveRadio.finish(saved);saveWifi.fireRadio();
    CHECK("durable_save_does_not_claim_authentication",saveWifi.networkStatusText().contains(QString::fromUtf8("配置保存：已保存"))&&saveWifi.networkStatusText().contains(QString::fromUtf8("关联与 IP 尚未验证")));
    saveRadio.finish(connected);saveWifi.fireRadio();
    CHECK("actual_link_retains_saved_result",saveWifi.networkStatusText().contains(QString::fromUtf8("配置保存：已保存"))&&saveWifi.networkStatusText().contains("192.0.2.7"));
    frame(saveWifi,"wifi-profile-saved");
    tap(saveWifi,80,366);for(int k=0;k<8;++k)tap(saveWifi,32,505);tap(saveWifi,360,425);saveRadio.finish(requested);saveWifi.fireRadio();saveRadio.finish(connected);saveWifi.fireRadio();
    CHECK("legacy_volatile_connect_never_claims_saved",saveWifi.networkStatusText().contains(QString::fromUtf8("本次仅临时连接"))&&!saveWifi.networkStatusText().contains(QString::fromUtf8("配置保存：已保存")));
    frame(saveWifi,"wifi-profile-volatile");
    // Fake monotonic time + real widget mouse/timer handlers; SIMULATED offline only.
    ObservedShell race(content);race.now=0;tap(race,376,744);
    race.now=59900;send(race,QEvent::MouseButtonPress,120,200);
    CHECK("press_resets_without_navigation",race.page()==Panel && race.changes==1);
    race.now=60000;race.fireIdle();
    CHECK("press_spans_previous_idle_deadline",race.page()==Panel && race.changes==1);
    race.now=60200;send(race,QEvent::MouseButtonRelease,120,200);
    CHECK("release_after_old_deadline_navigates_once",race.page()==Schedule && race.changes==2 && race.source=="release");
    ObservedShell held(content);held.now=0;tap(held,376,744);
    held.now=59900;send(held,QEvent::MouseButtonPress,120,200);
    held.now=119899;held.fireIdle();CHECK("long_hold_before_new_deadline",held.page()==Panel);
    held.now=119900;held.fireIdle();CHECK("long_hold_expires_on_new_deadline",held.page()==Home && held.source=="idle");
    int afterIdle=held.changes;held.now=120200;send(held,QEvent::MouseButtonRelease,120,200);
    CHECK("stale_release_cannot_hit_new_page",held.page()==Home && held.changes==afterIdle);
    // The cancelled gesture remains cancelled even when the release is repeated.
    send(held,QEvent::MouseButtonRelease,376,744);
    CHECK("orphan_release_does_not_navigate",held.page()==Home && held.changes==afterIdle);
    const char *nonPersonal[]={"enterprise","wpa3","wep","unknown","WPA2",""};for(int j=0;j<6;++j){FixtureRadio denyRadio;ObservedShell deny(content,&denyRadio);tap(deny,376,744);tap(deny,360,380);RadioReply denied=scanned(1);denied.wifi[0].security=nonPersonal[j];denyRadio.finish(denied);deny.fireRadio();denyRadio.finish(actualStatus());deny.fireRadio();int count=denyRadio.actions.size();tap(deny,80,366);CHECK("all_unrecognized_security_refuses_dialog_and_connect",!deny.inputActive()&&denyRadio.actions.size()==count);}
    QString wsRoot="/tmp/local-apps-gui";::mkdir(wsRoot.toUtf8().constData(),0700);LocalApps seed;CHECK("gui_workspace_seed",seed.open(wsRoot)&&seed.importWords(QString::fromUtf8("book\t书\nread\t阅读\n").toUtf8()));
    ObservedShell local(content);CHECK("workspace_explicit",local.configureWorkspace(wsRoot));tap(local,376,744);tap(local,350,210);CHECK("words_entry_real",local.page()==Words);frame(local,"words-study");tap(local,240,300);tap(local,120,590);LocalApps inspect;CHECK("known_is_saved",inspect.open(wsRoot)&&inspect.words()[0].known);tap(local,240,665);tap(local,380,170);frame(local,"words-list");tap(local,40,76);tap(local,100,390);CHECK("notes_entry_real",local.page()==Notes);tap(local,240,645);CHECK("new_note_opens_editor",local.inputActive());tap(local,32,505);tap(local,78,505);CHECK("draft_ascii_typing",local.noteDraft()=="qw");local.now=60000;local.fireIdle();CHECK("draft_survives_idle",local.page()==Notes&&local.noteDraft()=="qw");tap(local,440,76);CHECK("home_does_not_discard_draft",local.page()==Notes&&local.noteDraft()=="qw");tap(local,350,415);CHECK("note_saved",inspect.open(wsRoot)&&inspect.notes().size()==1&&inspect.notes()[0].body=="qw");frame(local,"notes-list");tap(local,100,200);frame(local,"note-view");tap(local,100,645);tap(local,124,505);tap(local,100,415);CHECK("cancel_keeps_saved_note",inspect.open(wsRoot)&&inspect.notes()[0].body=="qw");tap(local,350,645);CHECK("delete_requires_confirm",inspect.open(wsRoot)&&inspect.notes().size()==1);tap(local,100,415);CHECK("delete_cancel_keeps_note",inspect.open(wsRoot)&&inspect.notes().size()==1);tap(local,350,645);tap(local,350,415);CHECK("delete_confirmed",inspect.open(wsRoot)&&inspect.notes().isEmpty());
    tap(local,240,645);tap(local,32,505);::chmod((wsRoot+"/notes").toUtf8().constData(),0500);tap(local,350,415);CHECK("save_failure_keeps_draft",local.noteDraft()=="q"&&local.inputActive());frame(local,"note-save-error");::chmod((wsRoot+"/notes").toUtf8().constData(),0700);tap(local,100,415);tap(local,40,76);tap(local,100,570);frame(local,"info-actual-status");CHECK("storage_truthful_unverified",local.workspaceStatus().contains(QString::fromUtf8("未核验")));
    QString longBody;for(int i=0;i<120;++i)longBody+=QString("Part%1 ").arg(i);longBody+="TAIL_UNICODE";QString longId;CHECK("long_note_seed",inspect.saveNote(QString(),longBody,&longId)&&local.configureWorkspace(wsRoot));tap(local,40,76);tap(local,100,390);tap(local,100,200);CHECK("long_note_first_page_bounded",!local.noteVisibleText().contains("TAIL_UNICODE"));for(int i=0;i<100;++i)tap(local,180,600);CHECK("single_line_long_note_reaches_tail",local.noteVisibleText().contains("TAIL_UNICODE"));frame(local,"note-long-tail");
    QString unicodeId;CHECK("unicode_edit_seed",inspect.saveNote(QString(),QString::fromUtf8("中文😀"),&unicodeId)&&local.configureWorkspace(wsRoot));tap(local,350,600);tap(local,100,260);tap(local,100,645);tap(local,338,750);CHECK("unicode_backspace_removes_whole_codepoint",local.noteDraft()==QString::fromUtf8("中文"));frame(local,"note-unicode-editor");tap(local,100,415);
    QString longFront;for(int i=0;i<125;++i)longFront+="W ";longFront+="ENDXYZ";QString visibilityRoot="/tmp/local-apps-visibility";::mkdir(visibilityRoot.toUtf8().constData(),0700);LocalApps visibilityStore;CHECK("visibility_fixture_root",visibilityStore.open(visibilityRoot)&&visibilityStore.importWords(longFront.toUtf8()+"\tshort back\n"));QString multiline;for(int i=0;i<10;++i)multiline+=QString("Line%1\n").arg(i);multiline+=QString::fromUtf8("末尾😀");QString multilineId;CHECK("visibility_note_seed",visibilityStore.saveNote(QString(),multiline,&multilineId));ObservedShell visibility(content);CHECK("visibility_workspace",visibility.configureWorkspace(visibilityRoot));tap(visibility,376,744);tap(visibility,350,210);for(int i=0;i<30;++i)drag(visibility,490,250);CHECK("front_swipe_keeps_front_and_reaches_final_marker",!visibility.wordBackShowing()&&visibility.wordScrollOffset()>0&&QString(visibility.wordVisibleText()).remove('\n').contains("ENDXYZ"));frame(visibility,"word-front-final-marker");tap(visibility,240,550);CHECK("front_flip_still_works",visibility.wordBackShowing()&&visibility.wordVisibleText()=="short back");tap(visibility,100,590);CHECK("front_fix_keeps_progress",visibilityStore.open(visibilityRoot)&&visibilityStore.words()[0].known);
    tap(visibility,40,76);tap(visibility,100,390);tap(visibility,100,200);tap(visibility,100,645);tap(visibility,32,505);QString visibleDraft=visibility.noteDraftVisibleText();QFont draftFont=visibility.font();draftFont.setPixelSize(20);int fitRows=qMax(1,90/QFontMetrics(draftFont).lineSpacing());CHECK("multiline_append_point_fits_viewport",visibleDraft.endsWith(QString::fromUtf8("末尾😀q"))&&visibleDraft.count('\n')+1<=fitRows);frame(visibility,"note-multiline-append-tail");tap(visibility,338,750);CHECK("multiline_backspace_remains_visible",visibility.noteDraftVisibleText().endsWith(QString::fromUtf8("末尾😀")));tap(visibility,338,750);CHECK("multiline_unicode_backspace_visible",visibility.noteDraftVisibleText().endsWith(QString::fromUtf8("末尾"))&&!visibility.noteDraft().contains(QChar(0xd83d)));frame(visibility,"note-multiline-backspace-tail");tap(visibility,100,415);
    if(qgetenv("PANDANOTE_BT_GUI_FIXTURE")=="1"){
      // A real listening Unix socket moves into the private parent only after UI startup.
      const char *lateParent="/tmp/bt-fixture/late-parent";
      const QString lateSocket=QString::fromLatin1(lateParent)+"/core.sock";
      ObservedShell delayed(content);
      CHECK("bt_delayed_initial_parent_absent",!QFile::exists(QString::fromLatin1(lateParent))&&!delayed.configureBluetooth(lateSocket));
      pumpBluetooth(delayed,20);
      CHECK("bt_delayed_never_creates_service_directory",!QFile::exists(QString::fromLatin1(lateParent)));
      CHECK("bt_delayed_public_parent_fixture",::mkdir(lateParent,0755)==0);
      pumpBluetooth(delayed,50);
      CHECK("bt_delayed_public_parent_refused",!QFile::exists("/tmp/bt-fixture/delayed.ops"));
      CHECK("bt_delayed_remove_public_parent",::rmdir(lateParent)==0);
      CHECK("bt_delayed_symlink_fixture",::symlink("late-ready",lateParent)==0);
      pumpBluetooth(delayed,50);
      CHECK("bt_delayed_symlink_parent_refused",!QFile::exists("/tmp/bt-fixture/delayed.ops"));
      CHECK("bt_delayed_remove_symlink",::unlink(lateParent)==0);
      CHECK("bt_delayed_private_service_arrives",::rename("/tmp/bt-fixture/late-ready",lateParent)==0);
      // Reconfiguration is rate-limited: no request before the monotonic retry deadline.
      pumpBluetooth(delayed,19);
      CHECK("bt_delayed_retry_not_per_tick",!QFile::exists("/tmp/bt-fixture/delayed.ops"));
      pumpBluetooth(delayed,70);
      QFile delayedOps("/tmp/bt-fixture/delayed.ops");
      CHECK("bt_delayed_real_service_rebound",delayedOps.open(QIODevice::ReadOnly)&&delayedOps.readAll().contains("2:0"));
      tap(delayed,376,744);tap(delayed,360,380);tap(delayed,230,180);tap(delayed,100,280);pumpBluetooth(delayed,100);
      CHECK("bt_delayed_pair_window_usable",delayed.bluetoothPending()&&delayed.bluetoothPasskey()=="000042");
      tap(delayed,350,280);pumpBluetooth(delayed,70);
      CHECK("bt_delayed_cancel_preserved",!delayed.bluetoothPending()&&!delayed.bluetoothActive());
      ObservedShell invalidBt(content);int baselineTimers=invalidBt.fastTimers();
      CHECK("bt_delayed_invalid_path_refused",!invalidBt.configureBluetooth("/tmp/bt-fixture/../late-parent/core.sock"));
      CHECK("bt_delayed_invalid_path_no_retry_timer",invalidBt.fastTimers()==baselineTimers);
      ObservedShell bt(content);CHECK("bt_gui_explicit_ipc",bt.configureBluetooth("/tmp/bt-fixture/ui.sock"));tap(bt,376,744);tap(bt,360,380);tap(bt,230,180);pumpBluetooth(bt,80);frame(bt,"bluetooth-service-state");tap(bt,100,280);pumpBluetooth(bt,160);CHECK("bt_gui_actual_pending_and_six_digits",bt.bluetoothPending()&&bt.bluetoothPasskey()=="000042"&&!bt.bluetoothActive());frame(bt,"bluetooth-pending-confirmation");CHECK("bt_gui_never_auto_approves",bt.bluetoothAppliedCount()==0);tap(bt,100,610);pumpBluetooth(bt,10);CHECK("bt_gui_empty_grants_never_authorize",bt.bluetoothPending()&&!bt.bluetoothActive());tap(bt,100,540);tap(bt,350,540);frame(bt,"bluetooth-local-grants-selected");tap(bt,100,610);pumpBluetooth(bt,300);CHECK("bt_gui_home_effect_applied",bt.page()==Home);CHECK("bt_gui_refresh_deduped_across_failed_ack",bt.syncs==1&&bt.bluetoothAppliedCount()==3);CHECK("bt_gui_file_notification_only",bt.bluetoothFileBytes()==123);QFile uiOps("/tmp/bt-fixture/ui.ops");CHECK("bt_gui_exact_local_grants_on_wire",uiOps.open(QIODevice::ReadOnly)&&uiOps.readAll().contains("3:261"));tap(bt,376,744);tap(bt,360,380);tap(bt,230,180);frame(bt,"bluetooth-active-file-receipt");tap(bt,350,280);pumpBluetooth(bt,100);CHECK("bt_gui_cancel_session",!bt.bluetoothActive()&&!bt.bluetoothPending());tap(bt,100,280);pumpBluetooth(bt,100);tap(bt,350,610);pumpBluetooth(bt,100);CHECK("bt_gui_explicit_deny",!bt.bluetoothPending()&&!bt.bluetoothActive());
      ObservedShell btTimeout(content);CHECK("bt_timeout_explicit_ipc",btTimeout.configureBluetooth("/tmp/bt-fixture/timeout.sock"));tap(btTimeout,376,744);tap(btTimeout,360,380);tap(btTimeout,230,180);tap(btTimeout,100,280);pumpBluetooth(btTimeout,180);QFile timeoutOps("/tmp/bt-fixture/timeout.ops");CHECK("bt_timeout_actual_cancel_sent",timeoutOps.open(QIODevice::ReadOnly)&&timeoutOps.readAll().contains("4:0"));CHECK("bt_timeout_never_approves",!btTimeout.bluetoothPending()&&!btTimeout.bluetoothActive()&&btTimeout.bluetoothAppliedCount()==0);
      QString btRoot="/tmp/bt-draft-workspace";::mkdir(btRoot.toUtf8().constData(),0700);ObservedShell btDraft(content);CHECK("bt_draft_explicit_configuration",btDraft.configureWorkspace(btRoot)&&btDraft.configureBluetooth("/tmp/bt-fixture/draft.sock"));tap(btDraft,376,744);tap(btDraft,360,380);tap(btDraft,230,180);tap(btDraft,100,280);pumpBluetooth(btDraft,100);tap(btDraft,100,540);tap(btDraft,350,540);tap(btDraft,100,610);pumpBluetooth(btDraft,10);CHECK("bt_draft_session_approved",btDraft.bluetoothActive());tap(btDraft,40,76);tap(btDraft,100,390);tap(btDraft,240,645);tap(btDraft,32,505);pumpBluetooth(btDraft,120);CHECK("bt_home_waits_for_saved_or_cancelled_draft",btDraft.page()==Notes&&btDraft.noteDraft()=="q"&&btDraft.bluetoothAppliedCount()==0);QFile draftOps("/tmp/bt-fixture/draft.ops");CHECK("bt_home_not_acked_before_application",draftOps.open(QIODevice::ReadOnly)&&!draftOps.readAll().contains("5:258\n"));tap(btDraft,100,415);pumpBluetooth(btDraft,240);CHECK("bt_deferred_home_then_ack",btDraft.page()==Home&&btDraft.bluetoothAppliedCount()==3&&btDraft.syncs==1);CHECK("bt_file_never_imports_payload",!QFile::exists(btRoot+"/words/data")&&!QFile::exists(btRoot+"/notes/data"));
    }
    if(qgetenv("PANDANOTE_BT_GUI_FIXTURE")=="1"){
      const char *shortSessions[]={"expired-home","expired-refresh","expired-file","expired-zero"};for(int i=0;i<4;++i){ObservedShell expired(content);QString name=QString::fromLatin1(shortSessions[i]);CHECK("expired_fixture_configuration",expired.configureBluetooth("/tmp/bt-fixture/"+name+".sock"));tap(expired,376,744);tap(expired,360,380);tap(expired,230,180);tap(expired,100,280);pumpBluetooth(expired,100);tap(expired,100,540);tap(expired,350,540);tap(expired,100,610);pumpBluetooth(expired,240);CHECK("expired_fresh_effect_never_applies",expired.page()==Control&&expired.syncs==0&&expired.bluetoothAppliedCount()==0&&expired.bluetoothFileBytes()==0);QFile ops("/tmp/bt-fixture/"+name+".ops");CHECK("expired_fixture_operations_readable",ops.open(QIODevice::ReadOnly));QByteArray raw=ops.readAll();CHECK("expired_effect_never_acked_and_session_closed",!raw.contains("5:258\n")&&raw.contains("4:0\n"));}
      QString expiryRoot="/tmp/bt-expired-draft";::mkdir(expiryRoot.toUtf8().constData(),0700);ObservedShell expiredDraft(content);CHECK("expired_deferred_configuration",expiredDraft.configureWorkspace(expiryRoot)&&expiredDraft.configureBluetooth("/tmp/bt-fixture/expired-deferred.sock"));tap(expiredDraft,376,744);tap(expiredDraft,360,380);tap(expiredDraft,230,180);tap(expiredDraft,100,280);pumpBluetooth(expiredDraft,100);tap(expiredDraft,100,540);tap(expiredDraft,350,540);tap(expiredDraft,100,610);pumpBluetooth(expiredDraft,10);tap(expiredDraft,40,76);tap(expiredDraft,100,390);tap(expiredDraft,240,645);tap(expiredDraft,32,505);pumpBluetooth(expiredDraft,220);CHECK("expired_deferred_keeps_draft",expiredDraft.page()==Notes&&expiredDraft.noteDraft()=="q"&&expiredDraft.bluetoothAppliedCount()==0);tap(expiredDraft,100,415);pumpBluetooth(expiredDraft,120);QFile expiredOps("/tmp/bt-fixture/expired-deferred.ops");CHECK("expired_deferred_never_applies_or_acks",expiredDraft.page()==Notes&&expiredDraft.bluetoothAppliedCount()==0&&expiredOps.open(QIODevice::ReadOnly)&&!expiredOps.readAll().contains("5:258\n"));frame(expiredDraft,"bluetooth-expired-draft-retained");
    }

    // A system UI: real widget rendering and real input handlers, simulated transport only.
    Content uiContent;CHECK("ui_fixture",loadContent("/content-test/fixtures/valid",&uiContent,&error));
    FixtureRadio uiRadio;ObservedShell ui(uiContent,&uiRadio);ui.show();ui.setTrustedTime(1792458000);app.processEvents();
    QImage uiHome=frame(ui,"a-home-implemented");
    tap(ui,376,744);CHECK("a_home_primary_button_opens_apps",ui.page()==Panel);
    frame(ui,"a-apps-implemented");
    tap(ui,30,190);CHECK("a_app_whitespace_is_touchable",ui.page()==Schedule);
    tap(ui,40,76);CHECK("a_subpage_back_returns_apps",ui.page()==Panel);
    tap(ui,40,76);CHECK("a_apps_back_returns_home",ui.page()==Home);
    send(ui,QEvent::MouseButtonPress,240,20);app.processEvents();int gesturePaints=ui.paints;
    send(ui,QEvent::MouseMove,240,180);app.processEvents();
    CHECK("a_drag_has_no_follow_finger_redraw",ui.paints==gesturePaints);
    send(ui,QEvent::MouseButtonRelease,240,180);app.processEvents();
    int ackBeforePanel=ui.paintAcks;QImage uiOverlay=frame(ui,"a-system-panel-implemented");
    CHECK("a_drag_opens_overlay_without_navigation",ui.page()==Home&&uiOverlay.copy(0,40,480,360)!=uiHome.copy(0,40,480,360));
    CHECK("a_overlay_does_not_ack_calendar",ui.paintAcks==ackBeforePanel);
    CHECK("a_overlay_preserves_lower_app_pixels",uiOverlay.copy(0,400,480,400)==uiHome.copy(0,400,480,400));
    tap(ui,376,744);CHECK("a_outside_dismiss_never_clicks_through",ui.page()==Home);
    CHECK("a_dismiss_restores_home_pixels",frame(ui,"a-home-restored")==uiHome);
    tap(ui,376,744);CHECK("a_second_tap_activates_app",ui.page()==Panel);
    QImage appsBeforeOverlay=frame(ui,"a-apps-before-overlay");tap(ui,240,20);
    tap(ui,300,401);CHECK("a_outside_boundary_keeps_apps",ui.page()==Panel);
    CHECK("a_apps_context_survives_overlay",frame(ui,"a-apps-restored")==appsBeforeOverlay);
    tap(ui,240,20);int syncBefore=ui.syncs;tap(ui,350,180);tap(ui,350,180);
    CHECK("a_repeated_sync_is_not_resubmitted",ui.syncs==syncBefore+1);
    ui.setSyncActivity(false);tap(ui,350,180);
    CHECK("a_sync_completion_reenables_action",ui.syncs==syncBefore+2);
    ui.setSyncActivity(false);
    send(ui,QEvent::MouseButtonPress,240,300);send(ui,QEvent::MouseButtonRelease,240,200);
    CHECK("a_swipe_up_restores_apps",frame(ui,"a-apps-after-up")==appsBeforeOverlay);
    tap(ui,240,20);tap(ui,350,280);CHECK("a_system_settings_open_existing_control",ui.page()==Control);
    tap(ui,40,76);CHECK("a_settings_return_to_origin_apps",ui.page()==Panel);
    app.processEvents();int unchangedPaints=ui.paints;ui.refreshTime();ui.refreshTime();app.processEvents();
    CHECK("a_unchanged_time_does_not_redraw",ui.paints==unchangedPaints);
    FixtureRadio draftUiRadio;ObservedShell draftUi(uiContent,&draftUiRadio);
    CHECK("a_draft_workspace",draftUi.configureWorkspace(wsRoot));
    tap(draftUi,376,744);tap(draftUi,120,380);tap(draftUi,240,645);tap(draftUi,32,505);
    CHECK("a_draft_editor_ready",draftUi.page()==Notes&&draftUi.inputActive()&&draftUi.noteDraft()=="q");
    QImage editorBeforeOverlay=frame(draftUi,"a-editor-before-overlay");tap(draftUi,240,20);
    QImage editorOverlay=frame(draftUi,"a-editor-with-overlay");
    CHECK("a_editor_overlay_preserves_lower_pixels",editorOverlay.copy(0,400,480,400)==editorBeforeOverlay.copy(0,400,480,400));
    tap(draftUi,32,505);
    CHECK("a_editor_outside_tap_only_dismisses",draftUi.page()==Notes&&draftUi.inputActive()&&draftUi.noteDraft()=="q");
    CHECK("a_editor_dismiss_restores_pixels",frame(draftUi,"a-editor-after-dismiss")==editorBeforeOverlay);
    tap(draftUi,32,505);CHECK("a_editor_input_resumes_after_dismiss",draftUi.noteDraft()=="qq");
    QImage editorBeforeSettings=frame(draftUi,"a-editor-before-settings");
    tap(draftUi,240,20);tap(draftUi,350,280);
    CHECK("a_editor_can_open_system_settings",draftUi.page()==Control&&draftUi.noteDraft()=="qq");
    tap(draftUi,40,76);
    CHECK("a_settings_restore_editor_input",draftUi.page()==Notes&&draftUi.inputActive()&&draftUi.noteDraft()=="qq");
    CHECK("a_settings_restore_editor_pixels",frame(draftUi,"a-editor-after-settings")==editorBeforeSettings);
    // Power standby locks the complete touch sequence and wakes to Home.
    ObservedShell powerUi(uiContent);powerUi.show();app.processEvents();tap(powerUi,376,744);
    send(powerUi,QEvent::MouseButtonPress,120,200);powerUi.shortPowerPress();
    CHECK("power_short_enters_standby",powerUi.standby()&&!powerUi.shuttingDown());
    app.processEvents();int sleepPaints=powerUi.paints,powerAcks=powerUi.paintAcks;
    tap(powerUi,376,744);send(powerUi,QEvent::MouseMove,240,170);send(powerUi,QEvent::MouseButtonRelease,120,200);powerUi.refreshTime();app.processEvents();
    CHECK("power_standby_consumes_touch",powerUi.page()==Panel);
    CHECK("power_standby_no_periodic_repaint",powerUi.paints==sleepPaints&&powerUi.paintAcks==powerAcks);
    frame(powerUi,"a-standby");powerUi.shortPowerPress();
    CHECK("power_wake_home",!powerUi.standby()&&powerUi.page()==Home);
    send(powerUi,QEvent::MouseButtonRelease,376,744);CHECK("power_wake_no_release_clickthrough",powerUi.page()==Home);
    powerUi.longPowerPress();CHECK("power_long_requests_shutdown_once",powerUi.shutdowns==1&&powerUi.shuttingDown());
    powerUi.longPowerPress();powerUi.shortPowerPress();CHECK("power_shutdown_latches",powerUi.shutdowns==1&&powerUi.shuttingDown());
    ObservedShell powerFailed(uiContent);powerFailed.shutdownOk=false;powerFailed.longPowerPress();
    CHECK("power_failed_shutdown_remains_usable",!powerFailed.shuttingDown()&&powerFailed.standby());
    powerFailed.shortPowerPress();CHECK("power_failed_shutdown_wakes_home",powerFailed.page()==Home&&!powerFailed.standby());
    // Standby/shutdown draft survives a fresh LocalApps/ReaderShell instance.
    ObservedShell unsafeDraft(uiContent);tap(unsafeDraft,376,744);tap(unsafeDraft,120,380);tap(unsafeDraft,240,645);tap(unsafeDraft,32,505);
    CHECK("power_fixture_has_unsaved_draft",unsafeDraft.noteDraft()=="q");unsafeDraft.longPowerPress();
    CHECK("power_unconfigured_draft_blocks_shutdown",unsafeDraft.shutdowns==0&&!unsafeDraft.shuttingDown()&&unsafeDraft.noteDraft()=="q");
    const QString powerRoot="/tmp/gui-power-draft";::mkdir(powerRoot.toUtf8().constData(),0700);
    ObservedShell durableDraft(uiContent);CHECK("power_workspace_open",durableDraft.configureWorkspace(powerRoot));
    tap(durableDraft,376,744);tap(durableDraft,120,380);tap(durableDraft,240,645);tap(durableDraft,32,505);durableDraft.shortPowerPress();
    CHECK("power_draft_standby_saved",durableDraft.standby()&&durableDraft.noteDraft()=="q");
    {ObservedShell restarted(uiContent);CHECK("power_draft_survives_restart",restarted.configureWorkspace(powerRoot)&&restarted.noteDraft()=="q");}
    durableDraft.shortPowerPress();durableDraft.now=300;tap(durableDraft,376,744);tap(durableDraft,120,380);
    CHECK("power_draft_can_resume_after_wake",durableDraft.page()==Notes&&durableDraft.noteDraft()=="q");
    tap(durableDraft,100,415);CHECK("power_explicit_cancel_clears_memory",durableDraft.noteDraft().isEmpty());
    {ObservedShell restarted(uiContent);CHECK("power_cancel_clears_persistent_draft",restarted.configureWorkspace(powerRoot)&&restarted.noteDraft().isEmpty());}
    const QString powerFailRoot="/tmp/gui-power-storage-fail";::mkdir(powerFailRoot.toUtf8().constData(),0700);
    ObservedShell sleepFailure(uiContent);sleepFailure.show();app.processEvents();CHECK("power_failure_workspace",sleepFailure.configureWorkspace(powerFailRoot));
    tap(sleepFailure,376,744);tap(sleepFailure,120,380);tap(sleepFailure,240,645);tap(sleepFailure,32,505);sleepFailure.shortPowerPress();
    CHECK("power_failure_initial_standby",sleepFailure.standby());int failurePaints=sleepFailure.paints;
    CHECK("power_failure_permissions_changed",::chmod((powerFailRoot+"/notes/draft/data").toUtf8().constData(),0644)==0);
    sleepFailure.longPowerPress();CHECK("power_storage_failure_never_shutdowns",sleepFailure.shutdowns==0&&!sleepFailure.shuttingDown()&&sleepFailure.standby());
    CHECK("power_storage_failure_paints_error_while_locked",sleepFailure.paints>failurePaints);
    // Explicit hardware refresh is one request; repeat taps are rate limited.
    ObservedShell refreshUi(uiContent);tap(refreshUi,240,20);QImage refreshBefore=frame(refreshUi,"a-full-refresh-before");
    tap(refreshUi,120,280);CHECK("a_refresh_requests_hardware",refreshUi.fullRefreshes==1);
    CHECK("a_refresh_keeps_page",refreshUi.page()==Home);
    QImage refreshAfter=frame(refreshUi,"a-full-refresh-after");CHECK("a_refresh_reports_result",refreshBefore!=refreshAfter);
    tap(refreshUi,120,280);CHECK("a_refresh_debounces_repeat",refreshUi.fullRefreshes==1);
    refreshUi.now=2000;refreshUi.fullResult=EinkRefreshUnavailable;tap(refreshUi,120,280);
    CHECK("a_refresh_can_retry_after_cooldown",refreshUi.fullRefreshes==2);
    CHECK("a_refresh_unavailable_keeps_drawer",frame(refreshUi,"a-full-refresh-unavailable")!=refreshAfter);
    tap(refreshUi,376,744);CHECK("a_refresh_outside_does_not_navigate",refreshUi.page()==Home);
    // Settings opened from the drawer lose their origin when idle returns Home.
    FixtureRadio idleSettingsRadio;ObservedShell idleSettings(uiContent,&idleSettingsRadio);
    tap(idleSettings,376,744);tap(idleSettings,120,200);tap(idleSettings,240,20);tap(idleSettings,350,280);
    CHECK("a_idle_settings_origin_is_schedule",idleSettings.page()==Control);
    idleSettings.now=60000;int idleSettingsTimers=0;
    QList<QAbstractEventDispatcher::TimerInfo> settingsTimers=QAbstractEventDispatcher::instance()->registeredTimers(&idleSettings);
    for(int i=0;i<settingsTimers.size();++i)if(settingsTimers[i].second==60000){++idleSettingsTimers;QTimerEvent e(settingsTimers[i].first);QApplication::sendEvent(&idleSettings,&e);}
    CHECK("a_idle_settings_has_one_idle_timer",idleSettingsTimers==1);
    CHECK("a_idle_settings_reaches_home",idleSettings.page()==Home);
    tap(idleSettings,376,744);tap(idleSettings,360,380);tap(idleSettings,40,76);
    CHECK("a_normal_settings_back_has_no_stale_drawer_origin",idleSettings.page()==Panel);
    // Drawer Wi-Fi switches an existing settings tab and repaints its exposed lower half.
    FixtureRadio tabRadio;ObservedShell tabUi(uiContent,&tabRadio);tabUi.show();app.processEvents();
    tap(tabUi,376,744);tap(tabUi,360,380);tabRadio.finish(scanned(1));tabUi.fireRadio();tabRadio.finish(actualStatus());tabUi.fireRadio();
    const int settingsTabs[]={230,385};
    for(int tab=0;tab<2;++tab){
        tap(tabUi,settingsTabs[tab],180);app.processEvents();
        QImage oldSettingsTab=frame(tabUi,tab==0?"a-bluetooth-before-drawer-wifi":"a-sync-before-drawer-wifi");
        tap(tabUi,240,20);if(tabRadio.busy()){tabRadio.finish(actualStatus());tabUi.fireRadio();}app.processEvents();tabUi.paintedRegion=QRegion();int radioBeforeDrawerWifi=tabRadio.actions.size();
        tap(tabUi,120,180);app.processEvents();
        CHECK("a_drawer_wifi_restarts_actual_status_lifecycle",tabRadio.actions.size()==radioBeforeDrawerWifi+1&&tabRadio.actions.last()=="wifi-scan");
        CHECK("a_drawer_wifi_repaints_lower_settings",tabUi.paintedRegion.contains(QRect(0,400,480,400)));
        QImage wifiFromDrawer=frame(tabUi,tab==0?"a-wifi-from-bluetooth":"a-wifi-from-sync");
        CHECK("a_drawer_wifi_displays_existing_wifi_tab",wifiFromDrawer.copy(12,154,144,52)!=oldSettingsTab.copy(12,154,144,52));
        if(tabRadio.busy()){tabRadio.finish(scanned(1));tabUi.fireRadio();tabRadio.finish(actualStatus());tabUi.fireRadio();}
    }
    // Compact Apps target excludes its former empty left area while retaining an easy edge target.
    ObservedShell compactEntry(uiContent);
    tap(compactEntry,343,752);CHECK("compact_apps_outside_does_not_open",compactEntry.page()==Home);
    if(compactEntry.page()==Panel)tap(compactEntry,40,76);
    tap(compactEntry,344,752);CHECK("compact_apps_expanded_left_edge_opens",compactEntry.page()==Panel);
    tap(compactEntry,40,76);tap(compactEntry,376,744);
    CHECK("compact_apps_existing_point_still_opens",compactEntry.page()==Panel);
    // Completion changes the visible Home footer without an explicit render call.
    ObservedShell footerUi(uiContent);footerUi.show();footerUi.setSyncActivity(true);app.processEvents();
    QImage activeFooter=frame(footerUi,"a-home-sync-active");footerUi.paintedRegion=QRegion();int footerPaints=footerUi.paints;
    footerUi.setSyncActivity(false);app.processEvents();
    CHECK("a_sync_completion_repaints_home_footer",footerUi.paints>footerPaints&&footerUi.paintedRegion.contains(QRect(60,724,220,56)));
    CHECK("a_sync_completion_clears_visible_footer_status",frame(footerUi,"a-home-sync-complete").copy(60,724,220,56)!=activeFooter.copy(60,724,220,56));
    FixtureRadio sleepRadio;ObservedShell sleepNetwork(uiContent,&sleepRadio);tap(sleepNetwork,376,744);tap(sleepNetwork,360,380);
    for(int i=0;i<5&&sleepRadio.busy();++i){sleepRadio.finish(actualStatus());sleepNetwork.fireRadio();}
    CHECK("standby_radio_fixture_idle",!sleepRadio.busy());int beforeStandbyRequests=sleepRadio.actions.size();
    sleepNetwork.shortPowerPress();sleepNetwork.now=10000;sleepNetwork.fireRadio(true);sleepNetwork.fireBluetooth();
    CHECK("standby_does_not_start_radio_requests",sleepRadio.actions.size()==beforeStandbyRequests);
    ::mkdir("/tmp/system-resume-workspace",0700);ObservedShell systemWake(uiContent);CHECK("system_resume_workspace",systemWake.configureWorkspace("/tmp/system-resume-workspace"));
    systemWake.shortPowerPress();CHECK("system_resume_starts_standby",systemWake.standby());
    systemWake.systemStandbyCompleted(true);CHECK("system_resume_returns_home",!systemWake.standby()&&systemWake.page()==Home);
    systemWake.now+=300;systemWake.shortPowerPress();systemWake.systemStandbyCompleted(false);
    CHECK("system_resume_failure_unlocks_home",!systemWake.standby()&&systemWake.page()==Home);frame(systemWake,"suspend-rejected-home");
    Content compactContent=content;compactContent.events[4].summary=QString::fromUtf8("第五条日程");
    ObservedShell compactUi(compactContent);compactUi.setTrustedTime(1792458000);
    CHECK("compact_home_selects_five",selectUpcomingEvents(compactContent,1792458000,QDate(2026,10,20)).size()==5);
    QImage compactHome=frame(compactUi,"compact-home-five");
    compactContent.events[4].summary=QString::fromUtf8("第五条已更新");compactContent.version="compact-v2";compactUi.setContent(compactContent);
    QImage updatedHome=frame(compactUi,"compact-home-fifth-updated");
    CHECK("compact_home_fifth_visible",compactHome.copy(24,576,432,92)!=updatedHome.copy(24,576,432,92));
    CHECK("compact_home_fifth_cannot_overflow_footer",compactHome.copy(0,696,480,104)==updatedHome.copy(0,696,480,104));
    tap(compactUi,240,650);CHECK("compact_fifth_row_opens_schedule",compactUi.page()==Schedule);
    QImage compactAgenda=frame(compactUi,"compact-schedule-five");
    compactContent.events[4].summary=QString::fromUtf8("第五条再次更新");compactContent.version="compact-v3";compactUi.setContent(compactContent);
    CHECK("compact_schedule_fifth_visible",compactAgenda.copy(24,584,432,108)!=frame(compactUi,"compact-schedule-fifth-updated").copy(24,584,432,108));
    QImage compactAgendaStart=frame(compactUi,"compact-schedule-start");
    drag(compactUi,650,140);CHECK("compact_schedule_next_reaches_end",frame(compactUi,"compact-schedule-last")!=compactAgendaStart);
    drag(compactUi,140,650);CHECK("compact_schedule_returns_first",frame(compactUi,"compact-schedule-returned")==compactAgendaStart);
    // Synthetic-only standby agenda: visible nearest three, never a live source.
    Content standbyContent=content;standbyContent.version="standby-synthetic-v1";
    standbyContent.events[0].summary=QString::fromUtf8("项目进展沟通");standbyContent.events[0].location=QString::fromUtf8("线上会议");
    standbyContent.events[1].summary=QString::fromUtf8("团队学习日");standbyContent.events[1].location=QString::fromUtf8("一楼活动室");
    standbyContent.events[2].summary=QString::fromUtf8("产品方案讨论与下周工作安排及重要事项确认");standbyContent.events[2].location=QString::fromUtf8("会议室 A");
    // Readable synthetic previews, separate from the deliberately oversized
    // strings used by the truncation and fifth-row visibility assertions.
    Content landscapePreview=standbyContent;landscapePreview.version="landscape-preview-five";
    landscapePreview.events[3].summary=QString::fromUtf8("周报整理");landscapePreview.events[3].location=QString::fromUtf8("办公区");
    landscapePreview.events[4].summary=QString::fromUtf8("客户需求回顾");landscapePreview.events[4].location=QString::fromUtf8("会议室 B");
    ObservedShell landscapeFive(landscapePreview);landscapeFive.setTrustedTime(1792458000);frame(landscapeFive,"landscape-home-five-synthetic");
    Content landscapeTwo=landscapePreview;landscapeTwo.version="landscape-preview-two";while(landscapeTwo.events.size()>2)landscapeTwo.events.removeLast();
    ObservedShell landscapeTwoUi(landscapeTwo);landscapeTwoUi.setTrustedTime(1792458000);frame(landscapeTwoUi,"landscape-home-two-synthetic");
    Content landscapeLong=standbyContent;landscapeLong.version="landscape-preview-long-crossday";
    landscapeLong.events[0].summary=QString::fromUtf8("跨日项目复盘与下一阶段的工作安排讨论");
    landscapeLong.events[0].end.epoch+=86400;landscapeLong.events[0].end.localDate=landscapeLong.events[0].end.localDate.addDays(1);
    landscapeLong.events[1].end.epoch+=2*86400;landscapeLong.events[1].end.localDate=landscapeLong.events[1].end.localDate.addDays(2);
    ObservedShell landscapeLongUi(landscapeLong);landscapeLongUi.setTrustedTime(1792458000);landscapeLongUi.shortPowerPress();frame(landscapeLongUi,"landscape-standby-long-crossday-synthetic");
    ObservedShell agendaSleep(standbyContent);agendaSleep.setTrustedTime(1792458000);agendaSleep.show();app.processEvents();
    int beforeStandbyAck=agendaSleep.paintAcks;agendaSleep.shortPowerPress();app.processEvents();
    CHECK("standby_agenda_real_paint_acks_content",agendaSleep.paintAcks>beforeStandbyAck);
    QImage standbyThree=frame(agendaSleep,"standby-agenda-three-synthetic");
    Content thirdChanged=standbyContent;thirdChanged.version="standby-third-changed";thirdChanged.events[2].summary=QString::fromUtf8("第三项已更新");
    ObservedShell changedThird(thirdChanged);changedThird.setTrustedTime(1792458000);changedThird.shortPowerPress();
    CHECK("standby_third_event_is_visible",standbyThree.copy(0,40,480,656)!=frame(changedThird,"standby-agenda-third-changed").copy(0,40,480,656));
    Content fourthChanged=standbyContent;fourthChanged.version="standby-fourth-changed";fourthChanged.events[3].summary=QString::fromUtf8("第四项不可显示");fourthChanged.events[5].summary=QString::fromUtf8("已结束不可显示");
    ObservedShell hiddenFourth(fourthChanged);hiddenFourth.setTrustedTime(1792458000);hiddenFourth.shortPowerPress();
    CHECK("standby_only_nearest_three_and_no_ended_events",standbyThree==frame(hiddenFourth,"standby-agenda-hidden-fourth"));
    Content noAgenda=standbyContent;noAgenda.version="standby-empty";noAgenda.events.clear();ObservedShell emptySleep(noAgenda);emptySleep.setTrustedTime(1792458000);emptySleep.shortPowerPress();
    CHECK("standby_empty_state_differs_from_events",standbyThree.copy(0,160,480,520)!=frame(emptySleep,"standby-agenda-empty").copy(0,160,480,520));
    ObservedShell cachedSleep(standbyContent);cachedSleep.shortPowerPress();
    CHECK("standby_cached_state_is_explicit",standbyThree.copy(0,128,480,72)!=frame(cachedSleep,"standby-agenda-cached").copy(0,128,480,72));
    ObservedShell statusDamage(standbyContent);statusDamage.setTrustedTime(1792458000);statusDamage.show();settleEvents();int statusAcks=statusDamage.paintAcks;statusDamage.paintedRegion=QRegion();
    statusDamage.setTrustedTime(1792458060);settleEvents();
    if(statusDamage.windowSurface())fprintf(stdout,"QT_SURFACE partial=%d size=%dx%d widget=%dx%d\n",statusDamage.windowSurface()->hasPartialUpdateSupport(),statusDamage.windowSurface()->geometry().width(),statusDamage.windowSurface()->geometry().height(),statusDamage.width(),statusDamage.height());
    fprintf(stdout,"QT_PAINT_DAMAGE home %d,%d %dx%d\n",statusDamage.paintedRegion.boundingRect().x(),statusDamage.paintedRegion.boundingRect().y(),statusDamage.paintedRegion.boundingRect().width(),statusDamage.paintedRegion.boundingRect().height());
    CHECK("clock_change_home_only_top40_damage",!statusDamage.paintedRegion.isEmpty()&&statusDamage.paintedRegion.subtracted(QRegion(QRect(0,0,480,40))).isEmpty());
    CHECK("status_only_paint_never_acks_calendar",statusDamage.paintAcks==statusAcks);
    CHECK("qt_surface_matches_undecorated_production",statusDamage.windowSurface()&&statusDamage.windowSurface()->geometry().size()==statusDamage.size()&&statusDamage.windowSurface()->hasPartialUpdateSupport());
    statusDamage.paintedRegion=QRegion();statusAcks=statusDamage.paintAcks;statusDamage.batteryDirty=true;statusDamage.refreshTime();settleEvents();
    CHECK("battery_change_home_only_top40_damage",!statusDamage.paintedRegion.isEmpty()&&statusDamage.paintedRegion.subtracted(QRegion(QRect(0,0,480,40))).isEmpty());
    CHECK("battery_only_never_acks_calendar",statusDamage.paintAcks==statusAcks);
    tap(statusDamage,376,744);tap(statusDamage,120,200);settleEvents();statusDamage.paintedRegion=QRegion();statusAcks=statusDamage.paintAcks;
    statusDamage.setTrustedTime(1792458120);settleEvents();
    CHECK("clock_change_schedule_only_top40_damage",!statusDamage.paintedRegion.isEmpty()&&statusDamage.paintedRegion.subtracted(QRegion(QRect(0,0,480,40))).isEmpty());
    CHECK("schedule_status_only_never_acks_calendar",statusDamage.paintAcks==statusAcks);
    // Background state changes cannot dirty Qt backing store during locked sleep.
    statusDamage.hide();agendaSleep.raise();settleEvents();agendaSleep.paintedRegion=QRegion();int frozenPaints=agendaSleep.paints,frozenAcks=agendaSleep.paintAcks;
    agendaSleep.setSyncActivity(true);agendaSleep.setConnectionStatus("offline fixture");agendaSleep.setSyncActivity(false);agendaSleep.refreshTime();app.processEvents();
    CHECK("standby_background_changes_do_not_paint",agendaSleep.paints==frozenPaints&&agendaSleep.paintAcks==frozenAcks);
    agendaSleep.refreshStandbySnapshot();app.processEvents();
    CHECK("standby_unchanged_snapshot_does_not_paint",agendaSleep.paints==frozenPaints);
    agendaSleep.setTrustedTime(1792458060);app.processEvents();CHECK("standby_clock_waits_for_explicit_snapshot",agendaSleep.paints==frozenPaints);
    agendaSleep.refreshStandbySnapshot();app.processEvents();
    fprintf(stdout,"QT_PAINT_DAMAGE standby %d,%d %dx%d\n",agendaSleep.paintedRegion.boundingRect().x(),agendaSleep.paintedRegion.boundingRect().y(),agendaSleep.paintedRegion.boundingRect().width(),agendaSleep.paintedRegion.boundingRect().height());
    CHECK("standby_clock_snapshot_only_top40_damage",!agendaSleep.paintedRegion.isEmpty()&&agendaSleep.paintedRegion.subtracted(QRegion(QRect(0,0,480,40))).isEmpty());
    CHECK("standby_status_snapshot_does_not_ack",agendaSleep.paintAcks==frozenAcks);
    agendaSleep.paintedRegion=QRegion();frozenPaints=agendaSleep.paints;agendaSleep.setContent(thirdChanged);app.processEvents();
    CHECK("standby_new_package_waits_for_explicit_snapshot",agendaSleep.paints==frozenPaints);
    agendaSleep.refreshStandbySnapshot();app.processEvents();
    fprintf(stdout,"QT_PAINT_DAMAGE newbody %d,%d %dx%d\n",agendaSleep.paintedRegion.boundingRect().x(),agendaSleep.paintedRegion.boundingRect().y(),agendaSleep.paintedRegion.boundingRect().width(),agendaSleep.paintedRegion.boundingRect().height());
    CHECK("standby_new_snapshot_paints_whole_body",agendaSleep.paintedRegion.contains(QRect(0,40,480,760)));
    CHECK("standby_new_snapshot_acks_new_version_after_painter_end",agendaSleep.paintAcks>frozenAcks&&agendaSleep.ackVersion==thirdChanged.version&&!agendaSleep.ackWhilePainting);
    int stablePaints=agendaSleep.paints;agendaSleep.refreshStandbySnapshot();app.processEvents();CHECK("standby_repeated_snapshot_has_no_hidden_full_update",agendaSleep.paints==stablePaints);
    const Page lockedPage=agendaSleep.page();tap(agendaSleep,376,744);drag(agendaSleep,200,600);CHECK("standby_agenda_touch_remains_locked",agendaSleep.page()==lockedPage&&agendaSleep.standby());
    // An existing empty list at its boundary must not repaint on page requests.
    ObservedShell emptyList(content);emptyList.show();tap(emptyList,376,744);tap(emptyList,350,210);settleEvents();int emptyListPaints=emptyList.paints;
    QWheelEvent emptyWheel(QPoint(240,350),-120,Qt::NoButton,Qt::NoModifier,Qt::Vertical);QApplication::sendEvent(&emptyList,&emptyWheel);settleEvents();
    CHECK("list_empty_words_boundary_does_not_repaint",emptyList.paints==emptyListPaints&&emptyList.page()==Words);
    // Physical-key API only flips existing content; no selection or edit action.
    Content volumeContent=content;volumeContent.version="volume-synthetic";volumeContent.events.clear();
    for(int i=0;i<13;++i){Event e=content.events[0];e.id=QString("volume%1").arg(i);e.summary=QString("Schedule%1").arg(i);volumeContent.events<<e;}
    FixtureRadio volumeScheduleRadio;ObservedShell volumeSchedule(volumeContent,&volumeScheduleRadio);volumeSchedule.show();tap(volumeSchedule,376,744);tap(volumeSchedule,120,200);settleEvents();
    QImage scheduleFirst=frame(volumeSchedule,"volume-schedule-first");int volumePaints=volumeSchedule.paints;
    CHECK("volume_schedule_first_boundary",!volumeSchedule.listNavigate(-1));settleEvents();CHECK("volume_schedule_boundary_no_repaint",volumeSchedule.paints==volumePaints);
    CHECK("volume_schedule_next_page",volumeSchedule.listNavigate(1)&&volumeSchedule.page()==Schedule);settleEvents();QImage scheduleSecond=frame(volumeSchedule,"volume-schedule-second");
    ObservedShell wheelExpected(volumeContent);tap(wheelExpected,376,744);tap(wheelExpected,120,200);QWheelEvent fiveRows(QPoint(240,350),-120,Qt::NoButton,Qt::NoModifier,Qt::Vertical);QApplication::sendEvent(&wheelExpected,&fiveRows);
    CHECK("volume_schedule_matches_existing_five_row_step",scheduleSecond==frame(wheelExpected,"volume-schedule-five-row-reference"));
    CHECK("volume_schedule_second_to_last_page",volumeSchedule.listNavigate(1));settleEvents();volumePaints=volumeSchedule.paints;
    CHECK("volume_schedule_last_boundary",!volumeSchedule.listNavigate(1));settleEvents();CHECK("volume_schedule_last_no_repaint",volumeSchedule.paints==volumePaints);
    CHECK("volume_schedule_up_twice",volumeSchedule.listNavigate(-1)&&volumeSchedule.listNavigate(-1));CHECK("volume_schedule_returns_first",frame(volumeSchedule,"volume-schedule-returned")==scheduleFirst);
    settleEvents();volumePaints=volumeSchedule.paints;CHECK("volume_invalid_direction_ignored",!volumeSchedule.listNavigate(0)&&!volumeSchedule.listNavigate(2)&&!volumeSchedule.listNavigate(-2));settleEvents();CHECK("volume_invalid_direction_no_repaint",volumeSchedule.paints==volumePaints);
    tap(volumeSchedule,240,20);if(volumeScheduleRadio.busy()){volumeScheduleRadio.finish(actualStatus());volumeSchedule.fireRadio();}settleEvents();QImage volumeOverlay=frame(volumeSchedule,"volume-overlay");settleEvents();volumePaints=volumeSchedule.paints;
    send(volumeSchedule,QEvent::MouseButtonPress,350,180);int overlaySyncs=volumeSchedule.syncs;CHECK("volume_overlay_ignored",!volumeSchedule.listNavigate(1)&&!volumeSchedule.listNavigate(-1));send(volumeSchedule,QEvent::MouseButtonRelease,350,180);CHECK("volume_overlay_release_cannot_sync",volumeSchedule.syncs==overlaySyncs);settleEvents();CHECK("volume_overlay_no_repaint",volumeSchedule.paints==volumePaints);CHECK("volume_overlay_pixels_unchanged",frame(volumeSchedule,"volume-overlay-unchanged")==volumeOverlay);tap(volumeSchedule,240,20);
    volumeSchedule.shortPowerPress();settleEvents();volumePaints=volumeSchedule.paints;CHECK("volume_standby_ignored",!volumeSchedule.listNavigate(1)&&!volumeSchedule.listNavigate(-1)&&volumeSchedule.standby());settleEvents();CHECK("volume_standby_no_repaint",volumeSchedule.paints==volumePaints);
    volumeSchedule.longPowerPress();settleEvents();volumePaints=volumeSchedule.paints;CHECK("volume_shutdown_ignored",!volumeSchedule.listNavigate(1)&&!volumeSchedule.listNavigate(-1)&&volumeSchedule.shuttingDown());settleEvents();CHECK("volume_shutdown_no_repaint",volumeSchedule.paints==volumePaints);
    QString volumeRoot="/tmp/volume-list-workspace";::mkdir(volumeRoot.toUtf8().constData(),0700);LocalApps volumeSeed;CHECK("volume_workspace_seed",volumeSeed.open(volumeRoot));QByteArray volumeWords;QStringList volumeNoteIds;
    for(int i=0;i<13;++i){volumeWords+=QString("Word%1\tBack%1\n").arg(i).toUtf8();QString id;CHECK("volume_note_seed",volumeSeed.saveNote(QString(),QString("Note%1").arg(i),&id));volumeNoteIds<<id;}
    CHECK("volume_words_seed",volumeSeed.importWords(volumeWords));ObservedShell volumeWordUi(content);CHECK("volume_words_workspace",volumeWordUi.configureWorkspace(volumeRoot));volumeWordUi.show();tap(volumeWordUi,376,744);tap(volumeWordUi,350,210);tap(volumeWordUi,380,170);settleEvents();QImage wordListFirst=frame(volumeWordUi,"volume-word-list-first");
    volumePaints=volumeWordUi.paints;CHECK("volume_word_list_first_boundary",!volumeWordUi.listNavigate(-1));settleEvents();CHECK("volume_word_list_boundary_no_repaint",volumeWordUi.paints==volumePaints);
    CHECK("volume_word_list_next_without_selecting",volumeWordUi.listNavigate(1)&&volumeWordUi.wordVisibleText()=="Word0"&&!volumeWordUi.wordBackShowing());
    send(volumeWordUi,QEvent::MouseButtonPress,100,300);CHECK("volume_word_list_moves_and_cancels_old_press",volumeWordUi.listNavigate(-1));send(volumeWordUi,QEvent::MouseButtonRelease,100,300);CHECK("volume_move_release_cannot_select_new_row",frame(volumeWordUi,"volume-word-list-release")==wordListFirst&&volumeWordUi.wordVisibleText()=="Word0");
    send(volumeWordUi,QEvent::MouseButtonPress,100,300);CHECK("volume_word_boundary_cancels_old_press",!volumeWordUi.listNavigate(-1));send(volumeWordUi,QEvent::MouseButtonRelease,100,300);CHECK("volume_boundary_release_cannot_select_row",frame(volumeWordUi,"volume-word-boundary-release")==wordListFirst);
    CHECK("volume_word_list_reaches_tail",volumeWordUi.listNavigate(1)&&volumeWordUi.listNavigate(1));settleEvents();volumePaints=volumeWordUi.paints;CHECK("volume_word_list_last_boundary",!volumeWordUi.listNavigate(1));settleEvents();CHECK("volume_word_list_last_no_repaint",volumeWordUi.paints==volumePaints);
    CHECK("volume_word_list_returns_first",volumeWordUi.listNavigate(-1)&&volumeWordUi.listNavigate(-1));CHECK("volume_word_list_six_step",volumeWordUi.listNavigate(1));tap(volumeWordUi,100,240);CHECK("volume_word_list_step_is_six",volumeWordUi.wordVisibleText()=="Word6");
    ObservedShell volumeDetail(content);CHECK("volume_detail_workspace",volumeDetail.configureWorkspace(visibilityRoot));volumeDetail.show();tap(volumeDetail,376,744);tap(volumeDetail,350,210);settleEvents();QString detailFirst=volumeDetail.wordVisibleText();
    CHECK("volume_word_detail_pages_visible_rows",volumeDetail.listNavigate(1)&&volumeDetail.wordVisibleText()!=detailFirst&&!volumeDetail.wordBackShowing());
    for(int i=0;i<30;++i)volumeDetail.listNavigate(1);settleEvents();volumePaints=volumeDetail.paints;CHECK("volume_word_detail_reaches_tail",QString(volumeDetail.wordVisibleText()).remove('\n').contains("ENDXYZ"));CHECK("volume_word_detail_tail_boundary",!volumeDetail.listNavigate(1));settleEvents();CHECK("volume_word_detail_tail_no_repaint",volumeDetail.paints==volumePaints);
    for(int i=0;i<30;++i)volumeDetail.listNavigate(-1);CHECK("volume_word_detail_returns_first",volumeDetail.wordScrollOffset()==0&&volumeDetail.wordVisibleText()==detailFirst);tap(volumeDetail,240,550);settleEvents();volumePaints=volumeDetail.paints;CHECK("volume_short_word_back_does_not_flip_or_repaint",!volumeDetail.listNavigate(1)&&volumeDetail.wordBackShowing()&&volumeDetail.wordVisibleText()=="short back");settleEvents();CHECK("volume_short_word_back_no_repaint",volumeDetail.paints==volumePaints);
    ObservedShell volumeNotes(content);CHECK("volume_notes_workspace",volumeNotes.configureWorkspace(volumeRoot));volumeNotes.show();tap(volumeNotes,376,744);tap(volumeNotes,120,380);settleEvents();QImage notesFirst=frame(volumeNotes,"volume-notes-first");CHECK("volume_note_list_first_boundary",!volumeNotes.listNavigate(-1));CHECK("volume_note_list_next",volumeNotes.listNavigate(1));tap(volumeNotes,100,200);CHECK("volume_note_list_step_is_six",volumeNotes.noteVisibleText()=="Note6");
    tap(volumeNotes,100,650);settleEvents();QString beforeVolumeDraft=volumeNotes.noteDraft();volumePaints=volumeNotes.paints;send(volumeNotes,QEvent::MouseButtonPress,350,415);CHECK("volume_note_editor_ignored",!volumeNotes.listNavigate(1)&&!volumeNotes.listNavigate(-1)&&volumeNotes.inputActive()&&volumeNotes.noteDraft()==beforeVolumeDraft);send(volumeNotes,QEvent::MouseButtonRelease,350,415);CHECK("volume_editor_release_cannot_save",volumeNotes.inputActive()&&volumeNotes.noteDraft()==beforeVolumeDraft);settleEvents();CHECK("volume_note_editor_no_repaint",volumeNotes.paints==volumePaints);tap(volumeNotes,100,415);
    tap(volumeNotes,350,650);settleEvents();volumePaints=volumeNotes.paints;CHECK("volume_note_delete_confirmation_ignored",!volumeNotes.listNavigate(1)&&!volumeNotes.listNavigate(-1));settleEvents();CHECK("volume_note_delete_no_repaint",volumeNotes.paints==volumePaints);tap(volumeNotes,100,415);CHECK("volume_note_delete_keeps_store",volumeSeed.open(volumeRoot)&&volumeSeed.notes().size()==13);tap(volumeNotes,350,600);
    CHECK("volume_note_list_last_page",volumeNotes.listNavigate(1));settleEvents();volumePaints=volumeNotes.paints;CHECK("volume_note_list_last_boundary",!volumeNotes.listNavigate(1));settleEvents();CHECK("volume_note_list_last_no_repaint",volumeNotes.paints==volumePaints);CHECK("volume_note_list_returns_top",volumeNotes.listNavigate(-1)&&volumeNotes.listNavigate(-1));CHECK("volume_note_list_first_restored",frame(volumeNotes,"volume-notes-returned").copy(24,170,432,408)==notesFirst.copy(24,170,432,408));
    QString volumeLongNote;for(int i=0;i<40;++i)volumeLongNote+=QString("Line%1").arg(i)+(i==39?QString():QString("\n"));CHECK("volume_note_detail_seed",volumeSeed.saveNote(volumeNoteIds[0],volumeLongNote,0)&&volumeNotes.configureWorkspace(volumeRoot));tap(volumeNotes,100,200);CHECK("volume_note_detail_first_page",volumeNotes.noteVisibleText().startsWith("Line0\n")&&!volumeNotes.noteVisibleText().contains("Line14"));CHECK("volume_note_detail_next_fourteen",volumeNotes.listNavigate(1)&&volumeNotes.noteVisibleText().startsWith("Line14\n"));CHECK("volume_note_detail_last_fourteen",volumeNotes.listNavigate(1)&&volumeNotes.noteVisibleText().endsWith("Line39"));settleEvents();volumePaints=volumeNotes.paints;CHECK("volume_note_detail_last_boundary",!volumeNotes.listNavigate(1));settleEvents();CHECK("volume_note_detail_boundary_no_repaint",volumeNotes.paints==volumePaints);CHECK("volume_note_detail_returns_first",volumeNotes.listNavigate(-1)&&volumeNotes.listNavigate(-1)&&volumeNotes.noteVisibleText().startsWith("Line0\n"));
    FixtureRadio volumeRadio;ObservedShell volumeWifi(content,&volumeRadio);volumeWifi.show();tap(volumeWifi,376,744);tap(volumeWifi,360,380);volumeRadio.finish(scanned(13));volumeWifi.fireRadio();volumeRadio.finish(actualStatus());volumeWifi.fireRadio();settleEvents();int volumeRequests=volumeRadio.actions.size();volumePaints=volumeWifi.paints;
    CHECK("volume_wifi_first_boundary",!volumeWifi.listNavigate(-1));settleEvents();CHECK("volume_wifi_boundary_no_repaint",volumeWifi.paints==volumePaints);CHECK("volume_wifi_next_without_connecting",volumeWifi.listNavigate(1)&&volumeRadio.actions.size()==volumeRequests&&!volumeWifi.inputActive());
    send(volumeWifi,QEvent::MouseButtonPress,100,366);CHECK("volume_wifi_move_cancels_pressed_row",volumeWifi.listNavigate(-1));send(volumeWifi,QEvent::MouseButtonRelease,100,366);CHECK("volume_wifi_old_release_not_selected",!volumeWifi.inputActive()&&volumeRadio.actions.size()==volumeRequests);
    send(volumeWifi,QEvent::MouseButtonPress,100,366);CHECK("volume_wifi_boundary_cancels_pressed_row",!volumeWifi.listNavigate(-1));send(volumeWifi,QEvent::MouseButtonRelease,100,366);CHECK("volume_wifi_boundary_release_not_selected",!volumeWifi.inputActive());CHECK("volume_wifi_six_row_step",volumeWifi.listNavigate(1));tap(volumeWifi,100,366);CHECK("volume_wifi_step_is_six",volumeWifi.inputValue(0)=="Fixture AP 6");tap(volumeWifi,32,505);settleEvents();volumePaints=volumeWifi.paints;
    send(volumeWifi,QEvent::MouseButtonPress,350,425);int beforeVolumeConfirm=volumeRadio.actions.size();CHECK("volume_wifi_password_dialog_ignored",!volumeWifi.listNavigate(1)&&!volumeWifi.listNavigate(-1)&&volumeWifi.inputValue(1)=="q");send(volumeWifi,QEvent::MouseButtonRelease,350,425);CHECK("volume_dialog_release_cannot_connect",volumeRadio.actions.size()==beforeVolumeConfirm&&volumeWifi.inputActive());settleEvents();CHECK("volume_wifi_dialog_no_repaint",volumeWifi.paints==volumePaints);tap(volumeWifi,90,425);tap(volumeWifi,200,280);settleEvents();volumePaints=volumeWifi.paints;CHECK("volume_wifi_status_page_ignored",!volumeWifi.listNavigate(1)&&!volumeWifi.listNavigate(-1));settleEvents();CHECK("volume_wifi_status_no_repaint",volumeWifi.paints==volumePaints);tap(volumeWifi,75,280);
    CHECK("volume_wifi_reaches_last",volumeWifi.listNavigate(1));settleEvents();volumePaints=volumeWifi.paints;CHECK("volume_wifi_last_boundary",!volumeWifi.listNavigate(1));settleEvents();CHECK("volume_wifi_last_no_repaint",volumeWifi.paints==volumePaints);
    tap(volumeWifi,230,180);settleEvents();volumePaints=volumeWifi.paints;CHECK("volume_bluetooth_page_ignored",!volumeWifi.listNavigate(1)&&!volumeWifi.listNavigate(-1));settleEvents();CHECK("volume_bluetooth_no_repaint",volumeWifi.paints==volumePaints);
    ObservedShell noList(content);noList.show();settleEvents();volumePaints=noList.paints;CHECK("volume_home_ignored",!noList.listNavigate(1)&&!noList.listNavigate(-1));settleEvents();CHECK("volume_home_no_repaint",noList.paints==volumePaints);tap(noList,376,744);settleEvents();volumePaints=noList.paints;CHECK("volume_apps_ignored",!noList.listNavigate(1)&&!noList.listNavigate(-1));settleEvents();CHECK("volume_apps_no_repaint",noList.paints==volumePaints);
    printf("%s GUI %d checks input=SIMULATED reader_execution=false\n",failures?"FAIL":"PASS",checks);return failures?1:0;
}
