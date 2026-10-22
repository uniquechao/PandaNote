import hashlib
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
try:
    import package
except ImportError:
    package = None


class PackageTests(unittest.TestCase):
    def assert_rejects_capture_race(self, target):
        # Real verifier, isolated files: replacement happens precisely after its
        # successful return, before the packager captures the archive bytes.
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            base = Path(directory)
            release, source = base/'release', base/'source'
            release.mkdir()
            source.mkdir()
            (release/'reader-shell.mipsel').write_bytes(b'reviewed ELF')
            (source/'main.cpp').write_bytes(b'reviewed src')
            manifest = {'artifacts':[{'path':'reader-shell.mipsel', 'bytes':12,
                'sha256':hashlib.sha256(b'reviewed ELF').hexdigest()}],
                'sources':{'main.cpp':hashlib.sha256(b'reviewed src').hexdigest()}}
            manifest_bytes = (json.dumps(manifest)+'\n').encode()
            (release/'manifest.json').write_bytes(manifest_bytes)
            for name in ('stage_ram.py','package.py','tests/test_stage_ram.py','tests/test_package.py'):
                file = source/name
                file.parent.mkdir(exist_ok=True)
                file.write_bytes(b'host delivery source')
            verify = package.stage.verify_release
            def verify_then_replace():
                result = verify(release, source)
                file = {'release':release/'reader-shell.mipsel',
                        'source':source/'main.cpp',
                        'manifest':release/'manifest.json'}[target]
                before = file.read_bytes()
                # Same length, different bytes: size-only validation cannot pass.
                file.write_bytes(bytes([before[0]^1])+before[1:])
                self.assertEqual(file.stat().st_size, len(before))
                return result
            with patch.object(package, 'ROOT', source), \
                 patch.object(package.stage, 'REVIEWED_MANIFEST_SHA', hashlib.sha256(manifest_bytes).hexdigest()), \
                 patch.object(package.stage, 'verify_release', side_effect=verify_then_replace):
                with self.assertRaisesRegex(ValueError, 'captured .* mismatch'):
                    package.create_package(base/'output')
            self.assertFalse((base/'output/reader-shell-phase1.tar.gz').exists())

    def test_same_size_release_replaced_after_verification_is_rejected(self):
        self.assert_rejects_capture_race('release')

    def test_same_size_source_replaced_after_verification_is_rejected(self):
        self.assert_rejects_capture_race('source')

    def test_same_size_manifest_replaced_after_verification_is_rejected(self):
        self.assert_rejects_capture_race('manifest')

    def test_package_contains_owned_sources_release_and_no_vendor_libraries(self):
        self.assertIsNotNone(package, 'delivery packager is missing')
        with patch.object(package.stage, 'REVIEWED_MANIFEST_SHA', hashlib.sha256((ROOT/'build/manifest.json').read_bytes()).hexdigest()), \
             tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            archive, inventory = package.create_package(Path(directory))
            with tarfile.open(archive) as bundle:
                names = bundle.getnames()
                self.assertIn('release/reader-shell.mipsel', names)
                self.assertIn('release/assets/wqy-microhei.ttc', names)
                self.assertIn('source/main.cpp', names)
                self.assertIn('source/stage_ram.py', names)
                self.assertIn('release/manifest.json', names)
                self.assertIn('DELIVERY.txt', names)
                self.assertFalse(any('.so' in name or name.endswith('.img') for name in names))
                manifest_bytes = bundle.extractfile('release/manifest.json').read()
                self.assertEqual(hashlib.sha256(manifest_bytes).hexdigest(), package.stage.REVIEWED_MANIFEST_SHA)
                manifest = json.loads(manifest_bytes)
                for record in manifest['artifacts']:
                    data = bundle.extractfile('release/'+record['path']).read()
                    self.assertEqual(len(data), record['bytes'])
                    self.assertEqual(hashlib.sha256(data).hexdigest(), record['sha256'])
                for name, digest in manifest['sources'].items():
                    self.assertEqual(hashlib.sha256(bundle.extractfile('source/'+name).read()).hexdigest(), digest)
                for name, digest in inventory['files'].items():
                    self.assertEqual(hashlib.sha256(bundle.extractfile(name).read()).hexdigest(), digest)

    def test_delivery_discloses_failed_touch_and_pending_font_cache_experiment(self):
        self.assertIn('QWS_NO_SHARE_FONTS=1', package.DELIVERY)
        self.assertIn('OOM', package.DELIVERY)
        self.assertIn('physical re-test pending', package.DELIVERY)

    def test_archive_is_reproducible(self):
        self.assertIsNotNone(package, 'delivery packager is missing')
        with patch.object(package.stage, 'REVIEWED_MANIFEST_SHA', hashlib.sha256((ROOT/'build/manifest.json').read_bytes()).hexdigest()), \
             tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            first, _ = package.create_package(Path(directory)/'a')
            second, _ = package.create_package(Path(directory)/'b')
            self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__=='__main__':
    unittest.main()
