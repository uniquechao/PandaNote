#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "core.h"
#include "sha256.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/file.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
int64_t c2_now(void) { struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t))return -1;return (int64_t)t.tv_sec*1000+t.tv_nsec/1000000; }
static void nap(void){struct timespec t={0,10000000};nanosleep(&t,NULL);}
int c2_alive(struct child *c){
 if(c->pid<=0||c->reaped)return 0;
 pid_t p=waitpid(c->pid,&c->status,WNOHANG);
 if(p==0)return 1;
 if(p==c->pid){c->reaped=1;return 0;}
 if(errno==EINTR)return 1;
 return -1; /* ECHILD is never permission to signal that PID. */
}
int c2_stop(struct child *c){
 int a=c2_alive(c);if(a<=0)return a;
 if(kill(c->pid,SIGTERM)&&errno!=ESRCH)return -1;
 int64_t end=c2_now()+300;
 while((a=c2_alive(c))==1&&c2_now()<end)nap();
 if(a<=0)return a;
 if(kill(c->pid,SIGKILL)&&errno!=ESRCH)return -1;
 end=c2_now()+700;
 while((a=c2_alive(c))==1&&c2_now()<end)nap();
 return a==0?0:-1; /* Never remove socket/state if a child was not reaped. */
}
static int limit(int kind,rlim_t n){struct rlimit r={n,n};return setrlimit(kind,&r);}
int c2_spawn(struct child *c,int executable_fd,char *const argv[],char *const env[],int logfd,unsigned memory_mb){
 int pipefd[2];struct stat st;long maximum=sysconf(_SC_OPEN_MAX);
 if(c->pid||executable_fd<3||logfd<3||maximum<0||maximum>1048576||fstat(executable_fd,&st)||!S_ISREG(st.st_mode)||pipe(pipefd))return -1;
 if(fcntl(pipefd[0],F_SETFD,FD_CLOEXEC)||fcntl(pipefd[1],F_SETFD,FD_CLOEXEC)){close(pipefd[0]);close(pipefd[1]);return -1;}
 pid_t p=fork();
 if(p<0){close(pipefd[0]);close(pipefd[1]);return -1;}
 if(!p){
  int error=1;signal(SIGTERM,SIG_DFL);signal(SIGINT,SIG_DFL);signal(SIGALRM,SIG_DFL);signal(SIGXFSZ,SIG_DFL);
  if(dup2(logfd,1)<0||dup2(logfd,2)<0)goto failed;
  close(0);
  for(int fd=3;fd<maximum;fd++)if(fd!=executable_fd&&fd!=pipefd[1])close(fd);
  if(limit(RLIMIT_CORE,0)||limit(RLIMIT_FSIZE,16384)||limit(RLIMIT_NOFILE,32)||limit(RLIMIT_CPU,8))goto failed;
#ifdef __linux__
  if(limit(RLIMIT_AS,(rlim_t)memory_mb*1024*1024)||limit(RLIMIT_STACK,512*1024))goto failed;
  fexecve(executable_fd,argv,env);
#else
  /* Host-only fixture compatibility; the reader build always uses fexecve. */
  (void)memory_mb;char path[1024];if(fcntl(executable_fd,F_GETPATH,path)==0)execve(path,argv,env);
#endif
 failed:
  error=errno; (void)write(pipefd[1],&error,sizeof error);_exit(126);
 }
 c->pid=p;c->reaped=0;c->status=0;close(pipefd[1]);
 struct pollfd pollfd={pipefd[0],POLLIN|POLLHUP,0};int n;
 int64_t deadline=c2_now()+1500;
 do {int left=(int)(deadline-c2_now());if(left<=0){n=0;break;}n=poll(&pollfd,1,left);}while(n<0&&errno==EINTR);
 int error=0;ssize_t got=n>0?read(pipefd[0],&error,sizeof error):-1;close(pipefd[0]);
 if(got!=0){(void)c2_stop(c);return -1;}return 0;
}
static int leaf(const char *n){return n&&*n&&strcmp(n,".")&&strcmp(n,"..")&&!strchr(n,'/');}
static int checked(int fd,int directory){struct stat s;if(fd<0)return -1;if(fstat(fd,&s)||s.st_uid!=geteuid()||(s.st_mode&07777)!=(directory?0700:0600)||(directory?!S_ISDIR(s.st_mode):(!S_ISREG(s.st_mode)||s.st_nlink!=1))){close(fd);return -1;}return fd;}
static int samefs(int parent,int fd){struct stat p,s;if(fd<0)return -1;if(fstat(parent,&p)||fstat(fd,&s)||p.st_dev!=s.st_dev){close(fd);return -1;}return fd;}
int c2_dir(int parent,const char *name){if(!leaf(name))return -1;if(mkdirat(parent,name,0700)&&errno!=EEXIST)return -1;return samefs(parent,checked(openat(parent,name,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC),1));}
int c2_file(int parent,const char *name,int create){if(!leaf(name))return -1;return samefs(parent,checked(openat(parent,name,O_RDWR|O_NOFOLLOW|O_CLOEXEC|(create?O_CREAT|O_EXCL:0),0600),0));}
int c2_lock(int fd){return flock(fd,LOCK_EX|LOCK_NB);}
int c2_empty(int fd){
 int copy=openat(fd,".",O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(copy<0)return -1;
 DIR *dir=fdopendir(copy);if(!dir){close(copy);return -1;}struct dirent *e;int ret=0;errno=0;
 while((e=readdir(dir)))if(strcmp(e->d_name,".")&&strcmp(e->d_name,"..")){ret=-1;break;}
 if(errno)ret=-1;
 closedir(dir);return ret;
}
int c2_hash(int fd,const char *want,unsigned limit_bytes){
 SHA256_CTX c;unsigned char block[4096],hash[32];char hex[65];unsigned total=0;ssize_t n;
 if(strlen(want)!=64||lseek(fd,0,SEEK_SET)<0)return -1;
 sha256_init(&c);
 while((n=read(fd,block,sizeof block))>0){if((unsigned)n>limit_bytes-total)return -1;total+=(unsigned)n;sha256_update(&c,block,(size_t)n);}
 if(n<0)return -1;
 sha256_final(&c,hash);for(int i=0;i<32;i++)snprintf(hex+2*i,3,"%02x",hash[i]);
 return strcmp(want,hex)||lseek(fd,0,SEEK_SET)<0?-1:0;
}

/* Only descendants of our initially empty state directory, after both children
 * are reaped. No symlink traversal; each entry checked via an opened descriptor.
 * Quota failure preserves remaining state and returns cleanup failure. */
int c2_erase(int dir,unsigned depth,unsigned *count,unsigned *bytes){
 if(depth>6)return -1;
 int copy=openat(dir,".",O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(copy<0)return -1;
 DIR *stream=fdopendir(copy);if(!stream){close(copy);return -1;}
 int result=0;struct dirent *e;
 for(;;){errno=0;e=readdir(stream);if(!e){if(errno)result=-1;break;}
  if(!strcmp(e->d_name,".")||!strcmp(e->d_name,".."))continue;
  if(++*count>64){result=-1;break;}
  int fd=samefs(dir,openat(dir,e->d_name,O_RDONLY|O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC));struct stat s;
  if(fd<0||fstat(fd,&s)||s.st_uid!=geteuid()){if(fd>=0)close(fd);result=-1;break;}
  int directory=S_ISDIR(s.st_mode);
  if((s.st_mode&07777)!=(directory?0700:0600)||(!directory&&(!S_ISREG(s.st_mode)||s.st_nlink!=1||s.st_size<0||s.st_size>65536))){close(fd);result=-1;break;}
  if(directory){if(c2_erase(fd,depth+1,count,bytes))result=-1;}
  else {*bytes+=(unsigned)s.st_size;if(*bytes>262144)result=-1;}
  close(fd);if(result||unlinkat(dir,e->d_name,directory?AT_REMOVEDIR:0)){result=-1;break;}
 }
 closedir(stream);return result;
}
