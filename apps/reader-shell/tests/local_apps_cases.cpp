#include "../localapps.h"
#include <QtCore/qcoreapplication.h>
#include <QtCore/qfile.h>
#include <QtCore/qdir.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>
#include <signal.h>
#include <sys/resource.h>
static int bad=0,checks=0;
#define CHECK(n,c) do{++checks;if(!(c)){fprintf(stderr,"FAIL %s line %d\n",n,__LINE__);++bad;}}while(0)
static void put(const QString &p,const QByteArray &b){QFile f(p);f.open(QIODevice::WriteOnly);f.write(b);f.close();::chmod(p.toUtf8().constData(),0600);}
int main(int argc,char **argv){QCoreApplication app(argc,argv);QString root="/tmp/local-apps-core";::mkdir(root.toUtf8().constData(),0700);LocalApps s;CHECK("disabled_default",!s.available());CHECK("relative_rejected",!s.open("relative"));CHECK("open_explicit_private_root",s.open(root));CHECK("empty_not_fake",s.words().isEmpty()&&s.notes().isEmpty());
 CHECK("import_unicode",s.importWords(QString::fromUtf8("你好\thello\nbook\t书\n").toUtf8()));CHECK("word_count",s.words().size()==2);CHECK("word_mark",s.markWord(0,true));LocalApps again;CHECK("restart",again.open(root)&&again.words().size()==2&&again.words()[0].known);
 CHECK("malformed_import_keeps_good",!s.importWords("missing tab\n")&&s.words().size()==2&&s.words()[0].known);CHECK("bad_utf8",!s.importWords(QByteArray("bad\t")+char(0xff)+"\n"));CHECK("word_limits",!s.importWords(QByteArray(257,'a')+"\tb\n"));
 QString id;CHECK("create_note",s.saveNote(QString(),QString::fromUtf8("中文\nhello"),&id));CHECK("note_id",!id.isEmpty());CHECK("restart_notes",again.open(root)&&again.notes().size()==1&&again.notes()[0].body==QString::fromUtf8("中文\nhello"));CHECK("edit_note",s.saveNote(id,"edited",0));CHECK("oversize_keeps_last",!s.saveNote(id,QString(16385,'x'),0)&&s.notes()[0].body=="edited");CHECK("missing_id_rejected",!s.saveNote("999","x",0));CHECK("export_utf8",s.notes()[0].body.toUtf8()=="edited");
 QByteArray prior;{QFile f(root+"/notes/data");f.open(QIODevice::ReadOnly);prior=f.readAll();}put(root+"/notes/data","broken");CHECK("malformed_reopen_keeps_loaded",!s.open(root)&&s.notes().size()==1&&s.notes()[0].body=="edited");put(root+"/notes/data",prior);CHECK("reopen_good",s.open(root));
 ::rename((root+"/notes/data").toUtf8().constData(),(root+"/notes/saved").toUtf8().constData());::symlink("saved",(root+"/notes/data").toUtf8().constData());CHECK("symlink_save_refused",!s.saveNote(id,"lost",0)&&s.notes()[0].body=="edited");::unlink((root+"/notes/data").toUtf8().constData());::rename((root+"/notes/saved").toUtf8().constData(),(root+"/notes/data").toUtf8().constData());CHECK("delete_note",s.deleteNote(id)&&s.notes().isEmpty());CHECK("delete_persisted",again.open(root)&&again.notes().isEmpty());
 ::chmod((root+"/words").toUtf8().constData(),0500);CHECK("write_failure_retains_progress",!s.markWord(0,false)&&s.words()[0].known);::chmod((root+"/words").toUtf8().constData(),0700);
 QByteArray saved;{QFile f(root+"/words/data");f.open(QIODevice::ReadOnly);saved=f.readAll();}put(root+"/words/.pending-"+QString::number(::getpid()),"partial");CHECK("stale_partial_refuses_overwrite",!s.markWord(0,false)&&s.words()[0].known);QFile::remove(root+"/words/.pending-"+QString::number(::getpid()));
 struct rlimit original,limited;::getrlimit(RLIMIT_FSIZE,&original);limited=original;limited.rlim_cur=4;::signal(SIGXFSZ,SIG_IGN);::setrlimit(RLIMIT_FSIZE,&limited);CHECK("partial_write_failure",!s.markWord(0,false));::setrlimit(RLIMIT_FSIZE,&original);{QFile f(root+"/words/data");f.open(QIODevice::ReadOnly);CHECK("partial_write_preserves_prior",f.readAll()==saved);}CHECK("partial_write_preserves_memory",s.words()[0].known);CHECK("future_write_after_failure",s.markWord(0,false));
 QByteArray goodNotes;{QFile f(root+"/notes/data");f.open(QIODevice::ReadOnly);goodNotes=f.readAll();}put(root+"/notes/data","PANDANOTE-NOTES-1");CHECK("truncated_header_rejected",!s.open(root));put(root+"/notes/data",goodNotes);
 QString link="/tmp/local-apps-link";::symlink(root.toUtf8().constData(),link.toUtf8().constData());LocalApps x;CHECK("root_symlink_rejected",!x.open(link));::chmod(root.toUtf8().constData(),0755);CHECK("public_root_rejected",!x.open(root));::chmod(root.toUtf8().constData(),0700);
 QString draftPath=root+"/notes/draft/data";QString draftText=QString::fromUtf8("待恢复的草稿\nhello 😀");
 CHECK("draft_starts_empty",s.draft().isEmpty());
 CHECK("draft_unicode_save",s.saveDraft(draftText)&&s.draft()==draftText);
 {QFile f(root+"/notes/data");f.open(QIODevice::ReadOnly);CHECK("draft_never_modifies_legacy_notes_file",f.readAll()==goodNotes);}
 {LocalApps restored;CHECK("draft_restart_restores_without_committing_note",restored.open(root)&&restored.draft()==draftText&&restored.notes().isEmpty());}
 CHECK("draft_clear_atomic",s.saveDraft(QString())&&s.draft().isEmpty());
 {LocalApps restored;CHECK("draft_clear_survives_restart",restored.open(root)&&restored.draft().isEmpty());}
 CHECK("draft_restore_for_safety_checks",s.saveDraft(draftText));
 CHECK("draft_exact_utf8_capacity",s.saveDraft(QString(16384,'x')));
 {LocalApps restored;CHECK("draft_capacity_restores",restored.open(root)&&restored.draft()==QString(16384,'x'));}
 CHECK("draft_restore_after_capacity",s.saveDraft(draftText));
 QByteArray draftGood;{QFile f(draftPath);f.open(QIODevice::ReadOnly);draftGood=f.readAll();}
 CHECK("draft_bound_rejected",!s.saveDraft(QString(16385,'x'))&&s.draft()==draftText);
 QString invalidDraft;invalidDraft+=QChar(0xd800);CHECK("draft_invalid_unicode_rejected",!s.saveDraft(invalidDraft)&&s.draft()==draftText);
 CHECK("draft_nul_rejected",!s.saveDraft(QString("prefix")+QChar(0)+"suffix")&&s.draft()==draftText);
 put(draftPath,"broken");{LocalApps restored;CHECK("draft_corruption_refuses_open",!restored.open(root));}
 CHECK("draft_corruption_cannot_be_silently_overwritten",!s.saveDraft("lost")&&s.draft()==draftText);
 {QFile f(draftPath);f.open(QIODevice::ReadOnly);CHECK("draft_corruption_kept_on_disk",f.readAll()=="broken");}put(draftPath,draftGood);
 const QByteArray badDrafts[]={"PANDANOTE-DRAFT-1\n/wo=\n","PANDANOTE-DRAFT-1\nYQ\n","PANDANOTE-DRAFT-1\nYQ==\nextra\n","PANDANOTE-DRAFT-1\nAA==\n",QByteArray()};
 for(unsigned i=0;i<sizeof(badDrafts)/sizeof(badDrafts[0]);++i){put(draftPath,badDrafts[i]);LocalApps restored;CHECK("draft_bad_encoding_or_framing_refused",!restored.open(root));CHECK("draft_bad_encoding_refuses_clear",!s.saveDraft(QString()));}put(draftPath,draftGood);
 ::chmod(draftPath.toUtf8().constData(),0644);{LocalApps restored;CHECK("draft_public_file_refused",!restored.open(root));}CHECK("draft_public_file_save_refused",!s.saveDraft("lost"));::chmod(draftPath.toUtf8().constData(),0600);
 ::chmod((root+"/notes/draft").toUtf8().constData(),0755);{LocalApps restored;CHECK("draft_public_directory_refused",!restored.open(root));}CHECK("draft_public_directory_save_refused",!s.saveDraft("lost"));::chmod((root+"/notes/draft").toUtf8().constData(),0700);
 ::rename(draftPath.toUtf8().constData(),(draftPath+".saved").toUtf8().constData());::symlink("data.saved",draftPath.toUtf8().constData());{LocalApps restored;CHECK("draft_symlink_file_refused",!restored.open(root));}CHECK("draft_symlink_save_refused",!s.saveDraft("lost"));::unlink(draftPath.toUtf8().constData());::rename((draftPath+".saved").toUtf8().constData(),draftPath.toUtf8().constData());
 CHECK("draft_hardlink_fixture",::link(draftPath.toUtf8().constData(),(draftPath+".linked").toUtf8().constData())==0);{LocalApps restored;CHECK("draft_hardlink_refused",!restored.open(root));}CHECK("draft_hardlink_save_refused",!s.saveDraft("lost"));::unlink((draftPath+".linked").toUtf8().constData());
 ::rename((root+"/notes/draft").toUtf8().constData(),(root+"/notes/draft.saved").toUtf8().constData());::symlink("draft.saved",(root+"/notes/draft").toUtf8().constData());{LocalApps restored;CHECK("draft_symlink_directory_refused",!restored.open(root));}CHECK("draft_symlink_directory_save_refused",!s.saveDraft("lost"));::unlink((root+"/notes/draft").toUtf8().constData());::rename((root+"/notes/draft.saved").toUtf8().constData(),(root+"/notes/draft").toUtf8().constData());
 CHECK("draft_reopen_after_repair",s.open(root)&&s.draft()==draftText);
 put(root+"/notes/draft/.pending-"+QString::number(::getpid()),"partial");CHECK("draft_stale_partial_preserves_original",!s.saveDraft("lost")&&s.draft()==draftText);QFile::remove(root+"/notes/draft/.pending-"+QString::number(::getpid()));
 ::getrlimit(RLIMIT_FSIZE,&original);limited=original;limited.rlim_cur=4;::setrlimit(RLIMIT_FSIZE,&limited);CHECK("draft_partial_write_rejected",!s.saveDraft("lost"));::setrlimit(RLIMIT_FSIZE,&original);{QFile f(draftPath);f.open(QIODevice::ReadOnly);CHECK("draft_partial_write_preserves_original",f.readAll()==draftGood);}CHECK("draft_still_recoverable",again.open(root)&&again.draft()==draftText&&again.notes().isEmpty());
 printf("%s LOCAL_APPS %d checks real_fs=true hardware_access=false\n",bad?"FAIL":"PASS",checks);return bad?1:0;}
