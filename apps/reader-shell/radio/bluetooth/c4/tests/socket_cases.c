#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <assert.h>
#include <stdio.h>
#include <sys/wait.h>
#include "../session.c"
volatile sig_atomic_t c2_cancelled;
int c4_socket_child(int,const char *,int,int);
static int bind_fixture(mode_t mode){
 int fd=socket(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0);assert(fd>=0);struct sockaddr_un address;memset(&address,0,sizeof address);address.sun_family=AF_UNIX;strcpy(address.sun_path,C4_SOCKET);assert(!bind(fd,(struct sockaddr *)&address,sizeof address));assert(!chmod(C4_SOCKET,mode));return fd;
}
int main(void){
 umask(077);assert(!mkdir("/tmp/pandanote-connectivity",0700));assert(!mkdir(C4_ROOT,0700));assert(!mkdir(C4_ROOT "/service",0700));
 int dir=open(C4_ROOT "/service",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);assert(dir>=0);int tx[2],rx[2];assert(!pipe(tx)&&!pipe(rx));pid_t child=fork();assert(child>=0);
 if(!child){close(tx[0]);close(rx[1]);_exit(c4_socket_child(dir,C4_ROOT "/service",tx[1],rx[0]));}
 close(tx[1]);close(rx[0]);char stage;assert(read(tx[0],&stage,1)==1&&stage=='B');
 struct c4_context context;memset(&context,0,sizeof context);context.service_socket=(struct c4_socket){.directory=dir,.name="local.sock",.path=C4_SOCKET};
 int early=service(&context,child);struct stat during;assert(!fstatat(dir,"local.sock",&during,AT_SYMLINK_NOFOLLOW));
 assert(write(rx[1],"G",1)==1);assert(read(tx[0],&stage,1)==1);int wrong=-1,ready=-1;
 if(stage=='R'){wrong=service(&context,getpid());ready=service(&context,child);}
 int status;assert(waitpid(child,&status,0)==child);close(tx[0]);close(rx[1]);
 /* Clean the exact observed old socket even on RED, before reporting failure. */
 assert(!c4_unlink_socket(&context.service_socket));
 fprintf(stderr,"controlled C3 validation: observed_mode=%o stage=%c child_exit=%d\n",(unsigned)(during.st_mode&07777),stage,WIFEXITED(status)?WEXITSTATUS(status):-1);
 assert(early==-1);assert(stage=='R'&&WIFEXITED(status)&&WEXITSTATUS(status)==0);assert((during.st_mode&07777)==0700);assert(wrong==-1&&ready==0);
 struct stat absent;assert(fstatat(dir,"local.sock",&absent,AT_SYMLINK_NOFOLLOW)&&errno==ENOENT);
 int socket1=bind_fixture(0666);memset(&context.service_socket.identity,0,sizeof context.service_socket.identity);context.service_socket.seen=0;
 assert(service(&context,getpid())==-1);struct stat wrong_mode;assert(!fstatat(dir,"local.sock",&wrong_mode,AT_SYMLINK_NOFOLLOW)&&(wrong_mode.st_mode&07777)==0666);assert(!unlinkat(dir,"local.sock",0));close(socket1);
 socket1=bind_fixture(0700);context.service_socket.seen=0;assert(service(&context,getpid())==-1&&context.service_socket.seen);assert(!unlinkat(dir,"local.sock",0));int socket2=bind_fixture(0600);
 assert(service(&context,getpid())==-1);assert(c4_unlink_socket(&context.service_socket)==-1);assert(!fstatat(dir,"local.sock",&absent,AT_SYMLINK_NOFOLLOW));assert(!unlinkat(dir,"local.sock",0));close(socket2);close(socket1);
 socket1=bind_fixture(0700);context.service_socket.seen=0;assert(socket_ready(&context.service_socket,1)==1);assert(!fstatat(dir,"local.sock",&absent,AT_SYMLINK_NOFOLLOW)&&(absent.st_mode&07777)==0600);assert(!c4_unlink_socket(&context.service_socket));close(socket1);close(dir);
 puts("PASS C4 socket interleaving: actual C3 bind/validate/chmod, owned IPC, wrong peer/mode, inode replacement and retained bus tightening");return 0;
}
