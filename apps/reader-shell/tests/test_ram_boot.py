"""Accepted real bytes, fake USB only. Never opens hardware."""
import importlib.util
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import stage_ram as stage
sys.path.insert(0, str(ROOT/'deploy'))
try:
    import ram_boot as boot
except ImportError:
    boot = None


class USB:
    def __init__(self):
        self.calls = []
        self.cpu = b'X2000'
        self.partial = False
    def cpu_info(self):
        self.calls.append(('cpu',))
        return self.cpu
    def out(self, request, value):
        self.calls.append(('out', request, value))
    def bulk_out(self, data):
        self.calls.append(('bulk', len(data)))
        return len(data)-int(self.partial)


class BootTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(boot, 'narrow accepted-profile adapter missing')
        # Candidate release acceptance is local to this fake-USB test. Boot
        # inputs and release bytes still pass their real pinned verifiers.
        pin = patch.object(stage, 'REVIEWED_MANIFEST_SHA', hashlib.sha256((ROOT/'build/manifest.json').read_bytes()).hexdigest())
        self.addCleanup(pin.stop)
        pin.start()
        self.plan = boot.load_plan()
        self.usb = USB()
        self.events = []
    def run_plan(self, **kw):
        boot.run_plan(self.usb, self.plan, self.events.append, pause=lambda _: None, **kw)
    def test_actual_profile_addresses_and_pins(self):
        self.assertEqual([s.address for s in self.plan], [0xb2401000,0xb2401800,0x80010000,0x84000000,0x84001000,0x84010000,0x81000000])
        self.assertEqual(boot.digest(self.plan[-1].data), boot.BOOTSTRAP_SHA)
    def test_upload_order_one_handoff_no_cpu_after_capsule_load(self):
        self.run_plan()
        self.assertEqual(self.usb.calls[-2:], [('out',3,0),('out',5,0x81000000)])
        self.assertEqual(sum(c==('cpu',) for c in self.usb.calls),2)
        self.assertFalse(any(c[0]=='cpu' for c in self.usb.calls[self.usb.calls.index(('out',1,0x80010000)):]))
        self.assertEqual(self.events[-2]['event'],'control_out_before')
        self.assertIn('conditional_ram_handoff_requested',[e['event'] for e in self.events])
    def test_rogue_plan_rejected_before_usb(self):
        self.plan[2] = boot.Segment(self.plan[2].address, b'rogue', 'rogue')
        with self.assertRaisesRegex(ValueError,'modified'):
            self.run_plan()
        self.assertEqual(self.usb.calls,[])
    def test_partial_transfer_stops_without_retry_or_handoff(self):
        self.usb.partial = True
        with self.assertRaisesRegex(RuntimeError,'Partial'):
            self.run_plan()
        self.assertEqual(sum(c[0]=='bulk' for c in self.usb.calls),1)
        self.assertFalse(any(c[:2]==('out',5) for c in self.usb.calls))
    def test_nonbare_cpu_stops_before_any_out(self):
        self.usb.cpu = b'X2000_V1'
        with self.assertRaisesRegex(RuntimeError,'bare X2000'):
            self.run_plan()
        self.assertEqual(self.usb.calls,[('cpu',)])
    def test_single_deadline_covers_usb_calls(self):
        now=[0]
        def clock():
            now[0] += 31
            return now[0]
        with self.assertRaisesRegex(TimeoutError,'deadline'):
            self.run_plan(clock=clock)
        self.assertFalse(any(c[:2]==('out',5) for c in self.usb.calls))
    def test_repeated_attempt_file_is_exclusive(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as d:
            path=Path(d)/'attempt.jsonl'
            with boot.open_attempt(path):
                pass
            with self.assertRaises(FileExistsError):
                boot.open_attempt(path)
    def test_readiness_requires_fresh_review_of_all_current_sources(self):
        import tempfile,json
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as d:
            path=Path(d)/'readiness.json'
            value=dict(profile=boot.PROFILE,scope='one bounded RAM diagnostic attempt',
                review_verdict='no actionable defects remain',reviewed_epoch=10000,source_sha256=boot.source_hashes())
            path.write_text(json.dumps(value))
            boot.verify_readiness(path,now=10001)
            for change in ({'reviewed_epoch':1},{'profile':'old'}, {'source_sha256':{}}, {'review_verdict':'pending'}):
                path.write_text(json.dumps(dict(value,**change)))
                with self.assertRaisesRegex(ValueError,'Fresh root review'):
                    boot.verify_readiness(path,now=10001)
    def test_payload_bytes_are_captured_before_usb_observation(self):
        mutable=bytearray(self.plan[0].data)
        self.plan[0]=boot.Segment(self.plan[0].address,mutable,'parameters')
        original=self.usb.cpu_info
        def cpu():
            mutable[0]^=1
            return original()
        self.usb.cpu_info=cpu
        self.run_plan()
        self.assertEqual(self.events[1]['sha256'],boot.PARAM_SHA)
    def test_changed_capsule_fails_before_usb(self):
        import tempfile,shutil
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as d:
            target=Path(d)/'capsule'
            shutil.copytree(ROOT/'deploy/sdio_guard/build',target)
            (target/'ram-84010000.bin').write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError,'Unverified'):
                boot.load_plan(target)
        self.assertEqual(self.usb.calls,[])

if __name__=='__main__':
    unittest.main()
