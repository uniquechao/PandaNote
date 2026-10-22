// Real own-process exec/pipe lifecycle; NSS alone is a local deterministic fixture.
#include "../resolver.h"
#include <netdb.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <sys/wait.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <stdlib.h>
static bool fixtureDhcpAvailable=true;
bool configureDhcpDns(const char *){return fixtureDhcpAvailable;} // filesystem policy tested independently
static int checks=0,failures=0;
#define CHECK(n,x) do{++checks;if(!(x)){++failures;fprintf(stderr,"FAIL %s line %d\n",n,__LINE__);}}while(0)
extern "C" int getaddrinfo(const char *host,const char *,const struct addrinfo *,struct addrinfo **out){
 static struct addrinfo a;static struct sockaddr_in v;memset(&a,0,sizeof a);memset(&v,0,sizeof v);
 if(!strcmp(host,"slow.example"))usleep(500000);
 if(!strcmp(host,"bad.example"))return EAI_NONAME;
 a.ai_family=AF_INET;a.ai_socktype=SOCK_STREAM;a.ai_addrlen=sizeof v;a.ai_addr=reinterpret_cast<sockaddr*>(&v);v.sin_family=AF_INET;inet_pton(AF_INET,"192.0.2.42",&v.sin_addr);*out=&a;return 0;
}
extern "C" void freeaddrinfo(struct addrinfo *){}
static long long now(){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (long long)t.tv_sec*1000+t.tv_nsec/1000000;}
int main(int argc,char **argv){
 if(argc==3&&!strcmp(argv[1],"--resolve-host")){if(!strcmp(argv[2],"no-dhcp.example"))fixtureDhcpAvailable=false;if(!strcmp(argv[2],"oversize.example")){for(int i=0;i<512;i++)putchar('x');return 0;}if(!strcmp(argv[2],"malformed.example")){printf("pandanote-dns-v1\n192.0.2.001\n");return 0;}if(!strcmp(argv[2],"duplicate.example")){printf("pandanote-dns-v1\n192.0.2.42\n192.0.2.42\n");return 0;}return runDnsWorker(argv[2]);}
 char exe[4096];CHECK("absolute_exe",realpath(argv[0],exe)!=0);
 CHECK("canonical_host",validDnsHost("pandanote.example.invalid"));
 const char *bad[]={"bad..test","-bad.test","bad-.test","bad.test.","127.0.0.1","bad/test","user@bad.test","bad\r\ntest","bad_test.example","Bad.test"};for(unsigned i=0;i<sizeof bad/sizeof bad[0];i++)CHECK("reject_noncanonical_host",!validDnsHost(bad[i]));
 DnsResolver dns;char addresses[4][16];unsigned count=0;CHECK("start_async",dns.start(exe,"ok.example")&&dns.busy());int result=0;long long until=now()+1500;while(!result&&now()<until){result=dns.poll(addresses,&count);usleep(1000);}CHECK("worker_result",result==1&&count==1&&!strcmp(addresses[0],"192.0.2.42")&&!dns.busy());
 CHECK("invalid_start",!dns.start(exe,"user@bad.test")&&!dns.busy());
 CHECK("slow_async_start",dns.start(exe,"slow.example"));long long before=now();dns.cancel();CHECK("cancel_is_nonblocking",now()-before<100);until=now()+1500;while(dns.busy()&&now()<until){dns.poll(addresses,&count);usleep(1000);}CHECK("cancel_reaps_owned_child",!dns.busy());
 CHECK("replacement_start",dns.start(exe,"ok.example"));result=0;until=now()+1500;while(!result&&now()<until){result=dns.poll(addresses,&count);usleep(1000);}CHECK("cancelled_result_cannot_replace",result==1&&count==1&&!strcmp(addresses[0],"192.0.2.42"));
 CHECK("dns_failure_start",dns.start(exe,"bad.example"));result=0;until=now()+1500;while(!result&&now()<until){result=dns.poll(addresses,&count);usleep(1000);}CHECK("dns_failure_closed",result==-1&&!dns.busy());
 CHECK("exec_failure_start",dns.start("/definitely/missing/worker","ok.example"));result=0;until=now()+1500;while(!result&&now()<until){result=dns.poll(addresses,&count);usleep(1000);}CHECK("exec_failure_closed",result==-1&&!dns.busy());
 const char *badReplies[]={"oversize.example","malformed.example","duplicate.example","no-dhcp.example"};for(unsigned i=0;i<4;++i){CHECK("malformed_worker_start",dns.start(exe,badReplies[i]));result=0;until=now()+1500;while(!result&&now()<until){result=dns.poll(addresses,&count);usleep(1000);}CHECK("malformed_reply_rejected",result==-1);while(dns.busy()&&now()<until){dns.poll(addresses,&count);usleep(1000);}CHECK("malformed_worker_reaped",!dns.busy());}
 printf("%d checks, %d failures\n",checks,failures);return failures?1:0;
}
