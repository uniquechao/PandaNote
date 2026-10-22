"""Deterministic narrow transform of pinned golden PID1. No execution."""
from pathlib import Path
import hashlib,difflib
ROOT=Path(__file__).resolve().parent
REF=(Path(__import__('os').environ.get('PANDANOTE_REFERENCE_ROOT', 'external-inputs')) / 'pandanote-analysis/app-development-research/ram-linux-research')
GOLDEN='c4db0c1788bd4b647964a59ee383e88d6dffc955e07f4a7d754f5798a6538810'
def transform(source):
    if hashlib.sha256(source).hexdigest()!=GOLDEN: raise ValueError('Unreviewed PID1 source')
    s=source.decode()
    s=s.replace('    roots=0\n','    roots=0\n    opt_mounts=0\n',1)
    start=s.index('        else\n            case "$target:$fstype"')
    s=s[:start]+'''        elif [ "$target" = /run/pandanote-opt ]; then
            [ "$source" = /dev/mmcblk0p5 ] || return 1
            [ "$fstype" = ext4 ] || return 1
            case ",$options," in *,ro,*) ;; *) return 1;; esac
            case ",$options," in *,rw,*) return 1;; esac
            case ",$options," in *,noload,*|*,norecovery,*) ;; *) return 1;; esac
            opt_mounts=$((opt_mounts + 1))
            [ "$opt_mounts" = 1 ] || return 1
'''+s[start:]
    start=s.index('check_network_down() {'); end=s.index('\ncheck_listeners()',start)
    s=s[:start]+'''check_network_down() {
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
'''+s[end:]
    s=s.replace("network=USB only'", "network=USB and wlan0; TCP listeners loopback only'")
    s=s.replace("write_status() {\n", "write_status() {\n    write_control /tmp/pandanote-network-profile-wlan0-v1 'wlan0-only-listeners-loopback-storage-ro-v1' || return 1\n")
    return s.encode()
def main():
    before=(REF/'pid1-ram.sh').read_bytes(); after=transform(before)
    (ROOT/'pid1-ram.sh').write_bytes(after)
    (ROOT/'evidence/pid1.diff').write_text(''.join(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='golden-pid1',tofile='candidate-pid1',n=0)))
    print(hashlib.sha256(after).hexdigest())
if __name__=='__main__': main()
