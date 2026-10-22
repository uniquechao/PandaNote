"""Real clone filesystem tests; none execute a payload or touch a device.

Mutations caught: skip prehash/path/type/backup checks, entry-first switching,
forget durable writes, ignore interrupted state, or accept failed boot evidence.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

DEPLOY = Path(__file__).resolve().parents[1]
PROJECT = DEPLOY.parents[2]
sys.path.insert(0, str(DEPLOY))
try:
    import install_support as subject
except ModuleNotFoundError:
    subject = None


def sha(data):
    return hashlib.sha256(data).hexdigest()


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(subject, 'manifest-bound clone installer is not implemented')
        self.scratch = tempfile.TemporaryDirectory(prefix='install-test-', dir=DEPLOY)
        self.addCleanup(self.scratch.cleanup)
        self.work = Path(self.scratch.name)
        self.root = self.work / 'clone'
        self.root.mkdir()
        (self.root / '.pandanote-install-clone').write_text('local-filesystem-rehearsal-v1\n')
        self.bundle = self.work / 'bundle'
        self.bundle.mkdir()
        self.old = b'#!/bin/sh\nprintf stock-entry\n'
        self.new = b'#!/bin/sh\nprintf rehearsal-entry\n'
        self.payload = b'LOCAL TEST DATA, NOT AN ELF\n'
        for path in ['etc/init.d', 'home/pandanote-reader', 'user/books']:
            (self.root / path).mkdir(parents=True, exist_ok=True)
        self.entry = self.root / 'etc/init.d/rcS'
        self.entry.write_bytes(self.old)
        self.entry.chmod(0o755)
        (self.root / 'user/books/keep.epub').write_bytes(b'book untouched')
        (self.bundle / 'entry').write_bytes(self.new)
        (self.bundle / 'payload').write_bytes(self.payload)
        self.manifest = {
            'schema': 1, 'scope': 'local-clone-only', 'target': 'Guowen 966U2',
            'blockers': [], 'backup_root': '/home/pandanote-reader/rollback',
            'files': [
                {'role': 'payload', 'path': '/home/pandanote-reader/versions/demo/reader',
                 'source': 'payload', 'old_sha256': None, 'new_sha256': sha(self.payload), 'mode': 0o755},
                {'role': 'entry', 'path': '/etc/init.d/rcS', 'source': 'entry',
                 'old_sha256': sha(self.old), 'old_mode': 0o755, 'new_sha256': sha(self.new), 'mode': 0o755}],
        }

    def apply(self, **kwargs):
        return subject.apply_clone(self.root, self.bundle, self.manifest, **kwargs)

    def recovery(self):
        return subject.rollback_clone(self.root, self.manifest)

    def assert_old(self):
        self.assertEqual(self.entry.read_bytes(), self.old)
        self.assertEqual((self.root / 'user/books/keep.epub').read_bytes(), b'book untouched')

    def test_plan_has_no_writes_and_real_candidate_is_blocked(self):
        before = set(self.root.rglob('*'))
        result = subject.plan(self.manifest)
        self.assertEqual(result['status'], 'clone-rehearsal-only')
        self.assertEqual(set(self.root.rglob('*')), before)
        actual = json.loads((DEPLOY / 'install-plan.json').read_text())
        self.assertEqual(subject.plan(actual)['status'], 'blocked')
        with self.assertRaises(subject.InstallError):
            subject.apply_clone(self.root, self.bundle, actual)

    def test_hash_failure_leaves_entry_and_books_untouched(self):
        self.entry.write_bytes(b'unexpected old entry')
        with self.assertRaisesRegex(subject.InstallError, 'old hash'):
            self.apply()
        self.assertEqual(self.entry.read_bytes(), b'unexpected old entry')
        self.assertFalse((self.root / 'home/pandanote-reader/versions').exists())

    def test_source_hash_failure_prevents_any_switch(self):
        (self.bundle / 'payload').write_bytes(b'corrupt')
        with self.assertRaisesRegex(subject.InstallError, 'source hash'):
            self.apply()
        self.assert_old()

    def test_missing_source_does_not_create_transaction(self):
        (self.bundle / 'entry').unlink()
        with self.assertRaises(subject.InstallError):
            self.apply()
        self.assert_old()

    def test_traversal_absolute_source_and_shadowing_rejected(self):
        for field, value in [('path', '/etc/../private/SN.txt'), ('source', '../escape'),
                             ('source', '/etc/passwd'), ('path', '/user/books/keep.epub')]:
            with self.subTest(field=field, value=value):
                broken = copy.deepcopy(self.manifest)
                broken['files'][0][field] = value
                with self.assertRaises(subject.InstallError):
                    subject.apply_clone(self.root, self.bundle, broken)
                self.assert_old()
        broken = copy.deepcopy(self.manifest)
        broken['files'][0]['path'] = '/etc/init.d/rcS/child'
        with self.assertRaises(subject.InstallError):
            subject.plan(broken)

    def test_duplicate_entry_and_payload_paths_rejected(self):
        broken = copy.deepcopy(self.manifest)
        broken['files'][0]['path'] = broken['files'][1]['path']
        with self.assertRaises(subject.InstallError):
            subject.plan(broken)

    def test_symlink_ancestor_and_source_rejected(self):
        (self.root / 'home/pandanote-reader').rmdir()
        (self.root / 'home/pandanote-reader').symlink_to(self.bundle)
        with self.assertRaises(subject.InstallError):
            self.apply()
        self.assert_old()
        (self.root / 'home/pandanote-reader').unlink()
        (self.root / 'home/pandanote-reader').mkdir()
        (self.bundle / 'payload').unlink()
        (self.bundle / 'payload').symlink_to(self.bundle / 'entry')
        with self.assertRaises(subject.InstallError):
            self.apply()
        self.assert_old()

    def test_hardlink_entry_rejected(self):
        os.link(self.entry, self.root / 'entry-alias')
        with self.assertRaises(subject.InstallError):
            self.apply()
        self.assert_old()

    def test_backup_must_be_persistent_and_separate(self):
        for value in ['/tmp/backup', '/home/pandanote-reader/versions/demo', '/etc/init.d/rcS']:
            broken = copy.deepcopy(self.manifest)
            broken['backup_root'] = value
            with self.assertRaises(subject.InstallError):
                subject.apply_clone(self.root, self.bundle, broken)
            self.assert_old()

    def test_unmarked_clone_refused(self):
        (self.root / '.pandanote-install-clone').unlink()
        with self.assertRaisesRegex(subject.InstallError, 'clone marker'):
            self.apply()
        self.assert_old()

    def test_install_and_rollback_preserve_persistent_backup_and_modes(self):
        result = self.apply()
        self.assertEqual(result['state'], 'awaiting-verification')
        self.assertEqual(self.entry.read_bytes(), self.new)
        backup = self.root / result['backup'].lstrip('/')
        self.assertEqual((backup / 'old/1').read_bytes(), self.old)
        self.assertEqual((backup / 'manifest.json').read_text(), subject.canonical(self.manifest))
        self.recovery()
        self.assert_old()
        self.assertEqual(self.entry.stat().st_mode & 0o777, 0o755)
        self.assertTrue((backup / 'old/1').exists())
        self.recovery()
        self.assert_old()

    def test_failed_boot_verification_restores_entry(self):
        self.apply()
        with self.assertRaisesRegex(subject.InstallError, 'verification failed'):
            subject.verify_clone(self.root, self.manifest, {'display': False, 'touch': True,
                                 'calendar': True, 'offline': True, 'stable': True})
        self.assert_old()

    def test_all_boot_checks_required_and_success_remains_clone_only(self):
        self.apply()
        with self.assertRaises(subject.InstallError):
            subject.verify_clone(self.root, self.manifest, {})
        self.assert_old()
        self.apply()
        result = subject.verify_clone(self.root, self.manifest,
                   dict.fromkeys(['display', 'touch', 'calendar', 'offline', 'stable'], True))
        self.assertEqual(result['state'], 'clone-verified')
        self.recovery()
        self.assert_old()

    def test_chmod_only_entry_verification_rejects_and_restores_original(self):
        result = self.apply()
        self.entry.chmod(0o644)
        self.assertEqual(self.entry.read_bytes(), self.new)
        with self.assertRaisesRegex(subject.InstallError, 'verification current mode mismatch'):
            subject.verify_clone(self.root, self.manifest,
                dict.fromkeys(['display', 'touch', 'calendar', 'offline', 'stable'], True))
        self.assert_old()
        self.assertEqual(self.entry.stat().st_mode & 0o7777, 0o755)
        backup = self.root / result['backup'].lstrip('/')
        self.assertEqual(json.loads((backup / 'journal.json').read_text())['state'], 'rolled-back')
        self.assertEqual((backup / 'old/1').read_bytes(), self.old)
        self.assertFalse((self.root / self.manifest['files'][0]['path'].lstrip('/')).exists())

    def test_chmod_only_payload_verification_rejects_and_restores_original(self):
        result = self.apply()
        payload = self.root / self.manifest['files'][0]['path'].lstrip('/')
        payload.chmod(0o644)
        self.assertEqual(payload.read_bytes(), self.payload)
        with self.assertRaisesRegex(subject.InstallError, 'verification current mode mismatch'):
            subject.verify_clone(self.root, self.manifest,
                dict.fromkeys(['display', 'touch', 'calendar', 'offline', 'stable'], True))
        self.assert_old()
        self.assertEqual(self.entry.stat().st_mode & 0o7777, 0o755)
        backup = self.root / result['backup'].lstrip('/')
        self.assertEqual(json.loads((backup / 'journal.json').read_text())['state'], 'rolled-back')
        self.assertEqual((backup / 'old/1').read_bytes(), self.old)
        self.assertFalse(payload.exists())

    def test_interrupted_stage_switch_and_journal_recover_idempotently(self):
        # Each point is after a durable on-disk transition, including the window
        # after entry rename but before the awaiting-verification journal.
        for point in ['backed-up', 'payload-staged', 'before-entry-switch', 'entry-switched']:
            with self.subTest(point=point):
                def power_loss(event):
                    if event == point:
                        raise KeyboardInterrupt('simulated power loss')
                with self.assertRaises(KeyboardInterrupt):
                    self.apply(checkpoint=power_loss)
                with self.assertRaisesRegex(subject.InstallError, 'recover'):
                    self.apply()
                self.recovery()
                self.recovery()
                self.assert_old()

    def test_rollback_failure_can_retry_without_losing_last_entry(self):
        self.apply()
        def loss(point):
            if point == 'entry-restored':
                raise KeyboardInterrupt('simulated recovery interruption')
        with self.assertRaises(KeyboardInterrupt):
            subject.rollback_clone(self.root, self.manifest, checkpoint=loss)
        self.assert_old()
        self.recovery()
        self.assert_old()

    def test_missing_or_bad_backup_never_overwrites_entry(self):
        result = self.apply()
        backup = self.root / result['backup'].lstrip('/') / 'old/1'
        old = backup.read_bytes()
        backup.unlink()
        with self.assertRaises(subject.InstallError):
            self.recovery()
        self.assertEqual(self.entry.read_bytes(), self.new)
        backup.write_bytes(b'bad backup')
        with self.assertRaises(subject.InstallError):
            self.recovery()
        self.assertEqual(self.entry.read_bytes(), self.new)
        backup.write_bytes(old)
        backup.chmod(0o755)
        self.recovery()
        self.assert_old()

    def test_manifest_mismatch_and_post_switch_tamper_refused(self):
        self.apply()
        broken = copy.deepcopy(self.manifest)
        broken['target'] = 'another device'
        with self.assertRaises(subject.InstallError):
            subject.rollback_clone(self.root, broken)
        self.entry.write_bytes(b'unknown entry')
        with self.assertRaisesRegex(subject.InstallError, 'current hash'):
            self.recovery()
        self.assertEqual(self.entry.read_bytes(), b'unknown entry')

    def test_durable_event_trace_orders_backup_before_entry(self):
        trace = []
        self.apply(checkpoint=trace.append)
        self.assertLess(trace.index('backed-up'), trace.index('entry-switched'))
        self.assertLess(trace.index('payload-staged'), trace.index('entry-switched'))
        self.assertIn('before-entry-switch', trace)

    def test_wrong_old_mode_and_backup_mode_tamper_refused(self):
        # Losing the executable bit must not create an unbootable restored entry.
        self.entry.chmod(0o644)
        with self.assertRaisesRegex(subject.InstallError, 'old mode'):
            self.apply()
        self.entry.chmod(0o755)
        result = self.apply()
        backup = self.root / result['backup'].lstrip('/') / 'old/1'
        backup.chmod(0o644)
        with self.assertRaisesRegex(subject.InstallError, 'backup mode'):
            self.recovery()
        self.assertEqual(self.entry.read_bytes(), self.new)
        backup.chmod(0o755)
        self.recovery()
        self.assert_old()

    def test_payload_cannot_replace_existing_file(self):
        # Version directories are immutable; an upgrade requires a new path.
        dest = self.root / self.manifest['files'][0]['path'].lstrip('/')
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b'prior version')
        self.manifest['files'][0]['old_sha256'] = sha(b'prior version')
        with self.assertRaisesRegex(subject.InstallError, 'new version'):
            self.apply()
        self.assert_old()

    def test_abrupt_process_exit_after_switch_is_recoverable(self):
        manifest = self.work / 'manifest.json'
        manifest.write_text(json.dumps(self.manifest))
        code = ("import sys,json,os;sys.path.insert(0,sys.argv[1]);"
                "import install_support as s;"
                "s.apply_clone(sys.argv[2],sys.argv[3],json.load(open(sys.argv[4])),"
                "checkpoint=lambda event: os._exit(73) if event=='entry-switched' else None)")
        proc = subprocess.run([sys.executable, '-c', code, str(DEPLOY),
                               str(self.root), str(self.bundle), str(manifest)])
        self.assertEqual(proc.returncode, 73)
        self.assertEqual(self.entry.read_bytes(), self.new)
        out = subprocess.run([sys.executable, str(DEPLOY / 'rollback.py'),
                              '--manifest', str(manifest), '--apply-clone', str(self.root)],
                             text=True, capture_output=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assert_old()

    def test_cli_defaults_to_read_only_blocked_plan(self):
        out = subprocess.run([sys.executable, str(DEPLOY / 'install.py')],
                             capture_output=True, text=True, cwd=PROJECT)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)['status'], 'blocked')
        out = subprocess.run([sys.executable, str(DEPLOY / 'install.py'), '--device'],
                             capture_output=True, text=True, cwd=PROJECT)
        self.assertNotEqual(out.returncode, 0)


if __name__ == '__main__':
    unittest.main()
