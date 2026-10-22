// Real tmpfs filesystem failures and restart state; no test hooks in production.
#include "../sync.h"
#include <QtCore/qcoreapplication.h>
#include <QtCore/qfile.h>
#include <QtCore/qfileinfo.h>
#include <QtCore/qdir.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>
static int checks=0,failures=0;
#define CHECK(n,c) do{++checks;if(!(c)){fprintf(stderr,"FAIL %s line %d\n",n,__LINE__);++failures;}}while(0)
static QByteArray read(const QString &p){QFile f(p);f.open(QIODevice::ReadOnly);return f.readAll();}
static QByteArray manifest(int n){return read(QString("/content-test/fixtures/device-manifest%1.json").arg(n==1?QString():QString::number(n)));}
static QString fixture(int n){return QString("/content-test/fixtures/device%1/").arg(n==1?QString():QString::number(n));}
static QString id(int n){return n==1?QString("0123456789abcdef0123456789abcdef"):QString(32,QChar('0'+n));}
static void download(DeviceSync &s,int n){s.refresh();CHECK("download_manifest",s.receive(200,manifest(n)));for(int i=0;i<3;++i){SyncRequest r=s.request();CHECK("download_resource",s.receive(200,read(fixture(n)+r.path.section('/',-1))));}}
static void paintedAck(DeviceSync &s,int n){s.painted(id(n));CHECK("actual_paint_prepares_ack",s.request().path=="/reader/v1/ack");CHECK("ack_accepted",s.receive(200,"{}"));}
static void copyVersion(const QString &cache,int n){QDir().mkdir(cache+"/"+id(n));QFile::setPermissions(cache+"/"+id(n),QFile::ReadOwner|QFile::WriteOwner|QFile::ExeOwner);QStringList names;names<<"content.ini"<<"background.png"<<"SHA256SUMS";for(int i=0;i<names.size();++i)CHECK("fixture_version_copied",QFile::copy(fixture(n)+names[i],cache+"/"+id(n)+"/"+names[i]));}
int main(int argc,char **argv){QCoreApplication app(argc,argv);Content update;
 const QString cache="/tmp/recovery-cache";DeviceSync first(cache);download(first,1);paintedAck(first,1);
 CHECK("pointer_failure_injected",QDir().mkdir(cache+"/current.new"));first.refresh();CHECK("second_manifest",first.receive(200,manifest(2)));bool received=true;for(int i=0;i<3;++i){SyncRequest r=first.request();received=first.receive(200,read(fixture(2)+r.path.section('/',-1)));}
 CHECK("pointer_commit_fails",!received&&first.error()=="cache-pointer");CHECK("last_good_before_pointer",first.cachedContent().version==id(1)&&read(cache+"/current")==id(1).toLatin1()+"\n");CHECK("promotion_survived",QFileInfo(cache+"/"+id(2)).isDir());CHECK("failed_promotion_no_update_or_ack",!first.takeUpdate(&update)&&first.request().path.isEmpty());
 CHECK("pointer_failure_removed",QDir().rmdir(cache+"/current.new"));DeviceSync interrupted(cache);CHECK("interruption_loaded_old_pointer",interrupted.cachedContent().version==id(1));interrupted.refresh();CHECK("recover_promoted_after_restart",interrupted.receive(200,manifest(2)));CHECK("recovery_avoids_redownload",interrupted.request().path.isEmpty());CHECK("recovered_pointer",read(cache+"/current")==id(2).toLatin1()+"\n");CHECK("recovery_requires_paint",interrupted.takeUpdate(&update)&&interrupted.lastDisplayed().isEmpty());paintedAck(interrupted,2);
 interrupted.refresh();CHECK("adopt_retained_previous",interrupted.receive(200,manifest(1)));CHECK("rollback_not_download_or_ack",interrupted.request().path.isEmpty()&&interrupted.takeUpdate(&update));paintedAck(interrupted,1);CHECK("retained_versions_bound",QDir(cache).entryList(QDir::Dirs|QDir::NoDotAndDotDot).size()==2);
 // Existing package can be self-consistent yet disagree with authenticated bytes.
 DeviceManifest expected;QString error;CHECK("manifest_for_digest_case",parseDeviceManifest(manifest(2),&expected,&error));QByteArray wrong=manifest(2);wrong.replace(expected.files[0].sha256.toLatin1(),QByteArray(64,'0'));interrupted.refresh();CHECK("exact_manifest_digest_required",!interrupted.receive(200,wrong));CHECK("digest_failure_retains_pointer",read(cache+"/current")==id(1).toLatin1()+"\n");
 QFile corrupt(cache+"/"+id(2)+"/background.png");CHECK("corrupt_file_open",corrupt.open(QIODevice::WriteOnly|QIODevice::Truncate));corrupt.write("corrupt");corrupt.close();interrupted.refresh();CHECK("corrupt_collision_rejected",!interrupted.receive(200,manifest(2)));CHECK("corrupt_collision_no_download",interrupted.request().path.isEmpty()&&interrupted.cachedContent().version==id(1));
 // A symlink collision must never be adopted, even if its target is valid.
 QString badDirectory=cache+"/"+id(2);QStringList collisionFiles;collisionFiles<<"content.ini"<<"background.png"<<"SHA256SUMS";for(int i=0;i<collisionFiles.size();++i)QFile::remove(badDirectory+"/"+collisionFiles[i]);QDir().rmdir(badDirectory);
 CHECK("collision_symlink_created",QFile::link(cache+"/"+id(1),badDirectory));interrupted.refresh();CHECK("symlink_collision_rejected",!interrupted.receive(200,manifest(2))&&interrupted.request().path.isEmpty()&&interrupted.cachedContent().version==id(1));
 // A paint before authentication records local observation, but cannot send ACK.
 DeviceSync beforeAuth(cache);beforeAuth.painted(id(1));CHECK("cached_paint_no_pre_auth_ack",beforeAuth.request().path.isEmpty()&&beforeAuth.freshEpoch()==0);beforeAuth.refresh();CHECK("same_manifest_auth_after_cached_paint",beforeAuth.receive(200,manifest(1)));CHECK("prepaint_then_auth_ack",beforeAuth.request().path=="/reader/v1/ack"&&!beforeAuth.takeUpdate(&update));beforeAuth.failed("lost-before-restart");
 DeviceSync afterAuth(cache);afterAuth.refresh();CHECK("same_manifest_after_restart",afterAuth.receive(200,manifest(1)));CHECK("authenticated_download_alone_no_ack",afterAuth.request().path.isEmpty()&&!afterAuth.takeUpdate(&update)&&afterAuth.lastDisplayed().isEmpty());afterAuth.painted(id(2));CHECK("wrong_painted_version_no_ack",afterAuth.request().path.isEmpty());afterAuth.painted(id(1));CHECK("auth_then_paint_ack",afterAuth.request().path=="/reader/v1/ack");CHECK("restart_ack_success",afterAuth.receive(200,"{}"));afterAuth.refresh();CHECK("unchanged_after_ack",afterAuth.receive(200,manifest(1))&&afterAuth.request().path.isEmpty()&&!afterAuth.takeUpdate(&update));
 // A second failure within the same process is retryable without repainting old data.
 const QString retry="/tmp/retry-cache";DeviceSync sameProcess(retry);download(sameProcess,1);paintedAck(sameProcess,1);QDir().mkdir(retry+"/current.new");sameProcess.refresh();sameProcess.receive(200,manifest(2));for(int i=0;i<3;++i){SyncRequest r=sameProcess.request();sameProcess.receive(200,read(fixture(2)+r.path.section('/',-1)));}QDir().rmdir(retry+"/current.new");sameProcess.refresh();CHECK("same_process_pointer_retry",sameProcess.receive(200,manifest(2))&&sameProcess.takeUpdate(&update)&&sameProcess.request().path.isEmpty());
 // Crash after rename but before pointer creation, with no failure handler run.
 const QString crash="/tmp/crash-cache";DeviceSync prior(crash);download(prior,1);paintedAck(prior,1);copyVersion(crash,2);DeviceSync recovered(crash);recovered.refresh();CHECK("interrupted_rename_window_recovered",recovered.receive(200,manifest(2))&&recovered.takeUpdate(&update)&&read(crash+"/current")==id(2).toLatin1()+"\n");
 // Explicit nested cache survives new DeviceSync objects, but unsafe ancestors cannot be adopted.
 QDir().mkdir("/tmp/persistent-parent");::chmod("/tmp/persistent-parent",0700);
 {DeviceSync persistent("/tmp/persistent-parent/cache");download(persistent,1);paintedAck(persistent,1);}
 {DeviceSync restarted("/tmp/persistent-parent/cache");CHECK("explicit_nested_restart",restarted.cachedContent().version==id(1)&&restarted.freshEpoch()==0&&restarted.request().path.isEmpty());}
 CHECK("ancestor_symlink_created",QFile::link("/tmp/persistent-parent","/tmp/cache-alias"));
 {DeviceSync linked("/tmp/cache-alias/cache");CHECK("ancestor_symlink_not_loaded",linked.cachedContent().schema!=1);linked.refresh();CHECK("ancestor_symlink_not_written",!linked.receive(200,manifest(2))&&linked.error()=="cache-root");}
 ::chmod("/tmp/persistent-parent",0777);
 {DeviceSync unsafe("/tmp/persistent-parent/cache");CHECK("writable_ancestor_not_loaded",unsafe.cachedContent().schema!=1);unsafe.refresh();CHECK("writable_ancestor_not_written",!unsafe.receive(200,manifest(2))&&unsafe.error()=="cache-root");}
 ::chmod("/tmp/persistent-parent",0700);
 {DeviceSync dot("/tmp/persistent-parent/../persistent-parent/cache");CHECK("noncanonical_cache_not_loaded",dot.cachedContent().schema!=1);}
 QDir().mkdir("/tmp/public-cache-leaf");::chmod("/tmp/public-cache-leaf",0755);
 {DeviceSync publicLeaf("/tmp/public-cache-leaf");publicLeaf.refresh();CHECK("public_cache_leaf_not_adopted",!publicLeaf.receive(200,manifest(1))&&publicLeaf.error()=="cache-root");CHECK("unsafe_leaf_permissions_unchanged",QFileInfo("/tmp/public-cache-leaf").permissions()&QFile::ReadOther);}
 printf("%s recovery %d checks network=none input=SIMULATED\n",failures?"FAIL":"PASS",checks);return failures?1:0;
}
