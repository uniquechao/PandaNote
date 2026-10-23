#include "localapps.h"
#include <QtCore/qstringlist.h>
#include <QtCore/qregexp.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <stddef.h>
#if defined(__mips__)
typedef char StatSize[sizeof(struct stat)==144?1:-1];
typedef char StatMode[offsetof(struct stat,st_mode)==20?1:-1];
typedef char StatUid[offsetof(struct stat,st_uid)==28?1:-1];
typedef char StatSizeField[offsetof(struct stat,st_size)==48?1:-1];
// MIPS o32 retained glibc exposes versioned stat entry points; headers are newer.
extern "C" int __fxstat(int,int,struct stat *);
extern "C" int __fxstatat(int,int,const char *,struct stat *,int);
static int oldFstat(int fd,struct stat *s){return __fxstat(3,fd,s);}
static int oldFstatat(int fd,const char *p,struct stat *s,int flags){return __fxstatat(3,fd,p,s,flags);}
#else
static int oldFstat(int fd,struct stat *s){return ::fstat(fd,s);}
static int oldFstatat(int fd,const char *p,struct stat *s,int flags){return ::fstatat(fd,p,s,flags);}
#endif
static const int CAP=2*1024*1024;
static bool privateDir(int fd){struct stat s;return fd>=0&&!oldFstat(fd,&s)&&S_ISDIR(s.st_mode)&&s.st_uid==::geteuid()&&(s.st_mode&07777)==0700;}
static bool privateFile(int fd){struct stat s;return fd>=0&&!oldFstat(fd,&s)&&S_ISREG(s.st_mode)&&s.st_uid==::geteuid()&&(s.st_mode&07777)==0600&&s.st_nlink==1&&s.st_size>0&&s.st_size<=CAP;}
static int child(int parent,const char *name){if(::mkdirat(parent,name,0700)&&errno!=EEXIST)return -1;int fd=::openat(parent,name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);if(!privateDir(fd)){if(fd>=0)::close(fd);return -1;}return fd;}
static bool readData(int dir,QByteArray *data,int limit=CAP){int fd=::openat(dir,"data",O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);if(fd<0)return errno==ENOENT;if(!privateFile(fd)){::close(fd);return false;}char buf[4096];ssize_t n;while((n=::read(fd,buf,sizeof(buf)))>0){data->append(buf,int(n));if(data->size()>limit){::close(fd);return false;}}::close(fd);return n==0;}
static bool utf8(const QByteArray &b,QString *s,int limit){if(b.size()>limit||b.contains('\0'))return false;*s=QString::fromUtf8(b);return s->toUtf8()==b;}
static bool decode(const QByteArray &b,QString *s,int limit){QByteArray raw=QByteArray::fromBase64(b);return raw.toBase64()==b&&utf8(raw,s,limit);}
static QByteArray encode(const QString &s){return s.toUtf8().toBase64();}
static bool parseWords(const QByteArray &data,QList<WordCard> *out){if(data.isEmpty())return true;QList<QByteArray> lines=data.split('\n');if(lines.size()<2||lines.takeFirst()!="PANDANOTE-WORDS-1"||!lines.takeLast().isEmpty()||lines.size()>1000)return false;for(int i=0;i<lines.size();++i){QList<QByteArray> cols=lines[i].split('\t');WordCard w;if(cols.size()!=3||!decode(cols[0],&w.front,256)||w.front.isEmpty()||!decode(cols[1],&w.back,1024)||w.back.isEmpty()||(cols[2]!="0"&&cols[2]!="1"))return false;w.known=cols[2]=="1";*out<<w;}return true;}
static bool parseNotes(const QByteArray &data,QList<ReadingNote> *out){if(data.isEmpty())return true;QList<QByteArray> lines=data.split('\n');if(lines.size()<2||lines.takeFirst()!="PANDANOTE-NOTES-1"||!lines.takeLast().isEmpty()||lines.size()>100)return false;QStringList ids;for(int i=0;i<lines.size();++i){QList<QByteArray> cols=lines[i].split('\t');ReadingNote n;if(cols.size()!=2||!QRegExp("[1-9][0-9]{0,8}").exactMatch(QString::fromLatin1(cols[0]))||!decode(cols[1],&n.body,16384))return false;n.id=QString::fromLatin1(cols[0]);if(ids.contains(n.id))return false;ids<<n.id;*out<<n;}return true;}
static const int DRAFT_CAP=21864; // Header, bounded canonical base64 and two newlines.
static bool parseDraft(const QByteArray &data,QString *out){if(data.isEmpty()){out->clear();return true;}QList<QByteArray> lines=data.split('\n');return lines.size()==3&&lines[0]=="PANDANOTE-DRAFT-1"&&lines[2].isEmpty()&&decode(lines[1],out,16384);}
LocalApps::LocalApps():rootFd_(-1),wordsFd_(-1),notesFd_(-1){}
LocalApps::~LocalApps(){if(wordsFd_>=0)::close(wordsFd_);if(notesFd_>=0)::close(notesFd_);if(rootFd_>=0)::close(rootFd_);}
bool LocalApps::fail(const char *code){error_=QString::fromLatin1(code);return false;}
bool LocalApps::open(const QString &root){
 if(!root.startsWith('/')||root.contains("//")||root.endsWith('/')||root.split('/').contains("..")||root.split('/').contains("."))return fail("workspace-path");
 // Walk every component, refusing symlinked ancestors as well as the final path.
 QStringList parts=root.mid(1).split('/');QByteArray first=("/"+parts[0]).toUtf8();int r=::open(first.constData(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);for(int i=1;r>=0&&i<parts.size();++i){int next=::openat(r,parts[i].toUtf8().constData(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);::close(r);r=next;}
 if(!privateDir(r)){if(r>=0)::close(r);return fail("workspace-private-directory");}
 int w=child(r,"words"),n=child(r,"notes");QByteArray wd,nd,dd;QList<WordCard> words;QList<ReadingNote> notes;QString draft;
 int d=n>=0?child(n,"draft"):-1;
 bool ok=w>=0&&n>=0&&d>=0&&!::fsync(r)&&!::fsync(n)&&readData(w,&wd)&&readData(n,&nd)&&readData(d,&dd,DRAFT_CAP)&&parseWords(wd,&words)&&parseNotes(nd,&notes)&&parseDraft(dd,&draft);
 if(d>=0)::close(d);
 if(!ok){if(w>=0)::close(w);if(n>=0)::close(n);::close(r);return fail("workspace-invalid-data");}
 if(wordsFd_>=0)::close(wordsFd_);if(notesFd_>=0)::close(notesFd_);if(rootFd_>=0)::close(rootFd_);rootFd_=r;wordsFd_=w;notesFd_=n;root_=root;words_=words;notes_=notes;draft_=draft;error_.clear();return true;
}
bool LocalApps::writeData(int fd,const QByteArray &data){
 if(fd<0)return fail("workspace-unconfigured");if(data.size()>CAP||!privateDir(fd))return fail("workspace-limit-or-permissions");
 struct stat st;if(!oldFstatat(fd,"data",&st,AT_SYMLINK_NOFOLLOW)){if(!S_ISREG(st.st_mode)||st.st_uid!=::geteuid()||(st.st_mode&07777)!=0600||st.st_nlink!=1)return fail("workspace-unsafe-file");}else if(errno!=ENOENT)return fail("workspace-inspect");
 QByteArray tmp=QByteArray(".pending-")+QByteArray::number(::getpid());int out=::openat(fd,tmp.constData(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);if(out<0)return fail("workspace-create");if(::fchmod(out,0600)){::close(out);::unlinkat(fd,tmp.constData(),0);return fail("workspace-permissions");}
 int off=0;bool ok=true;while(off<data.size()){ssize_t n=::write(out,data.constData()+off,data.size()-off);if(n<0&&errno==EINTR)continue;if(n<=0){ok=false;break;}off+=int(n);}if(ok&&::fsync(out))ok=false;if(::close(out))ok=false;
 if(!ok){::unlinkat(fd,tmp.constData(),0);return fail("workspace-write");}
 if(::renameat(fd,tmp.constData(),fd,"data")){::unlinkat(fd,tmp.constData(),0);return fail("workspace-rename");}
 // A directory fsync error means rename happened but durability is uncertain.
 if(::fsync(fd))return fail("workspace-durability-uncertain");error_.clear();return true;
}
bool LocalApps::saveWords(const QList<WordCard> &words){QByteArray b="PANDANOTE-WORDS-1\n";for(int i=0;i<words.size();++i)b+=encode(words[i].front)+'\t'+encode(words[i].back)+'\t'+(words[i].known?'1':'0')+'\n';if(!writeData(wordsFd_,b))return false;words_=words;return true;}
bool LocalApps::importWords(const QByteArray &tsv){if(!available())return fail("workspace-unconfigured");if(tsv.size()>CAP)return fail("words-limit");QList<QByteArray> lines=tsv.split('\n');if(!lines.isEmpty()&&lines.last().isEmpty())lines.removeLast();if(lines.isEmpty()||lines.size()>1000)return fail("words-limit");QList<WordCard> words;for(int i=0;i<lines.size();++i){QByteArray line=lines[i];if(line.endsWith('\r'))line.chop(1);QList<QByteArray> cols=line.split('\t');WordCard w;if(cols.size()!=2||!utf8(cols[0],&w.front,256)||w.front.trimmed().isEmpty()||!utf8(cols[1],&w.back,1024)||w.back.trimmed().isEmpty())return fail("words-tsv-invalid");w.known=false;words<<w;}return saveWords(words);}
bool LocalApps::markWord(int index,bool known){if(index<0||index>=words_.size())return fail("word-index");QList<WordCard> words=words_;words[index].known=known;return saveWords(words);}
bool LocalApps::saveNotes(const QList<ReadingNote> &notes){QByteArray b="PANDANOTE-NOTES-1\n";for(int i=0;i<notes.size();++i)b+=notes[i].id.toLatin1()+'\t'+encode(notes[i].body)+'\n';if(!writeData(notesFd_,b))return false;notes_=notes;return true;}
bool LocalApps::saveNote(const QString &id,const QString &body,QString *created){if(!available())return fail("workspace-unconfigured");if(body.toUtf8().size()>16384||QString::fromUtf8(body.toUtf8())!=body||body.contains(QChar(0)))return fail("note-limit");QList<ReadingNote> notes=notes_;int index=-1,maxId=0;for(int i=0;i<notes.size();++i){maxId=qMax(maxId,notes[i].id.toInt());if(notes[i].id==id)index=i;}if(id.isEmpty()){if(notes.size()>=100||maxId>=999999999)return fail("notes-limit");ReadingNote note;note.id=QString::number(maxId+1);notes<<note;index=notes.size()-1;}else if(index<0)return fail("note-id");notes[index].body=body;if(!saveNotes(notes))return false;if(created)*created=notes[index].id;return true;}
bool LocalApps::deleteNote(const QString &id){QList<ReadingNote> notes=notes_;for(int i=0;i<notes.size();++i)if(notes[i].id==id){notes.removeAt(i);return saveNotes(notes);}return fail("note-id");}
bool LocalApps::saveDraft(const QString &body){
 if(!available())return fail("workspace-unconfigured");
 if(body.toUtf8().size()>16384||QString::fromUtf8(body.toUtf8())!=body||body.contains(QChar(0)))return fail("draft-limit");
 if(!privateDir(notesFd_))return fail("draft-private-directory");
 int d=::openat(notesFd_,"draft",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
 if(!privateDir(d)){if(d>=0)::close(d);return fail("draft-private-directory");}
 // Revalidate even after a successful open: damaged draft bytes are evidence,
 // never silently replaced by a later save or clear request.
 QByteArray old;QString prior;
 if(!readData(d,&old,DRAFT_CAP)||!parseDraft(old,&prior)){::close(d);return fail("draft-invalid-data");}
 bool ok=writeData(d,QByteArray("PANDANOTE-DRAFT-1\n")+encode(body)+'\n');::close(d);
 if(ok)draft_=body;return ok;
}
