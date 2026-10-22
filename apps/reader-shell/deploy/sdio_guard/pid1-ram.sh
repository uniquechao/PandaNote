#!/bin/sh
# Analysis candidate only. No bootstrap transport currently executes this file.
# Policy functions are fixture-tested separately from the hardware entry below.

check_mounts() {
    roots=0
    opt_mounts=0
    while read -r source target fstype options rest; do
        if [ "$target" = / ]; then
            case "$source" in /dev/root|/dev/mmcblk0p2) ;; *) return 1;; esac
            [ "$fstype" = ext4 ] || return 1
            case ",$options," in *,ro,*) ;; *) return 1;; esac
            case ",$options," in *,rw,*) return 1;; esac
            case ",$options," in *,noload,*|*,norecovery,*) ;; *) return 1;; esac
            roots=$((roots + 1))
        elif [ "$target" = /run/pandanote-opt ]; then
            [ "$source" = /dev/mmcblk0p5 ] || return 1
            [ "$fstype" = ext4 ] || return 1
            case ",$options," in *,ro,*) ;; *) return 1;; esac
            case ",$options," in *,rw,*) return 1;; esac
            case ",$options," in *,noload,*|*,norecovery,*) ;; *) return 1;; esac
            opt_mounts=$((opt_mounts + 1))
            [ "$opt_mounts" = 1 ] || return 1
        else
            case "$target:$fstype" in
                /proc:proc|/sys:sysfs|/dev:devtmpfs|/tmp:tmpfs|/run:tmpfs|\
                /sys/kernel/config:configfs|/dev/usb-ffs/adb:functionfs|/dev/pts:devpts) ;;
                *) return 1;;
            esac
        fi
    done < "$MOUNTS_FILE"
    [ "$roots" = 1 ]
}

protect_disks() {
    seen=0
    for disk in "$BLOCK_BASE"/mmcblk[0-9]; do
        [ -d "$disk" ] || continue
        seen=$((seen + 1))
        name=${disk##*/}
        # Busybox hdparm reports success even after failed ioctl. sysfs is the
        # decisive check; the independently tested kernel command gate is primary.
        bb hdparm -r1 "/dev/$name" >/dev/null 2>&1 || :
        [ "$(bb cat "$disk/ro")" = 1 ] || return 1
        for boot in "$disk"boot[01]; do
            [ -d "$boot" ] || continue
            [ "$(bb cat "$boot/ro")" = 1 ] || return 1
            [ "$(bb cat "$boot/force_ro")" = 1 ] || return 1
        done
    done
    [ "$seen" = 1 ] && [ -d "$BLOCK_BASE/mmcblk0" ]
}

check_network_down() {
    seen_lo=0
    for interface in "$NET_BASE"/*; do
        [ -d "$interface" ] || continue
        flags=$(bb cat "$interface/flags") || return 1
        case "$flags" in 0x*) digits=${flags#0x};; *) return 1;; esac
        case "$digits" in ''|*[!0-9a-fA-F]*) return 1;; esac
        [ "${#digits}" -le 8 ] || return 1
        case "${interface##*/}" in
            lo) seen_lo=1;;
            wlan0) :;;
            *) [ $((flags & 1)) = 0 ] || return 1;;
        esac
    done
    [ "$seen_lo" = 1 ]
}

check_listeners() {
    [ -f "$TCP_FILE" ] || return 1
    for table in "$TCP_FILE" "$TCP6_FILE"; do
        [ -f "$table" ] || continue
        while read -r number local remote state rest; do
            [ "$state" = 0A ] || continue
            case "$local" in *:15B3) return 1;; esac
            case "$local" in
                0100007F:*|00000000000000000000000001000000:*) ;;
                *) return 1;;
            esac
        done < "$table"
    done
}
# END POLICY LIBRARY


bb() { /bin/busybox "$@"; }
is_pid1() { [ "$$" = 1 ]; }
go_to() { cd "$1"; }
path_exists() { [ -e "$1" ]; }
write_control() { bb printf '%s\n' "$2" > "$1"; }
swap_is_empty() { [ "$(bb wc -l < /proc/swaps)" = 1 ]; }
adbd_hash_matches() {
    actual=$(bb sha256sum /usr/bin/adbd) || return 1
    [ "${actual%% *}" = f819818a78b04a6aa90970231d050cd037b0650e595de8b3aa42b7687cab17d5 ]
}
halt_forever() {
    bb printf 'PANDANOTE_RAM_RO_STOP: %s\n' "$1"
    while :; do bb sleep 3600; done
}
need() { "$@" || halt_forever "$*"; }
start_adbd() {
    # No stock looping adbserver/rcS. Original adbd uses the separately audited
    # usb_adb_enable.sh only to bind the volatile adb_demo gadget.
    bb env -i PATH="$PATH" HOME=/tmp TMPDIR=/tmp EXTERNAL_STORAGE=/tmp \
        /usr/bin/adbd > /tmp/adbd.log 2>&1 &
    daemon=$!
}
stop_adbd() {
    bb kill "$daemon" 2>/dev/null || :
    write_control "$gadget/UDC" '' || :
}
write_status() {
    write_control /tmp/pandanote-network-profile-wlan0-v1 'wlan0-only-listeners-loopback-storage-ro-v1' || return 1
    write_control /tmp/pandanote-ram-status.txt 'PANDANOTE966U2_RAM_RO
root=ro,noload
disk_ro=1
network=USB and wlan0; TCP listeners loopback only'
}

main() {
    umask 077
    PATH=/sbin:/bin:/usr/sbin:/usr/bin
    HOME=/tmp
    TMPDIR=/tmp
    export PATH HOME TMPDIR
    unset LD_PRELOAD LD_LIBRARY_PATH ENV BASH_ENV
    MOUNTS_FILE=/proc/mounts
    BLOCK_BASE=/sys/block
    NET_BASE=/sys/class/net
    TCP_FILE=/proc/net/tcp
    TCP6_FILE=/proc/net/tcp6
    readonly MOUNTS_FILE BLOCK_BASE NET_BASE TCP_FILE TCP6_FILE

    need is_pid1
    [ "$#" = 0 ] || halt_forever 'Unexpected script arguments'
    need bb mount -t proc -o nosuid,nodev,noexec proc /proc
    need bb mount -t sysfs -o nosuid,nodev,noexec sysfs /sys
    need check_mounts
    if ! bb grep -q ' /dev devtmpfs ' /proc/mounts; then
        need bb mount -t devtmpfs -o nosuid devtmpfs /dev
    fi
    need check_mounts
    need protect_disks
    need check_network_down
    need swap_is_empty
    need bb mount -t tmpfs -o mode=0755,nosuid,nodev tmpfs /run
    need bb mkdir -p /dev/pts
    need bb mount -t devpts -o mode=0600,nosuid,noexec devpts /dev/pts
    need bb ifconfig lo 127.0.0.1 up
    need check_network_down
    need adbd_hash_matches
    need bb mount -t configfs -o nosuid,nodev,noexec configfs /sys/kernel/config
    gadget=/sys/kernel/config/usb_gadget/adb_demo
    need bb mkdir "$gadget"
    need go_to "$gadget"
    need bb mkdir strings/0x409 configs/c.1 configs/c.1/strings/0x409 functions/ffs.adb
    need write_control idVendor 0x18d1
    need write_control idProduct 0xd002
    need write_control bcdUSB 0x0200
    need write_control bcdDevice 0x0100
    need write_control strings/0x409/manufacturer 'PandaNote RAM diagnostic'
    need write_control strings/0x409/product 'Temporary read-only diagnostic'
    need write_control strings/0x409/serialnumber PANDANOTE966U2_RAM_RO
    need write_control configs/c.1/MaxPower 120
    need write_control configs/c.1/strings/0x409/configuration adb
    need bb ln -s functions/ffs.adb configs/c.1/ffs.adb
    need bb mkdir -p /dev/usb-ffs/adb
    need bb mount -t functionfs -o nosuid,nodev,noexec adb /dev/usb-ffs/adb
    need path_exists /dev/usb-ffs/adb/ep0
    need check_mounts
    need protect_disks
    need check_network_down
    need go_to /tmp
    start_adbd
    ready=0
    while :; do
        bb sleep 1
        if ! bb kill -0 "$daemon" 2>/dev/null || ! check_mounts ||
           ! protect_disks || ! check_network_down || ! check_listeners; then
            stop_adbd
            halt_forever 'Temporary diagnostic stopped; no automatic retry'
        fi
        ready=$((ready + 1))
        if [ "$ready" = 3 ]; then
            if ! write_status; then
                stop_adbd
                halt_forever 'Cannot publish verified runtime status'
            fi
        fi
    done
}
# RUN PID1
main "$@"
