#!/bin/sh
# Controller-only candidate. Never run factory rcS, aic8800.sh or startup chains.
# This script starts only Wi-Fi. Bluetooth shares GPIOs and needs its own review.
radio_board_supported() {
    radio_board=$(sed -n 's/^system type[[:space:]]*:[[:space:]]*//p' "$CPUINFO_FILE")
    case "$radio_board" in epd86s2_pro|epd86s2e) return 0;; *) return 1;; esac
}
radio_check_memory() {
    radio_free=$(sed -n 's/^MemFree:[[:space:]]*\([0-9]*\) kB$/\1/p' /proc/meminfo)
    radio_cma=$(sed -n 's/^CmaFree:[[:space:]]*\([0-9]*\) kB$/\1/p' /proc/meminfo)
    case "$radio_free:$radio_cma" in *[!0-9:]*|:*) return 1;; esac
    [ -n "$radio_cma" ] || radio_cma=0
    # Conservative launch gate, not a measured sufficiency guarantee. Driver RX
    # buffers, firmware allocations and native app headroom still require samples.
    [ $((radio_free-radio_cma)) -ge 8192 ]
}
radio_session_tools_ready() {
    # Never inherit the controller's legacy ADB PTY. Fail before module loading
    # if the acquired BusyBox cannot create an independent child session.
    /bin/busybox --list | awk '$0 == "setsid" { found=1 } END { exit !found }'
}
radio_guard_ready() {
    [ "$(id -u)" = 0 ] || return 1
    radio_session_tools_ready || return 1
    [ -f /tmp/pandanote-network-profile-wlan0-v1 ] && [ ! -L /tmp/pandanote-network-profile-wlan0-v1 ] || return 1
    [ "$(cat /tmp/pandanote-network-profile-wlan0-v1)" = 'wlan0-only-listeners-loopback-storage-ro-v1' ] || return 1
    # Current global sdhci_send_command filter denies SDIO CMD52/53 too.
    # No marker is supplied by this worker; a separately reviewed host-specific
    # guard must establish this proof without loosening the eMMC filter.
    [ -f /tmp/pandanote-sdio-host1-guard-v1 ] && [ ! -L /tmp/pandanote-sdio-host1-guard-v1 ] || return 1
    [ "$(cat /tmp/pandanote-sdio-host1-guard-v1)" = 'msc1-only-sdio-cmd52-cmd53-emmc-filter-unchanged-v1' ] || return 1
    radio_check_storage && radio_check_network && radio_check_memory || return 1
    # Refuse a second supplicant or DHCP client, even if not ours.
    if pidof wpa_supplicant udhcpc >/dev/null 2>&1; then return 1; fi
}
radio_verify_inputs() {
    # Complete factory firmware tree is pinned, including revision variants and
    # configuration files. Reject extra entries/links before any runtime/module
    # side effects; fixed BSP path below is identical to RADIO_FIRMWARE.
    (cd "$RADIO_SCRIPTS" && sha256sum -c radio-stage-inputs.sha256 >/dev/null 2>&1) || return 1
    sha256sum -c "$RADIO_SCRIPTS/radio-factory-inputs.sha256" >/dev/null 2>&1 || return 1
    [ -d "$RADIO_FIRMWARE" ] && [ ! -L "$RADIO_FIRMWARE" ] || return 1
    radio_links=$(find "$RADIO_FIRMWARE" -type l -print) || return 1
    [ -z "$radio_links" ] || return 1
    radio_actual=$(find "$RADIO_FIRMWARE" -type f -print) || return 1
    radio_actual=$(printf '%s\n' "$radio_actual" | LC_ALL=C sort) || return 1
    radio_expected=$(awk -v prefix="$RADIO_FIRMWARE/" 'index($2,prefix)==1 { print $2 }' "$RADIO_SCRIPTS/radio-factory-inputs.sha256" | LC_ALL=C sort) || return 1
    [ -n "$radio_expected" ] && [ "$radio_actual" = "$radio_expected" ]
}
radio_prepare_runtime() {
    [ ! -e "$RADIO_RUNTIME" ] && [ ! -L "$RADIO_RUNTIME" ] || return 1
    mkdir -m 700 "$RADIO_RUNTIME" || return 1
    mkdir -m 700 "$RADIO_RUNTIME/wpa" || return 1
    cp "$RADIO_SCRIPTS/radio_dhcp.sh" "$RADIO_RUNTIME/dhcp.sh" || return 1
    cp "$RADIO_SCRIPTS/pandanote-radio.mipsel" "$RADIO_RUNTIME/pandanote-radio.mipsel" || return 1
    chmod 700 "$RADIO_RUNTIME/dhcp.sh" "$RADIO_RUNTIME/pandanote-radio.mipsel" || return 1
    printf 'ctrl_interface=%s/wpa\nupdate_config=0\n' "$RADIO_RUNTIME" > "$RADIO_RUNTIME/wpa.conf" || return 1
    : > "$RADIO_RUNTIME/resolv.conf"
}
radio_module_present() {
    while read -r radio_name radio_rest; do [ "$radio_name" = "$1" ] && return 0; done < "$MODULES_FILE"
    return 1
}
radio_load_clock() {
    # Audited stock provider: GPIO151/PE23 is requested during init; zero avoids
    # initial mux switching. No factory scripts, unloads or unrelated GPIOs.
    radio_module_present utils || return 1
    if ! radio_module_present soc_utils; then
        insmod /module_driver/soc_utils.ko rtc32k_init_on=0 || return 1
    fi
    radio_module_present soc_utils || return 1
    [ "$(cat "${SYS_MODULE_BASE:-/sys/module}/soc_utils/parameters/rtc32k_init_on")" = 0 ] || return 1
    # Vendor init returns success even if gpio_request fails. Fail closed on its
    # diagnostic, and demand both exports from this provider rather than relying
    # on insmod status or accepting an unrelated symbol provider.
    radio_clock_log=$(dmesg) || return 1
    case "$radio_clock_log" in
        *'request rtc32k gpio fail!'*|*'rtc32k is not init ok'*) return 1;;
    esac
    awk '$2 == "T" && $4 == "[soc_utils]" {
        if ($3 == "ingenic_rtc32k_enable") enabled++
        if ($3 == "ingenic_rtc32k_disable") disabled++
    } END { exit !(enabled == 1 && disabled == 1) }' "$KALLSYMS_FILE"
}
radio_load_sdio() {
    # Existing utils is the sole modinfo dependency. Never load a utility chain.
    radio_module_present utils || return 1
    if ! radio_module_present soc_msc; then
        insmod /module_driver/soc_msc.ko \
        wifi_power_on=-1 \
        wifi_power_on_level=0 \
        wifi_reg_on=-1 \
        wifi_reg_on_level=0 \
            msc0_is_enable=0 \
                msc0_cd_method=-1 \
                msc0_bus_width=0 \
                msc0_speed=-1 \
                msc0_max_frequency=0 \
                msc0_cap_power_off_card=0 \
                msc0_cap_mmc_hw_reset=0 \
                msc0_cap_sdio_irq=0 \
                msc0_full_pwr_cycle=0 \
                msc0_keep_power_in_suspend=0 \
                msc0_enable_sdio_wakeup=0 \
                msc0_dsr=0 \
                msc0_pio_mode=0 \
                msc0_enable_autocmd12=0 \
                msc0_enable_cpm_rx_tuning=0 \
                msc0_enable_cpm_tx_tuning=0 \
                msc0_sdio_clk=0 \
                msc0_rst=-1 msc0_rst_enable_level=-1 \
                msc0_wp=-1 msc0_wp_enable_level=-1 \
                msc0_pwr=-1 msc0_pwr_enable_level=-1 \
                msc0_cd=-1 msc0_cd_enable_level=-1 \
                msc0_sdr=-1 msc0_sdr_enable_level=-1 \
            msc1_is_enable=1 \
                msc1_cd_method=cd-internal \
                msc1_bus_width=4 \
                msc1_speed=sdio \
                msc1_max_frequency=100000000 \
                msc1_cap_power_off_card=0 \
                msc1_cap_mmc_hw_reset=0 \
                msc1_cap_sdio_irq=y \
                msc1_full_pwr_cycle=y \
                msc1_keep_power_in_suspend=y \
                msc1_enable_sdio_wakeup=y \
                msc1_dsr=0x404 \
                msc1_pio_mode=0 \
                msc1_enable_autocmd12=0 \
                msc1_enable_cpm_rx_tuning=0 \
                msc1_enable_cpm_tx_tuning=0 \
                msc1_sdio_clk=y \
                msc1_rst=-1 msc1_rst_enable_level=-1 \
                msc1_wp=-1 msc1_wp_enable_level=-1 \
                msc1_pwr=-1 msc1_pwr_enable_level=-1 \
                msc1_cd=-1 msc1_cd_enable_level=-1 \
                msc1_sdr=-1 msc1_sdr_enable_level=-1 \
            msc2_is_enable=0 \
                msc2_cd_method=-1 \
                msc2_bus_width=0 \
                msc2_speed=-1 \
                msc2_max_frequency=0 \
                msc2_cap_power_off_card=0 \
                msc2_cap_mmc_hw_reset=0 \
                msc2_cap_sdio_irq=0 \
                msc2_full_pwr_cycle=0 \
                msc2_keep_power_in_suspend=0 \
                msc2_enable_sdio_wakeup=0 \
                msc2_dsr=0 \
                msc2_pio_mode=0 \
                msc2_enable_autocmd12=0 \
                msc2_enable_cpm_rx_tuning=0 \
                msc2_enable_cpm_tx_tuning=0 \
                msc2_sdio_clk=0 \
                msc2_rst=-1 msc2_rst_enable_level=-1 \
                msc2_wp=-1 msc2_wp_enable_level=-1 \
                msc2_pwr=-1 msc2_pwr_enable_level=-1 \
                msc2_cd=-1 msc2_cd_enable_level=-1 \
                msc2_sdr=-1 msc2_sdr_enable_level=-1 \
            || return 1
    fi
}
radio_load_wifi() {
    if ! radio_module_present aic8800_bsp; then
        insmod /module_driver/aic8800_bsp.ko aic_fw_path=/module_driver/firmware \
            wlan_mmc_num=1 gpio_bt_wifi_power=PB20 gpio_wlan_reg_on=PB19 \
            gpio_wlan_wake_host=PE24 gpio_bt_rst_n=-1 gpio_bt_reg_on=PA07 \
            gpio_host_wake_bt=PD31 gpio_bt_wake_host=PD30 gpio_bt_uart_rts=-1 || return 1
    fi
    if ! radio_module_present aic8800_fdrv; then insmod /module_driver/aic8800_fdrv.ko || return 1; fi
    # Do not rename arbitrary interfaces or reset GPIOs. Require known wlan0.
    [ -d /sys/class/net/wlan0 ] || return 1
    rfkill unblock wifi && ifconfig wlan0 up
}
radio_cleanup_children() {
    # Only children created in THIS invocation, before their ownership is released.
    [ -z "${radio_dhcp_pid:-}" ] || kill "$radio_dhcp_pid" 2>/dev/null || :
    [ -z "${radio_wpa_pid:-}" ] || kill "$radio_wpa_pid" 2>/dev/null || :
}
radio_start_children() {
    radio_wpa_pid=;radio_dhcp_pid=
    radio_session_tools_ready || return 1
    trap 'radio_cleanup_children' HUP INT TERM
    env -i PATH="$PATH" HOME="$RADIO_RUNTIME" TMPDIR="$RADIO_RUNTIME" \
        /bin/busybox setsid /usr/sbin/wpa_supplicant -i wlan0 -D wext -c "$RADIO_RUNTIME/wpa.conf" \
        < /dev/null > /dev/null 2>&1 &
    radio_wpa_pid=$!
    printf '%s\n' "$radio_wpa_pid" > "$RADIO_RUNTIME/wpa.pid"
    radio_wait=0
    while [ ! -S "$RADIO_RUNTIME/wpa/wlan0" ]; do
        radio_wait=$((radio_wait+1))
        if [ "$radio_wait" -gt 8 ] || ! kill -0 "$radio_wpa_pid" 2>/dev/null; then radio_cleanup_children;return 1;fi
        sleep 1
    done
    # -f prevents daemonizing, preserving $! ownership. A separate session and
    # closed terminal input let DHCP survive the controller's PTY hangup.
    # No factory callback, persistent DNS or automatic process adoption.
    env -i PATH="$PATH" HOME="$RADIO_RUNTIME" TMPDIR="$RADIO_RUNTIME" \
        /bin/busybox setsid /sbin/udhcpc -f -i wlan0 -s "$RADIO_RUNTIME/dhcp.sh" -p "$RADIO_RUNTIME/dhcp.pid" \
        -t 3 -T 3 -A 5 < /dev/null > /dev/null 2>&1 &
    radio_dhcp_pid=$!
    printf '%s\n' "$radio_dhcp_pid" > "$RADIO_RUNTIME/udhcpc.pid"
    sleep 1
    if ! kill -0 "$radio_wpa_pid" 2>/dev/null || ! kill -0 "$radio_dhcp_pid" 2>/dev/null; then radio_cleanup_children;return 1;fi
    trap - HUP INT TERM
}
radio_initialize_wifi() {
    radio_board_supported && radio_verify_inputs && radio_guard_ready || return 1
    # Preserve existing interrupted runtime for exact controller review; never adopt
    # or remove it. Module failures create no new runtime directory.
    [ ! -e "$RADIO_RUNTIME" ] && [ ! -L "$RADIO_RUNTIME" ] || return 1
    radio_load_clock && radio_load_sdio && radio_load_wifi && radio_prepare_runtime && radio_start_children
}
# RUN INIT
umask 077
PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH
unset LD_PRELOAD LD_LIBRARY_PATH ENV BASH_ENV
[ "$#" = 1 ] && [ "$1" = --wifi ] || exit 2
RADIO_SCRIPTS=$(CDPATH= cd -P "$(dirname "$0")" && pwd) || exit 1
RADIO_RUNTIME=/tmp/pandanote-connectivity
RADIO_FIRMWARE=/module_driver/firmware
CPUINFO_FILE=/proc/cpuinfo
MODULES_FILE=/proc/modules
KALLSYMS_FILE=/proc/kallsyms
MOUNTS_FILE=/proc/mounts
BLOCK_BASE=/sys/block
NET_BASE=/sys/class/net
SWAPS_FILE=/proc/swaps
. "$RADIO_SCRIPTS/radio_guard.sh" || exit 1
radio_initialize_wifi
