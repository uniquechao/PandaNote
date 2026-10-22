#!/usr/bin/env python3
"""Build a separate Wi-Fi entry for the verified writable RAM profile; no USB."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
COMMON=ROOT/'radio_init.sh'
GUARD=ROOT/'writable_boot/build/candidate/payload/radio-development-guard.sh'
COMMON_SHA='2510ba42b0cba39bf602d120065c57d31c30ed9cb2b541cd3ac9f34fc9c869c5'
GUARD_SHA='75618371be37d51ffe56a295188f16322f58eaceba0c6f79def628238ca8a3cd'

def sha(b):return hashlib.sha256(b).hexdigest()

def render(common=None,guard=None):
    common=COMMON.read_bytes() if common is None else common
    guard=GUARD.read_bytes() if guard is None else guard
    if sha(common)!=COMMON_SHA or sha(guard)!=GUARD_SHA:
        raise ValueError('reviewed Wi-Fi source or writable guard changed')
    if common.count(b'# RUN INIT\n')!=1:
        raise ValueError('common function boundary changed')
    # Reuse the exact audited module/firmware/session functions. This independent
    # entry replaces only the profile selection; it never publishes old markers.
    functions=common.split(b'# RUN INIT\n',1)[0]
    return functions+b'''\n# Explicit writable profile. Guard input SHA: '''+GUARD_SHA.encode()+b'''\n'''+guard+b'''
radio_guard_ready() {
    [ "$(id -u)" = 0 ] || return 1
    radio_session_tools_ready || return 1
    radio_check_storage && radio_check_network && radio_check_memory || return 1
    if pidof wpa_supplicant udhcpc >/dev/null 2>&1; then return 1; fi
}
# RUN DEVELOPMENT INIT
umask 077
PATH=/sbin:/bin:/usr/sbin:/usr/bin
export PATH
unset LD_PRELOAD LD_LIBRARY_PATH ENV BASH_ENV
[ "$#" = 1 ] && [ "$1" = --wifi-development ] || exit 2
RADIO_SCRIPTS=$(CDPATH= cd -P "$(dirname "$0")" && pwd) || exit 1
RADIO_RUNTIME=/tmp/pandanote-connectivity
RADIO_FIRMWARE=/module_driver/firmware
CPUINFO_FILE=/proc/cpuinfo
MODULES_FILE=/proc/modules
KALLSYMS_FILE=/proc/kallsyms
radio_initialize_wifi
'''

def main():
    blob=render();out=ROOT/'writable_boot/build/radio-development-init.sh'
    out.write_bytes(blob);out.chmod(0o600)
    print(json.dumps({'file':str(out),'bytes':len(blob),'sha256':sha(blob),
        'common_sha256':COMMON_SHA,'guard_sha256':GUARD_SHA,
        'hardware_execution':False,'staged_on_device':False},indent=2))

if __name__=='__main__':main()
