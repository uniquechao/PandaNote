#ifndef PANDANOTE_DEVICE_SYNC_H
#define PANDANOTE_DEVICE_SYNC_H
#include "content.h"
#include "tls.h"
#include "resolver.h"
#include <QtCore/qmap.h>
#include <QtCore/qbytearray.h>
#include <QtCore/qprocess.h>
struct DeviceFile { QString name,sha256,path;int bytes; };
struct DeviceManifest { QString version;qint64 serverEpoch,generatedAt;int pollSeconds;QList<DeviceFile> files;DeviceManifest():serverEpoch(0),generatedAt(0),pollSeconds(300){} };
bool parseDeviceManifest(const QByteArray &,DeviceManifest *,QString *);
struct DeviceEndpoint { QString host,basePath;int port;bool tls;QByteArray certificatePem;QString certificateSha256;qint64 bootstrapEpoch;DeviceEndpoint():port(0),tls(false),bootstrapEpoch(0){} };
// Production requires pinned HTTPS; loopback HTTP is a protocol-test capability.
bool parseDeviceEndpoint(const QString &,DeviceEndpoint *,QString *);
QString deviceRequestTarget(const DeviceEndpoint &,const QString &logicalPath);
// Canonical absolute path; fd-walk rejects symlink/untrusted ancestors.
bool validSyncPath(const QString &);
bool syncCacheDirectory(const QString &,bool create=false);
bool readSyncFile(const QString &,int limit,bool privateFile,QByteArray *);
class HttpReply {
public:
 HttpReply():header_(false),complete_(false),length_(0),status_(0){}
 bool feed(const QByteArray &,int limit,QString *error);
 bool complete()const{return complete_;}int status()const{return status_;}QByteArray body()const{return data_;}
private:QByteArray buffer_,data_;bool header_,complete_;int length_,status_;
};
struct SyncRequest { QString method,path;QByteArray body;int limit;SyncRequest():limit(0){} };
class DeviceSync {
public:
 explicit DeviceSync(const QString &cache);
 void refresh();SyncRequest request()const{return request_;}
 bool receive(int status,const QByteArray &body);void failed(const QString &code);
 bool takeUpdate(Content *);void painted(const QString &version);
 bool waitingForPaint()const{return !pending_.isEmpty();}
 Content cachedContent()const{return content_;}QString lastDisplayed()const{return displayed_;}QString error()const{return error_;}
 qint64 freshEpoch()const{return freshEpoch_;}int pollSeconds()const{return manifest_.pollSeconds;}
private:
 QString cache_,staging_,error_,displayed_,pending_,acknowledged_,authenticated_;Content content_;DeviceManifest manifest_;SyncRequest request_;int resource_;qint64 freshEpoch_;
 void getResource();bool store(const QString &,const QByteArray &);void discardStaging();
 bool validateVersion(const QString &,Content *)const;
 bool commitVersion(const Content &);void pruneVersions(const QString &,const QString &);
 void prepareAck();
};
// A bounded nonblocking numeric-IPv4 HTTPS client. No DNS, redirects,
// cookies, proxies, TLS fallbacks, secrets in argv, or blocking event-loop waits.
class DeviceHttp {
public:
 DeviceHttp();~DeviceHttp();bool start(const DeviceEndpoint &,const QByteArray &token,const SyncRequest &,QString *);
 int poll(int *status,QByteArray *body,QString *error);void cancel();bool reapCancelledResolver();void trustEpoch(qint64 e);bool busy()const{return fd_>=0||resolving_||resolver_.busy();}
private:
 bool connectAddress(const char *,QString *);int pollResolver(QString *);
 int fd_,phase_,sent_,limit_;QByteArray outgoing_;HttpReply reply_;QElapsedTimer clock_;DeviceTls tls_;bool useTls_,resolving_;qint64 trustedEpoch_,trustedAtMs_;
 DnsResolver resolver_;DeviceEndpoint activeEndpoint_;char addresses_[4][16];unsigned addressCount_,nextAddress_;

};
struct WifiRow {QString ssid,signal,security;};
struct BluetoothRow {QString peer,name,paired,connected;};
struct RadioReply {bool ok;QString code,message,wifiSsid;QMap<QString,QString> status;QList<WifiRow> wifi;QList<BluetoothRow> bluetooth;RadioReply():ok(false){} };
QByteArray radioRequest(const QString &action,const QString &ssidOrPeer=QString(),const QString &password=QString());
bool parseRadioReply(const QByteArray &,RadioReply *,QString *);
class RadioClient {
public:
 RadioClient();virtual ~RadioClient();virtual bool start(const QString &,const QString &value=QString(),const QString &password=QString());
 virtual bool poll();virtual bool busy()const{return running_;}virtual RadioReply reply()const{return reply_;}
private:QProcess process_;QElapsedTimer clock_;QByteArray output_;RadioReply reply_;bool running_;void stop(const QString &);
};
#endif
