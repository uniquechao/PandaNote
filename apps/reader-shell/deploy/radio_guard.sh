#!/bin/sh
# Controller review library. Sourcing defines functions only; no hardware action.
# PID1 must retain its existing mount/disk/swap/listener checks. Replace ONLY its
# check_network_down body with radio_check_network after explicit sourcepin review.
radio_check_network() {
    radio_seen_lo=0
    for radio_interface in "$NET_BASE"/*; do
        [ -d "$radio_interface" ] || continue
        radio_flags=$(cat "$radio_interface/flags") || return 1
        case "$radio_flags" in 0x*) radio_digits=${radio_flags#0x};; *) return 1;; esac
        case "$radio_digits" in ''|*[!0-9a-fA-F]*) return 1;; esac
        [ "${#radio_digits}" -le 8 ] || return 1
        case "${radio_interface##*/}" in
            lo) radio_seen_lo=1;;
            wlan0) :;;
            *) [ $((radio_flags & 1)) = 0 ] || return 1;;
        esac
    done
    [ "$radio_seen_lo" = 1 ]
}
radio_check_storage() {
    radio_roots=0; radio_tmp=0; radio_opt=0
    while read -r radio_source radio_target radio_type radio_options radio_rest; do
        case "$radio_target" in
            /)
                case "$radio_source" in /dev/root|/dev/mmcblk0p2) ;; *) return 1;; esac
                [ "$radio_type" = ext4 ] || return 1
                case ",$radio_options," in *,ro,*) ;; *) return 1;; esac
                case ",$radio_options," in *,rw,*) return 1;; esac
                case ",$radio_options," in *,noload,*|*,norecovery,*) ;; *) return 1;; esac
                radio_roots=$((radio_roots+1));;
            /run/pandanote-opt)
                [ "$radio_source" = /dev/mmcblk0p5 ] || return 1
                [ "$radio_type" = ext4 ] || return 1
                case ",$radio_options," in *,ro,*) ;; *) return 1;; esac
                case ",$radio_options," in *,rw,*) return 1;; esac
                case ",$radio_options," in *,noload,*|*,norecovery,*) ;; *) return 1;; esac
                radio_opt=$((radio_opt+1))
                [ "$radio_opt" = 1 ] || return 1;;
            /tmp) [ "$radio_type" = tmpfs ] || return 1
                case ",$radio_options," in *,rw,*) ;; *) return 1;; esac
                radio_tmp=$((radio_tmp+1));;
            *) case "$radio_target:$radio_type" in
                /proc:proc|/sys:sysfs|/dev:devtmpfs|/run:tmpfs|/sys/kernel/config:configfs|/dev/usb-ffs/adb:functionfs|/dev/pts:devpts) ;;
                *) return 1;; esac;;
        esac
    done < "$MOUNTS_FILE"
    [ "$radio_roots" = 1 ] && [ "$radio_tmp" = 1 ] || return 1
    radio_disks=0
    for radio_disk in "$BLOCK_BASE"/mmcblk[0-9]; do
        [ -d "$radio_disk" ] || continue
        radio_disks=$((radio_disks+1))
        [ "${radio_disk##*/}" = mmcblk0 ] || return 1
        [ "$(cat "$radio_disk/ro")" = 1 ] || return 1
        for radio_boot in "$radio_disk"boot[01]; do
            [ -d "$radio_boot" ] || continue
            [ "$(cat "$radio_boot/ro")" = 1 ] && [ "$(cat "$radio_boot/force_ro")" = 1 ] || return 1
        done
    done
    [ "$radio_disks" = 1 ] || return 1
    [ "$(wc -l < "$SWAPS_FILE" | tr -d ' ')" = 1 ]
}
