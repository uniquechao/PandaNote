#define _POSIX_C_SOURCE 200809L
#include <signal.h>
#include <string.h>
#include <unistd.h>
int main(int argc,char **argv) {
 alarm(5);
 if(argc!=2)return 2;
 if(!strcmp(argv[1],"exit"))return 17;
 if(!strcmp(argv[1],"ignore")){signal(SIGTERM,SIG_IGN);write(1,"ready\n",6);for(;;)pause();}
 if(!strcmp(argv[1],"flood")){char b[1024];memset(b,'x',sizeof b);for(;;)if(write(1,b,sizeof b)<0)return 3;}
 return 2;
}
