#!/bin/sh
# A reviewed replacement for the factory callback. Never writes /etc or /home.
radio_ipv4() {
    case "$1" in ''|*[!0-9.]*) return 1;; esac
    radio_save_ifs=$IFS; IFS=.; set -- $1; IFS=$radio_save_ifs
    [ "$#" = 4 ] || return 1
    for radio_octet do
        case "$radio_octet" in ''|*[!0-9]*) return 1;; esac
        [ "${#radio_octet}" -le 3 ] && [ "$radio_octet" -le 255 ] || return 1
    done
}
radio_routes_clear() {
    radio_attempt=0
    while [ "$radio_attempt" -lt 4 ]; do
        route del default dev wlan0 >/dev/null 2>&1 || break
        radio_attempt=$((radio_attempt+1))
    done
}
radio_dhcp_event() {
    [ "${interface:-}" = wlan0 ] || return 1
    case "$1" in
        deconfig)
            ifconfig wlan0 0.0.0.0 || return 1
            radio_routes_clear
            : > "$RADIO_RUNTIME/resolv.conf"
            return 0;;
        bound|renew) ;;
        *) return 1;;
    esac
    radio_ipv4 "${ip:-}" && radio_ipv4 "${subnet:-}" || return 1
    radio_count=0; radio_gateway=
    for radio_addr in ${router:-}; do
        radio_count=$((radio_count+1)); [ "$radio_count" -le 3 ] || return 1
        radio_ipv4 "$radio_addr" || return 1
        [ -n "$radio_gateway" ] || radio_gateway=$radio_addr
    done
    radio_count=0
    for radio_addr in ${dns:-}; do
        radio_count=$((radio_count+1)); [ "$radio_count" -le 3 ] || return 1
        radio_ipv4 "$radio_addr" || return 1
    done
    ifconfig wlan0 "$ip" netmask "$subnet" || return 1
    radio_routes_clear
    if [ -n "$radio_gateway" ]; then route add default gw "$radio_gateway" dev wlan0 || return 1; fi
    : > "$RADIO_RUNTIME/resolv.conf.new" || return 1
    for radio_addr in ${dns:-}; do printf 'nameserver %s\n' "$radio_addr" >> "$RADIO_RUNTIME/resolv.conf.new" || return 1; done
    chmod 600 "$RADIO_RUNTIME/resolv.conf.new" || return 1
    mv "$RADIO_RUNTIME/resolv.conf.new" "$RADIO_RUNTIME/resolv.conf"
}
# RUN DHCP
umask 077
set -f
PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH
RADIO_RUNTIME=/tmp/pandanote-connectivity
[ "$#" = 1 ] && [ -d "$RADIO_RUNTIME" ] && [ ! -L "$RADIO_RUNTIME" ] || exit 1
radio_dhcp_event "$1"
