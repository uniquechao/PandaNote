#include "capability.h"
static unsigned le16(const unsigned char *p) { return p[0]|((unsigned)p[1]<<8); }
static uint32_t le32(const unsigned char *p) { return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24); }
int bt_parse_mgmt(const unsigned char *p,size_t n,struct bt_caps *c) {
    uint32_t supported,current;
    if (!p || !c || n<6) return -1;
    if (le16(p)!=1 || le16(p+2)!=0) return 0;
    if (n<9 || le16(p+4)!=n-6) return -1;
    if (le16(p+6)!=4) return 0;
    if (p[8] || n!=289) return -1;
    supported=le32(p+18); current=le32(p+22);
    c->hci_version=p[15]; c->manufacturer=le16(p+16);
    c->le_supported=!!(supported&0x200); c->le_enabled=!!(current&0x200);
    c->advertising_supported=!!(supported&0x400); c->mgmt_valid=1;
    return 1;
}
int bt_parse_hci(const unsigned char *p,size_t n,uint16_t op,struct bt_caps *c) {
    if (!p || !c || n<3) return -1;
    if (p[0]!=4) return 0;
    if ((size_t)p[2]+3!=n) return -1;
    /* Command Status for our exact opcode: nonzero is terminal, success waits
     * for Command Complete. Other controller activity is ignored. */
    if (p[1]==15) {
        if(n!=7) return -1;
        if(le16(p+5)!=op) return 0;
        return p[3]?-1:0;
    }
    if (p[1]!=14) return 0;
    if (n<7) return -1;
    if (le16(p+4)!=op) return 0;
    if (p[6] || n!=15) return -1;
    switch(op) {
    case 0x1001:
        c->hci_version=p[7]; c->revision=le16(p+8); c->manufacturer=le16(p+11);
        c->subversion=le16(p+13); c->version_valid=1; break;
    case 0x1003: c->controller_le=!!(p[11]&0x40); c->features_valid=1; break;
    case 0x201c:
        c->connectable_advertising=!!(p[7]&4); c->peripheral_role=!!(p[8]&1);
        c->states_valid=1; break;
    default: return -1;
    }
    return 1;
}
