"""Host-only failure injection into the real proof finalizers; no vendor code."""
import base64
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'c1'))
import proof
from lifecycle import Children


class ProofTests(unittest.TestCase):
    def setUp(self):
        # Independently retained actual run, with the new mandatory size flag.
        self.good = json.loads((ROOT / 'evidence/c1/offline-repro.stdout.json').read_text())
        self.good['result']['oversize_trace'] = False

    def guest(self, payload):
        code = 'import json,sys;from proof import emit_guest_proof;p=json.load(sys.stdin);sys.exit(emit_guest_proof(p["result"],p["files"]))'
        return subprocess.run([sys.executable, '-c', code], input=json.dumps(payload), text=True,
                              capture_output=True, env={'PYTHONPATH': str(ROOT / 'c1')})

    def check_both_reject_preserving_evidence(self, payload):
        guest = self.guest(payload)
        with self.subTest(boundary='guest'):
            self.assertEqual(json.loads(guest.stdout), payload, 'guest must emit proof before rejection')
            self.assertNotEqual(guest.returncode, 0, 'guest must reject after emitting proof')
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as temp:
            prefix = Path(temp) / 'failed'
            raw = json.dumps(payload).encode()
            summary, status = proof.retain_result(prefix, raw, b'synthetic stderr', 0, 'host-fixture')
            self.assertEqual(prefix.with_suffix('.stdout.json').read_bytes(), raw)
            self.assertEqual(prefix.with_suffix('.stderr.txt').read_bytes(), b'synthetic stderr')
            self.assertEqual(json.loads(prefix.with_suffix('.result.json').read_text()), summary)
            self.assertTrue(summary['proof_errors'])
            for name, data in payload['files'].items():
                if name not in proof.LOG_NAMES:
                    continue
                try:
                    expected = base64.b64decode(data, validate=True)
                except ValueError:
                    continue
                self.assertEqual((prefix.parent / (prefix.name + '-' + name)).read_bytes(), expected)
            self.assertNotEqual(status, 0, 'parent must reject even an incorrectly green guest')

    def test_accepts_complete_observed_good_proof(self):
        self.assertEqual(self.guest(self.good).returncode, 0)
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as temp:
            _, status = proof.retain_result(Path(temp) / 'good', json.dumps(self.good).encode(), b'', 0, 'host-fixture')
            self.assertEqual(status, 0)

    def test_cleanup_exception_is_emitted_then_rejected(self):
        class BrokenCleanup(Children):
            def close(self):
                raise RuntimeError('injected reap failure')
        proof.collect_cleanup(BrokenCleanup(), self.good['result'])
        self.assertEqual(self.good['result']['cleanup_error'], 'injected reap failure')
        self.check_both_reject_preserving_evidence(self.good)

    def test_actual_unreaped_child_is_rejected(self):
        class SkippedCleanup(Children):
            def close(self):
                return []
        group = SkippedCleanup()
        child = group.spawn([sys.executable, '-c', 'import time;time.sleep(10)'])
        try:
            proof.collect_cleanup(group, self.good['result'])
            self.assertFalse(self.good['result']['all_children_reaped'])
            self.check_both_reject_preserving_evidence(self.good)
        finally:
            child.kill()
            child.wait(timeout=2)

    def test_forbidden_state_and_premature_bus_exit_rejected(self):
        for key, value in [('forbidden_state_exists', True), ('bus_alive_before_cleanup', False)]:
            with self.subTest(key=key):
                payload = copy.deepcopy(self.good)
                payload['result'][key] = value
                self.check_both_reject_preserving_evidence(payload)

    def test_oversized_real_trace_rejected_even_if_flag_claims_false(self):
        data = b'x' * (2 * 1024 * 1024 + 1)
        self.good['files']['bus.trace'] = base64.b64encode(data).decode()
        self.check_both_reject_preserving_evidence(self.good)

    def test_oversize_flag_rejected_even_with_small_files(self):
        self.good['result']['oversize_trace'] = True
        self.check_both_reject_preserving_evidence(self.good)

    def test_missing_or_wrong_typed_lifecycle_proof_rejected(self):
        for key in ['owned_cleanup', 'all_children_reaped', 'private_bus_ready', 'bus_alive_before_cleanup',
                    'forbidden_state_exists', 'oversize_trace', 'version', 'list_names', 'daemon_startup', 'private_paths']:
            for value in ['missing', 'wrong-type']:
                with self.subTest(key=key, value=value):
                    payload = copy.deepcopy(self.good)
                    if value == 'missing':
                        del payload['result'][key]
                    else:
                        payload['result'][key] = 'false'
                    self.check_both_reject_preserving_evidence(payload)

    def test_missing_trace_or_bad_cleanup_status_rejected(self):
        for change in ['missing-trace', 'cleanup-count', 'cleanup-status', 'forbidden-write']:
            with self.subTest(change=change):
                payload = copy.deepcopy(self.good)
                if change == 'missing-trace':
                    del payload['files']['bus.trace']
                elif change == 'cleanup-count':
                    payload['result']['owned_cleanup'] = ['terminated']
                elif change == 'cleanup-status':
                    payload['result']['owned_cleanup'][0] = 'unreaped'
                else:
                    payload['files']['bus.trace'] = base64.b64encode(b'15 mkdir("/var/lib/bluetooth",0700) = 0\n').decode()
                self.check_both_reject_preserving_evidence(payload)

    def test_malformed_request_and_file_proof_rejected(self):
        for change in ['wrong-stdout-type', 'empty-bus-trace', 'bad-base64', 'unsafe-name', 'wrong-mode', 'stale-socket']:
            with self.subTest(change=change):
                payload = copy.deepcopy(self.good)
                if change == 'wrong-stdout-type':
                    payload['result']['version']['stdout'] = 587
                elif change == 'empty-bus-trace':
                    payload['files']['bus.trace'] = ''
                elif change == 'bad-base64':
                    payload['files']['bus.trace'] = 'invalid*'
                elif change == 'unsafe-name':
                    payload['files']['../escape'] = 'eA=='
                elif change == 'wrong-mode':
                    payload['result']['private_paths'][proof.ROOT + '/run'] = '0o777'
                else:
                    payload['result']['private_paths'][proof.ROOT + '/run/bus'] = '0o600'
                self.check_both_reject_preserving_evidence(payload)

    def test_parent_rejects_failed_guest_with_good_proof(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as temp:
            _, status = proof.retain_result(Path(temp) / 'failed', json.dumps(self.good).encode(), b'', 1, 'host-fixture')
            self.assertNotEqual(status, 0)

    def test_parent_preserves_and_rejects_missing_malformed_proof(self):
        for raw in [b'', b'{', b'{}', b'{"result":{},"files":{}}']:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory(dir=ROOT / 'build') as temp:
                prefix = Path(temp) / 'failed'
                summary, status = proof.retain_result(prefix, raw, b'failure', 0, 'host-fixture')
                self.assertEqual(prefix.with_suffix('.stdout.json').read_bytes(), raw)
                self.assertTrue(summary['proof_errors'])
                self.assertNotEqual(status, 0)


if __name__ == '__main__':
    unittest.main()
