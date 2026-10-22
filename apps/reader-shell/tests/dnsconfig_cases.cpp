#include "../dnsconfig.h"
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <string>
#if defined(__GLIBC__)
#include <resolv.h>
#include <netdb.h>
extern "C" int __res_init(void);
#else
static char observed[3][16];static unsigned observedCount;
extern "C" bool dnsConfigTestApply(const char servers[3][16],unsigned count){observedCount=count;memcpy(observed,servers,sizeof observed);return true;}
#endif
static int checks=0,failures=0;
#define CHECK(n,c) do{++checks;if(!(c)){++failures;fprintf(stderr,"FAIL %s line %d\n",n,__LINE__);}}while(0)
static void store(const std::string &p,const char *s){int fd=open(p.c_str(),O_WRONLY|O_CREAT|O_TRUNC,0600);if(fd<0)exit(5);size_t n=strlen(s);if(write(fd,s,n)!=ssize_t(n)||close(fd))exit(5);chmod(p.c_str(),0600);}
int main(int argc,char **argv){
 if(argc!=2&&argc!=3)return 2;std::string dir=argv[1],file=dir+"/resolv.conf";
 const char *valid="nameserver 223.5.5.5\nnameserver 119.29.29.29\n";
 store(file,valid);CHECK("DHCP nameservers applied",configureDhcpDns(dir.c_str()));
#if defined(__GLIBC__)
 CHECK("real glibc resolver uses two supplied servers",_res.nscount==2&&ntohl(_res.nsaddr_list[0].sin_addr.s_addr)==0xdf050505U&&ntohl(_res.nsaddr_list[1].sin_addr.s_addr)==0x771d1d1dU&&_res.nsaddr_list[0].sin_port==htons(53));
 CHECK("reload/search disabled bounded retries",(_res.options&RES_NORELOAD)&&!(_res.options&(RES_DNSRCH|RES_DEFNAMES))&&_res.retrans==2&&_res.retry==1);
#else
 CHECK("only DHCP addresses reach resolver",observedCount==2&&!strcmp(observed[0],"223.5.5.5")&&!strcmp(observed[1],"119.29.29.29"));
#endif
 const char *bad[]={"","nameserver 223.5.5.5","nameserver 223.005.5.5\n","nameserver 223.5.5.5\nsearch attacker.test\n","nameserver 1.1.1.1\nnameserver 2.2.2.2\nnameserver 3.3.3.3\nnameserver 4.4.4.4\n","nameserver 1.1.1.1\nnameserver 1.1.1.1\n"};
 for(unsigned i=0;i<sizeof bad/sizeof bad[0];i++){store(file,bad[i]);CHECK("malformed DHCP file refused",!configureDhcpDns(dir.c_str()));}
 store(file,valid);chmod(file.c_str(),0644);CHECK("public file refused",!configureDhcpDns(dir.c_str()));chmod(file.c_str(),0600);
 std::string alias=dir+"/hard";CHECK("hardlink setup",!link(file.c_str(),alias.c_str()));CHECK("hardlinked DNS refused",!configureDhcpDns(dir.c_str()));unlink(alias.c_str());unlink(file.c_str());
 CHECK("symlink setup",!symlink("target",file.c_str()));CHECK("symlink file refused",!configureDhcpDns(dir.c_str()));unlink(file.c_str());store(file,valid);
 chmod(dir.c_str(),0755);CHECK("public directory refused",!configureDhcpDns(dir.c_str()));chmod(dir.c_str(),0700);
 std::string linkdir=dir+"-link";CHECK("directory symlink setup",!symlink(dir.c_str(),linkdir.c_str()));CHECK("symlink directory refused",!configureDhcpDns(linkdir.c_str()));unlink(linkdir.c_str());
 store(file,std::string(257,'x').c_str());CHECK("oversize refused",!configureDhcpDns(dir.c_str()));unlink(file.c_str());CHECK("missing refused without host fallback",!configureDhcpDns(dir.c_str()));
#if defined(__GLIBC__)
 if(argc==3&&!strcmp(argv[2],"--query")){
  store(file,"nameserver 127.0.0.1\n");CHECK("loopback DHCP snapshot",configureDhcpDns(dir.c_str()));
  // Test-only nonprivileged port: production always uses DNS port 53.
  _res.nsaddr_list[0].sin_port=htons(1053);
  struct addrinfo hints,*answer=0;memset(&hints,0,sizeof hints);hints.ai_family=AF_INET;hints.ai_socktype=SOCK_STREAM;
  int r=getaddrinfo("dhcp-proof.example",0,&hints,&answer);bool match=!r&&answer&&answer->ai_family==AF_INET&&ntohl(reinterpret_cast<struct sockaddr_in *>(answer->ai_addr)->sin_addr.s_addr)==0xcb007129U;
  CHECK("actual stock getaddrinfo uses DHCP DNS",match);if(answer)freeaddrinfo(answer);unlink(file.c_str());
 }
#endif
 printf("%s DHCP DNS %d checks\n",failures?"FAIL":"PASS",checks);return failures?1:0;
}
