/* Behavioral fixtures catch wrong wire offsets, truncated replies, index/opcode
 * confusion, status errors, and conflating kernel settings with controller LE. */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include "../capability.h"
static int failures;
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x); failures++; } } while(0)
int main(void) {
    struct bt_caps c; unsigned char p[289]={1,0,0,0,27,1,4,0,0};
    memset(&c,0,sizeof(c));
    /* Complete event, index0, payload 283: command4/status0 then 280-byte info. */
    p[15]=9; p[16]=0x34; p[17]=0x12; p[19]=6; p[23]=2;
    CHECK(bt_parse_mgmt(p,sizeof(p),&c)==1);
    CHECK(c.mgmt_valid && c.le_supported && c.advertising_supported && c.le_enabled);
    CHECK(c.manufacturer==0x1234 && c.hci_version==9);
    CHECK(bt_parse_mgmt(p,288,&c)==-1);
    p[2]=1; CHECK(bt_parse_mgmt(p,sizeof(p),&c)==0); p[2]=0;
    p[6]=5; CHECK(bt_parse_mgmt(p,sizeof(p),&c)==0); p[6]=4;
    p[8]=0x11; CHECK(bt_parse_mgmt(p,sizeof(p),&c)==-1); p[8]=0;
    p[19]=0; CHECK(bt_parse_mgmt(p,sizeof(p),&c)==1 && !c.le_supported);
    unsigned char f[]={4,14,12,1,3,16,0,0,0,0,0,0x40,0,0,0};
    CHECK(bt_parse_hci(f,sizeof(f),0x1003,&c)==1 && c.features_valid && c.controller_le);
    f[11]=0; CHECK(bt_parse_hci(f,sizeof(f),0x1003,&c)==1 && !c.controller_le);
    CHECK(bt_parse_hci(f,14,0x1003,&c)==-1);
    CHECK(bt_parse_hci(f,sizeof(f),0x1001,&c)==0);
    f[6]=1; CHECK(bt_parse_hci(f,sizeof(f),0x1003,&c)==-1);
    unsigned char s[]={4,14,12,1,28,32,0,4,1,0,0,0,0,0,0};
    CHECK(bt_parse_hci(s,sizeof(s),0x201c,&c)==1 && c.states_valid && c.connectable_advertising && c.peripheral_role);
    s[8]=0; CHECK(bt_parse_hci(s,sizeof(s),0x201c,&c)==1 && !c.peripheral_role);
    unsigned char v[]={4,14,12,1,1,16,0,9,0x78,0x56,9,0x34,0x12,0xbc,0x9a};
    CHECK(bt_parse_hci(v,sizeof(v),0x1001,&c)==1 && c.version_valid && c.manufacturer==0x1234 && c.revision==0x5678 && c.subversion==0x9abc);
    printf("probe fixture failures=%d\n",failures); return failures?1:0;
}
