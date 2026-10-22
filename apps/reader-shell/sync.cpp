#include "sync.h"
#include "tlsclock.h"
#include <QtCore/qcoreapplication.h>
#include <poll.h>
#include <QtCore/qdir.h>
#include <QtCore/qfile.h>
#include <QtCore/qfileinfo.h>
#include <QtCore/qregexp.h>
#include <QtCore/qstringlist.h>
#include <QtCore/qset.h>
#include <QtCore/qvariant.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <errno.h>
#include <unistd.h>
#include <stdio.h>
#include <stddef.h>
#if defined(__mips__)
extern "C" int __fxstat(int,int,struct stat *);
typedef char SyncStatSize[sizeof(struct stat)==144?1:-1];
typedef char SyncStatMode[offsetof(struct stat,st_mode)==20?1:-1];
typedef char SyncStatUid[offsetof(struct stat,st_uid)==28?1:-1];
typedef char SyncStatBytes[offsetof(struct stat,st_size)==48?1:-1];
static int syncStat(int fd,struct stat *s){return __fxstat(3,fd,s);}
#else
static int syncStat(int fd,struct stat *s){return ::fstat(fd,s);}
#endif
extern "C" {
#include "third_party/sha256/sha256.h"
}
namespace {
bool fail(QString *e,const QString &s){if(e)*e=s;return false;}
QByteArray sha(const QByteArray &data){SHA256_CTX c;BYTE hash[32];sha256_init(&c);sha256_update(&c,reinterpret_cast<const BYTE *>(data.constData()),data.size());sha256_final(&c,hash);return QByteArray(reinterpret_cast<char *>(hash),32).toHex();}
bool version(const QString &s){return QRegExp("[0-9a-f]{32}").exactMatch(s);}
bool text64(const QByteArray &raw,QString *out,int limit){QByteArray d=QByteArray::fromBase64(raw);QString s=QString::fromUtf8(d.constData(),d.size());if(raw.size()%4 || d.toBase64()!=raw || d.size()>limit || d.contains('\0') || s.toUtf8()!=d)return false;*out=s;return true;}
// Deliberately small JSON grammar: objects, arrays, strings, unsigned integers.
// Duplicate keys, escaped keys/values, booleans, fractional/exponent numbers,
// NUL and excessive nesting are rejected. No executable parser or QtScript.
class Json {
 const QByteArray &b;int i;bool ok;
 void space(){while(i<b.size() && (b[i]==' '||b[i]=='\r'||b[i]=='\n'||b[i]=='\t'))++i;}
 QString str(){if(i>=b.size()||b[i++]!='"'){ok=false;return QString();}int s=i;while(i<b.size()&&b[i]!='"'){if(uchar(b[i])<32 || b[i]=='\\')ok=false;++i;}if(i>=b.size()){ok=false;return QString();}QByteArray raw=b.mid(s,i++-s);QString v=QString::fromUtf8(raw.constData(),raw.size());if(v.toUtf8()!=raw)ok=false;return v;}
 QVariant value(int depth){space();if(depth>5||i>=b.size()){ok=false;return QVariant();}
 if(b[i]=='"')return str();
 if(b[i]=='{'){++i;QVariantMap map;space();if(i<b.size()&&b[i]=='}'){++i;return map;}while(ok){space();QString key=str();space();if(i>=b.size()||b[i++]!=':'||map.contains(key)){ok=false;break;}map[key]=value(depth+1);space();if(i<b.size()&&b[i]=='}'){++i;return map;}if(i>=b.size()||b[i++]!=','){ok=false;break;}}return QVariant();}
 if(b[i]=='['){++i;QVariantList list;space();if(i<b.size()&&b[i]==']'){++i;return list;}while(ok&&list.size()<8){list.append(value(depth+1));space();if(i<b.size()&&b[i]==']'){++i;return list;}if(i>=b.size()||b[i++]!=','){ok=false;break;}}ok=false;return QVariant();}
 int s=i;while(i<b.size()&&b[i]>='0'&&b[i]<='9')++i;QByteArray n=b.mid(s,i-s);bool parsed=false;qint64 number=n.toLongLong(&parsed);if(!parsed||(n.size()>1&&n[0]=='0'))ok=false;return QVariant(number);
 }
public:explicit Json(const QByteArray &data):b(data),i(0),ok(true){}bool parse(QVariantMap *out){QVariant v=value(0);space();if(!ok||i!=b.size()||v.type()!=QVariant::Map)return false;*out=v.toMap();return true;}
};
bool keys(const QVariantMap &m,const QString &list){QStringList expected=list.split(',');return m.keys().toSet()==expected.toSet();}
bool integer(const QVariantMap &m,const char *key,qint64 lo,qint64 hi,qint64 *out){QVariant v=m.value(key);if(v.type()!=QVariant::LongLong)return false;qint64 n=v.toLongLong();if(n<lo||n>hi)return false;*out=n;return true;}
QString string(const QVariantMap &m,const char *key){return m.value(key).type()==QVariant::String?m.value(key).toString():QString();}
}
bool parseDeviceManifest(const QByteArray &raw,DeviceManifest *out,QString *error){
 if(!out||raw.size()>65536||raw.contains('\0'))return fail(error,"manifest-size");QVariantMap m;if(!Json(raw).parse(&m)||!keys(m,"schema,version,serverEpoch,generatedAt,pollSeconds,files"))return fail(error,"manifest-json");
 DeviceManifest c;qint64 n=0;if(!integer(m,"schema",1,1,&n)||!integer(m,"serverEpoch",946684800LL,4133980799LL,&c.serverEpoch)||!integer(m,"generatedAt",946684800LL,4133980799LL,&c.generatedAt)||!integer(m,"pollSeconds",30,3600,&n))return fail(error,"manifest-fields");c.pollSeconds=int(n);c.version=string(m,"version");if(!version(c.version)||m.value("files").type()!=QVariant::List)return fail(error,"manifest-version");
 QVariantList files=m.value("files").toList();if(files.size()!=3)return fail(error,"manifest-files");QSet<QString> seen;
 for(int i=0;i<files.size();++i){if(files[i].type()!=QVariant::Map)return fail(error,"manifest-file");QVariantMap f=files[i].toMap();if(!keys(f,"name,bytes,sha256,path"))return fail(error,"manifest-file-fields");DeviceFile d;d.name=string(f,"name");int cap=d.name=="content.ini"?131072:d.name=="background.png"?2097152:d.name=="SHA256SUMS"?512:0;if(!cap||seen.contains(d.name)||!integer(f,"bytes",1,cap,&n))return fail(error,"manifest-file-size");seen.insert(d.name);d.bytes=int(n);d.sha256=string(f,"sha256");d.path=string(f,"path");if(!QRegExp("[0-9a-f]{64}").exactMatch(d.sha256)||d.path!="/reader/v1/resources/"+c.version+"/"+d.name)return fail(error,"manifest-file-path");c.files.append(d);}
 *out=c;if(error)error->clear();return true;
}
bool parseDeviceEndpoint(const QString &raw,DeviceEndpoint *out,QString *error){
 if(!out||raw.toUtf8().size()>2048||raw.contains(QChar(0)))return fail(error,"endpoint-origin");
 QRegExp legacy("(http|https)://([0-9.]+):([1-9][0-9]{0,4})");
 if(legacy.exactMatch(raw)){struct in_addr addr;QByteArray host=legacy.cap(2).toLatin1();if(::inet_pton(AF_INET,host.constData(),&addr)!=1)return fail(error,"endpoint-ip");int port=legacy.cap(3).toInt();bool tls=legacy.cap(1)=="https";if(port>65535||!port)return fail(error,"endpoint-port");if(!tls&&host!="127.0.0.1")return fail(error,"cleartext-lan-forbidden");DeviceEndpoint e;e.host=legacy.cap(2);e.port=port;e.tls=tls;*out=e;if(error)error->clear();return true;}
 QRegExp domain("https://([A-Za-z0-9.-]+)(:([1-9][0-9]{0,4}))?(/pandanote/?)?");
 if(!domain.exactMatch(raw))return fail(error,"endpoint-domain");
 QString host=domain.cap(1).toLower();if(!validDnsHost(host.toLatin1().constData()))return fail(error,"endpoint-domain");
 int port=domain.cap(3).isEmpty()?443:domain.cap(3).toInt();if(port>65535||!port)return fail(error,"endpoint-port");
 DeviceEndpoint e;e.host=host;e.port=port;e.tls=true;e.basePath=domain.cap(4).isEmpty()?QString():QString("/pandanote");*out=e;if(error)error->clear();return true;
}
QString deviceRequestTarget(const DeviceEndpoint &e,const QString &logical){
 if((!e.basePath.isEmpty()&&e.basePath!="/pandanote")||!logical.startsWith("/reader/v1/")||logical.contains("..")||logical.contains("//")||!QRegExp("/reader/v1/[A-Za-z0-9/._-]+").exactMatch(logical))return QString();
 return e.basePath+logical;
}

bool HttpReply::feed(const QByteArray &bytes,int limit,QString *error){
 if(complete_||limit<0)return fail(error,"http-extra-data");
 if(!header_){buffer_+=bytes;int split=buffer_.indexOf("\r\n\r\n");if(split<0){if(buffer_.size()>8192)return fail(error,"http-header-size");return true;}if(split>8192)return fail(error,"http-header-size");QList<QByteArray> lines=buffer_.left(split).split('\n');QByteArray first=lines.takeFirst().trimmed();QRegExp status("HTTP/1\\.[01] ([0-9]{3}) [ -~]*");if(!status.exactMatch(QString::fromLatin1(first)))return fail(error,"http-status");status_=status.cap(1).toInt();QSet<QByteArray> seen;bool got=false;
 for(int i=0;i<lines.size();++i){QByteArray line=lines[i].trimmed();int colon=line.indexOf(':');if(colon<1)return fail(error,"http-header");QByteArray key=line.left(colon).toLower(),v=line.mid(colon+1).trimmed();if(!QRegExp("[a-z0-9-]+").exactMatch(QString::fromLatin1(key))||seen.contains(key))return fail(error,"http-duplicate-header");seen.insert(key);if(key=="transfer-encoding"||key=="content-encoding")return fail(error,"http-encoding");if(key=="content-length"){bool ok=false;length_=v.toInt(&ok);if(!ok||!QRegExp("0|[1-9][0-9]*").exactMatch(QString::fromLatin1(v))||length_>limit||length_<0)return fail(error,"http-body-size");got=true;}}
 if(!got)return fail(error,"http-length-required");data_=buffer_.mid(split+4);buffer_.clear();header_=true;
 }else data_+=bytes;
 if(data_.size()>length_||data_.size()>limit)return fail(error,"http-extra-data");complete_=data_.size()==length_;return true;
}
bool validSyncPath(const QString &path){QByteArray b=path.toUtf8();return path.startsWith('/')&&path!="/"&&b.size()<=4096&&!b.contains('\0')&&!path.endsWith('/')&&!path.contains("//")&&!path.split('/').contains(".")&&!path.split('/').contains("..");}
namespace {
bool syncDirectoryFd(int fd,bool privateLeaf,bool publicTmp){struct stat st;if(fd<0||syncStat(fd,&st)||!S_ISDIR(st.st_mode))return false;if(privateLeaf)return st.st_uid==::geteuid()&&(st.st_mode&07777)==0700;return ((st.st_uid==0||st.st_uid==::geteuid())&&!(st.st_mode&0022))||(publicTmp&&st.st_uid==0&&(st.st_mode&07777)==01777);}
// Open the first absolute component directly: retained QEMU sysroot rewrites
// open("/") but not this explicit path. All remaining traversal is openat.
int syncDirectory(const QString &path,bool privateLeaf,bool create){
 if(!validSyncPath(path))return -1;QStringList parts=path.mid(1).split('/');int fd=::open(("/"+parts[0]).toUtf8().constData(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
 for(int i=0;i<parts.size();++i){bool final=i==parts.size()-1;
  if(!syncDirectoryFd(fd,final&&privateLeaf,i==0&&parts[i]=="tmp"&&(!final||!privateLeaf))){if(fd>=0)::close(fd);return -1;}
  if(final)return fd;QByteArray name=parts[i+1].toUtf8();int next=::openat(fd,name.constData(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
  if(next<0&&errno==ENOENT&&i+2==parts.size()&&privateLeaf){if(!create){::close(fd);return -2;}if(::mkdirat(fd,name.constData(),0700)&&errno!=EEXIST){::close(fd);return -1;}next=::openat(fd,name.constData(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);}
  ::close(fd);fd=next;
 }return -1;
}
}
bool syncCacheDirectory(const QString &path,bool create){int fd=syncDirectory(path,true,create);if(fd>=0)::close(fd);return fd>=0||(!create&&fd==-2);}
bool readSyncFile(const QString &path,int limit,bool privateFile,QByteArray *out){
 if(!out||limit<1||!validSyncPath(path))return false;int parent=syncDirectory(path.left(path.lastIndexOf('/')),false,false);if(parent<0)return false;
 int fd=::openat(parent,path.section('/',-1).toUtf8().constData(),O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);::close(parent);if(fd<0)return false;struct stat st;
 bool safe=!syncStat(fd,&st)&&S_ISREG(st.st_mode)&&st.st_uid==::geteuid()&&!(st.st_mode&(privateFile?0077:0022))&&st.st_size>0&&st.st_size<=limit;
 QByteArray bytes;char buffer[4096];while(safe&&bytes.size()<=limit){ssize_t n=::read(fd,buffer,qMin(int(sizeof buffer),limit+1-bytes.size()));if(n<0&&errno==EINTR)continue;if(n<0){safe=false;break;}if(!n)break;bytes.append(buffer,int(n));}
 ::close(fd);if(!safe||bytes.size()!=st.st_size||bytes.size()>limit){bytes.fill('\0');return false;}*out=bytes;return true;
}
DeviceSync::DeviceSync(const QString &cache):cache_(cache),resource_(0),freshEpoch_(0){
 if(!syncCacheDirectory(cache_))return;
 QFileInfo root(cache_);if(root.isSymLink() || !root.isDir() || root.ownerId()!=::geteuid() || (root.permissions()&(QFile::ReadGroup|QFile::WriteGroup|QFile::ExeGroup|QFile::ReadOther|QFile::WriteOther|QFile::ExeOther)))return;
 QFileInfo pointer(cache_+"/current");if(pointer.isSymLink()||!pointer.isFile())return;
 QFile file(pointer.filePath());if(!file.open(QIODevice::ReadOnly)||file.size()!=33)return;
 QByteArray id=file.read(34).trimmed();if(!version(QString::fromLatin1(id)))return;
 Content cached;QString error;
 if(loadContent(cache_+"/"+QString::fromLatin1(id),&cached,&error)&&cached.version==QString::fromLatin1(id))content_=cached;
 // Cached pixels may be observed before authentication. They never authenticate
 // the version or establish a fresh time anchor; prepareAck requires both facts.
}
bool DeviceSync::store(const QString &path,const QByteArray &bytes){QFile file(path);if(QFileInfo(path).exists()||QFileInfo(path).isSymLink()||!file.open(QIODevice::WriteOnly|QIODevice::Truncate))return false;file.setPermissions(QFile::ReadOwner|QFile::WriteOwner);bool ok=file.write(bytes)==bytes.size()&&file.flush();file.close();return ok;}
void DeviceSync::discardStaging(){if(staging_.isEmpty())return;if(QFileInfo(staging_).isSymLink()){staging_.clear();return;}QDir d(staging_);QStringList names;names<<"content.ini"<<"background.png"<<"SHA256SUMS";for(int i=0;i<names.size();++i)QFile::remove(d.filePath(names[i]));QDir().rmdir(staging_);staging_.clear();}
void DeviceSync::refresh(){if(!request_.path.isEmpty()||!pending_.isEmpty())return;freshEpoch_=0;authenticated_.clear();request_=SyncRequest();request_.method="GET";request_.path="/reader/v1/manifest";request_.limit=65536;}
void DeviceSync::getResource(){request_=SyncRequest();const DeviceFile &f=manifest_.files[resource_];request_.method="GET";request_.path=f.path;request_.limit=f.bytes;}
void DeviceSync::failed(const QString &code){error_=code;authenticated_.clear();request_=SyncRequest();discardStaging();}
bool DeviceSync::validateVersion(const QString &directory,Content *out)const {
 QFileInfo info(directory);
 if(info.isSymLink()||!info.isDir()||info.ownerId()!=::geteuid())return false;
 // A self-consistent package is insufficient: every exact stored buffer must
 // also match this authenticated immutable manifest, including SHA256SUMS.
 for(int i=0;i<manifest_.files.size();++i){
  const DeviceFile &expected=manifest_.files[i];QFileInfo fileInfo(directory+"/"+expected.name);
  if(fileInfo.isSymLink()||!fileInfo.isFile()||fileInfo.size()!=expected.bytes)return false;
  QFile file(fileInfo.filePath());if(!file.open(QIODevice::ReadOnly))return false;
  QByteArray bytes=file.read(expected.bytes+1);
  if(file.error()!=QFile::NoError||bytes.size()!=expected.bytes||sha(bytes)!=expected.sha256.toLatin1())return false;
 }
 Content candidate;QString error;
 if(!loadContent(directory,&candidate,&error)||candidate.version!=manifest_.version||candidate.generatedAt!=manifest_.generatedAt)return false;
 *out=candidate;return true;
}
void DeviceSync::pruneVersions(const QString &current,const QString &candidate){
 QDir cache(cache_);QStringList entries=cache.entryList(QDir::Dirs|QDir::NoDotAndDotDot);
 for(int i=0;i<entries.size();++i){
  QString id=entries[i];if(!version(id)||id==current||id==candidate)continue;
  QString directory=cache.filePath(id);QFileInfo info(directory);if(info.isSymLink()||info.ownerId()!=::geteuid())continue;
  QDir old(directory);QStringList files=old.entryList(QDir::Files|QDir::Hidden|QDir::System|QDir::NoDotAndDotDot);
  QStringList expected;expected<<"SHA256SUMS"<<"background.png"<<"content.ini";
  if(files.toSet()!=expected.toSet())continue;
  bool safe=true;for(int f=0;f<files.size();++f)if(QFileInfo(old.filePath(files[f])).isSymLink())safe=false;
  if(!safe)continue;for(int f=0;f<files.size();++f)QFile::remove(old.filePath(files[f]));QDir().rmdir(directory);
 }
}
bool DeviceSync::commitVersion(const Content &candidate){
 // Once the final directory is verified, it is safe recovery material even if
 // current.new/current cannot commit. Keep the old current and this candidate;
 // never remove old current or overwrite an immutable version to resolve it.
 pruneVersions(content_.version,candidate.version);
 QFile::remove(cache_+"/current.new");
 if(!store(cache_+"/current.new",candidate.version.toLatin1()+"\n")||
    ::rename((cache_+"/current.new").toLocal8Bit().constData(),(cache_+"/current").toLocal8Bit().constData())){
  failed("cache-pointer");return false;
 }
 content_=candidate;pending_=candidate.version;authenticated_=candidate.version;
 request_=SyncRequest();error_.clear();return true;
}
void DeviceSync::prepareAck(){
 if(content_.schema!=1||displayed_!=content_.version||authenticated_!=content_.version||acknowledged_==displayed_||!request_.path.isEmpty())return;
 request_=SyncRequest();request_.method="POST";request_.path="/reader/v1/ack";request_.limit=4096;
 request_.body="{\"schema\":1,\"version\":\""+displayed_.toLatin1()+"\",\"displayed\":true}";
}
bool DeviceSync::receive(int status,const QByteArray &body){
 if(request_.path.isEmpty())return false;freshEpoch_=0;
 if(status!=200||body.size()>request_.limit){failed("http-status-or-size");return false;}
 if(request_.path=="/reader/v1/ack"){acknowledged_=displayed_;request_=SyncRequest();error_.clear();return true;}
 if(request_.path=="/reader/v1/manifest"){
  QString error;DeviceManifest candidateManifest;
  if(!parseDeviceManifest(body,&candidateManifest,&error)){failed(error);return false;}
  manifest_=candidateManifest;freshEpoch_=manifest_.serverEpoch;authenticated_.clear();error_.clear();request_=SyncRequest();
  if(!syncCacheDirectory(cache_,true)){failed("cache-root");return false;}
  QString destination=cache_+"/"+manifest_.version;QFileInfo existing(destination);Content candidate;
  if(content_.version==manifest_.version){
   if(!validateVersion(destination,&candidate)){failed("cache-version-integrity");return false;}
   authenticated_=manifest_.version;prepareAck();return true;
  }
  QStringList incoming=QDir(cache_).entryList(QStringList()<<".incoming-*",QDir::Dirs|QDir::Hidden|QDir::System|QDir::NoDotAndDotDot);
  if(!incoming.isEmpty()){failed("cache-unfinished-stage");return false;}
  if(existing.exists()||existing.isSymLink()){
   if(!validateVersion(destination,&candidate)){failed("cache-version-integrity");return false;}
   return commitVersion(candidate);
  }
  staging_=cache_+"/.incoming-"+manifest_.version+"-"+QString::number(::getpid());
  if(QFileInfo(staging_).isSymLink()||QFileInfo(staging_).exists()||!QDir().mkdir(staging_)){staging_.clear();failed("cache-stage");return false;}
  ::chmod(staging_.toLocal8Bit().constData(),0700);resource_=0;getResource();return true;
 }
 const DeviceFile &expected=manifest_.files[resource_];
 if(body.size()!=expected.bytes||sha(body)!=expected.sha256.toLatin1()||!store(staging_+"/"+expected.name,body)){failed("resource-integrity");return false;}
 if(++resource_<3){getResource();return true;}
 Content candidate;
 if(!validateVersion(staging_,&candidate)){failed("package-validation");return false;}
 QString destination=cache_+"/"+manifest_.version;
 if(QFileInfo(destination).exists()||QFileInfo(destination).isSymLink()){
  // A version appearing during this transfer is not silently overwritten.
  Content existing;if(!validateVersion(destination,&existing)){failed("cache-version-integrity");return false;}
  discardStaging();return commitVersion(existing);
 }
 if(!QDir().rename(staging_,destination)){failed("cache-promote");return false;}
 staging_.clear();
 if(!validateVersion(destination,&candidate)){failed("cache-final-validation");return false;}
 return commitVersion(candidate);
}
bool DeviceSync::takeUpdate(Content *out){if(!out||pending_.isEmpty())return false;*out=content_;return true;}
void DeviceSync::painted(const QString &id){
 if(content_.schema!=1||id!=content_.version)return;
 displayed_=id;if(pending_==id)pending_.clear();prepareAck();
}
static int httpTlsSend(void *context,unsigned char *data,int n){int fd=*static_cast<int *>(context);int r=::send(fd,data,n,MSG_NOSIGNAL);return r<0&&(errno==EAGAIN||errno==EWOULDBLOCK||errno==EINPROGRESS)?-1:r;}
static int httpTlsRecv(void *context,unsigned char *data,int n){int fd=*static_cast<int *>(context);int r=::recv(fd,data,n,0);return r<0&&(errno==EAGAIN||errno==EWOULDBLOCK)?-1:r;}
DeviceHttp::DeviceHttp():fd_(-1),phase_(0),sent_(0),limit_(0),useTls_(false),resolving_(false),trustedEpoch_(0),trustedAtMs_(-1),addressCount_(0),nextAddress_(0){}DeviceHttp::~DeviceHttp(){cancel();}
void DeviceHttp::trustEpoch(qint64 e){if(!validTlsEpoch(e))return;tls_.trustEpoch(e);trustedEpoch_=e;trustedAtMs_=tlsBootMs();}
void DeviceHttp::cancel(){if(fd_>=0)::close(fd_);fd_=-1;resolving_=false;resolver_.cancel();tls_.reset();outgoing_.fill('\0');outgoing_.clear();}
// The power timer calls this even when standby has stopped syncTick. A killed
// resolver remains owned until waitpid confirms exit; no new transport starts.
bool DeviceHttp::reapCancelledResolver(){
 if(!resolving_&&resolver_.busy()){char ignored[4][16];unsigned count=0;resolver_.poll(ignored,&count);}
 return !resolver_.busy();
}
bool DeviceHttp::connectAddress(const char *ip,QString *error){
 if(fd_>=0)::close(fd_);fd_=-1;tls_.reset();
 fd_=::socket(AF_INET,SOCK_STREAM,0);if(fd_<0)return fail(error,"http-socket");
 if(::fcntl(fd_,F_SETFL,O_NONBLOCK)<0||::fcntl(fd_,F_SETFD,FD_CLOEXEC)<0){::close(fd_);fd_=-1;return fail(error,"http-socket");}
 struct sockaddr_in addr;memset(&addr,0,sizeof addr);addr.sin_family=AF_INET;addr.sin_port=htons(activeEndpoint_.port);if(::inet_pton(AF_INET,ip,&addr.sin_addr)!=1){::close(fd_);fd_=-1;return fail(error,"http-connect");}
 int result=::connect(fd_,reinterpret_cast<sockaddr *>(&addr),sizeof addr);if(result<0&&errno!=EINPROGRESS){::close(fd_);fd_=-1;return fail(error,"http-connect");}
 phase_=-3;return true;
}
int DeviceHttp::pollResolver(QString *error){
 int result=resolver_.poll(addresses_,&addressCount_);if(result<=0){if(result<0){cancel();fail(error,"http-connect");}return result;}
 resolving_=false;nextAddress_=0;while(nextAddress_<addressCount_)if(connectAddress(addresses_[nextAddress_++],error))return 0;
 cancel();fail(error,"http-connect");return -1;
}
bool DeviceHttp::start(const DeviceEndpoint &e,const QByteArray &token,const SyncRequest &r,QString *error){
 QString target=deviceRequestTarget(e,r.path);struct in_addr numeric;bool ip=::inet_pton(AF_INET,e.host.toLatin1().constData(),&numeric)==1;
 if(busy()||(!e.tls&&e.host!="127.0.0.1")||(!ip&&!validDnsHost(e.host.toLatin1().constData()))||e.port<1||e.port>65535||target.isEmpty()||token.size()<16||token.size()>512||!QRegExp("[A-Za-z0-9._~-]+").exactMatch(QString::fromLatin1(token))||(r.method!="GET"&&r.method!="POST"))return fail(error,"http-config");
 activeEndpoint_=e;useTls_=e.tls;limit_=r.limit;sent_=0;reply_=HttpReply();clock_.start();
 outgoing_=r.method.toLatin1()+" "+target.toLatin1()+" HTTP/1.1\r\nHost: "+e.host.toLatin1()+":"+QByteArray::number(e.port)+"\r\nAuthorization: Bearer "+token+"\r\nConnection: close\r\nAccept: application/json, application/octet-stream\r\n";if(r.method=="POST")outgoing_+="Content-Type: application/json\r\nContent-Length: "+QByteArray::number(r.body.size())+"\r\n";outgoing_+="\r\n"+r.body;
 if(useTls_&&!trustedEpoch_){trustedEpoch_=tlsInitialEpoch(!ip,e.bootstrapEpoch,tlsRealtimeEpoch());trustedAtMs_=tlsBootMs();}
 if(ip){strncpy(addresses_[0],e.host.toLatin1().constData(),15);addresses_[0][15]=0;addressCount_=nextAddress_=1;if(!connectAddress(addresses_[0],error)){cancel();return false;}}
 else{QByteArray executable=QCoreApplication::applicationFilePath().toLocal8Bit(),host=e.host.toLatin1();if(!resolver_.start(executable.constData(),host.constData())){cancel();return fail(error,"http-connect");}resolving_=true;}
 if(error)error->clear();return true;
}
int DeviceHttp::poll(int *status,QByteArray *body,QString *error){
 // Cancellation retains the owned resolver PID until waitpid reaps it.
 reapCancelledResolver();
 if(fd_<0&&!resolving_)return 0;if(clock_.elapsed()>15000){cancel();fail(error,"http-timeout");return -1;}
 if(resolving_)return pollResolver(error);
 if(phase_==-3){struct pollfd item;item.fd=fd_;item.events=POLLOUT;item.revents=0;int ready=::poll(&item,1,0);if(!ready||(ready<0&&errno==EINTR))return 0;
  int e=0;socklen_t n=sizeof e;if(ready<0||::getsockopt(fd_,SOL_SOCKET,SO_ERROR,&e,&n)<0||e){while(nextAddress_<addressCount_)if(connectAddress(addresses_[nextAddress_++],error))return 0;cancel();fail(error,"http-connect");return -1;}
  if(useTls_){qint64 epoch=tlsAdvanceEpoch(trustedEpoch_,trustedAtMs_,tlsBootMs());if(validDnsHost(activeEndpoint_.host.toLatin1().constData())&&validTlsEpoch(activeEndpoint_.bootstrapEpoch)&&epoch>0&&epoch<activeEndpoint_.bootstrapEpoch)epoch=activeEndpoint_.bootstrapEpoch;if(!epoch){cancel();fail(error,"tls-profile");return -1;}if(!tls_.configure(activeEndpoint_.host,activeEndpoint_.certificatePem,activeEndpoint_.certificateSha256,epoch,&fd_,httpTlsSend,httpTlsRecv,error)){cancel();return -1;}}phase_=useTls_?-1:0;
 }
 if(phase_==-1){int result=tls_.handshake(error);if(result<0){cancel();return -1;}if(!result)return 0;phase_=0;}
 if(phase_==0){int count=useTls_?tls_.write(reinterpret_cast<const unsigned char *>(outgoing_.constData()+sent_),outgoing_.size()-sent_) : ::send(fd_,outgoing_.constData()+sent_,outgoing_.size()-sent_,MSG_NOSIGNAL);if(count>0)sent_+=count;else if((useTls_&&count<-1)||(!useTls_&&count<0&&errno!=EAGAIN&&errno!=EWOULDBLOCK&&errno!=EINPROGRESS)){cancel();fail(error,"http-send");return -1;}if(sent_==outgoing_.size()){outgoing_.fill('\0');outgoing_.clear();phase_=1;}return 0;}
 char buffer[16384];for(int loops=0;loops<2;++loops){int count=useTls_?tls_.read(reinterpret_cast<unsigned char *>(buffer),sizeof buffer) : ::recv(fd_,buffer,sizeof buffer,0);if((useTls_&&count==-1)||(!useTls_&&count<0&&(errno==EAGAIN||errno==EWOULDBLOCK)))return 0;if(count<=0){cancel();fail(error,"http-truncated");return -1;}if(!reply_.feed(QByteArray(buffer,count),limit_,error)){cancel();return -1;}if(reply_.complete()){*status=reply_.status();*body=reply_.body();cancel();return 1;}}return 0;
}
QByteArray radioRequest(const QString &action,const QString &value,const QString &password){
 QStringList actions;actions<<"status"<<"wifi-scan"<<"wifi-connect"<<"wifi-disconnect"<<"bluetooth-status"<<"bluetooth-scan"<<"bluetooth-pair"<<"bluetooth-disconnect";if(!actions.contains(action))return QByteArray();
 QByteArray out="[request]\nschema=1\naction="+action.toLatin1()+"\n";
 if(action=="wifi-connect"){QByteArray ssid=value.toUtf8(),pass=password.toUtf8();if(ssid.isEmpty()||ssid.size()>32||pass.size()>63||ssid.contains('\0')||pass.contains('\0'))return QByteArray();out+="ssid64="+ssid.toBase64()+"\npassword64="+pass.toBase64()+"\n";pass.fill('\0');}
 if(action=="bluetooth-pair"||action=="bluetooth-disconnect"){if(!QRegExp("[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}").exactMatch(value))return QByteArray();out+="peer64="+value.toUtf8().toBase64()+"\n";}
 return out;
}
static QString wifiSecurityFamily(const QString &security){
 QString kind=security.toLower();return kind=="wpa"||kind=="wpa2"?QString("wpa-personal"):security;
}
bool parseRadioReply(const QByteArray &raw,RadioReply *out,QString *error){
 if(!out||raw.size()>65536||raw.contains('\0'))return fail(error,"radio-reply-size");QMap<QString,QMap<QString,QByteArray> > sections;QString group;QSet<QString> seen;QList<QByteArray> lines=raw.split('\n');
 for(int i=0;i<lines.size();++i){QByteArray line=lines[i];if(line.endsWith('\r'))line.chop(1);if(line.isEmpty())continue;if(line.startsWith('[')&&line.endsWith(']')){group=QString::fromLatin1(line.mid(1,line.size()-2));if(seen.contains(group)||!QRegExp("reply|status|wifi[0-9]{1,2}|bluetooth[0-9]{1,2}").exactMatch(group))return fail(error,"radio-section");seen.insert(group);continue;}int p=line.indexOf('=');QString key=QString::fromLatin1(line.left(p));if(group.isEmpty()||p<1||!QRegExp("[a-zA-Z0-9_]+").exactMatch(key)||sections[group].contains(key))return fail(error,"radio-key");QByteArray v=line.mid(p+1);if(v.size()>8192)return fail(error,"radio-value-size");sections[group][key]=v;}
 QMap<QString,QByteArray> reply=sections.take("reply");if(reply.size()!=4||reply.value("schema")!="1"||(reply.value("ok")!="0"&&reply.value("ok")!="1")||!QRegExp("[a-zA-Z0-9_-]{1,64}").exactMatch(QString::fromLatin1(reply.value("code"))))return fail(error,"radio-reply");RadioReply c;c.ok=reply.value("ok")=="1";c.code=QString::fromLatin1(reply.value("code"));if(!text64(reply.value("message64"),&c.message,4096))return fail(error,"radio-message");
 QMap<QString,QByteArray> status=sections.take("status");for(QMap<QString,QByteArray>::const_iterator it=status.begin();it!=status.end();++it){if(it.key().contains("password")||!QRegExp("[ -~]{0,256}").exactMatch(QString::fromLatin1(it.value())))return fail(error,"radio-status");c.status[it.key()]=QString::fromLatin1(it.value());}
 if(c.status.contains("wifi_ssid64")){QString ssid;if(!text64(c.status.value("wifi_ssid64").toLatin1(),&ssid,32))return fail(error,"radio-associated-ssid");if(c.status.value("wifi_state")=="COMPLETED")c.wifiSsid=ssid;}
 QMap<int,WifiRow> scanRows;
 for(QMap<QString,QMap<QString,QByteArray> >::const_iterator it=sections.begin();it!=sections.end();++it){QMap<QString,QByteArray> v=it.value();if(it.key().startsWith("wifi")){WifiRow row;if(v.size()!=3||!text64(v.value("ssid64"),&row.ssid,32))return fail(error,"radio-wifi");row.signal=QString::fromLatin1(v.value("signal"));row.security=QString::fromLatin1(v.value("security"));if(!QRegExp("-?[0-9]{1,3}").exactMatch(row.signal)||!QRegExp("[ -~]{0,80}").exactMatch(row.security))return fail(error,"radio-wifi-fields");int ordinal=it.key().mid(4).toInt();if(scanRows.size()>=64||scanRows.contains(ordinal))return fail(error,"radio-wifi-count-index");scanRows[ordinal]=row;}else {BluetoothRow row;if(v.size()!=4||!text64(v.value("peer64"),&row.peer,32)||!text64(v.value("name64"),&row.name,256)||!QRegExp("[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}").exactMatch(row.peer))return fail(error,"radio-bluetooth");row.paired=QString::fromLatin1(v.value("paired"));row.connected=QString::fromLatin1(v.value("connected"));if((row.paired!="0"&&row.paired!="1")||(row.connected!="0"&&row.connected!="1"))return fail(error,"radio-bluetooth-fields");c.bluetooth.append(row);}}
 // Numeric helper row order is stable; replacing a stronger representative
 // never moves its group. Exact SSID comparison preserves case and UTF-8 bytes.
 for(QMap<int,WifiRow>::const_iterator it=scanRows.begin();it!=scanRows.end();++it){
  const WifiRow &row=it.value();int group=-1;
  for(int i=0;i<c.wifi.size();++i)if(c.wifi[i].ssid==row.ssid&&wifiSecurityFamily(c.wifi[i].security)==wifiSecurityFamily(row.security)){group=i;break;}
  if(group<0)c.wifi.append(row);else if(row.signal.toInt()>c.wifi[group].signal.toInt())c.wifi[group]=row;
 }
 *out=c;if(error)error->clear();return true;
}
RadioClient::RadioClient():running_(false){}RadioClient::~RadioClient(){if(running_)process_.kill();}
bool RadioClient::start(const QString &action,const QString &value,const QString &password){
 if(running_)return false;QByteArray request=radioRequest(action,value,password);if(request.isEmpty()){reply_=RadioReply();reply_.code="invalid-request";return false;}
 process_.setProcessChannelMode(QProcess::SeparateChannels);process_.setReadChannel(QProcess::StandardOutput);QStringList args;args<<action;process_.start("/tmp/pandanote-connectivity/pandanote-radio.mipsel",args,QIODevice::ReadWrite);process_.write(request);process_.closeWriteChannel();request.fill('\0');output_.clear();reply_=RadioReply();running_=true;clock_.start();return true;
}
void RadioClient::stop(const QString &code){if(process_.state()!=QProcess::NotRunning)process_.kill();output_.fill('\0');output_.clear();reply_=RadioReply();reply_.code=code;running_=false;}
bool RadioClient::poll(){
 if(!running_)return false;if(clock_.elapsed()>45000){stop("helper-timeout");return true;}output_+=process_.read(65537-output_.size());process_.setReadChannel(QProcess::StandardError);QByteArray discarded=process_.read(65537);process_.setReadChannel(QProcess::StandardOutput);if(discarded.size()>65536){stop("helper-error-size");return true;}discarded.fill('\0');if(output_.size()>65536){stop("helper-output-size");return true;}
 if(process_.state()!=QProcess::NotRunning)return false;QString e;if(process_.exitStatus()!=QProcess::NormalExit||!parseRadioReply(output_,&reply_,&e)){stop("helper-failed");return true;}output_.clear();running_=false;return true;
}
