#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE
#endif
/* Independent bounded radio control. No shell or vendor execution. Persistent
 * Wi-Fi is enabled only by the reviewed writable-profile fixed-path pointer. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <ctype.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <time.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/select.h>
#include <sys/wait.h>
#include <sys/ioctl.h>
#include <net/if.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#ifndef RADIO_CTRL
#define RADIO_CTRL "/tmp/pandanote-connectivity/wpa/wlan0"
#endif
#ifndef RADIO_LOCAL
#define RADIO_LOCAL "/tmp/pandanote-connectivity"
#endif
#ifndef RADIO_BTCTL
#define RADIO_BTCTL "/usr/bin/bluetoothctl"
#endif
/* Stock glibc 2.29 exports __lxstat rather than the glibc >=2.33 lstat alias.
 * Its inspected MIPS converter accepts version 3 (Linux struct stat ABI). */
#if defined(__mips__) && defined(__linux__)
extern int __lxstat(int, const char *, struct stat *);
extern int __fxstat(int, int, struct stat *);
extern int __fxstatat(int, int, const char *, struct stat *, int);
#define lstat(path, st) __lxstat(3, path, st)
#define fstat(fd, st) __fxstat(3, fd, st)
#define fstatat(fd, path, st, flags) __fxstatat(3, fd, path, st, flags)
#endif
#define LIMIT 16384
#define OUTPUT 65536
static const char alphabet[]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
static char result[OUTPUT];
static size_t used;
static void append(const char *s) {size_t n=strlen(s);if(used+n<OUTPUT){memcpy(result+used,s,n);used+=n;result[used]=0;}}
static void encode(const unsigned char *in,size_t n,char *out){size_t i,j=0;for(i=0;i<n;i+=3){unsigned x=(unsigned)in[i]<<16;if(i+1<n)x|=(unsigned)in[i+1]<<8;if(i+2<n)x|=in[i+2];out[j++]=alphabet[(x>>18)&63];out[j++]=alphabet[(x>>12)&63];out[j++]=i+1<n?alphabet[(x>>6)&63]:'=';out[j++]=i+2<n?alphabet[x&63]:'=';}out[j]=0;}
static int utf8(const unsigned char *s,size_t n){size_t i=0;while(i<n){unsigned c=s[i++],v,min;int k;if(!c)return 0;if(c<128)continue;if(c>=194&&c<=223){k=1;v=c&31;min=128;}else if(c>=224&&c<=239){k=2;v=c&15;min=2048;}else if(c>=240&&c<=244){k=3;v=c&7;min=65536;}else return 0;while(k--){if(i==n||s[i]<128||s[i]>191)return 0;v=(v<<6)|(s[i++]&63);}if(v<min||v>0x10ffff||(v>=0xd800&&v<=0xdfff))return 0;}return 1;}
static int decode(const char *s,unsigned char *out,size_t max){size_t n=strlen(s),i,j=0;char check[256];if(n%4||n>252)return -1;for(i=0;i<n;i+=4){unsigned x=0;int k;for(k=0;k<4;k++){const char *p=strchr(alphabet,s[i+k]);if(s[i+k]=='='){if(i+4!=n||k<2)return -1;x<<=6;}else{if(!p||!s[i+k]||(k&&s[i+k-1]=='='))return -1;x=(x<<6)|(unsigned)(p-alphabet);}}if(j==max)return -1;out[j++]=(unsigned char)(x>>16);if(s[i+2]!='='){if(j==max)return -1;out[j++]=(unsigned char)(x>>8);}if(s[i+3]!='='){if(j==max)return -1;out[j++]=(unsigned char)x;}}encode(out,j,check);if(strcmp(check,s)||!utf8(out,j))return -1;out[j]=0;return (int)j;}
static void reply(int ok,const char *code,const char *message){char b[512],line[700];encode((const unsigned char*)message,strlen(message),b);snprintf(line,sizeof(line),"[reply]\nschema=1\nok=%d\ncode=%s\nmessage64=%s\n",ok,code,b);append(line);}
/* A single monotonic budget covers readiness, interrupted/would-block retries,
 * and the actual nonblocking I/O. Never restart a timeout after a signal. */
static int64_t monotonic_ms(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) return -1;
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}
static int set_nonblocking(int fd) {
    int flags = fcntl(fd, F_GETFL, 0);
    return flags >= 0 && fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0;
}
static int within_deadline(int64_t deadline) {
    int64_t now = monotonic_ms();
    return now >= 0 && now < deadline;
}
static int wait_ready(int fd, int writing, int64_t deadline) {
    if (fd < 0 || fd >= FD_SETSIZE) return 0;
    for (;;) {
        int64_t now = monotonic_ms();
        fd_set ready;
        struct timeval timeout;
        long left;
        int value;
        if (now < 0 || now >= deadline) return 0;
        left = (long)(deadline - now);
        timeout.tv_sec = left / 1000;
        timeout.tv_usec = (left % 1000) * 1000;
        FD_ZERO(&ready);
        FD_SET(fd, &ready);
        value = select(fd + 1, writing ? NULL : &ready,
                       writing ? &ready : NULL, NULL, &timeout);
        if (value > 0) return 1;
        if (value < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        return 0;
    }
}
static ssize_t read_request(char *buffer, size_t cap) {
    size_t n = 0;
    int64_t start = monotonic_ms(), deadline;
    if (start < 0 || !set_nonblocking(0)) return -1;
    deadline = start + 2000;
    while (n < cap) {
        ssize_t value;
        if (!wait_ready(0, 0, deadline) || !within_deadline(deadline)) return -1;
        value = read(0, buffer + n, cap - n);
        if (value == 0) return (ssize_t)n;
        if (value < 0) {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) continue;
            return -1;
        }
        n += (size_t)value;
    }
    return (ssize_t)n;
}
static void bt_limit(void){append("[status]\nbt_state=uninitialized\nble_capability=unverified\niphone_service=unavailable\nfile_transfer=unavailable\n");}
struct request{char action[32],ssid[256],password[256],peer[256];};
static int parse(char *buf,const char *action,struct request *r){char *p=buf,*line;unsigned seen=0;int section=0;memset(r,0,sizeof(*r));while((line=p)!=NULL){char *e=strchr(p,'\n'),*equal;unsigned bit;char *dest;size_t cap;if(e){*e=0;p=e+1;}else p=NULL;size_t len=strlen(line);if(len&&line[len-1]=='\r')line[--len]=0;if(!len)continue;if(!strcmp(line,"[request]")){if(section)return 0;section=1;continue;}if(!section||(equal=strchr(line,'='))==NULL)return 0;*equal++=0;if(!strcmp(line,"schema")){if(strcmp(equal,"1")||(seen&1))return 0;seen|=1;continue;}if(!strcmp(line,"action")){bit=2;dest=r->action;cap=sizeof(r->action);}else if(!strcmp(line,"ssid64")){bit=4;dest=r->ssid;cap=sizeof(r->ssid);}else if(!strcmp(line,"password64")){bit=8;dest=r->password;cap=sizeof(r->password);}else if(!strcmp(line,"peer64")){bit=16;dest=r->peer;cap=sizeof(r->peer);}else return 0;if((seen&bit)||strlen(equal)>=cap)return 0;seen|=bit;strcpy(dest,equal);}
if((seen&3)!=3||strcmp(action,r->action))return 0;
if(!strcmp(action,"wifi-connect"))return seen==15;
if(!strcmp(action,"bluetooth-pair")||!strcmp(action,"bluetooth-disconnect"))return seen==19;
if(strcmp(action,"status")&&strcmp(action,"wifi-scan")&&strcmp(action,"wifi-disconnect")&&strcmp(action,"wifi-restore")&&strcmp(action,"wifi-forget")&&strcmp(action,"bluetooth-status")&&strcmp(action,"bluetooth-scan"))return 0;
return seen==3;}
static void wipe(void *p, size_t n) { volatile unsigned char *q=p; while(n--) *q++=0; }
static int wifi_values_valid(const unsigned char *ssid, int ns, const unsigned char *password, int np) {
    int i;
    if(ns<1||ns>32||!utf8(ssid,(size_t)ns)||np<0||(np&&(np<8||np>63)))return 0;
    for(i=0;i<np;i++)if(password[i]<32||password[i]>126)return 0;
    return 1;
}
#include "persistence.h"
static int ctrl=-1;static char local_path[sizeof(((struct sockaddr_un*)0)->sun_path)];
static void close_ctrl(void){if(ctrl>=0)close(ctrl);ctrl=-1;if(local_path[0])unlink(local_path);local_path[0]=0;}
static int open_ctrl(void){struct sockaddr_un remote,local;struct stat st;int f;if(lstat(RADIO_LOCAL,&st)||!S_ISDIR(st.st_mode)||st.st_uid!=geteuid()||(st.st_mode&0077))return 0;
memset(&local,0,sizeof(local));memset(&remote,0,sizeof(remote));local.sun_family=remote.sun_family=AF_UNIX;
if(strlen(RADIO_CTRL)>=sizeof(remote.sun_path))return 0;strcpy(remote.sun_path,RADIO_CTRL);
if(snprintf(local_path,sizeof(local_path),"%s/ctl-XXXXXX",RADIO_LOCAL)>=(int)sizeof(local_path))return 0;
f=mkstemp(local_path);if(f<0)return 0;close(f);unlink(local_path);strcpy(local.sun_path,local_path);
ctrl=socket(AF_UNIX,SOCK_DGRAM,0);if(ctrl<0||!set_nonblocking(ctrl)||bind(ctrl,(struct sockaddr*)&local,sizeof(local))||connect(ctrl,(struct sockaddr*)&remote,sizeof(remote))){close_ctrl();return 0;}return 1;}
static int command(const char *cmd, char *out, size_t cap) {
    int64_t start = monotonic_ms(), deadline;
    size_t length = strlen(cmd);
    ssize_t value;
    if (start < 0 || cap < 2) return 0;
    deadline = start + 2000;
    for (;;) {
        if (!within_deadline(deadline)) return 0;
        value = send(ctrl, cmd, length, 0);
        if (value == (ssize_t)length) break;
        if (value < 0 && errno == EINTR) continue;
        if (value < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            if (wait_ready(ctrl, 1, deadline)) continue;
        }
        return 0;
    }
    for (;;) {
        if (!wait_ready(ctrl, 0, deadline) || !within_deadline(deadline)) return 0;
        value = recv(ctrl, out, cap - 1, 0);
        if (value < 0) {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) continue;
            return 0;
        }
        if ((size_t)value == cap - 1) return 0;
        out[value] = 0;
        return 1;
    }
}
static int accepted(const char *cmd){char out[128];return command(cmd,out,sizeof(out))&&!strcmp(out,"OK\n");}
#ifndef RADIO_ROUTE
#define RADIO_ROUTE "/proc/net/route"
#endif
static int unescape_ssid(const char *, unsigned char *);
/* Fixed proc path, finite bytes/lines and deadline. No resolver/config reads. */
static void default_gateway(char *gateway, size_t cap) {
    char data[8193], *line, *next;
    size_t n = 0;
    int fd = open(RADIO_ROUTE, O_RDONLY | O_NONBLOCK);
    int64_t start = monotonic_ms();
    unsigned long best = ~0UL;
    struct in_addr selected;
    int found = 0, ambiguous = 0;
    if (fd < 0) return;
    if (start < 0) { close(fd); return; }
    while (n < sizeof(data) - 1) {
        ssize_t k;
        if (!within_deadline(start + 100)) { close(fd); return; }
        k = read(fd, data + n, sizeof(data) - 1 - n);
        if (!k) break;
        if (k < 0) { if (errno == EINTR) continue; close(fd); return; }
        n += (size_t)k;
    }
    close(fd);
    if (!n || n == sizeof(data) - 1 || memchr(data, 0, n) || data[n-1] != '\n') return;
    data[n] = 0;
    line = strchr(data, '\n');
    if (!line || strncmp(data, "Iface", 5)) return;
    line++;
    while (*line) {
        char iface[16], dest[9], gw[9], flags[9], mask[9], extra;
        unsigned long ref, count, metric, mtu, window, irtt;
        unsigned long d, g, f, m;
        size_t i;
        next = strchr(line, '\n');
        if (!next || (size_t)(next - line) > 511) return;
        *next++ = 0;
        if (sscanf(line, "%15s %8s %8s %8s %lu %lu %lu %8s %lu %lu %lu %c",
                   iface, dest, gw, flags, &ref, &count, &metric, mask,
                   &mtu, &window, &irtt, &extra) != 11) return;
        if (strlen(dest)!=8 || strlen(gw)!=8 || strlen(mask)!=8 || !strlen(flags)) return;
        for (i=0; dest[i]; i++) if (!isxdigit((unsigned char)dest[i])) return;
        for (i=0; gw[i]; i++) if (!isxdigit((unsigned char)gw[i])) return;
        for (i=0; flags[i]; i++) if (!isxdigit((unsigned char)flags[i])) return;
        for (i=0; mask[i]; i++) if (!isxdigit((unsigned char)mask[i])) return;
        d=strtoul(dest,NULL,16); g=strtoul(gw,NULL,16);
        f=strtoul(flags,NULL,16); m=strtoul(mask,NULL,16);
        if (!strcmp(iface,"wlan0") && !d && !m && g && (f&3)==3 && !(f&0x200)) {
            /* proc route hex is little-endian byte order, independent of host. */
            unsigned char bytes[4]={(unsigned char)g,(unsigned char)(g>>8),
                                    (unsigned char)(g>>16),(unsigned char)(g>>24)};
            struct in_addr a;
            memcpy(&a,bytes,4);
            if (!found || metric < best) { selected=a; best=metric; found=1; ambiguous=0; }
            else if (metric==best && a.s_addr!=selected.s_addr) ambiguous=1;
        }
        line=next;
    }
    if (found && !ambiguous) inet_ntop(AF_INET,&selected,gateway,cap);
}
static void kernel_status(char *ip, char *netmask, char *mac, const char **state) {
#ifdef __linux__
    int fd=socket(AF_INET,SOCK_DGRAM,0);
    struct ifreq ifr;
    if (fd<0) return;
    memset(&ifr,0,sizeof(ifr)); strcpy(ifr.ifr_name,"wlan0");
    if (!ioctl(fd,SIOCGIFFLAGS,&ifr)) *state=(ifr.ifr_flags & IFF_UP)?"up":"down";
    memset(&ifr,0,sizeof(ifr)); strcpy(ifr.ifr_name,"wlan0");
    if (!ioctl(fd,SIOCGIFADDR,&ifr) && ifr.ifr_addr.sa_family==AF_INET) {
        struct sockaddr_in *a=(struct sockaddr_in*)&ifr.ifr_addr;
        if (a->sin_addr.s_addr) inet_ntop(AF_INET,&a->sin_addr,ip,INET_ADDRSTRLEN);
    }
    memset(&ifr,0,sizeof(ifr)); strcpy(ifr.ifr_name,"wlan0");
    if (!ioctl(fd,SIOCGIFNETMASK,&ifr) && ifr.ifr_netmask.sa_family==AF_INET) {
        struct sockaddr_in *a=(struct sockaddr_in*)&ifr.ifr_netmask;
        inet_ntop(AF_INET,&a->sin_addr,netmask,INET_ADDRSTRLEN);
    }
    memset(&ifr,0,sizeof(ifr)); strcpy(ifr.ifr_name,"wlan0");
    if (!ioctl(fd,SIOCGIFHWADDR,&ifr) && ifr.ifr_hwaddr.sa_family==1) {
        const unsigned char *a=(const unsigned char *)ifr.ifr_hwaddr.sa_data;
        snprintf(mac,18,"%02x:%02x:%02x:%02x:%02x:%02x",a[0],a[1],a[2],a[3],a[4],a[5]);
    }
    close(fd);
#else
    (void)ip; (void)netmask; (void)mac; (void)state;
#endif
}
static void wifi_status(void) {
    char out[4096],state[64]="UNKNOWN",ip[INET_ADDRSTRLEN]="",line[768];
    char netmask[INET_ADDRSTRLEN]="",mac[18]="",gateway[INET_ADDRSTRLEN]="",ssid64[48]="";
    unsigned char ssid[33];
    const char *interface_state="unknown";
    char *p;
    int ns=-1, seen_ssid=0, seen_state=0;
    if (!command("STATUS",out,sizeof(out))) { reply(0,"supplicant_timeout","Supplicant did not answer"); return; }
    p=strtok(out,"\n");
    while (p) {
        if (!strncmp(p,"wpa_state=",10)) {
            size_t i; const char *v=p+10;
            seen_state++;
            for (i=0;v[i];i++) if (!((v[i]>='A'&&v[i]<='Z')||v[i]=='_')) break;
            if (i && !v[i] && i<sizeof(state)) strcpy(state,v);
        } else if (!strncmp(p,"ssid=",5)) {
            seen_ssid++;
            ns=unescape_ssid(p+5,ssid);
        }
        p=strtok(NULL,"\n");
    }
    if (seen_state!=1) strcpy(state,"UNKNOWN");
    if (!strcmp(state,"COMPLETED") && seen_ssid==1 && ns>0) encode(ssid,(size_t)ns,ssid64);
    /* Association and address are independent: only the kernel supplies IP. */
    kernel_status(ip,netmask,mac,&interface_state);
    default_gateway(gateway,sizeof(gateway));
    reply(1,"status","Runtime status; application reachability is unverified");
    snprintf(line,sizeof(line),"[status]\nwifi_state=%s\nipv4=%s\naddress_state=%s\napplication_reachable=unverified\nbt_state=unverified\nwifi_ssid64=%s\ninterface_name=wlan0\ninterface_state=%s\nnetmask=%s\nmac=%s\ngateway=%s\n",
             state,ip,ip[0]?"assigned":"none",ssid64,interface_state,netmask,mac,gateway);
    append(line);
}
static int unescape_ssid(const char *s,unsigned char *out){size_t i=0;while(*s){unsigned char c=(unsigned char)*s++;if(c=='\\'){if(*s=='x'&&isxdigit((unsigned char)s[1])&&isxdigit((unsigned char)s[2])){char h[3]={s[1],s[2],0};c=(unsigned char)strtoul(h,NULL,16);s+=3;}else if(*s=='\\'||*s=='"')c=(unsigned char)*s++;else if(*s=='n'){c='\n';s++;}else if(*s=='r'){c='\r';s++;}else if(*s=='t'){c='\t';s++;}else if(*s=='e'){c=27;s++;}else return -1;}if(i==32||!c)return -1;out[i++]=c;}return utf8(out,i)?(int)i:-1;}
/* Preserve authentication families before the UI groups same-name APs.
 * This client supports open and WPA personal only; ESS alone must not turn
 * protected EAP/SAE/OWE networks into an open-network choice. */
static const char *wifi_security(const char *flags){
    if(strstr(flags,"EAP"))return "enterprise";
    if(strstr(flags,"PSK"))return strstr(flags,"WPA2")?"wpa2":strstr(flags,"WPA")?"wpa":"unknown";
    if(strstr(flags,"SAE"))return "wpa3";
    if(strstr(flags,"WEP"))return "wep";
    if(strstr(flags,"WPA")||strstr(flags,"RSN")||strstr(flags,"OWE")||strstr(flags,"PRIVACY"))return "unsupported";
    return strstr(flags,"ESS")?"open":"unknown";
}
static void wifi_scan(void){char out[32768],*p,*line;int count=0;if(!accepted("SCAN")){reply(0,"supplicant_rejected","Scan request rejected");return;}if(!command("SCAN_RESULTS",out,sizeof(out))){reply(0,"supplicant_timeout","Scan results unavailable");return;}reply(1,"scan_requested","Results may be cached; poll again for updates");append("[status]\nscan_freshness=unverified\n");p=strchr(out,'\n');if(!p)return;p++;
while(p&&*p&&count<64){char *tab[4],*next=strchr(p,'\n');int i,n;unsigned char ssid[33];char enc[48],row[256],*end;long signal;if(next)*next++=0;line=p;for(i=0;i<4;i++){tab[i]=strchr(line,'\t');if(!tab[i])break;*tab[i]++=0;line=tab[i];}if(i==4&&(n=unescape_ssid(tab[3],ssid))>=0){signal=strtol(tab[1],&end,10);if(*end||signal>0||signal< -200){p=next;continue;}encode(ssid,(size_t)n,enc);const char *security=wifi_security(tab[2]);snprintf(row,sizeof(row),"[wifi%d]\nssid64=%s\nsignal=%ld\nsecurity=%s\n",count++,enc,signal,security);append(row);}p=next;}}
static void wifi_connect(const unsigned char *ssid,int ns,const unsigned char *password,int np,struct saved_wifi *saved,int persist){char out[128],cmd[512],hex[65],quote[130];int id,i,j;char *end;if(!command("ADD_NETWORK",out,sizeof(out))){reply(0,"supplicant_timeout","Cannot allocate network");return;}long value=strtol(out,&end,10);if(end==out||strcmp(end,"\n")||value<0||value>65535){reply(0,"supplicant_rejected","Cannot allocate network");return;}id=(int)value;for(i=0;i<ns;i++)snprintf(hex+2*i,3,"%02x",ssid[i]);snprintf(cmd,sizeof(cmd),"SET_NETWORK %d ssid %s",id,hex);if(!accepted(cmd))goto failed;
if(np){j=0;for(i=0;i<np;i++){if(password[i]=='"'||password[i]=='\\')quote[j++]='\\';quote[j++]=(char)password[i];}quote[j]=0;snprintf(cmd,sizeof(cmd),"SET_NETWORK %d psk \"%s\"",id,quote);if(!accepted(cmd))goto failed;}
snprintf(cmd,sizeof(cmd),"SET_NETWORK %d key_mgmt %s",id,np?"WPA-PSK":"NONE");if(!accepted(cmd))goto failed;snprintf(cmd,sizeof(cmd),"SELECT_NETWORK %d",id);if(!accepted(cmd))goto failed;wipe(cmd,sizeof(cmd));wipe(quote,sizeof(quote));
if(persist&&saved->enabled){int stored=saved_store(saved,ssid,ns,password,np);if(stored<=0){reply(0,stored<0?"persistence_uncertain":"persistence_failed","Network selected; configuration save failed or durability is uncertain. Poll actual connection status");return;}}
reply(1,"association_requested","Poll status for authentication and address; application is unverified");
if(saved->enabled)append("[status]\nsaved_network=pending_authentication\n");return;
failed:wipe(cmd,sizeof(cmd));wipe(quote,sizeof(quote));snprintf(cmd,sizeof(cmd),"REMOVE_NETWORK %d",id);(void)accepted(cmd);reply(0,"supplicant_rejected","Network setup rejected; new network removed if responsive");}
static int mac_valid(const unsigned char *s,int n){int i;if(n!=17)return 0;for(i=0;i<n;i++)if(i%3==2?s[i]!=':':!isxdigit(s[i]))return 0;return 1;}
/* All child arguments are fixed except a validated Bluetooth MAC. Output is bounded and never echoed raw. */
static int bt_run(const char *op,const char *peer,char *out,size_t cap){int pipes[2],status=0;pid_t pid;size_t n=0;int64_t deadline;struct timespec ts;int done=0;if(pipe(pipes))return 0;pid=fork();if(pid<0){close(pipes[0]);close(pipes[1]);return 0;}if(!pid){int null=open("/dev/null",O_RDWR);dup2(pipes[1],1);dup2(null,0);dup2(null,2);close(pipes[0]);close(pipes[1]);if(null>2)close(null);setenv("LC_ALL","C",1);setenv("DBUS_SYSTEM_BUS_ADDRESS","unix:path=/tmp/pandanote-connectivity/dbus/system_bus_socket",1);if(peer)execl(RADIO_BTCTL,RADIO_BTCTL,"--timeout","4",op,peer,(char*)NULL);else execl(RADIO_BTCTL,RADIO_BTCTL,"--timeout","4",op,(char*)NULL);_exit(127);}close(pipes[1]);fcntl(pipes[0],F_SETFL,O_NONBLOCK);clock_gettime(CLOCK_MONOTONIC,&ts);deadline=(int64_t)ts.tv_sec*1000+ts.tv_nsec/1000000+5500;
while(!done){ssize_t k=read(pipes[0],out+n,cap-1-n);if(k>0){n+=(size_t)k;if(n==cap-1)break;}pid_t w=waitpid(pid,&status,WNOHANG);if(w==pid){done=1;continue;}if(w<0)break;clock_gettime(CLOCK_MONOTONIC,&ts);if((int64_t)ts.tv_sec*1000+ts.tv_nsec/1000000>=deadline)break;struct timespec delay={0,10000000};nanosleep(&delay,NULL);}
if(!done){kill(pid,SIGKILL);while(waitpid(pid,&status,0)<0&&errno==EINTR){}}else{ssize_t k;while(n<cap-1&&(k=read(pipes[0],out+n,cap-1-n))>0)n+=(size_t)k;}close(pipes[0]);out[n]=0;return done&&WIFEXITED(status)&&WEXITSTATUS(status)==0;}
static void bluetooth(const char *action,const unsigned char *peer){char out[16384];if(!strcmp(action,"bluetooth-pair")){reply(0,"pairing_agent_required","iPhone pairing requires reviewed agent and usable service; stock is classic-only");bt_limit();return;}
/* Only controller-prepared volatile BlueZ is permitted. Do not attach to a public bus. */
struct stat st;if(lstat("/tmp/pandanote-connectivity/bluez-ready",&st)||!S_ISREG(st.st_mode)||st.st_uid!=geteuid()||(st.st_mode&0077)){reply(0,"bluetooth_unavailable","Owned volatile BlueZ not initialized");bt_limit();return;}
if(!strcmp(action,"bluetooth-scan")){reply(0,"discovery_agent_required","Scoped discovery ownership is not configured");bt_limit();return;}
int ok=bt_run(!strcmp(action,"bluetooth-disconnect")?"disconnect":"show",!strcmp(action,"bluetooth-disconnect")?(const char*)peer:NULL,out,sizeof(out));if(!ok){reply(0,"bluetooth_unavailable","Bluetooth tool unavailable or timed out");bt_limit();return;}if(!strcmp(action,"bluetooth-disconnect")){reply(strstr(out,"Successful disconnected")!=NULL,"disconnect_requested","Poll actual peer state to confirm disconnection");return;}reply(1,"bluetooth_status","Controller status; BLE and iPhone services unverified");append("[status]\nbt_state=");append(strstr(out,"Powered: yes")?"powered\n":"off\n");append("ble_capability=unverified\niphone_service=unavailable\nfile_transfer=unavailable\n");}
int main(int argc,char **argv) {
    char input[LIMIT+2]; struct request r; struct saved_wifi saved;
    size_t n; unsigned char ssid[65],password[65],peer[65];
    int ns=0,np=0,npeer=0,store_state;
    ssize_t got;
    memset(&saved,0,sizeof(saved));saved.directory=saved.lock=-1;
    umask(0077);setvbuf(stdout,NULL,_IONBF,0);signal(SIGPIPE,SIG_IGN);
    got=read_request(input,sizeof(input)-1);
    if(got<0)goto invalid;
    n=(size_t)got;input[n]=0;
    if(argc!=2||n>LIMIT||memchr(input,0,n)||!parse(input,argc==2?argv[1]:"",&r))goto invalid;
    if(!strcmp(r.action,"wifi-connect")) {
        ns=decode(r.ssid,ssid,64);np=decode(r.password,password,64);
        if(!wifi_values_valid(ssid,ns,password,np))goto invalid;
    }
    if(!strcmp(r.action,"bluetooth-pair")||!strcmp(r.action,"bluetooth-disconnect")) {
        npeer=decode(r.peer,peer,64);if(!mac_valid(peer,npeer))goto invalid;
    }
    wipe(input,sizeof(input));wipe(r.password,sizeof(r.password));
    if(!strncmp(r.action,"bluetooth-",10)){bluetooth(r.action,peer);goto finish;}
    if(!strcmp(r.action,"wifi-connect")||!strcmp(r.action,"wifi-restore")||!strcmp(r.action,"wifi-forget")) {
        store_state=saved_open(&saved);
        if(store_state<0){reply(0,"persistence_unavailable","Saved network location is unsafe, busy or not the writable p9 profile");goto finish;}
        if(strcmp(r.action,"wifi-connect")&&!store_state){reply(0,"persistence_disabled","Writable-profile network persistence is not enabled");goto finish;}
        if(!strcmp(r.action,"wifi-forget")) {
            int forgotten=saved_update(&saved,NULL,0,1);
            reply(forgotten==1,forgotten==1?"saved_network_forgotten":forgotten<0?"persistence_uncertain":"persistence_failed",
                  forgotten==1?"Saved configuration removed; the active connection is unchanged":"Saved configuration removal failed or durability is uncertain");
            goto finish;
        }
        if(!strcmp(r.action,"wifi-restore")&&(!saved.present||!decode_saved(saved.previous,saved.bytes,ssid,&ns,password,&np))) {
            reply(0,"saved_network_absent","No valid saved network request is available");goto finish;
        }
    }
    if(!open_ctrl()){reply(0,"wifi_unavailable","Owned supplicant runtime unavailable");goto finish;}
    if(!strcmp(r.action,"status"))wifi_status();
    else if(!strcmp(r.action,"wifi-scan"))wifi_scan();
    else if(!strcmp(r.action,"wifi-connect")||!strcmp(r.action,"wifi-restore"))wifi_connect(ssid,ns,password,np,&saved,!strcmp(r.action,"wifi-connect"));
    else if(!strcmp(r.action,"wifi-disconnect")) {
        int ok=accepted("DISCONNECT");reply(ok,ok?"disconnected":"supplicant_rejected",ok?"Supplicant disconnected":"Disconnect request rejected");
    }
    goto finish;
invalid:
    reply(0,"invalid_request","Malformed or unsupported request");
finish:
    close_ctrl();saved_close(&saved);wipe(password,sizeof(password));wipe(ssid,sizeof(ssid));wipe(peer,sizeof(peer));wipe(input,sizeof(input));wipe(&r,sizeof(r));
    fputs(result,stdout);return strstr(result,"\nok=1\n")?0:1;
}
