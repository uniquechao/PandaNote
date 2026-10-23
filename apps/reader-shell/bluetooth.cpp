#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "bluetooth.h"
#include <QtCore/qstringlist.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <poll.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stddef.h>
#include <string.h>
#if defined(__mips__)
extern "C" int __fxstat(int,int,struct stat *);
extern "C" int __fxstatat(int,int,const char *,struct stat *,int);
typedef char BluetoothStatSize[sizeof(struct stat)==144?1:-1];
typedef char BluetoothStatMode[offsetof(struct stat,st_mode)==20?1:-1];
typedef char BluetoothStatUid[offsetof(struct stat,st_uid)==28?1:-1];
#else
static int __fxstat(int,int fd,struct stat*s){return ::fstat(fd,s);}
static int __fxstatat(int,int fd,const char*p,struct stat*s,int flags){return ::fstatat(fd,p,s,flags);}
#endif
static bool trustedDirectory(int fd,bool final){struct stat s;if(fd<0||__fxstat(3,fd,&s)||!S_ISDIR(s.st_mode))return false;if(final)return s.st_uid==::geteuid()&&(s.st_mode&07777)==0700;return (s.st_uid==0||s.st_uid==::geteuid())&&!(s.st_mode&0022);}
static int parentDirectory(const QString &path){QStringList parts=path.mid(1).split('/');parts.removeLast();if(parts.isEmpty())return -1;int fd=::open(("/"+parts[0]).toUtf8().constData(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);for(int i=0;fd>=0&&i<parts.size();++i){bool tmp=i==0&&i+1<parts.size()&&parts[i]=="tmp";struct stat s;bool ok=trustedDirectory(fd,i==parts.size()-1)||(tmp&&!__fxstat(3,fd,&s)&&S_ISDIR(s.st_mode)&&s.st_uid==0&&(s.st_mode&07777)==01777);if(!ok){::close(fd);return -1;}if(i+1<parts.size()){int next=::openat(fd,parts[i+1].toUtf8().constData(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);::close(fd);fd=next;}}return fd;}
static bool socketStat(int dir,const QByteArray &name,struct stat *s){return !__fxstatat(3,dir,name.constData(),s,AT_SYMLINK_NOFOLLOW)&&S_ISSOCK(s->st_mode)&&s->st_uid==::geteuid()&&(s->st_mode&07777)==0600;}
static unsigned read32(const QByteArray &b,int at){unsigned n=0;for(int i=0;i<4;++i)n|=unsigned(uchar(b[at+i]))<<(8*i);return n;}
static bool nonzero(const QByteArray &b){for(int i=0;i<b.size();++i)if(b[i])return true;return false;}
BluetoothClient::BluetoothClient():fd_(-1),sent_(0),connecting_(false),ack_(false),operation_(0){}
BluetoothClient::~BluetoothClient(){cancel();}
void BluetoothClient::cancel(){if(fd_>=0)::close(fd_);fd_=-1;request_.clear();received_.clear();}
bool BluetoothClient::fail(const char *code){cancel();reply_=BluetoothReply();error_=QString::fromLatin1(code);return false;}
bool BluetoothClient::configure(const QString &path){cancel();path_.clear();error_.clear();QByteArray raw=path.toUtf8();if(!path.startsWith('/')||raw.size()>=int(sizeof(((struct sockaddr_un *)0)->sun_path))||raw.contains('\0')||path.endsWith('/')||path.contains("//")||path.split('/').contains(".")||path.split('/').contains(".."))return fail("bluetooth-path");int parent=parentDirectory(path);if(parent<0)return fail("bluetooth-private-directory");::close(parent);path_=path;return true;}
bool BluetoothClient::request(unsigned op,unsigned grants,bool allow,const QByteArray &nonce){if(busy())return false;if(op<1||op>5||((op!=3)&&(grants||allow||!nonce.isEmpty()))||(op==3&&((grants&~5U)||nonce.size()!=16||(allow&&!grants))))return fail("bluetooth-request");QByteArray b(24,0);b.replace(0,4,"OBT1",4);b[4]=char(op);b[5]=char(grants);b[6]=allow?1:0;if(op==3)b.replace(8,16,nonce);ack_=false;operation_=op;expectedNonce_=nonce;return begin(b);}
bool BluetoothClient::ack(const QByteArray &nonce,unsigned id){if(busy())return false;if(nonce.size()!=16||!nonzero(nonce)||!id||id>65535)return fail("bluetooth-ack");QByteArray b(24,0);b.replace(0,4,"OBT1",4);b[4]=5;b[5]=char(id&255);b[6]=char(id>>8);b.replace(8,16,nonce);ack_=true;operation_=5;expectedNonce_=nonce;return begin(b);}
bool BluetoothClient::begin(const QByteArray &b){error_.clear();reply_=BluetoothReply();if(path_.isEmpty())return fail("bluetooth-unconfigured");int dir=parentDirectory(path_);if(dir<0)return fail("bluetooth-private-directory");QByteArray name=path_.section('/',-1).toUtf8();struct stat before,after;if(!socketStat(dir,name,&before)){::close(dir);return fail("bluetooth-service-unavailable");}fd_=::socket(AF_UNIX,SOCK_STREAM,0);if(fd_<0){::close(dir);return fail("bluetooth-socket");}if(::fcntl(fd_,F_SETFD,FD_CLOEXEC)||::fcntl(fd_,F_SETFL,O_NONBLOCK)){::close(dir);return fail("bluetooth-nonblocking");}struct sockaddr_un addr;::memset(&addr,0,sizeof addr);addr.sun_family=AF_UNIX;QByteArray raw=path_.toUtf8();::memcpy(addr.sun_path,raw.constData(),raw.size()+1);int result=::connect(fd_,reinterpret_cast<struct sockaddr *>(&addr),sizeof addr);int saved=errno;bool same=socketStat(dir,name,&after)&&before.st_dev==after.st_dev&&before.st_ino==after.st_ino;::close(dir);if(!same)return fail("bluetooth-socket-changed");if(result&&saved!=EINPROGRESS&&saved!=EAGAIN)return fail("bluetooth-service-unavailable");connecting_=result!=0;request_=b;received_.clear();sent_=0;clock_.start();return true;}
bool BluetoothClient::decode(){
 const QByteArray &b=received_;if(b.size()!=48)return fail("bluetooth-frame-size");if(b.left(4)!="OBT1"||uchar(b[4])>1||(uchar(b[5])&~7U)||(uchar(b[6])&~5U)||b[39]||b[46]||b[47])return fail("bluetooth-response-fields");BluetoothReply r;r.accepted=b[4]==0;r.flags=uchar(b[5]);r.grants=uchar(b[6]);r.control=uchar(b[7]);r.passkey=read32(b,8);r.nonce=b.mid(12,16);r.remainingMs=read32(b,28);r.peer=b.mid(32,6);r.effectKind=uchar(b[38]);r.fileBytes=read32(b,40);r.eventId=uchar(b[44])|(unsigned(uchar(b[45]))<<8);
 if(r.passkey>999999||r.remainingMs>120000||(r.pending()&&(r.approved()||r.active()))||(r.active()&&!r.approved())||((r.pending()||r.approved()||r.active())&&(!nonzero(r.nonce)||!nonzero(r.peer)))||(r.pending()&&(!r.remainingMs||r.remainingMs>30000))||(r.effectKind!=0&&r.effectKind!=1&&r.effectKind!=5))return fail("bluetooth-response-fields");
 if(r.active()&&!r.remainingMs)return fail("bluetooth-session-expired");
 if(r.effectKind){if(!r.accepted||operation_!=5||ack_||!r.active()||!r.eventId||(r.effectKind==1&&(!(r.grants&1)||r.control>2||r.fileBytes))||(r.effectKind==5&&(!(r.grants&4)||r.control||r.fileBytes>262144)))return fail("bluetooth-response-fields");}else if(r.eventId||r.fileBytes||r.control)return fail("bluetooth-response-fields");
 if(r.accepted&&((operation_==1||operation_==4)&&r.flags))return fail("bluetooth-response-fields");
 if(r.accepted&&operation_==3&&(!r.approved()||r.grants!=uchar(request_[5])))return fail("bluetooth-response-fields");
 if(r.accepted&&(operation_==3||ack_)&&r.nonce!=expectedNonce_)return fail("bluetooth-response-nonce");reply_=r;error_.clear();return true;
}
bool BluetoothClient::poll(){if(!busy())return false;if(clock_.elapsed()>=500){fail("bluetooth-timeout");return true;}if(connecting_){struct pollfd p={fd_,POLLOUT,0};int ready=::poll(&p,1,0);if(ready<0&&errno!=EINTR){fail("bluetooth-connect");return true;}if(!ready)return false;int error=0;socklen_t n=sizeof error;if(::getsockopt(fd_,SOL_SOCKET,SO_ERROR,&error,&n)||error){fail("bluetooth-connect");return true;}connecting_=false;}
 struct ucred cred;socklen_t size=sizeof cred;if(::getsockopt(fd_,SOL_SOCKET,SO_PEERCRED,&cred,&size)||size!=sizeof cred||cred.uid!=::geteuid()){fail("bluetooth-peer-owner");return true;}
 if(sent_<request_.size()){ssize_t n=::send(fd_,request_.constData()+sent_,request_.size()-sent_,MSG_NOSIGNAL);if(n<0&&(errno==EAGAIN||errno==EWOULDBLOCK||errno==EINTR))return false;if(n<=0){fail("bluetooth-send");return true;}sent_+=int(n);if(sent_<request_.size())return false;}
 char buffer[49];ssize_t n=::recv(fd_,buffer,sizeof buffer,0);if(n<0&&(errno==EAGAIN||errno==EWOULDBLOCK||errno==EINTR))return false;if(n<0){fail("bluetooth-receive");return true;}if(n>0){received_.append(buffer,int(n));if(received_.size()>48){fail("bluetooth-frame-size");return true;}return false;}
 ::close(fd_);fd_=-1;decode();request_.clear();received_.clear();return true;
}
