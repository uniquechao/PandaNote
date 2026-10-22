"""Real candidate bytes + fake USB/libusb. NEVER opens physical USB."""
import ctypes as C
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
module=None
if (ROOT/'transport.py').exists():
    spec=importlib.util.spec_from_file_location('writable_transport',ROOT/'transport.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
REFERENCE=(Path(__import__('os').environ.get('PANDANOTE_REFERENCE_ROOT', 'external-inputs')))


class FakeUSB:
    def __init__(self,cpu=None,short=False,advance=None):
        self.cpu=list(cpu or [b'X2000',b'X2000']);self.short=short;self.calls=[];self.advance=advance
    def cpu_info(self):self.calls.append(('cpu',));return self.cpu.pop(0)
    def out(self,request,value):self.calls.append(('out',request,value))
    def bulk_out(self,data):
        self.calls.append(('bulk',len(data),hashlib.sha256(data).hexdigest()))
        if self.advance:self.advance()
        return len(data)-1 if self.short else len(data)
    def __enter__(self):return self
    def __exit__(self,*args):pass


class Symbol:
    def __init__(self,call):self.call=call
    def __call__(self,*args):return self.call(*args)


class FakeLib:
    def __init__(self,devices):
        self.devices=devices;self.opened=[];self.closed=[];self.exits=0;self.freed=0
        for name in ('init','get_device_list','free_device_list','get_device_descriptor',
                     'get_bus_number','get_device_address','get_port_numbers','open',
                     'claim_interface','release_interface','close','exit',
                     'control_transfer','bulk_transfer'):
            setattr(self,'libusb_'+name,Symbol(getattr(self,name)))
    def init(self,ctx):ctx._obj.value=123;return 0
    def get_device_list(self,ctx,pointer):
        self.array=(C.c_void_p*(len(self.devices)+1))(*self.devices,0)
        C.cast(pointer,C.POINTER(C.POINTER(C.c_void_p)))[0]=C.cast(self.array,C.POINTER(C.c_void_p))
        return len(self.devices)
    def free_device_list(self,*args):self.freed+=1
    def get_device_descriptor(self,device,target):
        desc=C.cast(target,C.POINTER(module.DeviceDescriptor)).contents
        desc.idVendor,desc.idProduct=self.devices[device]
        return 0
    def get_bus_number(self,device):return 1
    def get_device_address(self,device):return device+20
    def get_port_numbers(self,device,target,size):target[0]=device;target[1]=2;return 2
    def open(self,device,handle):self.opened.append(device);handle._obj.value=1000+device;return 0
    def claim_interface(self,*args):return 0
    def release_interface(self,*args):return 0
    def close(self,handle):self.closed.append(handle.value)
    def exit(self,*args):self.exits+=1
    def control_transfer(self,*args):raise AssertionError('not used by enumeration tests')
    def bulk_transfer(self,*args):raise AssertionError('not used by enumeration tests')


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module,'independent writable transport missing')
        self.plan=module.load_plan(reference_root=REFERENCE)
        self.events=[]
    def run_plan(self,usb,**kw):
        return module.run_plan(usb,self.plan,self.events.append,reference_root=REFERENCE,pause=lambda n:None,**kw)
    def test_exact_six_segments_and_only_ram_controls(self):
        self.assertEqual([s.address for s in self.plan],[0xb2401000,0xb2401800,0x80010000,0x84000000,0x84001000,0x81000000])
        usb=FakeUSB();self.run_plan(usb)
        self.assertEqual(sum(c[0]=='cpu' for c in usb.calls),2)
        self.assertEqual({c[1] for c in usb.calls if c[0]=='out'},{1,2,3,4,5})
        self.assertEqual(usb.calls[-1],('out',5,0x81000000))
        expected=sum((len(s.data)+65535)//65536 for s in self.plan)
        self.assertEqual(sum(c[0]=='bulk' for c in usb.calls),expected)
    def test_plan_mutation_stops_before_cpu_or_ram(self):
        changed=list(self.plan);s=changed[0]
        changed[0]=module.Segment(s.address+4,s.data,s.label)
        usb=FakeUSB()
        with self.assertRaises(ValueError):
            module.run_plan(usb,changed,self.events.append,reference_root=REFERENCE)
        self.assertEqual(usb.calls,[])
    def test_wrong_initial_and_post_spl_cpu_never_load_kernel(self):
        for cpu in ([b'X2000_V1'],[b'X2000',b'X2000_R2']):
            usb=FakeUSB(cpu=cpu)
            with self.assertRaises(RuntimeError):self.run_plan(usb)
            self.assertNotIn(('out',1,0x80010000),usb.calls)
            self.assertNotIn(('out',5,0x81000000),usb.calls)
    def test_short_write_never_retries_or_runs_spl(self):
        usb=FakeUSB(short=True)
        with self.assertRaises(RuntimeError):self.run_plan(usb)
        self.assertEqual(sum(c[0]=='bulk' for c in usb.calls),1)
        self.assertFalse(any(c[:2]==('out',4) for c in usb.calls))
    def test_deadline_stops_before_later_io(self):
        now=[0.0]
        usb=FakeUSB(advance=lambda:now.__setitem__(0,121.0))
        with self.assertRaises(TimeoutError):self.run_plan(usb,clock=lambda:now[0])
        self.assertEqual(sum(c[0]=='bulk' for c in usb.calls),1)
    def test_mutable_caller_buffer_is_captured_before_any_io(self):
        changed=list(self.plan);kernel=changed[2]
        changed[2]=module.Segment(kernel.address,bytearray(kernel.data),kernel.label)
        usb=FakeUSB(advance=lambda:changed[2].data.__setitem__(0,changed[2].data[0]^1))
        module.run_plan(usb,changed,self.events.append,reference_root=REFERENCE,pause=lambda n:None)
        kernel_record=next(row for row in self.events if row.get('event')=='segment_before' and row['address']=='0x80010000')
        self.assertEqual(kernel_record['sha256'],hashlib.sha256(kernel.data).hexdigest())


class UniqueDeviceTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(module,'independent writable transport missing')
    def target(self):return dict(vendor=0xa108,product=0xeaef,bus=1,address=22,ports=[2,2])
    def test_only_exact_unique_device_is_opened(self):
        lib=FakeLib({1:(0x1111,0x2222),2:(0xa108,0xeaef)})
        with module.UniqueUSB(self.target(),lib=lib):pass
        self.assertEqual(lib.opened,[2]);self.assertEqual(lib.freed,1);self.assertEqual(lib.exits,1)
    def test_zero_multiple_or_wrong_physical_location_opens_nothing(self):
        for devices in ({1:(0x1111,0x2222)},{1:(0xa108,0xeaef),2:(0xa108,0xeaef)},
                        {3:(0xa108,0xeaef)}):
            lib=FakeLib(devices)
            with self.assertRaises(RuntimeError):
                with module.UniqueUSB(self.target(),lib=lib):pass
            self.assertEqual(lib.opened,[]);self.assertEqual(lib.exits,1)
    def test_explicit_inventory_never_opens_handle(self):
        lib=FakeLib({2:(0xa108,0xeaef)})
        self.assertEqual(module.inventory(lib=lib),[self.target()])
        self.assertEqual(lib.opened,[])
    def test_control_bounds_and_backend_count_are_enforced(self):
        lib=FakeLib({2:(0xa108,0xeaef)})
        with module.UniqueUSB(self.target(),lib=lib) as usb:
            with self.assertRaises(ValueError):usb.out(0x20,0)
            lib.libusb_control_transfer.call=lambda *args:1
            with self.assertRaises(RuntimeError):usb.out(1,0x84000000)
        self.assertEqual(lib.closed,[1002])
    def test_remaining_deadline_caps_each_usb_timeout(self):
        lib=FakeLib({2:(0xa108,0xeaef)})
        usb=module.UniqueUSB(self.target(),lib=lib,deadline=120,clock=lambda:119.75)
        self.assertEqual(usb.timeout(4000),250)
        usb.clock=lambda:120
        with self.assertRaises(TimeoutError):usb.timeout(4000)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module,'independent writable transport missing')
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'build');self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name)
        self.plan=module.load_plan(reference_root=REFERENCE)
    def data(self):
        return dict(schema=1,profile=module.PROFILE,scope=module.SCOPE,
            execution_promotion=module.PROMOTION,review_verdict='no actionable defects remain',
            reviewed_epoch=1000,physical_cycle_confirmed=True,observed_cpu_info='X2000',
            attempt_id='unit-fixture-only',expected_usb=dict(vendor=0xa108,product=0xeaef,bus=1,address=22,ports=[2,2]),
            manifest_sha256=module.MANIFEST_SHA,plan_sha256=module.plan_digest(self.plan),
            source_sha256=module.source_hashes(reference_root=REFERENCE))
    def write(self,data):
        path=self.p/'readiness.json';path.write_text(json.dumps(data));path.chmod(0o600);return path
    def test_readiness_is_fresh_and_bound_to_current_sources_plan_and_device(self):
        data=self.data();path=self.write(data)
        self.assertEqual(module.verify_readiness(path,reference_root=REFERENCE,now=1000)['expected_usb'],data['expected_usb'])
        for key,value in [('reviewed_epoch',-10000),('manifest_sha256','0'*64),('plan_sha256','0'*64),
                          ('source_sha256',{}),('physical_cycle_confirmed',False),('execution_promotion','old-readonly-profile')]:
            bad=dict(data);bad[key]=value
            with self.assertRaises(ValueError):module.verify_readiness(self.write(bad),reference_root=REFERENCE,now=1000)
    def test_journal_is_new_exclusive_and_private(self):
        path=self.p/'attempt.jsonl'
        with module.open_attempt(path) as output:output.write('fixture\n')
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        with self.assertRaises(FileExistsError):module.open_attempt(path)
        self.assertEqual(path.read_text(),'fixture\n')
    def test_busy_shared_lease_consumes_attempt_without_opening_usb(self):
        data=self.data();data['reviewed_epoch']=int(time.time());path=self.write(data)
        opened=[]
        @contextmanager
        def busy(reference):yield None
        def fake_open(path):
            opened.append(path.name)
            return module.open_attempt_original(self.p/'journal.jsonl')
        original=module.open_attempt
        with patch.object(module,'open_attempt_original',original,create=True),patch.object(module,'open_attempt',fake_open):
            with self.assertRaisesRegex(RuntimeError,'lock busy'):
                module.execute_once(path,REFERENCE,usb_factory=lambda *a,**k:self.fail('USB opened while busy'),lease_factory=busy)
        self.assertEqual(opened,['writable-boot-unit-fixture-only.jsonl'])
        events=[json.loads(line) for line in (self.p/'journal.jsonl').read_text().splitlines()]
        self.assertEqual(events[-1]['event'],'stopped')
        self.assertFalse(events[0]['preparation_metadata_modified'])
    def test_actual_shared_lock_code_blocks_second_fixture_lease(self):
        source=module.read_pinned(module.lock_path(REFERENCE),module.LOCK_SHA)
        namespace={'__file__':str(self.p/'usb_access.py')}
        exec(compile(source,'fixture-shared-lock','exec'),namespace)
        with namespace['usb_access']('fixture only',blocking=False) as first:
            self.assertIsNotNone(first)
            with namespace['usb_access']('fixture contender',blocking=False) as second:
                self.assertIsNone(second)


if __name__=='__main__':unittest.main(verbosity=2)
