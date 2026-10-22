#include "resolver.h"
#include "dnsconfig.h"
#include <sys/socket.h>
#include <sys/wait.h>
#include <sys/resource.h>
#include <netdb.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
bool validDnsHost(const char *host){
 if(!host)return false;size_t n=strnlen(host,254);if(n<3||n>253)return false;
 unsigned label=0;bool dot=false,letter=false;
 for(size_t i=0;i<n;++i){const char c=host[i];if(c=='.'){if(!label||host[i-1]=='-')return false;dot=true;label=0;continue;}
  if(!((c>='a'&&c<='z')||(c>='0'&&c<='9')||c=='-')||(!label&&c=='-')||++label>63)return false;
  if(c>='a'&&c<='z')letter=true;
 }
 return dot&&letter&&label&&host[n-1]!='-';
}
int runDnsWorker(const char *host){
 if(!validDnsHost(host))return 2;
 if(!configureDhcpDns())return 3;
 struct addrinfo hints,*list=0;memset(&hints,0,sizeof hints);hints.ai_family=AF_INET;hints.ai_socktype=SOCK_STREAM;
 if(getaddrinfo(host,0,&hints,&list))return 3;
 char addresses[4][16];unsigned count=0,seen=0;
 for(struct addrinfo *a=list;a&&count<4&&seen++<64;a=a->ai_next){
  if(a->ai_family!=AF_INET||a->ai_addrlen<sizeof(struct sockaddr_in)||!a->ai_addr)continue;
  char ip[16];if(!inet_ntop(AF_INET,&reinterpret_cast<struct sockaddr_in *>(a->ai_addr)->sin_addr,ip,sizeof ip))continue;
  bool duplicate=false;for(unsigned i=0;i<count;i++)if(!strcmp(addresses[i],ip))duplicate=true;
  if(!duplicate)strcpy(addresses[count++],ip);
 }
 freeaddrinfo(list);if(!count)return 3;
 char result[96];size_t at=0;const char header[]="pandanote-dns-v1\n";memcpy(result,header,sizeof header-1);at=sizeof header-1;
 for(unsigned i=0;i<count;i++){size_t n=strlen(addresses[i]);memcpy(result+at,addresses[i],n);at+=n;result[at++]='\n';}
 size_t sent=0;while(sent<at){ssize_t n=write(STDOUT_FILENO,result+sent,at-sent);if(n<0&&errno==EINTR)continue;if(n<=0)return 4;sent+=size_t(n);}return 0;
}
DnsResolver::DnsResolver():child_(-1),fd_(-1),status_(-1),eof_(false),cancelled_(false),size_(0){}
DnsResolver::~DnsResolver(){cancel();}
bool DnsResolver::busy()const{return child_>0||fd_>=0;}
void DnsResolver::collect(){if(child_<=0)return;int status=0;pid_t done=waitpid(child_,&status,WNOHANG);if(done==child_){child_=-1;status_=WIFEXITED(status)?WEXITSTATUS(status):-1;}else if(done<0&&errno==ECHILD){child_=-1;status_=-1;}}
void DnsResolver::cancel(){if(fd_>=0)close(fd_);fd_=-1;cancelled_=true;size_=0;if(child_>0){kill(child_,SIGKILL);collect();}}
bool DnsResolver::start(const char *executable,const char *host){
 collect();if(busy()||!executable||executable[0]!='/'||strnlen(executable,4097)>4096||!validDnsHost(host))return false;
 int fds[2];if(pipe(fds))return false;
 if(fcntl(fds[0],F_SETFD,FD_CLOEXEC)<0||fcntl(fds[1],F_SETFD,FD_CLOEXEC)<0||fcntl(fds[0],F_SETFL,O_NONBLOCK)<0){close(fds[0]);close(fds[1]);return false;}
 struct rlimit limits;unsigned maxFd=1024;if(!getrlimit(RLIMIT_NOFILE,&limits)&&limits.rlim_cur<65536)maxFd=unsigned(limits.rlim_cur);else maxFd=65536;
 char *args[]={const_cast<char *>(executable),const_cast<char *>("--resolve-host"),const_cast<char *>(host),0};
 char *env[]={const_cast<char *>("PATH=/usr/sbin:/usr/bin:/sbin:/bin"),const_cast<char *>("LANG=C"),const_cast<char *>("LC_ALL=C"),const_cast<char *>("LD_LIBRARY_PATH=/run/pandanote-opt/opt/image/opt/Qtopia/lib:/opt/image/opt/Qtopia/lib:/lib:/usr/lib"),0};
 pid_t child=fork();if(child<0){close(fds[0]);close(fds[1]);return false;}
 if(!child){
  // Only async-signal-safe syscalls here. NSS/Qt begins in the fresh exec.
  if(dup2(fds[1],STDOUT_FILENO)<0)_exit(125);
  int nullfd=open("/dev/null",O_RDWR);if(nullfd<0||dup2(nullfd,STDIN_FILENO)<0||dup2(nullfd,STDERR_FILENO)<0)_exit(125);
  for(unsigned fd=3;fd<maxFd;fd++)close(int(fd));
  execve(executable,args,env);_exit(126);
 }
 close(fds[1]);fd_=fds[0];child_=child;status_=-1;eof_=false;cancelled_=false;size_=0;return true;
}
int DnsResolver::poll(char addresses[4][16],unsigned *count){
 if(!addresses||!count){cancel();return -1;}*count=0;collect();
 if(cancelled_){return -1;}
 if(fd_>=0){
  for(unsigned loops=0;loops<2;++loops){ssize_t n=read(fd_,output_+size_,sizeof output_-size_);if(n<0&&errno==EINTR)continue;if(n<0&&(errno==EAGAIN||errno==EWOULDBLOCK))break;if(n<0){cancel();return -1;}if(!n){close(fd_);fd_=-1;eof_=true;break;}size_+=unsigned(n);if(size_>=sizeof output_){cancel();return -1;}}
 }
 collect();if(child_>0||!eof_)return 0;
 if(status_||size_<14||memcmp(output_,"pandanote-dns-v1\n",13)||memchr(output_,0,size_)){cancel();return -1;}
 unsigned at=13;while(at<size_){unsigned end=at;while(end<size_&&output_[end]!='\n')end++;unsigned n=end-at;if(end==size_||!n||n>15||*count>=4){cancel();return -1;}char ip[16];memcpy(ip,output_+at,n);ip[n]=0;struct in_addr address;char canonical[16];if(inet_pton(AF_INET,ip,&address)!=1||!inet_ntop(AF_INET,&address,canonical,sizeof canonical)||strcmp(ip,canonical)){cancel();return -1;}for(unsigned i=0;i<*count;i++)if(!strcmp(addresses[i],ip)){cancel();return -1;}strcpy(addresses[(*count)++],ip);at=end+1;}
 if(!*count){cancel();return -1;}cancelled_=true;return 1;
}
