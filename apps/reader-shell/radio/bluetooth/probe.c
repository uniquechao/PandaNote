/* Controller-invoked readonly discovery. Never starts UART, loads firmware,
 * powers, resets, scans, pairs or advertises. No addresses/names are printed. */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/socket.h>
#include "capability.h"
#include "probe_io.h"
#ifdef __linux__
#define BT_FAMILY 31
struct bt_sockaddr { sa_family_t family; unsigned short index,channel; };
struct bt_filter { unsigned type_mask,event_mask[2]; unsigned short opcode; };
struct parse_context { struct bt_caps *caps;unsigned short opcode; };
static int parse_mgmt(const unsigned char *p,size_t n,void *ctx) {return bt_parse_mgmt(p,n,ctx);}
static int parse_hci(const unsigned char *p,size_t n,void *arg) {struct parse_context *ctx=arg;return bt_parse_hci(p,n,ctx->opcode,ctx->caps);}
static int open_hci(unsigned short index,unsigned short channel) {
    int fd,flags;struct bt_sockaddr address;
    fd=socket(BT_FAMILY,SOCK_RAW,1);if(fd<0)return -1;
    flags=fcntl(fd,F_GETFL);
    if(flags<0||fcntl(fd,F_SETFL,flags|O_NONBLOCK)<0||fcntl(fd,F_SETFD,FD_CLOEXEC)<0){close(fd);return -1;}
    memset(&address,0,sizeof(address));address.family=BT_FAMILY;address.index=index;address.channel=channel;
    if(bind(fd,(struct sockaddr *)&address,sizeof(address))<0){close(fd);return -1;}return fd;
}
static int query(int fd,unsigned short opcode,struct bt_caps *caps,int64_t deadline) {
    unsigned char request[4]={1,0,0,0};struct parse_context ctx={caps,opcode};
    struct bt_filter filter;
    /* Only the three fixed read commands are representable through this path. */
    if(opcode!=0x1001&&opcode!=0x1003&&opcode!=0x201c)return -1;
    request[1]=opcode&255;request[2]=opcode>>8;
    memset(&filter,0,sizeof(filter));filter.type_mask=1U<<4;
    filter.event_mask[0]=(1U<<14)|(1U<<15);filter.opcode=opcode;
    /* Kernel target is little-endian MIPS; opcode filter is little-endian. */
    if(setsockopt(fd,0,2,&filter,sizeof(filter))<0)return -1;
    return bt_exchange(fd,request,sizeof(request),deadline,parse_hci,&ctx);
}
#endif
int main(int argc,char **argv) {
    struct bt_caps c;int mgmt=-1,raw=-1,m=-1,v=-1,f=-1,s=-1;
    if(argc!=2||strcmp(argv[1],"--read-only-hci0")){
        fputs("usage: pandanote-bt-probe --read-only-hci0\nRequires controller-initialized hci0; no initialization performed.\n",stderr);return 2;
    }
    memset(&c,0,sizeof(c));
#ifdef __linux__
    /* One 3-second deadline covers all commands. The management request is
     * Read Controller Information opcode4/index0/no parameters. */
    int64_t deadline=bt_deadline(3000);
    const unsigned char info[]={4,0,0,0,0,0};
    mgmt=open_hci(0xffff,3);
    if(mgmt>=0){m=bt_exchange(mgmt,info,sizeof(info),deadline,parse_mgmt,&c);close(mgmt);}
    raw=open_hci(0,0);
    if(raw>=0){
        v=query(raw,0x1001,&c,deadline);
        f=query(raw,0x1003,&c,deadline);
        if(f==1&&c.controller_le)s=query(raw,0x201c,&c,deadline);
        close(raw);
    }
#else
    (void)mgmt;(void)raw;
#endif
    printf("[probe]\nschema=1\nreadonly=1\nindex=0\nmgmt_complete=%d\nversion_complete=%d\nfeatures_complete=%d\nstates_complete=%d\n",m==1,v==1,f==1,s==1);
    if(c.mgmt_valid)printf("kernel_le_supported=%d\nkernel_le_enabled=%d\nkernel_advertising_supported=%d\n",c.le_supported,c.le_enabled,c.advertising_supported);
    if(c.version_valid)printf("hci_version=%u\nmanufacturer=%u\nrevision=%u\nsubversion=%u\n",c.hci_version,c.manufacturer,c.revision,c.subversion);
    if(c.features_valid)printf("controller_le=%d\n",c.controller_le);
    if(c.states_valid)printf("connectable_advertising=%d\nperipheral_role=%d\n",c.connectable_advertising,c.peripheral_role);
    puts("phone_service=unverified\npairing=unverified\nfile_transfer=unverified");
    return m==1&&v==1&&f==1&&(!c.controller_le||s==1)?0:1;
}
