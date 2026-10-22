#!/usr/bin/env python3
"""Bounded OFFLINE backup metadata and writable-kernel preparation; no transport.

Reads primary GPT, partition prefixes and two 7.8 MB local kernels. Never opens
device paths or writes acquired images. Kernel output is not a complete capsule,
flash image, approved transport input, or a claim of physical write acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import struct
import zlib

PROJECT = Path(__file__).resolve().parents[3]
ORIGINAL_SHA = 'ce4e204c337d342fa9eb39a96cffcd7f03dc74df01a3ef1e6f205262652ed0bf'
GUARDED_SHA = '36b6222a69b76816ead4850574543c04fad3cc2a90b36dc1cb5948597e0e6c65'
BASE = 0x80010000
SDHCI_OFFSET = 0x8035c450 - BASE
STARTUP_REPLACEMENTS = (
    (0x80567a70 - BASE, struct.pack('<I', 0x1080001e)),
    (0x8004c9d8 - BASE, struct.pack('<II', 0x03e00008, 0)),
)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def regular(path):
    """Inputs must be local regular files, never /dev or symlink transports."""
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('expected regular local input: ' + str(path))
    return path


def ext_metadata(superblock, partition_bytes):
    if len(superblock) != 1024:
        raise ValueError('truncated superblock')
    if superblock[56:58] != b'\x53\xef':
        return None
    u32 = lambda offset: struct.unpack_from('<I', superblock, offset)[0]
    compat, incompat, rocompat = (u32(i) for i in (92, 96, 100))
    log_size = u32(24)
    if log_size > 6:
        raise ValueError('invalid ext block size')
    block_size = 1024 << log_size
    high = [u32(i) for i in (0x150, 0x154, 0x158)]
    if not incompat & 0x80 and any(high):
        raise ValueError('high block counters without 64bit feature')
    blocks, reserve, free = [u32(lo) + (hi << 32) for lo, hi in zip((4, 8, 12), high)]
    if not blocks or blocks * block_size > partition_bytes or free > blocks or reserve > blocks:
        raise ValueError('inconsistent ext capacity counters')
    return dict(
        filesystem='ext4' if incompat & 0x40 else 'ext3' if compat & 4 else 'ext2',
        block_size=block_size, blocks=blocks, filesystem_bytes=blocks * block_size,
        free_blocks=free, reserved_blocks=reserve,
        free_blocks_snapshot_bytes=free * block_size,
        unreserved_free_snapshot_bytes=max(free - reserve, 0) * block_size,
        live_available_bytes=None, snapshot_not_live=True,
        state=struct.unpack_from('<H', superblock, 58)[0],
        journal_recovery_needed=bool(incompat & 4),
        features=dict(compat=hex(compat), incompat=hex(incompat), rocompat=hex(rocompat)),
        unix_permissions_supported=True, superblock_checksum_verified=False,
        filesystem_consistency_checked=False, superblock_sha256=sha(superblock))


def backup_facts(backup):
    image = regular(backup / 'gpt-userarea.img.partial')
    acquisition_path = regular(backup / 'acquisition-manifest.json')
    audit_path = regular(backup / 'offline-independent-audit.json')
    acquisition = json.loads(acquisition_path.read_bytes())
    audit = json.loads(audit_path.read_bytes())
    if acquisition['status'] != 'partition_ranges_complete_tail_deferred' or audit['status'] != 'declared_partition_ranges_independently_audited':
        raise ValueError('expected completed declared-range backup and independent audit')
    if image.stat().st_size != acquisition['plan']['total_bytes']:
        raise ValueError('backup image length changed')
    audited = {entry['name']: entry for entry in audit['verified_ranges']}
    for name, entry in acquisition['completed'].items():
        if (audited[name]['sha256'], audited[name]['bytes']) != (entry['sha256'], entry['length']):
            raise ValueError('acquisition and audit disagree')
    results = []
    with image.open('rb') as reader:
        reader.seek(512)
        header = reader.read(512)
        if header[:8] != b'EFI PART':
            raise ValueError('missing primary GPT')
        header_size, checksum = struct.unpack_from('<II', header, 12)
        if not 92 <= header_size <= 512:
            raise ValueError('invalid GPT header length')
        checked = bytearray(header[:header_size])
        checked[16:20] = bytes(4)
        if zlib.crc32(checked) != checksum:
            raise ValueError('GPT header CRC mismatch')
        lba, count, size, table_crc = struct.unpack_from('<QIII', header, 72)
        if lba != 2 or count != 10 or size != 128:
            raise ValueError('unexpected 966U2 GPT layout')
        reader.seek(lba * 512)
        entries = reader.read(count * size)
        if len(entries) != count * size or zlib.crc32(entries) != table_crc:
            raise ValueError('GPT table CRC mismatch')
        for index in range(count):
            entry = entries[index*size:(index+1)*size]
            if entry[:16] == bytes(16):
                continue
            name = entry[56:128].decode('utf-16le').split('\0', 1)[0]
            start, end = struct.unpack_from('<QQ', entry, 32)
            offset, length = start * 512, (end - start + 1) * 512
            acquired = acquisition['completed'].get(name, {})
            if end < start or (offset, length) != (acquired.get('offset'), acquired.get('length')):
                raise ValueError('partition range does not match acquired backup')
            reader.seek(offset)
            prefix = reader.read(4096)
            if len(prefix) != 4096:
                raise ValueError('truncated partition prefix')
            results.append(dict(index=index+1, name=name, offset_bytes=offset,
                capacity_bytes=length, prefix_bytes=4096, prefix_sha256=sha(prefix),
                acquired_range_sha256=acquired['sha256'], range_rehashed_this_run=False,
                ext=ext_metadata(prefix[1024:2048], length)))
    return dict(schema=1, scope='offline-local-acquired-backup-metadata-only',
        hardware_access=False, image_writes=False, whole_image_rehashed=False,
        acquisition_manifest_sha256=sha(acquisition_path.read_bytes()),
        independent_audit_sha256=sha(audit_path.read_bytes()),
        primary_gpt_crc_valid=True, entry_table_crc_valid=True,
        input_read_bound_bytes=512 + count*size + len(results)*4096,
        partitions=results, full_device_recovery_proven=False,
        excluded_backup_regions=['boot0', 'boot1', 'RPMB', 'deferred tail/secondary GPT'],
        selected_route=dict(
            profile='writable-development-v1', status='offline-preparation-only',
            persistent_mounts=[dict(partition=3, name='homefs', mount='/home', filesystem='ext4'),
                               dict(partition=9, name='userdata', mount='/user', filesystem='ext4')],
            proposed_app_root='/user/pandanote', proposed_bootstrap_root='/home/pandanote-system',
            format_required=False, repartition_required=False, loop_image_required=False,
            linux_memory='64M@0 unchanged',
            reuse=['board DDR-only SPL and parameters', 'Qt libraries and display modules',
                   'RAM-NO-UPGRADE touch module'],
            replace_stock_startup=True, old_guarded_profile_modified=False),
        prerequisites=[
            'New independent PID1 with explicit mount table and no stock rcS/S??*/mount_mmc_ext4.sh/S22 execution.',
            'New capsule, bootstrap CRC table, immutable manifest and separate transport profile using this exact candidate.',
            'Offline policy and process-lifecycle tests plus scoped independent review of new PID1/profile.',
            'Live p3/p9 identity, ext4 compatibility/health and statvfs available space after reader reconnects.',
            'One explicit owned file write/fsync/readback/rename/reboot persistence test before application installation.',
            'Versioned application, configuration and rollback manifest frozen from the current accepted artifacts.',
            'Normal-boot inittab and initialization supervisor replace all dangerous early stock startup, not only final QPE dispatch.',
            'Normal reboot, USB recovery, network/calendar, touch, idle and interrupted-update acceptance.'
        ],
        writable_kernel=None, device_apply_supported=False)


def derive_writable_kernel(original, guarded):
    if len(original) != 7815440 or sha(original) != ORIGINAL_SHA:
        raise ValueError('original kernel identity mismatch')
    if len(guarded) != len(original) or sha(guarded) != GUARDED_SHA:
        raise ValueError('guarded kernel identity mismatch')
    stock = struct.pack('<II', 0x27bdff98, 0xafb60058)
    if original[SDHCI_OFFSET:SDHCI_OFFSET+8] != stock:
        raise ValueError('original SDHCI prologue mismatch')
    if guarded[SDHCI_OFFSET:SDHCI_OFFSET+8] != struct.pack('<II', 0x09004000, 0):
        raise ValueError('guarded SDHCI trampoline mismatch')
    candidate = bytearray(guarded)
    candidate[SDHCI_OFFSET:SDHCI_OFFSET+8] = stock
    expected = bytearray(original)
    for offset, replacement in STARTUP_REPLACEMENTS:
        expected[offset:offset+len(replacement)] = replacement
    if candidate != expected:
        raise ValueError('candidate differs from original outside two startup patches')
    return bytes(candidate)


def project_output(path):
    resolved = path.resolve()
    if not resolved.is_relative_to(PROJECT) or resolved == PROJECT:
        raise ValueError('output must be inside this project')
    return resolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-root', required=True, type=Path)
    parser.add_argument('--prepare-kernel', action='store_true')
    parser.add_argument('--output', type=Path,
                        default=PROJECT / 'docs/team/evidence/writable-development-facts.json')
    args = parser.parse_args()
    reference = args.reference_root / 'pandanote-analysis'
    facts = backup_facts(reference / 'factory-backup-20261020')
    if args.prepare_kernel:
        original = regular(reference / 'factory-backup-20261020/inspection/kernel-decompressed.bin').read_bytes()
        guarded = regular(reference / 'app-development-research/ram-linux-research/kernel-RAM-ANALYSIS-ONLY-NOT-FOR-FLASH.bin').read_bytes()
        candidate = derive_writable_kernel(original, guarded)
        target = project_output(PROJECT / 'apps/reader-shell/build/writable-development/kernel-WRITABLE-OFFLINE-CANDIDATE.bin')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(candidate)
        target.chmod(0o600)
        facts['writable_kernel'] = dict(path=str(target.relative_to(PROJECT)),
            bytes=len(candidate), sha256=sha(candidate), original_sha256=ORIGINAL_SHA,
            guarded_sha256=GUARDED_SHA, sdhci_address='0x8035c450',
            restored_words=['0x27bdff98', '0xafb60058'],
            changes_from_guarded_limited_to_bytes=[SDHCI_OFFSET, SDHCI_OFFSET+8],
            retained_startup_patch_addresses=['0x80567a70', '0x8004c9d8'],
            emmc_write_filter=False, hardware_execution_permitted=False,
            capsule_complete=False, flash_image=False)
    output = project_output(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(facts, indent=2) + '\n')
    print(str(output.relative_to(PROJECT)))


if __name__ == '__main__':
    main()
