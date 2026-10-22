#!/bin/sh
# Owned development policy library. Sourcing defines functions only.
# Writable eMMC profile: does NOT claim or publish an eMMC write filter.

dev_check_partitions() {
    local n start size
    for n in 2 3 5 9; do
        case "$n" in
            2) start=20480; size=262144;;
            3) start=282624; size=1048576;;
            5) start=2379776; size=1572864;;
            9) start=7131136; size=52019200;;
        esac
        [ "$(bb cat "$DEV_SYS_BLOCK/mmcblk0p$n/start")" = "$start" ] &&
        [ "$(bb cat "$DEV_SYS_BLOCK/mmcblk0p$n/size")" = "$size" ] &&
        [ "$(bb cat "$DEV_SYS_BLOCK/mmcblk0p$n/partition")" = "$n" ] || return 1
        case "$n" in 3|9) [ "$(bb cat "$DEV_SYS_BLOCK/mmcblk0p$n/ro")" = 0 ] || return 1;; esac
    done
}

dev_check_mounts() {
    local source target type options rest seen='' roots=0 tmp=0 run=0 home=0 user=0
    case "$1" in pre|post) ;; *) return 1;; esac
    while read -r source target type options rest; do
        case ":$seen:" in *":$target:"*) return 1;; esac
        seen="$seen:$target"
        case "$target" in
            /)
                case "$source" in /dev/root|/dev/mmcblk0p2) ;; *) return 1;; esac
                [ "$type" = ext4 ] || return 1
                case ",$options," in *,ro,*) ;; *) return 1;; esac
                case ",$options," in *,rw,*) return 1;; esac
                case ",$options," in *,noload,*|*,norecovery,*) ;; *) return 1;; esac
                roots=1;;
            /home|/user)
                [ "$1" = post ] && [ "$type" = ext4 ] || return 1
                case "$source:$target" in
                    /dev/mmcblk0p3:/home) home=1;;
                    /dev/mmcblk0p9:/user) user=1;;
                    *) return 1;;
                esac
                case ",$options," in *,rw,*) ;; *) return 1;; esac
                case ",$options," in *,ro,*|*,noexec,*|*,noload,*|*,norecovery,*) return 1;; esac
                case ",$options," in *,nosuid,*) ;; *) return 1;; esac
                case ",$options," in *,nodev,*) ;; *) return 1;; esac;;
            /run/pandanote-opt)
                [ "$source:$type" = /dev/mmcblk0p5:ext4 ] || return 1
                case ",$options," in *,ro,*) ;; *) return 1;; esac
                case ",$options," in *,rw,*) return 1;; esac
                case ",$options," in *,noload,*|*,norecovery,*) ;; *) return 1;; esac;;
            /tmp|/run)
                [ "$type" = tmpfs ] || return 1
                case ",$options," in *,rw,*) ;; *) return 1;; esac
                case ",$options," in *,nosuid,*) ;; *) return 1;; esac
                case ",$options," in *,nodev,*) ;; *) return 1;; esac
                case "$target" in /tmp) tmp=1;; /run) run=1;; esac;;
            *) case "$target:$type" in
                /proc:proc|/sys:sysfs|/dev:devtmpfs|/dev/pts:devpts|/sys/kernel/config:configfs|/dev/usb-ffs/adb:functionfs) ;;
                *) return 1;; esac;;
        esac
        case "$source:$target" in
            /dev/mmcblk0p3:/home|/dev/mmcblk0p9:/user) ;;
            /dev/mmcblk0p3:*|/dev/mmcblk0p9:*) return 1;;
        esac
    done < "$DEV_MOUNTS"
    [ "$roots:$tmp:$run" = 1:1:1 ] || return 1
    [ "$(bb wc -l < "$DEV_SWAPS" | bb tr -d ' ')" = 1 ] || return 1
    [ "$1" = pre ] || [ "$home:$user" = 1:1 ]
}

dev_check_network() {
    local interface flags digits loopback=0
    for interface in "$DEV_NET"/*; do
        [ -d "$interface" ] || continue
        flags=$(bb cat "$interface/flags") || return 1
        case "$flags" in 0x*) digits=${flags#0x};; *) return 1;; esac
        case "$digits" in ''|*[!0-9a-fA-F]*) return 1;; esac
        [ "${#digits}" -le 8 ] || return 1
        case "${interface##*/}" in
            lo) loopback=1;;
            wlan0) :;;
            *) [ $((flags & 1)) = 0 ] || return 1;;
        esac
    done
    [ "$loopback" = 1 ]
}

dev_check_listeners() {
    local table number address remote state rest
    for table in /proc/net/tcp /proc/net/tcp6; do
        [ -f "$table" ] || continue
        while read -r number address remote state rest; do
            [ "$state" = 0A ] || continue
            case "$address" in
                0100007F:*|00000000000000000000000001000000:*) ;;
                *) return 1;;
            esac
        done < "$table"
    done
}

dev_ls_fields() {
    local fields
    [ ! -L "$1" ] || return 1
    fields=$(LC_ALL=C bb ls -ldn "$1") || return 1
    set -- $fields
    [ "$#" -ge 6 ] || return 1
    case "$1" in [bd-][r-][w-][x-][r-][w-][x-][r-][w-][x-]) ;; *) return 1;; esac
    case "$2:$3:$4" in *[!0-9:]*|:*|*::*|*:) return 1;; esac
    if [ "${1#b}" != "$1" ]; then
        [ "$#" -ge 7 ] || return 1
        case "${5%,}:$6" in *[!0-9:]*|:*|*:) return 1;; esac
        [ "${5%,}," = "$5" ] || return 1
    else
        case "$5" in ''|*[!0-9]*) return 1;; esac
    fi
    bb printf '%s\n' "$fields"
}

dev_private_file() {
    [ -f "$1" ] || return 1
    set -- $(dev_ls_fields "$1")
    [ "$#" -ge 6 ] && [ "$1:$2:$3" = -rw-------:1:0 ]
}

dev_root_owner() {
    set -- $(dev_ls_fields "$1")
    [ "$#" -ge 6 ] && [ "$3" = 0 ]
}

dev_root_single_file() {
    [ -f "$1" ] || return 1
    set -- $(dev_ls_fields "$1")
    [ "$#" -ge 6 ] && [ "$2:$3" = 1:0 ]
}

dev_receipt_ok() {
    local expected actual pid1 cmdline pid1_file="${1:-/tmp/pid1}" cmdline_file="${2:-/proc/cmdline}"
    dev_private_file "$DEV_RUN/boot-operator-handoff" || return 1
    pid1=$(bb sha256sum "$pid1_file") || return 1; pid1=${pid1%% *}
    cmdline=$(bb sha256sum "$cmdline_file") || return 1; cmdline=${cmdline%% *}
    expected=$(bb printf 'profile=writable-development-v1\nkernel_sha256=c7afae1b766457df618fcb49b47736f27d10616baeddb6082a197094c53ba4d4\npid1_sha256=%s\ncmdline_sha256=%s\nbootstrap_status=PASS\n' "$pid1" "$cmdline" | bb sha256sum) || return 1
    actual=$(bb sha256sum "$DEV_RUN/boot-operator-handoff") || return 1
    [ "${expected%% *}" = "${actual%% *}" ]
}

dev_verify_before_mount() {
    local n digest major minor
    dev_receipt_ok && dev_check_partitions && dev_check_mounts pre || return 1
    [ -b /dev/mmcblk0 ] && [ ! -L /dev/mmcblk0 ] || return 1
    [ "$(bb cat /sys/class/block/mmcblk0/ro)" = 0 ] || return 1
    for n in 2 3 5 9; do
        [ -b "/dev/mmcblk0p$n" ] && [ ! -L "/dev/mmcblk0p$n" ] || return 1
        IFS=: read -r major minor < "$DEV_SYS_BLOCK/mmcblk0p$n/dev" || return 1
        case "$major:$minor" in *[!0-9:]*|:*|*:) return 1;; esac
        set -- $(dev_ls_fields "/dev/mmcblk0p$n")
        [ "$#" -ge 7 ] && [ "${5%,}:$6" = "$major:$minor" ] || return 1
    done
    for n in 3 9; do [ "$(bb cat "$DEV_SYS_BLOCK/mmcblk0p$n/ro")" = 0 ] || return 1; done
    digest=$(bb dd if=/dev/mmcblk0 bs=512 count=34 2>/dev/null | bb sha256sum) || return 1
    [ "${digest%% *}" = fd502b7cdf436ac11f291b8c34d3a4e5a3f483b8b6ed95b8b1fff77a5790ffd2 ] || return 1
    for n in /home /user; do
        [ -d "$n" ] && dev_root_owner "$n" || return 1
        [ -z "$(bb ls -A "$n")" ] || return 1
    done
}

dev_mount() { bb mount "$@"; }
dev_mount_persistent() {
    dev_verify_before_mount || return 1
    # ext4 journal replay is an intentional authorized persistent write.
    # Never fsck -y, format, retry with another filesystem, or invoke stock helpers.
    dev_mount -t ext4 -o rw,noatime,nosuid,nodev /dev/mmcblk0p3 /home || return 1
    if ! dev_mount -t ext4 -o rw,noatime,nosuid,nodev /dev/mmcblk0p9 /user; then
        bb umount /home || :
        return 1
    fi
    if ! dev_check_mounts post; then
        bb umount /user || :; bb umount /home || :
        return 1
    fi
}

dev_private_directory() {
    [ ! -L "$1" ] || return 1
    if [ -e "$1" ]; then
        [ -d "$1" ] && dev_root_owner "$1" || return 1
    else
        bb mkdir -m 0700 "$1" || return 1
    fi
    bb chmod 0700 "$1"
}

dev_prepare_workspace() {
    local root="$1" name file
    case "$root" in /*) ;; *) return 1;; esac
    [ "$(bb readlink -f "$root")" = "$root" ] || return 1
    dev_private_directory "$root" || return 1
    for name in apps cache config notes words logs state content rollback; do
        dev_private_directory "$root/$name" || return 1
    done
    file="$root/config/reader-sync.ini"
    [ ! -L "$file" ] || return 1
    if [ -e "$file" ]; then
        dev_root_single_file "$file" || return 1
    else
        (umask 077; bb printf '' > "$file") || return 1
    fi
    bb chmod 0600 "$file"
}

dev_log() {
    case "$1" in storage-ready|storage-failed|application-started|application-stopped|application-failed|profile-stopped) ;; *) return 1;; esac
    if [ -e "$DEV_RUN/status.log" ]; then
        dev_private_file "$DEV_RUN/status.log" || return 1
        if [ "$(bb wc -c < "$DEV_RUN/status.log")" -ge 32700 ]; then
            [ ! -L "$DEV_RUN/status.log.old" ] || return 1
            bb mv -f "$DEV_RUN/status.log" "$DEV_RUN/status.log.old" || return 1
        fi
    fi
    (umask 077; bb printf '%s\n' "$1" >> "$DEV_RUN/status.log")
}

dev_child_identity() {
    local fields include_zombie="${2-}"
    fields=$(bb cat "/proc/$1/stat" 2>/dev/null) || return 1
    fields=${fields##*) }
    set -- $fields
    [ "$2" = "$$" ] || return 1
    [ "$1" != Z ] || [ "$include_zombie" = include-zombie ] || return 1
    bb printf '%s:%s\n' "$3" "$4"
}

dev_spawn() {
    local name="$1" pid attempt=0 digest
    case "$name" in app|adbd|runtime) ;; *) return 1;; esac
    eval '[ -z "${DEV_PID_'"$name"'-}" ]' || return 1
    [ ! -e "$DEV_RUN/$name.pid" ] && [ ! -L "$DEV_RUN/$name.pid" ] || return 1
    [ ! -e "$DEV_RUN/$name.go" ] && [ ! -L "$DEV_RUN/$name.go" ] || return 1
    [ ! -e "$DEV_RUN/$name.exit" ] && [ ! -L "$DEV_RUN/$name.exit" ] || return 1
    dev_private_file "$DEV_SUPERVISOR" || return 1
    digest=$(bb sha256sum "$DEV_SUPERVISOR") || return 1
    [ "${digest%% *}" = "$DEV_SUPERVISOR_SHA" ] || return 1
    shift
    DEV_BB="$DEV_BB" "$DEV_BB" setsid "$DEV_BB" sh "$DEV_SUPERVISOR" "$DEV_RUN" "$name" "$@" </dev/null >/dev/null 2>&1 &
    pid=$!
    while [ "$(dev_child_identity "$pid")" != "$pid:$pid" ]; do
        attempt=$((attempt+1))
        if [ "$attempt" -ge 10 ]; then
            # Still our unreaped direct child; no pidfile is ever adopted.
            bb kill -KILL "$pid" 2>/dev/null || :; wait "$pid" 2>/dev/null || :
            return 1
        fi
        bb sleep 0.1
    done
    eval "DEV_PID_$name=$pid"
    bb printf '%s\n' "$pid" > "$DEV_RUN/$name.pid"
    bb printf '%s\n' start > "$DEV_RUN/$name.go"
}

dev_child_running() {
    local name="$1" pid
    case "$name" in app|adbd|runtime) ;; *) return 1;; esac
    eval 'pid=${DEV_PID_'"$name"'-}'
    [ -n "$pid" ] && [ ! -e "$DEV_RUN/$name.exit" ] || return 1
    [ "$(bb cat "$DEV_RUN/$name.go")" = start ] || return 1
    [ "$(dev_child_identity "$pid")" = "$pid:$pid" ]
}

dev_stop() {
    local name="$1" pid attempt=0 identity
    case "$name" in app|adbd|runtime) ;; *) return 1;; esac
    eval 'pid=${DEV_PID_'"$name"'-}'
    [ -n "$pid" ] || return 1
    identity=$(dev_child_identity "$pid" include-zombie)
    if [ "$identity" = "$pid:$pid" ]; then
        bb kill -TERM "-$pid" 2>/dev/null || :
        while [ "$(dev_child_identity "$pid" include-zombie)" = "$pid:$pid" ] && [ "$attempt" -lt 20 ]; do
            bb sleep 0.1; attempt=$((attempt+1))
        done
        [ "$(dev_child_identity "$pid" include-zombie)" != "$pid:$pid" ] || bb kill -KILL "-$pid" 2>/dev/null || :
    fi
    wait "$pid" 2>/dev/null || :
    eval "DEV_PID_$name=''"
    bb rm -f "$DEV_RUN/$name.pid" "$DEV_RUN/$name.go" "$DEV_RUN/$name.exit"
}
