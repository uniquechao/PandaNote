#ifndef PANDANOTE_OTA_CORE_H
#define PANDANOTE_OTA_CORE_H
#include <string>
#include <map>
#include <vector>
#include <stdint.h>
#include <sys/stat.h>
#if defined(__mips__) && defined(__linux__)
extern "C" int __lxstat(int,const char*,struct stat*);
extern "C" int __fxstat(int,int,struct stat*);
extern "C" int __fxstatat(int,int,const char*,struct stat*,int);
#define lstat(p,s) __lxstat(3,p,s)
#define fstat(f,s) __fxstat(3,f,s)
#define fstatat(f,p,s,a) __fxstatat(3,f,p,s,a)
#endif
namespace Ota {
struct Json {
 enum Type {Null,Boolean,Integer,String,Array,Object};Type type;int64_t number;std::string string;std::vector<Json> array;std::map<std::string,Json> object;
 Json():type(Null),number(0){} explicit Json(const std::string &s):type(String),number(0),string(s){}
 static Json integer(int64_t n);static Json obj();static Json list();
 const Json &get(const std::string &)const;std::string text(const std::string &)const;int64_t num(const std::string &)const;
 bool keys(const char *)const;bool has(const std::string &)const;
};
bool parse(const std::string &,Json &,size_t limit=786432);std::string encode(const Json &);
bool hex(const std::string &,size_t n=64);bool identifier(const std::string &);std::string decimal(int64_t);std::string digest(const std::string &);std::string randomHex(size_t bytes);
bool unbase64(const std::string &,std::string &,size_t);std::string base64(const std::string &);
// 绝对路径逐级通过描述符核验所有权，拒绝其他身份可写的路径。
int openFile(const std::string &,int flags,bool privateFile=true);bool directory(const std::string &,bool create=false);
bool readFile(const std::string &,std::string &,size_t,bool privateFile=true);bool atomic(const std::string &,const std::string &);bool removeFile(const std::string &);
bool hashFile(const std::string &,std::string &,uint64_t *bytes=0,bool procExe=false);bool rootReadOnly();bool freeSpace(const std::string &,uint64_t);
int64_t bootMs();int64_t epoch();
struct Process {int64_t pid,ppid,pgid,sid,start;std::string exe,cmd;Process():pid(0),ppid(0),pgid(0),sid(0),start(0){} };
bool process(int64_t,Process &);bool sameProcess(const Process &,const Process &);Json processJson(const Process &);
bool captureProof(std::string &,Process *native=0);bool closure(const Json &files);
struct Authorization {Json release,deployment,candidate;std::string releaseRaw,candidateRaw;};
// crypto.cpp 使用固定 MbedTLS 实现真实 P-256/DER 验签。
bool verifySignature(const std::string &pem,const std::string &message,const std::string &signature);
bool envelope(const Json &,const char *domain,const Json &keys,size_t,Json &,std::string &);
bool authorize(const Json &response,const Json &config,const Json &request,int64_t now,Authorization &,std::string &error);
bool validateBundle(const std::string &path,const Authorization &);
bool validateFiles(const Json &,const std::string &native,const std::string &boot,bool sourceFields);
bool checkpointChunk(const std::string &,int64_t done,int64_t total,const std::string &);
std::string resumeState(const std::string &,bool newBoot,bool targetActive);
bool confirmationGesture(const std::string &pressedAttempt,const std::string &pressedGeneration,const std::string &attempt,const std::string &generation,bool promptAtPress,bool promptNow,int dx,int dy);
bool due(int64_t now,int64_t lastSuccess);bool safePower();
const char *stateRoot();const char *runRoot();
}
#endif
