"""Offline metadata and exact native-kernel derivation; no device transport."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import json
import tempfile
import unittest
import zlib

DEPLOY = Path(__file__).resolve().parents[1]
SOURCE = DEPLOY / 'writable_preparation.py'
module = None
if SOURCE.exists():
    spec = importlib.util.spec_from_file_location('writable_preparation', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def superblock(blocks=131072, free=123668, reserve=6553, flags=0x2c6):
    data = bytearray(1024)
    for offset, value in ((4, blocks), (8, reserve), (12, free), (24, 2),
                          (92, 0x3c), (96, flags), (100, 0x46b)):
        struct.pack_into('<I', data, offset, value)
    struct.pack_into('<H', data, 56, 0xef53)
    struct.pack_into('<H', data, 58, 1)
    return data


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'offline preparation tooling is missing')

    def test_dirty_ext4_reports_estimates_never_live_free_space(self):
        result = module.ext_metadata(superblock(), 536870912)
        self.assertEqual(result['filesystem'], 'ext4')
        self.assertEqual(result['free_blocks_snapshot_bytes'], 123668 * 4096)
        self.assertEqual(result['unreserved_free_snapshot_bytes'], (123668 - 6553) * 4096)
        self.assertTrue(result['journal_recovery_needed'])
        self.assertIsNone(result['live_available_bytes'])
        self.assertFalse(result['superblock_checksum_verified'])

    def test_64bit_block_counters_are_not_truncated(self):
        data = superblock(blocks=1, free=1, reserve=0)
        struct.pack_into('<I', data, 0x150, 1)
        struct.pack_into('<I', data, 0x158, 1)
        result = module.ext_metadata(data, (2**32 + 1) * 4096)
        self.assertEqual(result['filesystem_bytes'], (2**32 + 1) * 4096)

    def test_unknown_signature_is_not_ext4(self):
        self.assertIsNone(module.ext_metadata(bytes(1024), 536870912))

    def test_invalid_metadata_cannot_claim_usable_capacity(self):
        for data, size in ((superblock(free=131073), 536870912),
                           (superblock(reserve=131073), 536870912),
                           (superblock(), 1024)):
            with self.assertRaises(ValueError):
                module.ext_metadata(data, size)

    def test_unsupported_high_words_without_64bit_are_rejected(self):
        data = superblock(flags=0x246)
        struct.pack_into('<I', data, 0x150, 1)
        with self.assertRaises(ValueError):
            module.ext_metadata(data, 536870912)


class BackupInputTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'offline preparation tooling is missing')
        scratch = DEPLOY.parent / 'build/writable-preparation-tests'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        entry = bytearray(128)
        entry[:16] = b'\x01' * 16
        struct.pack_into('<QQ', entry, 32, 8, 15)
        entry[56:72] = 'userdata'.encode('utf-16le')
        self.table = entry + bytes(128 * 9)
        self.header = bytearray(512)
        self.header[:8] = b'EFI PART'
        struct.pack_into('<I', self.header, 12, 92)
        struct.pack_into('<QIII', self.header, 72, 2, 10, 128, zlib.crc32(self.table))
        struct.pack_into('<I', self.header, 16, zlib.crc32(self.header[:92]))
        image = bytearray(8192)
        image[512:1024] = self.header
        image[1024:2304] = self.table
        image[5120:6144] = superblock(blocks=1, free=1, reserve=0)
        (self.root / 'gpt-userarea.img.partial').write_bytes(image)
        acquisition = dict(status='partition_ranges_complete_tail_deferred',
            plan=dict(total_bytes=8192), completed=dict(userdata=dict(
                offset=4096, length=4096, sha256='historical-range-hash')))
        audit = dict(status='declared_partition_ranges_independently_audited',
            verified_ranges=[dict(name='userdata', bytes=4096,
                                  sha256='historical-range-hash')])
        (self.root / 'acquisition-manifest.json').write_text(json.dumps(acquisition))
        (self.root / 'offline-independent-audit.json').write_text(json.dumps(audit))

    def test_bounded_reader_validates_gpt_and_keeps_backup_unchanged(self):
        path = self.root / 'gpt-userarea.img.partial'
        before = path.read_bytes()
        result = module.backup_facts(self.root)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(result['input_read_bound_bytes'], 512 + 1280 + 4096)
        self.assertTrue(result['primary_gpt_crc_valid'])
        self.assertFalse(result['whole_image_rehashed'])
        self.assertIsNone(result['partitions'][0]['ext']['live_available_bytes'])

    def test_corrupt_gpt_is_refused(self):
        path = self.root / 'gpt-userarea.img.partial'
        image = bytearray(path.read_bytes())
        image[1030] ^= 1
        path.write_bytes(image)
        with self.assertRaisesRegex(ValueError, 'table CRC'):
            module.backup_facts(self.root)

    def test_unacquired_range_is_refused(self):
        path = self.root / 'acquisition-manifest.json'
        data = json.loads(path.read_text())
        data['completed']['userdata']['offset'] = 0
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'partition range'):
            module.backup_facts(self.root)


class ActualKernelTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'offline preparation tooling is missing')
        reference = (Path(__import__('os').environ.get('PANDANOTE_REFERENCE_ROOT', 'external-inputs')) / 'pandanote-analysis')
        original = reference / 'factory-backup-20261020/inspection/kernel-decompressed.bin'
        guarded = reference / 'app-development-research/ram-linux-research/kernel-RAM-ANALYSIS-ONLY-NOT-FOR-FLASH.bin'
        if not original.is_file() or not guarded.is_file():
            self.skipTest('acquired original and guarded kernels are not present')
        self.original, self.guarded = original.read_bytes(), guarded.read_bytes()

    def test_candidate_exactly_preserves_two_startup_patches(self):
        candidate = module.derive_writable_kernel(self.original, self.guarded)
        delta = [i for i, (a, b) in enumerate(zip(candidate, self.guarded)) if a != b]
        self.assertTrue(delta)
        self.assertTrue(all(module.SDHCI_OFFSET <= i < module.SDHCI_OFFSET + 8 for i in delta))
        self.assertEqual(candidate[module.SDHCI_OFFSET:module.SDHCI_OFFSET + 8],
                         struct.pack('<II', 0x27bdff98, 0xafb60058))
        self.assertEqual(len(candidate), 7815440)
        for offset, expected in module.STARTUP_REPLACEMENTS:
            self.assertEqual(candidate[offset:offset+len(expected)], expected)
        self.assertNotEqual(hashlib.sha256(candidate).hexdigest(), module.GUARDED_SHA)

    def test_changed_original_kernel_is_refused(self):
        changed = bytearray(self.original)
        changed[0] ^= 1
        with self.assertRaises(ValueError):
            module.derive_writable_kernel(changed, self.guarded)

    def test_changed_guarded_kernel_is_refused(self):
        changed = bytearray(self.guarded)
        changed[-1] ^= 1
        with self.assertRaises(ValueError):
            module.derive_writable_kernel(self.original, changed)


if __name__ == '__main__':
    unittest.main()
