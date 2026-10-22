#ifndef PANDANOTE_LOCALAPPS_H
#define PANDANOTE_LOCALAPPS_H
#include <QtCore/qstring.h>
#include <QtCore/qbytearray.h>
#include <QtCore/qlist.h>
struct WordCard { QString front,back;bool known; };
struct ReadingNote { QString id,body; };
class LocalApps {
public:
 LocalApps();~LocalApps();
 bool open(const QString &root);
 bool available()const{return rootFd_>=0;}
 QString directory()const{return root_;} QString error()const{return error_;}
 const QList<WordCard> &words()const{return words_;}
 const QList<ReadingNote> &notes()const{return notes_;}
 bool importWords(const QByteArray &tsv);
 bool markWord(int index,bool known);
 bool saveNote(const QString &id,const QString &body,QString *createdId);
 bool deleteNote(const QString &id);
 bool saveDraft(const QString &body);
 QString draft()const{return draft_;}
private:
 LocalApps(const LocalApps &);LocalApps &operator=(const LocalApps &);
 int rootFd_,wordsFd_,notesFd_;QString root_,error_,draft_;QList<WordCard> words_;QList<ReadingNote> notes_;
 bool fail(const char *code);bool writeData(int fd,const QByteArray &data);
 bool saveWords(const QList<WordCard> &words);bool saveNotes(const QList<ReadingNote> &notes);
};
#endif
