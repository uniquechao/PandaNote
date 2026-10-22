#ifndef PANDANOTE_DNS_CONFIG_H
#define PANDANOTE_DNS_CONFIG_H
// Only the fresh exec worker calls this. No filesystem or global resolver
// state in the UI process changes. Invalid/missing DHCP state fails closed.
bool configureDhcpDns(const char *privateDirectory="/tmp/pandanote-connectivity");
#endif
