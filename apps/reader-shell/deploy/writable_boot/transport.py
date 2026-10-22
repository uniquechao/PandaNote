#!/usr/bin/env python3
"""Independent reviewed writable-profile RAM transport. Default: local dry run.

Preparation metadata remains hardware_execution_permitted=false. Only explicit
--execute-once plus a fresh, source/plan/device-bound review promotes one attempt.
No persistent-write, erase, reset, retry, old-profile load/readiness, or installer
API exists here. A RAM handoff request does not prove boot or storage readiness.
"""
import argparse
import ast
import ctypes as C
from dataclasses import dataclass
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[3]
PROFILE='writable-development-v1'
SCOPE='one bounded writable-development RAM boot'
PROMOTION='reviewed independent transport entrypoint for one RAM attempt'
MANIFEST_SHA='11a16c58eca78d52c6d3a4c76196ae6c8ecf6271c42e337c8b746a937867ac53'
TRANSPORT=PROJECT/'pandanote-analysis/app-development-research/ram-linux-research/bootrom_ram_transport.py'
TRANSPORT_SHA='7ea5bac32167060acfc5cbeffc9c6363840bb01f0c8354e4ebeb11d5873c97a9'
LOCK_SHA='0a96c02b4d6993b9ca136a65b9c8a7f37e9893d4791db643481d51e018e1ae84'
DEADLINE_SECONDS=120
DEFAULT_REFERENCE=PROJECT/'.local-deps/reference-root'
SHARED_LOCK_ORIGIN=(Path(__import__('os').environ.get('PANDANOTE_REFERENCE_ROOT', 'external-inputs')) / 'pandanote-analysis/readback-guard/usb_access.py')
EXPECTED_LAYOUT=((0xb2401000,392),(0xb2401800,8232),(0x80010000,7815440),
                 (0x84000000,36),(0x84001000,3902),(0x81000000,1440))


def read_pinned(path,expected,length=None):
    if not stat.S_ISREG(path.lstat().st_mode):raise ValueError('non-regular source/artifact: '+str(path))
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=expected or (length is not None and len(data)!=length):
        raise ValueError('source/artifact identity changed: '+str(path))
    return data


def inert_definitions():
    source=read_pinned(TRANSPORT,TRANSPORT_SHA)
    nodes=[node for node in ast.parse(source).body
           if isinstance(node,(ast.ClassDef,ast.FunctionDef)) and node.name in ('Segment','digest')]
    if [node.name for node in nodes]!=['Segment','digest']:raise ValueError('inert definitions changed')
    namespace=dict(dataclass=dataclass,hashlib=hashlib)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(TRANSPORT),'exec'),namespace)
    return namespace['Segment'],namespace['digest']


Segment,digest=inert_definitions()


def lock_path(reference_root):
    path=reference_root/'pandanote-analysis/readback-guard/usb_access.py'
    if path.resolve()!=SHARED_LOCK_ORIGIN:
        raise ValueError('reference must resolve to the actual shared USB lease origin')
    return path


def load_plan(build=None,reference_root=DEFAULT_REFERENCE):
    build=ROOT/'build/candidate' if build is None else build
    manifest=json.loads(read_pinned(build/'manifest.json',MANIFEST_SHA))
    if (manifest['profile']!=PROFILE or manifest['hardware_execution_permitted'] is not False or
        manifest['device_apply_supported'] is not False or manifest['emmc_write_filter'] is not False):
        raise ValueError('unexpected writable preparation metadata')
    for name,expected in manifest['sources'].items():read_pinned(ROOT/name,expected)
    read_pinned(lock_path(reference_root),LOCK_SHA)
    read_pinned(build/'pid1.sh',manifest['pid1_sha256'])
    for entry in manifest['payload']:
        read_pinned(build/entry['file'],entry['sha256'],entry['bytes'])
    analysis=reference_root/'pandanote-analysis'
    plan=[]
    for address,entry in zip((0xb2401000,0xb2401800),manifest['reused_inputs']):
        plan.append(Segment(address,read_pinned(analysis/entry['file'],entry['sha256'],entry['bytes']),'verified DDR-only input'))
    for entry in manifest['segments']:
        plan.append(Segment(int(entry['address'],16),read_pinned(build/entry['file'],entry['sha256'],entry['bytes']),'writable RAM capsule'))
    entry=manifest['bootstrap']
    plan.append(Segment(int(entry['address'],16),read_pinned(build/entry['file'],entry['sha256'],entry['bytes']),'CRC/alias bootstrap'))
    if tuple((entry.address,len(entry.data)) for entry in plan)!=EXPECTED_LAYOUT:
        raise ValueError('requires exact reviewed six-segment RAM layout')
    return tuple(plan)


def plan_identity(plan):
    return [dict(address=hex(s.address),bytes=len(s.data),sha256=digest(s.data)) for s in plan]


def plan_digest(plan):return digest(json.dumps(plan_identity(plan),sort_keys=True,separators=(',',':')).encode())


def source_hashes(reference_root=DEFAULT_REFERENCE):
    manifest=json.loads(read_pinned(ROOT/'build/candidate/manifest.json',MANIFEST_SHA))
    paths={name:ROOT/name for name in manifest['sources']}
    paths.update({name:ROOT/name for name in ('transport.py','tests/test_transport.py','tests/test_policy.py','tests/test_capsule.py')})
    paths['candidate-manifest.json']=ROOT/'build/candidate/manifest.json'
    paths['reference/usb_access.py']=lock_path(reference_root)
    paths['original/inert-transport-source.py']=TRANSPORT
    return {name:digest(path.read_bytes()) for name,path in sorted(paths.items())}


def validate_target(target):
    if not isinstance(target,dict) or set(target)!=set(('vendor','product','bus','address','ports')):
        raise ValueError('readiness requires exact USB bus/address/ports identity')
    if target['vendor']!=0xa108 or target['product']!=0xeaef:raise ValueError('not X2000 BootROM VID/PID')
    if any(type(target[key]) is not int or not 1<=target[key]<=255 for key in ('bus','address')):
        raise ValueError('invalid USB location')
    if (not isinstance(target['ports'],list) or not 1<=len(target['ports'])<=8 or
        any(type(port) is not int or not 1<=port<=255 for port in target['ports'])):
        raise ValueError('invalid USB port path')
    return target


def verify_readiness(path,reference_root=DEFAULT_REFERENCE,now=None):
    if not stat.S_ISREG(path.lstat().st_mode) or stat.S_IMODE(path.stat().st_mode)!=0o600:
        raise ValueError('readiness must be a private regular 0600 file')
    raw=path.read_bytes()
    if len(raw)>65536:raise ValueError('oversized readiness')
    data=json.loads(raw)
    now=time.time() if now is None else now
    epoch=data.get('reviewed_epoch')
    if (data.get('schema')!=1 or data.get('profile')!=PROFILE or data.get('scope')!=SCOPE or
        data.get('execution_promotion')!=PROMOTION or data.get('review_verdict')!='no actionable defects remain' or
        type(epoch) is not int or not 0<=now-epoch<=1800 or data.get('physical_cycle_confirmed') is not True or
        data.get('observed_cpu_info')!='X2000' or data.get('manifest_sha256')!=MANIFEST_SHA or
        data.get('source_sha256')!=source_hashes(reference_root) or
        data.get('plan_sha256')!=plan_digest(load_plan(reference_root=reference_root))):
        raise ValueError('fresh review does not cover current writable sources/plan/physical cycle')
    if not isinstance(data.get('attempt_id'),str) or not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9-]{0,63}',data['attempt_id']):
        raise ValueError('invalid single-attempt identity')
    validate_target(data.get('expected_usb'))
    return data


def open_attempt(path):
    return os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w')


class DeviceDescriptor(C.Structure):
    _fields_=[('bLength',C.c_uint8),('bDescriptorType',C.c_uint8),('bcdUSB',C.c_uint16),
        ('bDeviceClass',C.c_uint8),('bDeviceSubClass',C.c_uint8),('bDeviceProtocol',C.c_uint8),
        ('bMaxPacketSize0',C.c_uint8),('idVendor',C.c_uint16),('idProduct',C.c_uint16),
        ('bcdDevice',C.c_uint16),('iManufacturer',C.c_uint8),('iProduct',C.c_uint8),
        ('iSerialNumber',C.c_uint8),('bNumConfigurations',C.c_uint8)]


class UniqueUSB:
    def __init__(self,expected,lib=None,deadline=None,clock=time.monotonic):
        self.expected=validate_target(expected) if expected is not None else None
        self.lib=lib if lib is not None else C.CDLL('/opt/homebrew/lib/libusb-1.0.dylib')
        self.ctx=C.c_void_p();self.handle=C.c_void_p();self.claimed=False;self.initialized=False
        self.deadline=deadline;self.clock=clock
        p=C.c_void_p
        signatures={
            'init':([C.POINTER(p)],C.c_int),
            'get_device_list':([p,C.POINTER(C.POINTER(p))],C.c_ssize_t),
            'free_device_list':([C.POINTER(p),C.c_int],None),
            'get_device_descriptor':([p,C.POINTER(DeviceDescriptor)],C.c_int),
            'get_bus_number':([p],C.c_uint8),'get_device_address':([p],C.c_uint8),
            'get_port_numbers':([p,C.POINTER(C.c_uint8),C.c_int],C.c_int),
            'open':([p,C.POINTER(p)],C.c_int),'close':([p],None),'exit':([p],None),
            'claim_interface':([p,C.c_int],C.c_int),'release_interface':([p,C.c_int],C.c_int),
            'control_transfer':([p,C.c_uint8,C.c_uint8,C.c_uint16,C.c_uint16,p,C.c_uint16,C.c_uint],C.c_int),
            'bulk_transfer':([p,C.c_ubyte,p,C.c_int,C.POINTER(C.c_int),C.c_uint],C.c_int)}
        for name,(args,result) in signatures.items():
            function=getattr(self.lib,'libusb_'+name);function.argtypes=args;function.restype=result

    def timeout(self,maximum):
        if self.deadline is None:return maximum
        remaining=self.deadline-self.clock()
        if remaining<=0:raise TimeoutError('120 second RAM deadline expired')
        return max(1,min(maximum,int(remaining*1000)))

    def initialize(self):
        self.timeout(1500)
        result=self.lib.libusb_init(C.byref(self.ctx))
        if result:raise RuntimeError('libusb init: '+str(result))
        self.initialized=True

    def enumerate(self,open_unique=False):
        devices=C.POINTER(C.c_void_p)()
        count=self.lib.libusb_get_device_list(self.ctx,C.byref(devices))
        if count<0:raise RuntimeError('USB enumeration failed: '+str(count))
        candidates=[]
        try:
            if count>4096:raise RuntimeError('USB inventory exceeds bound')
            for index in range(count):
                self.timeout(1500)
                descriptor=DeviceDescriptor();device=devices[index]
                if self.lib.libusb_get_device_descriptor(device,C.byref(descriptor))!=0:
                    raise RuntimeError('USB descriptor unreadable; uniqueness unknown')
                if (descriptor.idVendor,descriptor.idProduct)!=(0xa108,0xeaef):continue
                ports=(C.c_uint8*8)()
                depth=self.lib.libusb_get_port_numbers(device,ports,len(ports))
                if not 1<=depth<=8:raise RuntimeError('USB physical path unavailable')
                identity=dict(vendor=descriptor.idVendor,product=descriptor.idProduct,
                    bus=int(self.lib.libusb_get_bus_number(device)),
                    address=int(self.lib.libusb_get_device_address(device)),ports=list(ports[:depth]))
                validate_target(identity);candidates.append((device,identity))
            if open_unique:
                if len(candidates)!=1:raise RuntimeError('requires exactly one BootROM device; found '+str(len(candidates)))
                device,identity=candidates[0]
                if identity!=self.expected:raise RuntimeError('USB physical identity differs from readiness')
                self.timeout(1500)
                result=self.lib.libusb_open(device,C.byref(self.handle))
                if result or not self.handle:raise RuntimeError('exact BootROM open failed: '+str(result))
            return [identity for _,identity in candidates]
        finally:self.lib.libusb_free_device_list(devices,1)

    def __enter__(self):
        try:self.initialize();self.enumerate(open_unique=True);return self
        except BaseException:self.close();raise

    def cpu_info(self):
        buffer=C.create_string_buffer(8)
        count=self.lib.libusb_control_transfer(self.handle,0xc0,0,0,0,buffer,8,self.timeout(1500))
        if not 0<=count<=8:raise RuntimeError('BootROM CPU_INFO failed: '+str(count))
        return buffer.raw[:count]

    def out(self,request,value):
        if request not in (1,2,3,4,5) or type(value) is not int or not 0<=value<=0xffffffff:
            raise ValueError('non-RAM BootROM control forbidden')
        self.timeout(4000)
        if not self.claimed:
            result=self.lib.libusb_claim_interface(self.handle,0)
            if result:raise RuntimeError('claim interface: '+str(result))
            self.claimed=True
        result=self.lib.libusb_control_transfer(self.handle,0x40,request,value>>16,value&0xffff,None,0,self.timeout(4000))
        if result!=0:raise RuntimeError('BootROM control returned: '+str(result))

    def bulk_out(self,data):
        if not 0<len(data)<=65536:raise ValueError('RAM bulk chunk outside bound')
        actual=C.c_int();buffer=C.create_string_buffer(data)
        result=self.lib.libusb_bulk_transfer(self.handle,1,buffer,len(data),C.byref(actual),self.timeout(4000))
        if result:raise RuntimeError('RAM bulk OUT failed: '+str(result))
        return actual.value

    def close(self):
        if self.handle:
            if self.claimed:self.lib.libusb_release_interface(self.handle,0)
            self.lib.libusb_close(self.handle);self.handle=C.c_void_p()
        if self.initialized:self.lib.libusb_exit(self.ctx);self.initialized=False

    def __exit__(self,*args):self.close()


def inventory(lib=None):
    usb=UniqueUSB(None,lib=lib)
    try:usb.initialize();return usb.enumerate()
    finally:usb.close()


def run_plan(usb,plan,record,reference_root=DEFAULT_REFERENCE,pause=time.sleep,clock=time.monotonic,deadline=None):
    plan=tuple(Segment(s.address,bytes(s.data),s.label) for s in plan)
    if plan_identity(plan)!=plan_identity(load_plan(reference_root=reference_root)):
        raise ValueError('modified writable RAM plan refused')
    maximum_deadline=clock()+DEADLINE_SECONDS
    deadline=maximum_deadline if deadline is None else min(deadline,maximum_deadline)
    def check():
        if clock()>=deadline:raise TimeoutError('120 second RAM deadline expired; no retry')
    def out(request,value):
        check()
        if request not in (1,2,3,4,5):raise ValueError('non-RAM control forbidden')
        record(dict(event='control_before',request=request,value=hex(value)))
        usb.out(request,value);check()
    def ready():
        check();cpu=usb.cpu_info();check();record(dict(event='cpu_info',value_hex=cpu.hex()))
        if cpu!=b'X2000':raise RuntimeError('bare X2000 required; no retry')
    def upload(segment):
        record(dict(event='segment_before',address=hex(segment.address),bytes=len(segment.data),sha256=digest(segment.data)))
        out(1,segment.address);out(2,len(segment.data))
        for offset in range(0,len(segment.data),65536):
            check();chunk=segment.data[offset:offset+65536];count=usb.bulk_out(chunk);check()
            record(dict(event='bulk_completed',address=hex(segment.address+offset),expected=len(chunk),actual=count))
            if count!=len(chunk):raise RuntimeError('short RAM write; no retry')
    ready();upload(plan[0]);upload(plan[1]);out(4,0xb2401800)
    check();pause(1);check();ready()
    for segment in plan[2:]:upload(segment)
    out(3,0);out(5,0x81000000)
    record(dict(event='conditional_ram_handoff_requested',entry='0x81000000',linux_boot_proven=False))


def shared_lease(reference_root):
    path=lock_path(reference_root);namespace={'__file__':str(path)}
    exec(compile(read_pinned(path,LOCK_SHA),str(path),'exec'),namespace)
    return namespace['usb_access']('Reviewed independent writable RAM boot',blocking=False)


def execute_once(readiness_path,reference_root=DEFAULT_REFERENCE,usb_factory=UniqueUSB,lease_factory=shared_lease):
    readiness=verify_readiness(readiness_path,reference_root)
    plan=load_plan(reference_root=reference_root)
    journal_path=ROOT/'evidence'/('writable-boot-'+readiness['attempt_id']+'.jsonl')
    with open_attempt(journal_path) as journal:
        def record(event):
            event['time']=datetime.datetime.now().astimezone().isoformat()
            journal.write(json.dumps(event)+'\n');journal.flush();os.fsync(journal.fileno())
        record(dict(event='execution_promotion',profile=PROFILE,promotion=PROMOTION,
            preparation_manifest_sha256=MANIFEST_SHA,preparation_metadata_modified=False,
            readiness=readiness,automatic_retry=False))
        deadline=time.monotonic()+DEADLINE_SECONDS
        try:
            with lease_factory(reference_root) as lease:
                if lease is None:raise RuntimeError('shared USB lock busy; attempt consumed; no retry')
                # Recheck source/readiness after lease acquisition before opening hardware.
                if verify_readiness(readiness_path,reference_root)!=readiness:
                    raise ValueError('reviewed readiness changed after attempt capture')
                with usb_factory(readiness['expected_usb'],deadline=deadline) as usb:
                    run_plan(usb,plan,record,reference_root=reference_root,deadline=deadline)
            record(dict(event='transport_completed',linux_boot_proven=False,persistent_storage_mounted=False))
        except BaseException as error:
            record(dict(event='stopped',error=str(error),automatic_retry=False));raise
    return journal_path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-root',type=Path,default=DEFAULT_REFERENCE)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--execute-once',action='store_true')
    mode.add_argument('--list-candidates',action='store_true',help='explicit USB enumeration only; opens no target')
    parser.add_argument('--readiness',type=Path)
    args=parser.parse_args()
    if args.list_candidates:
        with shared_lease(args.reference_root) as lease:
            if lease is None:raise RuntimeError('shared USB lock busy; no inventory opened')
            result=inventory()
        print(json.dumps(dict(status='USB enumeration only; no target opened',candidates=result),indent=2));return
    plan=load_plan(reference_root=args.reference_root)
    if not args.execute_once:
        print(json.dumps(dict(status='verified local dry run; USB untouched',profile=PROFILE,
            preparation_manifest_sha256=MANIFEST_SHA,plan_sha256=plan_digest(plan),
            source_sha256=source_hashes(args.reference_root),segments=plan_identity(plan)),indent=2));return
    if args.readiness is None:parser.error('--execute-once requires fresh root-reviewed --readiness')
    path=execute_once(args.readiness,args.reference_root)
    print('One conditional RAM handoff requested; verify actual boot and new-profile runtime separately. Journal: '+str(path))


if __name__=='__main__':main()
