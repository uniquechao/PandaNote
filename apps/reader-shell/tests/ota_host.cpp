#include "../ota/core.h"
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdarg.h>
#include <string.h>
using namespace Ota;
static const char *cloneRoot;
extern "C" int __real_open(const char*,int,...);
extern "C" int __real_fsync(int);
extern "C" int __wrap_open(const char*path,int flags,...){mode_t mode=0600;if(flags&O_CREAT){va_list v;va_start(v,flags);mode=va_arg(v,int);va_end(v);}return __real_open(!strcmp(path,"/")&&cloneRoot?cloneRoot:path,flags,mode);}
extern "C" int __wrap_fsync(int fd){static unsigned count=0;const char*fail=getenv("OTA_FAIL_FSYNC");if(fail&&++count==unsigned(atoi(fail)))return -1;return __real_fsync(fd);}
#ifdef OTA_TEST_NO_CRYPTO
namespace Ota {bool verifySignature(const std::string&,const std::string&,const std::string&){return false;}}
#endif
static std::string file(const char*p){std::ifstream f(p,std::ios::binary);return std::string(std::istreambuf_iterator<char>(f),std::istreambuf_iterator<char>());}
int main(int argc,char**argv){if(argc<2)return 2;std::string mode=argv[1];if(mode=="process"){Process first;if(!process(getpid(),first))return 1;for(int i=0;i<100;i++){Process next;if(!process(getpid(),next)||!sameProcess(first,next))return 1;}return process(1,first)?1:0;}if(mode=="json"){std::string s((std::istreambuf_iterator<char>(std::cin)),std::istreambuf_iterator<char>());Json j;if(!parse(s,j))return 1;std::cout<<encode(j);return 0;}if(mode=="due"&&argc==4){std::cout<<(due(strtoll(argv[2],0,10),strtoll(argv[3],0,10))?1:0);return 0;}
 if(mode=="gesture"&&argc==3){std::string variant=argv[2],attempt(32,'1'),generation(32,'2');std::cout<<(confirmationGesture(attempt,generation,variant=="new_attempt"?std::string(32,'3'):attempt,variant=="new_generation"?std::string(32,'4'):generation,variant!="late_prompt",true,variant=="drag"?40:variant=="boundary"?16:0,0)?1:0);return 0;}
 if(mode=="base64"&&argc==3){std::string out;return unbase64(argv[2],out,128)?0:1;}
 if(mode=="resume"&&argc==5){std::cout<<resumeState(argv[2],atoi(argv[3]),atoi(argv[4]));return 0;}
 if(mode=="chunks"&&argc==3){cloneRoot=argv[2];std::string block(262144,'a'),last(123,'b'),result;if(!checkpointChunk("/state/bundle",0,262267,block)||checkpointChunk("/state/bundle",262144,262267,last+"x")||checkpointChunk("/state/bundle",1,262267,last)||!checkpointChunk("/state/bundle",262144,262267,last)||checkpointChunk("/state/bundle",262267,262267,"")||!readFile("/state/bundle",result,262267)||result!=block+last)return 1;
 // Replay a segment whose bytes reached disk before the checkpoint did.
 if(!checkpointChunk("/state/bundle",0,262267,block)||!checkpointChunk("/state/bundle",262144,262267,last)||!readFile("/state/bundle",result,262267)||result!=block+last)return 1;return 0;}
 if(mode=="storage"&&argc==3){cloneRoot=argv[2];std::string s;bool ok=atomic("/state/value","new");if(getenv("OTA_FAIL_FSYNC")){std::cout<<(ok?"success":"failure");return ok?1:0;}if(!ok||!readFile("/state/value",s,128)||s!="new"||atomic("/state/link","bad")||atomic("/state/hard","bad")||atomic("/state/parent/file","bad")||atomic("/state/../escape","bad"))return 1;return 0;}
 if((mode=="authorize"||mode=="bundle")&&argc==7){Json c,r,response;Authorization a;std::string error;if(!parse(file(argv[2]),c)||!parse(file(argv[3]),r)||!parse(file(argv[4]),response))return 2;if(!authorize(response,c,r,strtoll(argv[5],0,10),a,error)){std::cout<<error;return 1;}if(mode=="bundle"){cloneRoot=argv[6];if(!validateBundle("/bundle",a)){std::cout<<"bundle_invalid";return 1;}}std::cout<<"accepted";return 0;}
 return 2;}
