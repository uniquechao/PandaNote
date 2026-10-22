"""Build a fixed-address local RAM capsule; contains no USB execution path.

Output remains analysis-only. Layout arithmetic and a stock mem= parser test
do not establish physical high-RAM availability or complete boot safety.
"""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parent
KERNEL_SHA = '36b6222a69b76816ead4850574543c04fad3cc2a90b36dc1cb5948597e0e6c65'
GUARD_SHA = 'cd98daa03fe0d14ef5e5da850498edad297c81a0696c5913db21426925e32f81'
PID1_SHA = '1ed1ef64aa71af447679e179efa69e6852902255e1ff056de9ee710b86cd354d'
BASE, ENTRY, KERNEL_END = 0x80010000, 0x805678A0, 0x80806BE0
WRAPPER, ARGV, GUARD = 0x84000000, 0x84001000, 0x84010000
LINUX_END, PROPOSED_DDR_END = 0x84000000, 0x88000000


def validate_layout(regions):
    ordered = sorted(regions)
    previous_end = LINUX_END
    for address, length in ordered:
        if (not isinstance(address, int) or not isinstance(length, int) or
                length <= 0 or address < LINUX_END or
                address + length > PROPOSED_DDR_END or address < previous_end):
            raise ValueError('Overlapping, allocatable, or out-of-range RAM segment')
        previous_end = address + length


def build_capsule(kernel: bytes, guard: bytes, pid1: bytes):
    for name, blob, digest in (('kernel', kernel, KERNEL_SHA),
                              ('guard', guard, GUARD_SHA), ('PID1', pid1, PID1_SHA)):
        if hashlib.sha256(blob).hexdigest() != digest:
            raise ValueError('Unverified ' + name + ' input')
    if len(kernel) != 7815440 or len(guard) != 576:
        raise ValueError('Unexpected image length')
    if not BASE + len(kernel) <= KERNEL_END < LINUX_END:
        raise ValueError('Kernel or BSS exceeds proposed Linux memory')
    compressed = gzip.compress(pid1, mtime=0)
    encoded = base64.b64encode(compressed).decode('ascii')
    # Only fixed tokens plus a base64 payload and hex digest. No caller-supplied
    # shell text, boot options, alternate init, or writable storage path.
    seed = ('/bin/busybox mount -t tmpfs -o mode=0700,nosuid,nodev tmpfs /tmp && '
            '/bin/busybox echo ' + encoded +
            ' | /bin/busybox base64 -d | /bin/busybox zcat > /tmp/pid1 && '
            '/bin/busybox sha256sum /tmp/pid1 | /bin/busybox grep -q ^' + PID1_SHA +
            ' && exec /bin/busybox sh /tmp/pid1; '
            'while :; do /bin/busybox sleep 3600; done')
    if '"' in seed or '\n' in seed or '\0' in seed:
        raise ValueError('Unsafe commandline quoting')
    commandline = ('root=/dev/mmcblk0p2 rootfstype=ext4 ro rootflags=noload '
        'rootwait mem=64M@0 maxcpus=1 panic=0 init=/bin/busybox -- sh -c "' + seed + '"')
    command_bytes = commandline.encode('ascii')
    if len(command_bytes) >= 4095:
        raise ValueError('Commandline would be truncated by original prom_init')
    name = b'pandanote-ram\0'
    argv = struct.pack('<III', ARGV + 12, ARGV + 12 + len(name), 0)
    argv += name + command_bytes + b'\0'
    if len(argv) > 4096:
        raise ValueError('Argument page overflow')
    # a0=argc2; a1=fixed argv; a2/a3=0. Original kernel_entry initializes
    # its own stack/GP and clears BSS before saving these firmware arguments.
    wrapper = struct.pack('<9I',
        0x24040002, 0x3C058400, 0x34A51000, 0x00003025, 0x00003825,
        0x3C198056, 0x373978A0, 0x03200008, 0)
    validate_layout([(WRAPPER, len(wrapper)), (ARGV, len(argv)), (GUARD, len(guard))])
    return dict(segments={BASE: kernel, WRAPPER: wrapper, ARGV: argv, GUARD: guard},
        commandline=commandline, pid1_gzip=compressed,
        kernel_entry=ENTRY, bootstrap_entry=WRAPPER, hardware_execution_permitted=False,
        unverified_gates=['physical high RAM range and nonaliasing',
            'complete original parameter propagation', 'PID1 hardware effects',
            'original adbd dependencies and isolated behavior',
            'BootROM cache/start transport', 'physical read-only diagnostic'])


def main():
    result = build_capsule(
        (ROOT / 'kernel-RAM-ANALYSIS-ONLY-NOT-FOR-FLASH.bin').read_bytes(),
        (ROOT / 'storage-guard.bin').read_bytes(), (ROOT / 'pid1-ram.sh').read_bytes())
    directory = ROOT / 'capsule-ANALYSIS-ONLY'
    directory.mkdir(exist_ok=True, mode=0o700)
    segments = []
    for address, blob in result['segments'].items():
        filename = 'ram-' + format(address, '08x') + '.bin'
        path = directory / filename
        path.write_bytes(blob)
        path.chmod(0o600)
        segments.append(dict(address=hex(address), file=filename, bytes=len(blob),
                             sha256=hashlib.sha256(blob).hexdigest()))
    (directory / 'manifest.json').write_text(json.dumps(dict(
        segments=segments, commandline_bytes=len(result['commandline'].encode()),
        kernel_bss_end=hex(KERNEL_END), linux_memory='64M@0',
        physical_ddr_128m_confirmed_by_this_builder=False,
        hardware_execution_permitted=False, flash_image=False,
        unverified_gates=result['unverified_gates'],
    ), indent=2) + '\n')
    print('Prepared local analysis capsule; hardware execution remains disabled.')


if __name__ == '__main__':
    main()
