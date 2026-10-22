#ifndef PANDANOTE_RESOLVER_H
#define PANDANOTE_RESOLVER_H
#include <sys/types.h>
bool validDnsHost(const char *canonicalHost);
// Invoked before QApplication, only in an exec-isolated copy of this ELF.
int runDnsWorker(const char *canonicalHost);
class DnsResolver {
public:
 DnsResolver();~DnsResolver();bool start(const char *executable,const char *host);
 int poll(char addresses[4][16],unsigned *count);void cancel();bool busy()const;
private:
 DnsResolver(const DnsResolver &);DnsResolver &operator=(const DnsResolver &);
 void collect();pid_t child_;int fd_,status_;bool eof_,cancelled_;unsigned size_;char output_[129];
};
#endif
