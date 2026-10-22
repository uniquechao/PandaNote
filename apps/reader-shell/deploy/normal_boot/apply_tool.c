/* Own ordinary-file installer. No exec/system/raw block write/format interface. */
#define _GNU_SOURCE
#define _DARWIN_C_SOURCE
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/file.h>
#include <sys/mman.h>
#ifndef PANDANOTE_FIXTURE
#include <sys/mount.h>
#include <sys/sysmacros.h>
#endif
#include <fcntl.h>
#include <dirent.h>
#include <unistd.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include "sha256.h"
/* Inspected stock glibc2.29 MIPS stat converter: Linux ABI version3. */
#if defined(__mips__) && defined(__linux__)
extern int __lxstat(int,const char*,struct stat*);
extern int __fxstat(int,int,struct stat*);
extern int __fxstatat(int,int,const char*,struct stat*,int);
#define lstat(p,s) __lxstat(3,p,s)
#define fstat(f,s) __fxstat(3,f,s)
#define fstatat(f,p,s,a) __fxstatat(3,f,p,s,a)
#endif
#ifdef PANDANOTE_FIXTURE
static int fixture_sync_count;
static int fixture_fsync(int fd){const char*v=getenv("PANDANOTE_FSYNC_FAIL_AT");fixture_sync_count++;if(v&&atoi(v)==fixture_sync_count){errno=EIO;return -1;}return fsync(fd);}
#define fsync fixture_fsync
#endif
#define MAX_FILES 128
#define MAX_BUNDLE (24*1024*1024)
static int rootfd=-1, restored=0, root_rw=0, backup_done=0, pointer_done=0, entry_done=0, rollback_mode=0;
static const char *bundle_key;static size_t mapping_len;
static volatile sig_atomic_t cancelled;
static void cancel(int sig){(void)sig;cancelled=1;}
static char backup[160];
static unsigned char *oldentry,*oldcurrent;static size_t oldlen,currentlen;static int hadcurrent;
struct item {char path[512],sha[65],role[16];unsigned mode;size_t len;const unsigned char *data;};
static struct item items[MAX_FILES];static unsigned count;
static void hex(const void *p,size_t n,char out[65]){SHA256_CTX c;unsigned char h[32];unsigned i;sha256_init(&c);sha256_update(&c,p,n);sha256_final(&c,h);for(i=0;i<32;i++)sprintf(out+2*i,"%02x",h[i]);out[64]=0;}
static int ishex(const char*s,size_t n){size_t i;if(strlen(s)!=n)return 0;for(i=0;i<n;i++)if(!((s[i]>='0'&&s[i]<='9')||(s[i]>='a'&&s[i]<='f')))return 0;return 1;}
static int writeall(int fd,const void *v,size_t n){const unsigned char*p=v;while(n){ssize_t r=write(fd,p,n);if(r<0&&errno==EINTR&&!cancelled)continue;if(r<=0)return -1;p+=r;n-=r;}return 0;}
static int safechar(const char*s){const char*p;if(!s||s[0]!='/')return 0;for(p=s;*p;p++)if(!((*p>='a'&&*p<='z')||(*p>='A'&&*p<='Z')||(*p>='0'&&*p<='9')||strchr("/._-",*p)))return 0;return !strstr(s,"//")&&!strstr(s,"/../")&&!strstr(s,"/./")&&strcmp(s,"/")&&strcmp(s+strlen(s)-1,"/");}
static int owner(const struct stat*s){return s->st_uid==geteuid();}
/* Descriptor-relative, no symlink component; only own regular target files. */
static int parentfd(const char*path,int create,char name[256]){
 char copy[512],*p,*next;int fd,newfd;struct stat s;
 if(!safechar(path)||strlen(path)>=sizeof copy)return -1;
 strcpy(copy,path+1);fd=dup(rootfd);if(fd<0)return -1;p=copy;
 while((next=strchr(p,'/'))){*next=0;if(!strcmp(p,".")||!strcmp(p,".."))goto bad;
  newfd=openat(fd,p,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
  if(newfd<0&&errno==ENOENT&&create){if(mkdirat(fd,p,0700)||fsync(fd))goto bad;newfd=openat(fd,p,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);}
  if(newfd<0)goto bad;
  if(fstat(newfd,&s)||!owner(&s)||((s.st_mode&0022)&&!(p==copy&&!strcmp(p,"tmp")&&(s.st_mode&S_ISVTX)))){close(newfd);goto bad;}
  close(fd);fd=newfd;p=next+1;
 }
 if(strlen(p)>255||!strcmp(p,".")||!strcmp(p,".."))goto bad;strcpy(name,p);return fd;
 bad:close(fd);return -1;
}
static int regfd(const char*path,int optional){char name[256];struct stat s;int p=parentfd(path,0,name),fd;if(p<0)return -1;fd=openat(p,name,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);close(p);if(fd<0){if(optional&&errno==ENOENT)return -2;return -1;}if(fstat(fd,&s)||!S_ISREG(s.st_mode)||!owner(&s)||s.st_nlink!=1){close(fd);return -1;}return fd;}
static unsigned char *readreg(const char*path,size_t*len,int optional){int fd=regfd(path,optional);struct stat s;unsigned char*b;size_t at=0;if(fd==-2){*len=0;return NULL;}if(fd<0)return NULL;if(fstat(fd,&s)||s.st_size<0||s.st_size>65536){close(fd);return NULL;}b=malloc((size_t)s.st_size+1);if(!b){close(fd);return NULL;}while(at<(size_t)s.st_size){ssize_t n=read(fd,b+at,(size_t)s.st_size-at);if(n<0&&errno==EINTR)continue;if(n<=0){free(b);close(fd);return NULL;}at+=n;}b[at]=0;*len=at;close(fd);return b;}
static int atomicfile(const char*path,const void*data,size_t len,mode_t mode){char name[256],tmp[256];struct stat s;int p=parentfd(path,1,name),fd,renamed=0,ok=-1;if(p<0)return -1;
 if(fstatat(p,name,&s,AT_SYMLINK_NOFOLLOW)){if(errno!=ENOENT)goto out;}else if(!S_ISREG(s.st_mode)||!owner(&s)||s.st_nlink!=1)goto out;
 if(snprintf(tmp,sizeof tmp,".pandanote-new-%s",name)>=(int)sizeof tmp)goto out;
 fd=openat(p,tmp,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);if(fd<0)goto out;
 if(!writeall(fd,data,len)&&!fchmod(fd,mode)&&!fsync(fd)){if(!close(fd)){fd=-1;if(!renameat(p,tmp,p,name)){renamed=1;if(!fsync(p))ok=0;}}}
 if(fd>=0)close(fd);if(!renamed)unlinkat(p,tmp,0);
 out:close(p);return ok;
}
static int removefile(const char*path){char n[256];int p=parentfd(path,0,n),r;if(p<0)return -1;r=unlinkat(p,n,0);if(r<0&&errno!=ENOENT){close(p);return -1;}r=fsync(p);close(p);return r;}
static int phase(const char*s){char path[256];if(cancelled)return -1;printf("phase=%s\n",s);fflush(stdout);snprintf(path,sizeof path,"%s/journal",backup);
 if(backup_done&&atomicfile(path,s,strlen(s),0600))return -1;
#ifdef PANDANOTE_FIXTURE
 const char*f=getenv("PANDANOTE_FAIL_PHASE");if(f&&!strcmp(f,s)){errno=EIO;return -1;}
 const char*sigh=getenv("PANDANOTE_SIGNAL_PHASE");if(sigh&&!strcmp(sigh,s))raise(SIGTERM);
 const char*c=getenv("PANDANOTE_CRASH_PHASE");if(c&&!strcmp(c,s))_exit(99);
#endif
 return cancelled?-1:0;}
static int filehash(const char*path,char out[65]){unsigned char b[4096],h[32];SHA256_CTX c;ssize_t n;int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);unsigned i;if(fd<0)return -1;sha256_init(&c);while((n=read(fd,b,sizeof b))>0)sha256_update(&c,b,n);close(fd);if(n<0)return -1;sha256_final(&c,h);for(i=0;i<32;i++)sprintf(out+2*i,"%02x",h[i]);out[64]=0;return 0;}
/* Same predicate in target code and native stream tests; never accept an
 * unlisted ancestor/descendant mount that can shadow a listed install path. */
static int mount_option(const char*options,const char*value){char padded[1030],needle[80];if(snprintf(padded,sizeof padded,",%s,",options)>=(int)sizeof padded||snprintf(needle,sizeof needle,",%s,",value)>=(int)sizeof needle)return 0;return strstr(padded,needle)!=NULL;}
static int mount_table(FILE*f,int rw){
 static const char*targets[]={"/","/home","/user","/run/pandanote-opt","/tmp","/run","/proc","/sys","/dev","/dev/pts","/sys/kernel/config","/dev/usb-ffs/adb"};
 static const char*types[]={"ext4","ext4","ext4","ext4","tmpfs","tmpfs","proc","sysfs","devtmpfs","devpts","configfs","functionfs"};
 unsigned seen=0;char line[8192],src[160],dst[160],type[32],opts[1024],extra;int a,b;size_t index;
 if(!f||(rw!=0&&rw!=1))return -1;
 while(fgets(line,sizeof line,f)){
  if(!strchr(line,'\n')||sscanf(line,"%159s %159s %31s %1023s %d %d %c",src,dst,type,opts,&a,&b,&extra)!=6)return -1;
  for(index=0;index<12;index++)if(!strcmp(dst,targets[index]))break;
  if(index==12||(seen&(1u<<index))||strcmp(type,types[index]))return -1;
  seen|=1u<<index;
  if(index==0){printf("root-options=%s\n",opts);if((strcmp(src,"/dev/root")&&strcmp(src,"/dev/mmcblk0p2"))||!mount_option(opts,rw?"rw":"ro")||mount_option(opts,rw?"ro":"rw"))return -1;}
  else if(index==1||index==2){if(strcmp(src,index==1?"/dev/mmcblk0p3":"/dev/mmcblk0p9")||!mount_option(opts,"rw")||mount_option(opts,"ro")||mount_option(opts,"noexec")||mount_option(opts,"noload")||mount_option(opts,"norecovery")||!mount_option(opts,"nosuid")||!mount_option(opts,"nodev"))return -1;}
  else if(index==3){if(strcmp(src,"/dev/mmcblk0p5")||!mount_option(opts,"ro")||mount_option(opts,"rw")||(!mount_option(opts,"noload")&&!mount_option(opts,"norecovery")))return -1;}
  else if(index==4||index==5){if(!mount_option(opts,"rw")||mount_option(opts,"ro")||!mount_option(opts,"nosuid")||!mount_option(opts,"nodev")||(index==4&&mount_option(opts,"noexec")))return -1;}
  if(index>=4&&!strncmp(src,"/dev/mmcblk",11))return -1;
 }
 if(ferror(f)||!feof(f))return -1;
 return (seen&0x3fu)==0x3fu?0:-1;
}
static unsigned sb16(const unsigned char*b){return (unsigned)b[0]|((unsigned)b[1]<<8);}
static uint32_t sb32(const unsigned char*b){return (uint32_t)b[0]|((uint32_t)b[1]<<8)|((uint32_t)b[2]<<16)|((uint32_t)b[3]<<24);}
static int superblock_compatible(const unsigned char*sb,int clean){
 unsigned state=sb16(sb+58);uint32_t incompat=sb32(sb+96);
 if(sb16(sb+56)!=0xef53||sb32(sb+4)!=131072||sb32(sb+24)!=0||sb32(sb+92)!=0x3c||sb32(sb+100)!=0x46b||(incompat&~4u)!=0x242)return 0;
 if(clean)return state==1&&!(incompat&4u);
 return state==0||state==1;
}
/* Pure production identity boundary. Capture/recheck a fixed starttime, exact
 * supervisor argv/executable and PID1-owned session before any group signal. */
static int supervisor_fields(pid_t pid,int role,const char*stattext,const char*exe,const unsigned char*cmd,size_t cmdlen,unsigned long long expected,unsigned long long*start){
 static const unsigned char adb_cmd[]="/bin/busybox\0sh\0/tmp/pandanote-development/boot-child.sh\0/tmp/pandanote-development\0adbd\0/usr/bin/adbd\0";
 static const unsigned char runtime_cmd[]="/bin/busybox\0sh\0/tmp/pandanote-development/child-supervisor.sh\0/tmp/pandanote-development\0runtime\0/bin/busybox\0sh\0/tmp/pandanote-development/runtime.sh\0";
 const unsigned char*want=role==1?adb_cmd:runtime_cmd;size_t wantlen=role==1?sizeof adb_cmd-1:sizeof runtime_cmd-1;
 char copy[4096],*tail,*save,*token,*end;unsigned index=0;unsigned long long begun=0;long parent=0,pgid=0,sid=0;
 long reported;
 if(sscanf(stattext,"%ld",&reported)!=1||reported!=pid)return -1;
 if(pid<2||(role!=1&&role!=2)||strcmp(exe,"/bin/busybox")||cmdlen!=wantlen||memcmp(cmd,want,wantlen)||strlen(stattext)>=sizeof copy)return -1;
 strcpy(copy,stattext);tail=strrchr(copy,')');if(!tail)return -1;tail++;
 for(token=strtok_r(tail," \n",&save);token;token=strtok_r(NULL," \n",&save),index++){
  if(index==0){if(strlen(token)!=1||*token=='Z'||*token=='X')return -1;}
  else if(index>=1&&index<=3){errno=0;long value=strtol(token,&end,10);if(errno||*end||value<1)return -1;if(index==1)parent=value;else if(index==2)pgid=value;else sid=value;}
  else if(index==19){errno=0;begun=strtoull(token,&end,10);if(errno||*end||*token=='-'||!begun)return -1;break;}
 }
 if(index!=19||parent!=1||pgid!=pid||sid!=pid||(expected&&begun!=expected))return -1;
 *start=begun;return 0;
}
static int distinct_supervisors(pid_t adb,pid_t runtime){return adb>1&&runtime>1&&adb!=runtime;}
#ifdef PANDANOTE_NORMAL_UPGRADE
#include "upgrade_wire.h"
#endif
#if !defined(PANDANOTE_FIXTURE) && !defined(PANDANOTE_NORMAL_UPGRADE)
static int text(const char*path,char*b,size_t cap){int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);ssize_t n;if(fd<0)return -1;n=read(fd,b,cap-1);close(fd);if(n<0||(size_t)n==cap-1)return -1;b[n]=0;return 0;}
static int identity(void){char h[65],b[16384],p[160];struct stat st;unsigned n,major_n,minor_n;struct {unsigned n,start,size;} parts[]={{2,20480,262144},{3,282624,1048576},{5,2379776,1572864},{9,7131136,52019200}};
 if(geteuid()!=0||filehash("/tmp/pid1",h)||strcmp(h,"16ee0bac0ce0f10e9338847b87a6c4ac64d35c1c062c19f4cbcf28e46a61de6d")||filehash("/proc/cmdline",h)||strcmp(h,"99056ed5ca547a6badf698ae3195d48c031c795ae53918c03b0377fd6a01e73f"))return -1;
 int block=open("/dev/mmcblk0",O_RDONLY|O_NOFOLLOW|O_CLOEXEC);unsigned char gpt[34*512];if(block<0)return -1;ssize_t got=pread(block,gpt,sizeof gpt,0);close(block);if(got!=sizeof gpt)return -1;hex(gpt,sizeof gpt,h);if(strcmp(h,"fd502b7cdf436ac11f291b8c34d3a4e5a3f483b8b6ed95b8b1fff77a5790ffd2"))return -1;
 for(n=0;n<4;n++){char want[48];
  snprintf(p,sizeof p,"/sys/class/block/mmcblk0p%u/start",parts[n].n);snprintf(want,sizeof want,"%u\n",parts[n].start);if(text(p,b,sizeof b)||strcmp(b,want))return -1;
  snprintf(p,sizeof p,"/sys/class/block/mmcblk0p%u/size",parts[n].n);snprintf(want,sizeof want,"%u\n",parts[n].size);if(text(p,b,sizeof b)||strcmp(b,want))return -1;
  snprintf(p,sizeof p,"/sys/class/block/mmcblk0p%u/dev",parts[n].n);if(text(p,b,sizeof b)||sscanf(b,"%u:%u",&major_n,&minor_n)!=2)return -1;
  snprintf(p,sizeof p,"/dev/mmcblk0p%u",parts[n].n);if(lstat(p,&st)||!S_ISBLK(st.st_mode)||major(st.st_rdev)!=major_n||minor(st.st_rdev)!=minor_n)return -1;
 }
 return 0;
}
static int mountcontext(int rw){FILE*f=fopen("/proc/mounts","r");int result;if(!f)return -1;result=mount_table(f,rw);if(fclose(f))result=-1;return result;}
static int capture_supervisor(pid_t pid,int role,unsigned long long expected,unsigned long long*start){char path[128],statbuf[4096],exe[256];unsigned char cmd[1024];ssize_t n;int fd;
 snprintf(path,sizeof path,"/proc/%ld/stat",(long)pid);if(text(path,statbuf,sizeof statbuf))return -1;
 snprintf(path,sizeof path,"/proc/%ld/exe",(long)pid);n=readlink(path,exe,sizeof exe-1);if(n<0||(size_t)n>=sizeof exe-1)return -1;exe[n]=0;
 snprintf(path,sizeof path,"/proc/%ld/cmdline",(long)pid);fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return -1;n=read(fd,cmd,sizeof cmd);close(fd);if(n<0||(size_t)n>=sizeof cmd)return -1;
 if(supervisor_fields(pid,role,statbuf,exe,cmd,(size_t)n,expected,start)||kill(pid,0))return -1;return 0;
}
static pid_t pidfile(const char*path){size_t n;struct stat st;int fd=regfd(path,0);char*end;long pid;unsigned char*b;if(fd<0)return -1;if(fstat(fd,&st)||(st.st_mode&0777)!=0600){close(fd);return -1;}close(fd);b=readreg(path,&n,0);if(!b)return -1;if(n<2||n>9||b[n-1]!='\n'){free(b);return -1;}for(size_t i=0;i<n-1;i++)if(b[i]<'0'||b[i]>'9'){free(b);return -1;}errno=0;pid=strtol((char*)b,&end,10);if(errno||end!=(char*)b+n-1||pid<2||pid>4194304)pid=-1;free(b);return (pid_t)pid;}
static int guard_halted(void){struct stat st;size_t n;unsigned char*b;int fd=regfd("/tmp/development-bootstrap-error",0);if(fd<0)return 0;if(fstat(fd,&st)||(st.st_mode&0777)!=0600){close(fd);return 0;}close(fd);b=readreg("/tmp/development-bootstrap-error",&n,0);if(!b)return 0;int okay=n==30&&!memcmp(b,"development-bootstrap-stopped\n",30);free(b);if(!okay)return 0;if(lstat("/tmp/pandanote-development/runtime.pid",&st)==0||errno!=ENOENT)return 0;return 1;}
static int qt_stopped(void){DIR*d=opendir("/proc");struct dirent*e;char path[128],line[2048];if(!d)return -1;while((e=readdir(d))){const char*p=e->d_name;if(!*p)continue;while(*p>='0'&&*p<='9')p++;if(*p)continue;snprintf(path,sizeof path,"/proc/%s/maps",e->d_name);FILE*f=fopen(path,"r");if(!f){if(errno==ENOENT||errno==ESRCH)continue;closedir(d);return -1;}while(fgets(line,sizeof line,f))if(strstr(line,"libQtGui")){fclose(f);closedir(d);fprintf(stderr,"refuse=active-qt-process\n");return -1;}if(ferror(f)){fclose(f);closedir(d);return -1;}fclose(f);}closedir(d);return 0;}
static int rescue_handoff(void){pid_t adb=pidfile("/tmp/pandanote-development/adbd.pid"),runtime;unsigned long long adb_start=0,runtime_start=0,checked;char hash[65];unsigned i;
 if(adb<2||capture_supervisor(adb,1,0,&adb_start)||filehash("/bin/busybox",hash)||strcmp(hash,"38081195a5342faafac704f96bec8fb5b4de7a706f74dab88e5c184374f9a593"))return -1;
 if(filehash("/tmp/pandanote-development/boot-child.sh",hash)||strcmp(hash,"41686b1f134df913014fe56acd8edc7921fce8c737dedc6b7336f7a25a620e84"))return -1;
 if(guard_halted())return capture_supervisor(adb,1,adb_start,&checked);
 runtime=pidfile("/tmp/pandanote-development/runtime.pid");if(!distinct_supervisors(adb,runtime)||capture_supervisor(runtime,2,0,&runtime_start))return -1;
 if(filehash("/tmp/pandanote-development/child-supervisor.sh",hash)||strcmp(hash,"41686b1f134df913014fe56acd8edc7921fce8c737dedc6b7336f7a25a620e84"))return -1;
 if(capture_supervisor(adb,1,adb_start,&checked)||capture_supervisor(runtime,2,runtime_start,&checked)||kill(-runtime,SIGTERM))return -1;
 for(i=0;i<100;i++){usleep(100000);if(capture_supervisor(adb,1,adb_start,&checked))return -1;if(guard_halted())return 0;}return -1;}
static int rollback_superblock(int clean){unsigned char sb[1024];int fd=open("/dev/mmcblk0p2",O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return -1;ssize_t n=pread(fd,sb,sizeof sb,1024);close(fd);return n==sizeof sb&&superblock_compatible(sb,clean)?0:-1;}
static int remountroot(int rw){if(rw){unsigned char sb[1024];char h[65];int fd=open("/dev/mmcblk0p2",O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return -1;ssize_t n=pread(fd,sb,sizeof sb,1024);close(fd);if(n!=sizeof sb)return -1;hex(sb,sizeof sb,h);if(!rollback_mode){if(strcmp(h,"acd494b26f7b2c51105670d9cbf2b00b89f38a7da82eeeb758c47b4b6db4ed4e"))return -1;}else if(!superblock_compatible(sb,1))return -1;}if(mount("/dev/mmcblk0p2","/","ext4",MS_REMOUNT|(rw?0:MS_RDONLY),NULL))return -1;root_rw=rw;return mountcontext(rw);}
#elif defined(PANDANOTE_NORMAL_UPGRADE) && !defined(PANDANOTE_FIXTURE)
#include "upgrade_target.h"
#else
static int rollback_superblock(int clean){(void)clean;return 0;}static int qt_stopped(void){return 0;}static int identity(void){return 0;}static int mountcontext(int rw){(void)rw;return 0;}static int rescue_handoff(void){return 0;}static int remountroot(int rw){root_rw=rw;return 0;}
#endif
static int parse(unsigned char*b,size_t len,const char*expected,char oldsha[65]){char line[1024],magic[32],boot[25],native[65],key[65];size_t pos=0,start,i;unsigned mode,n;char extra;hex(b,len,key);if(strcmp(key,expected))return -1;
 #define LINE() do{start=pos;while(pos<len&&b[pos]!='\n')pos++;if(pos==len||pos-start>=sizeof line)return -1;memcpy(line,b+start,pos-start);line[pos-start]=0;pos++;}while(0)
 LINE();if(sscanf(line,"%31s %24s %64s %64s %u %c",magic,boot,native,oldsha,&n,&extra)!=5
#ifdef PANDANOTE_NORMAL_UPGRADE
 ||strcmp(magic,"PANDANOTE-UPGRADE-1")
#else
 ||strcmp(magic,"PANDANOTE-FILES-1")
#endif
||!ishex(boot,24)||!ishex(native,64)||!ishex(oldsha,64)||n<3||n>MAX_FILES)return -1;count=n;
#ifdef PANDANOTE_NORMAL_UPGRADE
 if(upgrade_base(b,len,&pos,boot,native,oldsha))return -1;
#endif
 unsigned entries=0,pointers=0;char system[96],release[128];snprintf(system,sizeof system,"/etc/pandanote-system/%s/",boot);snprintf(release,sizeof release,"/user/pandanote/apps/releases/%s/",native);
 for(i=0;i<count;i++){struct item*t=&items[i];unsigned long z;LINE();if(sscanf(line,"%15s %o %lu %64s %511s %c",t->role,&mode,&z,t->sha,t->path,&extra)!=5||!ishex(t->sha,64)||!safechar(t->path)||z>MAX_BUNDLE||pos+z+1>len||b[pos+z]!='\n')return -1;
  t->mode=mode;t->len=z;t->data=b+pos;pos+=z+1;char h[65];hex(t->data,t->len,h);if(strcmp(h,t->sha))return -1;
  if(!strcmp(t->role,"system")){if(strncmp(t->path,system,strlen(system))||mode!=0600)return -1;}
  else if(!strcmp(t->role,"release")){if(strncmp(t->path,release,strlen(release))||(mode!=0600&&mode!=0700))return -1;}
  else if(!strcmp(t->role,"entry")){if(strcmp(t->path,"/etc/inittab")||mode!=0644||++entries>1)return -1;}
  else if(!strcmp(t->role,"pointer")){if(strcmp(t->path,"/user/pandanote/apps/current")||mode!=0600||++pointers>1)return -1;}
  else return -1;
  for(unsigned j=0;j<i;j++){size_t a=strlen(t->path),c=strlen(items[j].path);if(!strcmp(t->path,items[j].path)||(a<c&&!strncmp(t->path,items[j].path,a)&&items[j].path[a]=='/')||(c<a&&!strncmp(t->path,items[j].path,c)&&t->path[c]=='/'))return -1;}
 }return pos==len&&entries==1&&pointers==1?0:-1;
}
static int snapshot(const char*oldsha){char h[65];struct stat st;int fd;oldentry=readreg("/etc/inittab",&oldlen,0);if(!oldentry)return -1;hex(oldentry,oldlen,h);if(strcmp(h,oldsha))return -1;fd=regfd("/etc/inittab",0);if(fd<0)return -1;if(fstat(fd,&st)||(st.st_mode&0777)!=0644){close(fd);return -1;}close(fd);
 fd=regfd("/user/pandanote/apps/current",1);if(fd==-1)return -1;if(fd>=0){if(fstat(fd,&st)||(st.st_mode&0777)!=0600){close(fd);return -1;}close(fd);hadcurrent=1;oldcurrent=readreg("/user/pandanote/apps/current",&currentlen,0);if(!oldcurrent)return -1;}return 0;}
static int validate_targets(void){for(unsigned i=0;i<count;i++){struct item*t=&items[i];char name[256],h[65];int p=parentfd(t->path,0,name);struct stat st;if(p<0){if(errno==ENOENT)continue;return -1;}int fd=openat(p,name,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);close(p);if(fd<0){if(errno==ENOENT)continue;return -1;}if(fstat(fd,&st)||!S_ISREG(st.st_mode)||!owner(&st)||st.st_nlink!=1){close(fd);return -1;}
 if(!strcmp(t->role,"system")||!strcmp(t->role,"release")){if((size_t)st.st_size!=t->len||(st.st_mode&0777)!=t->mode){close(fd);return -1;}unsigned char*data=malloc(t->len?t->len:1);size_t n=0;if(!data){close(fd);return -1;}while(n<t->len){ssize_t r=read(fd,data+n,t->len-n);if(r<=0){free(data);close(fd);return -1;}n+=r;}hex(data,n,h);free(data);if(strcmp(h,t->sha)){close(fd);return -1;}}
 close(fd);}return 0;}
static int space(void){struct statvfs v;uint64_t root=1048576,user=1048576,home=1048576+oldlen+currentlen;for(unsigned i=0;i<count;i++)if(!strncmp(items[i].path,"/user/",6))user+=items[i].len+4096;else root+=items[i].len+4096;const char*p[]={"/","/home","/user"};uint64_t need[]={root,home,user};for(unsigned i=0;i<3;i++){char name[256];int fd=parentfd(i==0?"/etc/inittab":i==1?"/home/unused":"/user/unused",0,name);if(fd<0)return -1;if(fstatvfs(fd,&v)){close(fd);return -1;}close(fd);if((uint64_t)v.f_bavail*v.f_frsize<need[i])return -1;(void)p;}return 0;}
static int makebackup(void){char p[256],n[256];snprintf(backup,sizeof backup,"/home/pandanote-system/transactions/%s",bundle_key);snprintf(p,sizeof p,"%s/new-attempt",backup);int fd=parentfd(p,1,n);if(fd<0)return -1;/* exclusive attempt marker */int marker=openat(fd,n,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);if(marker<0){close(fd);return -1;}if(writeall(marker,bundle_key,64)||fsync(marker)||close(marker)||fsync(fd)){close(fd);return -1;}close(fd);
 snprintf(p,sizeof p,"%s/old-inittab",backup);if(atomicfile(p,oldentry,oldlen,0600))return -1;
 if(hadcurrent){snprintf(p,sizeof p,"%s/old-current",backup);if(atomicfile(p,oldcurrent,currentlen,0600))return -1;}
 char metadata[96],h[65];if(hadcurrent)hex(oldcurrent,currentlen,h);else strcpy(h,"absent");snprintf(metadata,sizeof metadata,"current=%s\n",h);snprintf(p,sizeof p,"%s/meta",backup);if(atomicfile(p,metadata,strlen(metadata),0600))return -1;
 backup_done=1;return phase("backup-durable");}
static int restore(void){int okay=0;cancelled=0;alarm(0);if(pointer_done){if(hadcurrent)okay=atomicfile("/user/pandanote/apps/current",oldcurrent,currentlen,0600);else okay=removefile("/user/pandanote/apps/current");}if(entry_done&&atomicfile("/etc/inittab",oldentry,oldlen,0644))okay=-1;if(root_rw&&remountroot(0))okay=-1;restored=okay==0;return okay;}
static int loadbackup(const char*oldsha){char p[256],h[65],want[65];size_t n;unsigned char*b;snprintf(backup,sizeof backup,"/home/pandanote-system/transactions/%s",bundle_key);
 snprintf(p,sizeof p,"%s/old-inittab",backup);oldentry=readreg(p,&oldlen,0);if(!oldentry)return -1;hex(oldentry,oldlen,h);if(strcmp(h,oldsha))return -1;
 snprintf(p,sizeof p,"%s/meta",backup);b=readreg(p,&n,0);if(!b)return -1;if(sscanf((char*)b,"current=%64s",want)!=1){free(b);return -1;}free(b);
 if(strcmp(want,"absent")){if(!ishex(want,64))return -1;hadcurrent=1;snprintf(p,sizeof p,"%s/old-current",backup);oldcurrent=readreg(p,&currentlen,0);if(!oldcurrent)return -1;hex(oldcurrent,currentlen,h);if(strcmp(h,want))return -1;}
 b=readreg("/etc/inittab",&n,0);if(!b)return -1;hex(b,n,h);free(b);int match=!strcmp(h,oldsha);for(unsigned i=0;i<count;i++)if(!strcmp(items[i].role,"entry")&&!strcmp(h,items[i].sha))match=1;if(!match)return -1;
 int currentfd=regfd("/user/pandanote/apps/current",1);if(currentfd==-1)return -1;if(currentfd>=0)close(currentfd);b=readreg("/user/pandanote/apps/current",&n,1);if(b){hex(b,n,h);free(b);match=hadcurrent&&!strcmp(h,want);for(unsigned i=0;i<count;i++)if(!strcmp(items[i].role,"pointer")&&!strcmp(h,items[i].sha))match=1;if(!match)return -1;}else if(hadcurrent)return -1;

#ifdef PANDANOTE_NORMAL_UPGRADE
 if(!hadcurrent||strcmp(want,upgrade_current))return -1;
#endif
 backup_done=1;return 0;
}
int main(int argc,char**argv){int fd=-1,lockfd=-1,status=1,index=1;struct stat st;unsigned char*b=MAP_FAILED;char oldsha[65],name[256];
#ifdef PANDANOTE_FIXTURE
 if((
#ifdef PANDANOTE_NORMAL_UPGRADE
 argc!=7&&argc!=8
#else
 argc!=5&&argc!=6
#endif
 )||strcmp(argv[1],"--clone")){fprintf(stderr,"fixture usage\n");return 2;}rootfd=open(argv[2],O_RDONLY|O_DIRECTORY|O_NOFOLLOW);index=3;size_t markerlen;unsigned char*marker=readreg("/.pandanote-normal-clone",&markerlen,0);if(!marker||strcmp((char*)marker,"pandanote-normal-boot-local-clone-v1\n")){free(marker);return 2;}free(marker);
#else
 if((
#ifdef PANDANOTE_NORMAL_UPGRADE
 argc!=5&&argc!=6
#else
 argc!=3&&argc!=4
#endif
 )||geteuid()!=0){fprintf(stderr,"usage: apply-tool bundle sha256\n");return 2;}rootfd=open("/",O_RDONLY|O_DIRECTORY);
#endif
 signal(SIGPIPE,SIG_IGN);struct sigaction sa;memset(&sa,0,sizeof sa);sa.sa_handler=cancel;sigemptyset(&sa.sa_mask);sigaction(SIGALRM,&sa,NULL);sigaction(SIGHUP,&sa,NULL);sigaction(SIGTERM,&sa,NULL);sigaction(SIGINT,&sa,NULL);
 if(!strcmp(argv[index],"--rollback")){rollback_mode=1;index++;}if(argc!=index+
#ifdef PANDANOTE_NORMAL_UPGRADE
 4
#else
 2
#endif
 ||rootfd<0||!ishex(argv[index+1],64))goto done;bundle_key=argv[index+1];fd=open(argv[index],O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0||fstat(fd,&st)||!S_ISREG(st.st_mode)||!owner(&st)||st.st_nlink!=1||st.st_size<100||st.st_size>MAX_BUNDLE)goto done;mapping_len=st.st_size;b=mmap(NULL,mapping_len,PROT_READ,MAP_PRIVATE,fd,0);if(b==MAP_FAILED||parse(b,mapping_len,bundle_key,oldsha))goto done;

#ifdef PANDANOTE_NORMAL_UPGRADE
 if(upgrade_proof(argv[index+2],argv[index+3])||upgrade_closure()||upgrade_pointer())goto done;
 if(identity())goto done;
#else
 if(identity()||qt_stopped())goto done;
#endif
if(rollback_mode){if(mountcontext(0)){if(mountcontext(1))goto done;root_rw=1;if(rollback_superblock(0))goto done;}if(loadbackup(oldsha))goto done;}else if(mountcontext(0)||snapshot(oldsha)||validate_targets()||space())goto done;
 /* Private p9 lease: no competing ordinary-file transaction. */
 lockfd=parentfd("/user/pandanote/state/normal-install.lock",1,name);if(lockfd<0)goto done;
 int parent=lockfd;lockfd=openat(parent,name,O_RDWR|O_CREAT|O_NOFOLLOW|O_CLOEXEC,0600);close(parent);if(lockfd<0||fstat(lockfd,&st)||!S_ISREG(st.st_mode)||!owner(&st)||st.st_nlink!=1||flock(lockfd,LOCK_EX|LOCK_NB))goto done;
 if(rollback_mode){if(rescue_handoff()||identity())goto done;if(!root_rw&&remountroot(1))goto done;pointer_done=entry_done=1;if(restore())goto done;phase("rolled-back-root-ro");status=0;goto done;}
 if(rescue_handoff()||identity()||qt_stopped()||mountcontext(0)||makebackup())goto done;
 if(remountroot(1))goto done;alarm(120);if(phase("root-rw"))goto failed;
 for(unsigned i=0;i<count;i++)if(strcmp(items[i].role,"entry")&&strcmp(items[i].role,"pointer")){if(atomicfile(items[i].path,items[i].data,items[i].len,items[i].mode)||phase("payload-file-durable"))goto failed;}
 if(phase("payload-durable"))goto failed;
 for(unsigned i=0;i<count;i++)if(!strcmp(items[i].role,"pointer")){pointer_done=1;if(atomicfile(items[i].path,items[i].data,items[i].len,items[i].mode))goto failed;}
 if(phase("pointer-durable")||phase("before-entry"))goto failed;
 for(unsigned i=0;i<count;i++)if(!strcmp(items[i].role,"entry")){entry_done=1;if(atomicfile(items[i].path,items[i].data,items[i].len,items[i].mode))goto failed;}
 if(phase("entry-durable")||phase("commit-ready-root-ro")||remountroot(0))goto failed;printf("phase=committed-root-ro\n");alarm(0);status=0;goto done;
 failed:if(restore())fprintf(stderr,"recovery=uncertain\n");else {phase("rolled-back-root-ro");fprintf(stderr,"recovery=restored-root-ro\n");}
 done:if(status&&root_rw&&!restored)restore();printf("result=%s root_rw=%d cleanup_ok=%d\n",status?"failed":rollback_mode?"rolled-back":"committed",root_rw,restored);if(b!=MAP_FAILED)munmap(b,mapping_len);if(fd>=0)close(fd);if(lockfd>=0)close(lockfd);if(rootfd>=0)close(rootfd);free(oldentry);free(oldcurrent);return status;}
