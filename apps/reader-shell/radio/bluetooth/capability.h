#ifndef PANDANOTE_BT_CAPABILITY_H
#define PANDANOTE_BT_CAPABILITY_H
#include <stddef.h>
#include <stdint.h>
struct bt_caps {
    int mgmt_valid,features_valid,states_valid,version_valid;
    int le_supported,le_enabled,advertising_supported,controller_le;
    int connectable_advertising,peripheral_role;
    unsigned hci_version,manufacturer,revision,subversion;
};
/* Return 1 accepted, 0 unrelated event, -1 invalid/failure. No I/O. */
int bt_parse_mgmt(const unsigned char *,size_t,struct bt_caps *);
int bt_parse_hci(const unsigned char *,size_t,uint16_t,struct bt_caps *);
#endif
