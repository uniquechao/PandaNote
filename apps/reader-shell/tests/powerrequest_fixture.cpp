#include "../powerrequest.h"
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <string>
#if defined(__linux__)
#include <sys/syscall.h>
#endif
static int failures=0,checks=0,writeCalls=0,syncCalls=0;
static bool failWrite=false,failFileSync=false,failDirSync=false,failClose=false,failRename=false,raceFinal=false,observedPartial=false;
static std::string directory;
#define CHECK(n,x) do{++checks;if(!(x)){++failures;fprintf(stderr,"FAIL %s line %d\n",n,__LINE__);}}while(0)
static std::string readFile(const std::string &path){int fd=::open(path.c_str(),O_RDONLY);if(fd<0)return "ABSENT";char b[128];ssize_t n=::read(fd,b,sizeof(b));::close(fd);return n<0?"ERROR":std::string(b,size_t(n));}
static void put(const std::string &path,const char *value){int fd=::open(path.c_str(),O_WRONLY|O_CREAT|O_TRUNC,0600);if(fd>=0){::write(fd,value,strlen(value));::close(fd);}}
static void observe(){std::string got=readFile(directory+"/poweroff.request");if(got!="ABSENT"&&got!="poweroff-v1\n")observedPartial=true;}
extern "C" ssize_t powerRequestTestWrite(int fd,const void *data,size_t count){observe();++writeCalls;if(failWrite){if(writeCalls==1)return ::write(fd,data,1);errno=EIO;return -1;}return ::write(fd,data,count);}
extern "C" int powerRequestTestFsync(int fd){observe();++syncCalls;if((syncCalls==1&&failFileSync)||(syncCalls==2&&failDirSync)){errno=EIO;return -1;}return ::fsync(fd);}
extern "C" int powerRequestTestClose(int fd){int result=::close(fd);if(failClose){failClose=false;errno=EIO;return -1;}return result;}
extern "C" int powerRequestTestRename(int olddir,const char *oldname,int newdir,const char *newname){
 observe();if(failRename){errno=EIO;return -1;}
 if(raceFinal)put(directory+"/poweroff.request","other request\n");
#if defined(__APPLE__)
 int result=::renameatx_np(olddir,oldname,newdir,newname,RENAME_EXCL);
#else
 int result=int(::syscall(SYS_renameat2,olddir,oldname,newdir,newname,1));
#endif
 if(!raceFinal)observe();return result;
}
static std::string temporary(){char b[64];snprintf(b,sizeof(b),"/.poweroff.request-%ld.pending",long(::getpid()));return directory+b;}
static void reset(){::unlink((directory+"/poweroff.request").c_str());::unlink(temporary().c_str());writeCalls=syncCalls=0;failWrite=failFileSync=failDirSync=failClose=failRename=raceFinal=observedPartial=false;}
int main(int argc,char **argv){
 if(argc!=2)return 2;directory=argv[1];
 reset();CHECK("publish_complete_request",publishPowerOffRequest(directory.c_str()));CHECK("content_and_no_partial_visibility",readFile(directory+"/poweroff.request")=="poweroff-v1\n"&&!observedPartial);CHECK("temporary_removed",readFile(temporary())=="ABSENT");CHECK("file_and_directory_fsync",syncCalls==2);
 struct stat st;CHECK("published_file_private",::stat((directory+"/poweroff.request").c_str(),&st)==0&&(st.st_mode&07777)==0600&&st.st_nlink==1);
 CHECK("existing_final_never_overwritten",!publishPowerOffRequest(directory.c_str())&&readFile(directory+"/poweroff.request")=="poweroff-v1\n");
 reset();put(temporary(),"owned by other attempt");CHECK("temporary_collision_refused",!publishPowerOffRequest(directory.c_str()));CHECK("temporary_collision_not_removed",readFile(temporary())=="owned by other attempt");CHECK("collision_does_not_publish",readFile(directory+"/poweroff.request")=="ABSENT");
 reset();failWrite=true;CHECK("partial_write_failure_never_published",!publishPowerOffRequest(directory.c_str())&&readFile(directory+"/poweroff.request")=="ABSENT"&&!observedPartial);CHECK("write_failure_cleans_only_own_temporary",readFile(temporary())=="ABSENT");
 reset();failFileSync=true;CHECK("file_fsync_failure_never_published",!publishPowerOffRequest(directory.c_str())&&readFile(directory+"/poweroff.request")=="ABSENT");CHECK("file_sync_failure_cleanup",readFile(temporary())=="ABSENT");
 reset();failClose=true;CHECK("close_failure_never_published",!publishPowerOffRequest(directory.c_str())&&readFile(directory+"/poweroff.request")=="ABSENT");
 reset();failRename=true;CHECK("rename_failure_never_published",!publishPowerOffRequest(directory.c_str())&&readFile(directory+"/poweroff.request")=="ABSENT");CHECK("rename_failure_cleanup",readFile(temporary())=="ABSENT");
 reset();failDirSync=true;CHECK("directory_fsync_failure_still_reports_published",publishPowerOffRequest(directory.c_str())&&readFile(directory+"/poweroff.request")=="poweroff-v1\n");CHECK("directory_sync_failure_does_not_unpublish",readFile(temporary())=="ABSENT");
 reset();raceFinal=true;CHECK("concurrent_final_creation_is_not_overwritten",!publishPowerOffRequest(directory.c_str())&&readFile(directory+"/poweroff.request")=="other request\n");CHECK("race_cleans_own_temporary",readFile(temporary())=="ABSENT");
 reset();::chmod(directory.c_str(),0755);CHECK("public_parent_refused",!publishPowerOffRequest(directory.c_str())&&readFile(directory+"/poweroff.request")=="ABSENT");::chmod(directory.c_str(),0700);
 const std::string link=directory+"-link";::symlink(directory.c_str(),link.c_str());CHECK("symlink_parent_refused",!publishPowerOffRequest(link.c_str()));::unlink(link.c_str());
 CHECK("relative_parent_refused",!publishPowerOffRequest("relative"));CHECK("root_parent_refused",!publishPowerOffRequest("/"));CHECK("dotdot_parent_refused",!publishPowerOffRequest((directory+"/../elsewhere").c_str()));CHECK("null_parent_refused",!publishPowerOffRequest(0));
 reset();const std::string target=directory+"/target";put(target,"unchanged");::symlink("target",(directory+"/poweroff.request").c_str());CHECK("final_symlink_refused",!publishPowerOffRequest(directory.c_str())&&readFile(target)=="unchanged");::unlink(target.c_str());reset();
 printf("%s POWER_REQUEST %d checks real_fs=true hardware_access=false\n",failures?"FAIL":"PASS",checks);return failures?1:0;
}
