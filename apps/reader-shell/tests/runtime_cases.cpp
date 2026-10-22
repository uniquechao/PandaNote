// Compile the production runtime class; all synthetic controls stay in this file.
#define main readerProductionMain
#include "../main.cpp"
#undef main
#include <QtGui/qpainter.h>
#include <QtCore/qdir.h>
static int failures=0,checks=0;
#define CHECK(name,condition) do { ++checks;if(!(condition)){fprintf(stderr,"FAIL %s line %d\n",name,__LINE__);++failures;} } while(0)
class RuntimeTest:public RuntimeShell {
public:
    RuntimeTest():now(0),paintCount(0) {}
    qint64 now;int paintCount;
protected:
    qint64 monotonicMs() const { return now; }
    void paintEvent(QPaintEvent *e) { ++paintCount;ReaderShell::paintEvent(e); }
};
#include <QtCore/qabstracteventdispatcher.h>
#include <QtCore/qtimer.h>
#include <unistd.h>
static bool syncConfig(RuntimeShell &shell,const QString &certificate,const QByteArray &fingerprint=QByteArray(64,'a')) {
 QByteArray raw="[sync]\nschema=1\nendpoint64="+QByteArray("https://127.0.0.1:8768").toBase64()+"\ntoken64="+QByteArray("SYNTHETIC-test-only-credential").toBase64()+"\ncertificate64="+certificate.toUtf8().toBase64()+"\ncertificateSha256="+fingerprint+"\nbootstrapEpoch=1792458000\n";
 QFile f("/tmp/runtime-sync.ini");if(!f.open(QIODevice::WriteOnly|QIODevice::Truncate))return false;f.setPermissions(QFile::ReadOwner|QFile::WriteOwner);f.write(raw);f.close();return shell.loadSyncConfiguration(f.fileName());
}
static void tap(RuntimeShell &shell,int x,int y) {
    QMouseEvent press(QEvent::MouseButtonPress,QPoint(x,y),Qt::LeftButton,Qt::LeftButton,Qt::NoModifier);QApplication::sendEvent(&shell,&press);
    QMouseEvent release(QEvent::MouseButtonRelease,QPoint(x,y),Qt::LeftButton,Qt::LeftButton,Qt::NoModifier);QApplication::sendEvent(&shell,&release);
}
static QImage frame(RuntimeShell &shell,const char *name) {
    QImage image(480,800,QImage::Format_RGB32);image.fill(0xffffffff);QPainter painter(&image);shell.render(&painter);painter.end();CHECK("frame_saved",image.save(QString("/tmp/")+name+".png"));return image;
}
int main(int argc,char **argv) {
    QApplication app(argc,argv,QApplication::GuiServer);app.setQuitOnLastWindowClosed(false);
    if(argc==2 && QString(argv[1])=="--serve-only") { QTimer::singleShot(8000,&app,SLOT(quit()));return app.exec(); }
    RuntimeTest shell;CHECK("valid_load",shell.loadDirectory("/content-test/fixtures/valid"));shell.show();app.processEvents();
    CHECK("font_loaded",shell.fontReady());CHECK("cached_by_default",shell.displayStatus().contains(QString::fromUtf8("缓存时间")));
    QImage before=frame(shell,"production-home");
    CHECK("bad_package_rejected",!shell.loadDirectory("/content-test/fixtures/bad-hash"));
    CHECK("retained_date",shell.displayDate()==QDate(2026,10,20));CHECK("retained_stale_status",shell.displayStatus().contains(QString::fromUtf8("已过期")));
    QImage after=frame(shell,"runtime-retained");
    int eventInk=0;for(int y=264;y<352;++y)for(int x=24;x<456;++x)if(qRed(before.pixel(x,y))<128)++eventInk;
    CHECK("retained_event_fixture_is_visible",eventInk>10);
    CHECK("bad_package_keeps_rendered_events",before.copy(24,176,432,440)==after.copy(24,176,432,440));
    tap(shell,376,744);CHECK("release_panel",shell.page()==Panel);frame(shell,"runtime-panel");
    tap(shell,120,200);CHECK("schedule_open",shell.page()==Schedule);
    shell.now=60000;
    QList<QAbstractEventDispatcher::TimerInfo> timers=QAbstractEventDispatcher::instance()->registeredTimers(&shell);
    for(int i=0;i<timers.size();++i) { QTimerEvent event(timers[i].first);QApplication::sendEvent(&shell,&event); }
    CHECK("idle_home",shell.page()==Home);
    QCloseEvent close;QApplication::sendEvent(&shell,&close);CHECK("ordinary_close_ignored",!close.isAccepted());
    CHECK("reload_after_bad",shell.loadDirectory("/content-test/fixtures/valid"));
    CHECK("successful_reload_clears_stale",!shell.displayStatus().contains(QString::fromUtf8("已过期")));
    CHECK("simulated_anchor",shell.setTrustedTime(1792458000));app.processEvents();int paints=shell.paintCount;
    timers=QAbstractEventDispatcher::instance()->registeredTimers(&shell);
    for(int i=0;i<timers.size();++i)if(timers[i].second==30000){QTimerEvent event(timers[i].first);QApplication::sendEvent(&shell,&event);}
    app.processEvents();CHECK("unchanged_refresh_no_repaint",shell.paintCount==paints);
    CHECK("ordinary_has_only_refresh_timer",timers.size()==1 && timers[0].second==30000);
    CHECK("boundary_simulated_anchor",shell.setTrustedTime(1792511999));app.processEvents();
    CHECK("before_midnight",shell.displayDate()==QDate(2026,10,20));paints=shell.paintCount;
    usleep(1200000); // Test-only: real monotonic elapsed crosses fixture midnight.
    for(int i=0;i<timers.size();++i)if(timers[i].second==30000){QTimerEvent event(timers[i].first);QApplication::sendEvent(&shell,&event);}
    app.processEvents();CHECK("meaningful_boundary_updates_date",shell.displayDate()==QDate(2026,10,21));
    CHECK("meaningful_boundary_repaints",shell.paintCount>paints);frame(shell,"runtime-midnight");
    // Real cache creation, destruction and RuntimeShell construction; no trust/time
    // is manufactured merely because bytes survived another object lifetime.
    const QString persistentCache="/tmp/runtime-persistent-cache";
    {DeviceSync bootstrap(persistentCache);bootstrap.refresh();QFile manifest("/content-test/fixtures/device-manifest.json");CHECK("runtime_cache_manifest_open",manifest.open(QIODevice::ReadOnly));CHECK("runtime_cache_manifest",bootstrap.receive(200,manifest.readAll()));
     for(int i=0;i<3;++i){QFile resource("/content-test/fixtures/device/"+bootstrap.request().path.section('/',-1));CHECK("runtime_cache_resource_open",resource.open(QIODevice::ReadOnly));CHECK("runtime_cache_resource",bootstrap.receive(200,resource.readAll()));}}
    {RuntimeShell restarted(persistentCache);CHECK("configured_cache_loaded_after_restart",restarted.loadCached());CHECK("restart_cache_is_stale",restarted.displayStatus().contains(QString::fromUtf8("缓存时间")));}
    {RuntimeShell isolated;CHECK("explicit_cache_does_not_change_default",!isolated.loadCached());}
    {RuntimeShell configured;CHECK("persistent_certificate_supported",syncConfig(configured,"/user/pandanote/config/test.crt"));}
    {RuntimeShell configured;CHECK("legacy_tmp_certificate_supported",QFile::copy("/user/pandanote/config/test.crt","/tmp/runtime-test.crt")&&syncConfig(configured,"/tmp/runtime-test.crt"));}
    {RuntimeShell configured;CHECK("certificate_symlink_rejected",QFile::link("/user/pandanote/config/test.crt","/tmp/runtime-link.crt")&&!syncConfig(configured,"/tmp/runtime-link.crt"));}
    {RuntimeShell configured;CHECK("certificate_ancestor_symlink_rejected",QFile::link("/user/pandanote/config","/tmp/runtime-config-link")&&!syncConfig(configured,"/tmp/runtime-config-link/test.crt"));}
    {RuntimeShell configured;CHECK("certificate_unapproved_location_rejected",!syncConfig(configured,"/content-test/fixtures/valid/content.ini"));CHECK("fingerprint_grammar_unchanged",!syncConfig(configured,"/user/pandanote/config/test.crt",QByteArray(64,'G')));}
    {QFile f("/tmp/runtime-test.crt");CHECK("writable_certificate_setup",f.setPermissions(QFile::ReadOwner|QFile::WriteOwner|QFile::WriteGroup));RuntimeShell configured;CHECK("writable_certificate_rejected",!syncConfig(configured,f.fileName()));}
    {QDir().mkdir("/tmp/runtime-public");::chmod("/tmp/runtime-public",0777);QFile::copy("/user/pandanote/config/test.crt","/tmp/runtime-public/test.crt");RuntimeShell configured;CHECK("writable_certificate_ancestor_rejected",!syncConfig(configured,"/tmp/runtime-public/test.crt"));}
    {RuntimeShell configured;CHECK("duplicate_fields_rejected",!syncConfig(configured,"/user/pandanote/config/test.crt",QByteArray(64,'a')+"\ncertificateSha256="+QByteArray(64,'a')));CHECK("noncanonical_certificate_path_rejected",!syncConfig(configured,"/user/pandanote/config/../config/test.crt"));}
    printf("%s production runtime %d checks input=SIMULATED\n",failures?"FAIL":"PASS",checks);
    return failures?1:0;
}
