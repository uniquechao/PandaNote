#!/usr/bin/env python3
"""One reviewed MSC1-profile RAM handoff. Default verifies local inputs only.

The golden transport/readiness remains untouched. The bounded upload sequence
below derives from its pinned run_plan, with this profile's explicit plan and a
single overall deadline. A requested handoff is never proof of a Linux boot.
"""
import argparse
import ast
import ctypes as C
from dataclasses import dataclass
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
APP = ROOT.parent
PROJECT = APP.parents[1]
REFERENCE = PROJECT/'.local-deps/reference-root/pandanote-analysis'
PROFILE = 'msc1-sdio-wlan0-opt-ro-v1'
TRANSPORT = PROJECT/'pandanote-analysis/app-development-research/ram-linux-research/bootrom_ram_transport.py'
TRANSPORT_SHA = '7ea5bac32167060acfc5cbeffc9c6363840bb01f0c8354e4ebeb11d5873c97a9'
USB_LOCK = REFERENCE/'readback-guard/usb_access.py'
USB_LOCK_SHA = '0a96c02b4d6993b9ca136a65b9c8a7f37e9893d4791db643481d51e018e1ae84'
MANIFEST_SHA = '2e748d9e4afe67bc5ec2c259b515c01c0410f53e61f011cabc45a4658978a547'
BOOTSTRAP_SHA = 'd050610bd76deadf4d7ef8b4c6a265cd80fcba73f5538899dd0f1e2c6e36edac'
PID1_SHA = '1ed1ef64aa71af447679e179efa69e6852902255e1ff056de9ee710b86cd354d'
PARAM_SHA = '4c93fa36efc87fbf925e63a8779dd1ce817ab4c14fe1f42003559b12f716beb6'
SPL_SHA = '61522b6712cf03616949b4415d8a292cff5c55e06b0088ab29e0ffe2f62abc91'
DEADLINE_SECONDS = 120
CAPSULE_SOURCES = {
    'ram_capsule.py':'73222e5475620eee3ccf11366a31a6afc0f2bf15b9458d83e331fbb6345331fa',
    'build_capsule.py':'bf8b2b08b7d0a6929853963f3435d8e394b1ed9d11f9d6acc1ac45f2fbf5d6dc',
    'prepare_profile.py':'8d2e20a135cf9af82ed63340ae78cc492614b2111d130cf268656b407106a489',
    'storage-guard.S':'9fffa51c4df0914d651692a6f10540695c6b88d88bbd731c0636f5685399685e',
    'pid1-ram.sh':PID1_SHA,
}


def _transport_definitions():
    """Reuse exactly three inert definitions, never original load/run/readiness.

    AST extraction avoids importing the old capsule module or executing any
    original module-level code. The complete original source is hash pinned.
    """
    raw=TRANSPORT.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=TRANSPORT_SHA:
        raise ValueError('Original transport source changed')
    tree=ast.parse(raw, filename=str(TRANSPORT))
    nodes=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in ('Segment','digest','LibUSB')]
    if [n.name for n in nodes]!=['Segment','digest','LibUSB']:
        raise ValueError('Original transport definitions missing')
    namespace=dict(C=C,dataclass=dataclass,hashlib=hashlib)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(TRANSPORT),'exec'),namespace)
    return namespace['Segment'],namespace['digest'],namespace['LibUSB']


Segment,digest,LibUSB = _transport_definitions()


def _read(path, expected, length=None):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Missing or symlink boot input: '+str(path))
    blob=path.read_bytes()
    if digest(blob)!=expected or (length is not None and len(blob)!=length):
        raise ValueError('Unverified boot input: '+str(path))
    return blob


def load_plan(build=ROOT/'sdio_guard/build'):
    # The new application must be a real accepted release, even for dry run.
    sys.path.insert(0,str(APP))
    import stage_ram
    stage_ram.verify_release()
    _read(USB_LOCK,USB_LOCK_SHA)
    for name,expected in CAPSULE_SOURCES.items():
        _read(ROOT/'sdio_guard'/name,expected)
    manifest=json.loads(_read(ROOT/'sdio_guard/evidence/build-manifest.json',MANIFEST_SHA))
    if manifest['profile']!=PROFILE or manifest['linux_memory']!='64M@0' or manifest['commandline_bytes']!=3807:
        raise ValueError('Unexpected reviewed RAM profile')
    _read(build/'pid1-ram.sh',PID1_SHA)
    plan=[Segment(0xb2401000,_read(REFERENCE/'readback-guard/ginfo-MSC0-PD17-PD22-CANDIDATE.bin',PARAM_SHA,392),'known DDR parameters'),
          Segment(0xb2401800,_read(REFERENCE/'cloner-2.5.50/cloner-2.5.50-ubuntu_alpha/firmwares/x2000/spl.bin',SPL_SHA),'known DDR-only SPL')]
    for item in manifest['segments']:
        plan.append(Segment(int(item['address'],16),_read(build/item['file'],item['sha256'],item['bytes']),'reviewed RAM capsule'))
    plan.append(Segment(0x81000000,_read(build/'bootstrap-selfcheck.bin',BOOTSTRAP_SHA,1456),'RAM alias/CRC selfcheck and conditional handoff'))
    return plan


def run_plan(usb, plan, record, pause=time.sleep, clock=time.monotonic):
    # Capture immutable segment bytes before validation or the first USB call.
    plan=tuple(Segment(s.address,bytes(s.data),s.label) for s in plan)
    expected=load_plan()
    identity=lambda p:[(s.address,len(s.data),digest(s.data)) for s in p]
    if identity(plan)!=identity(expected):
        raise ValueError('Refuse modified RAM plan')
    deadline=clock()+DEADLINE_SECONDS
    def check():
        if clock()>=deadline:
            raise TimeoutError('RAM attempt deadline expired; no automatic retry')
    def out(request,value):
        check()
        if request not in (1,2,3,4,5):
            raise ValueError('Non-BootROM request forbidden')
        record(dict(event='control_out_before',request=request,value=hex(value)))
        usb.out(request,value)
        check()
        record(dict(event='control_out_completed',request=request))
    def ready():
        check()
        cpu=usb.cpu_info()
        check()
        record(dict(event='cpu_info',value_hex=cpu.hex()))
        if cpu!=b'X2000':
            raise RuntimeError('Requires bare X2000 BootROM; no automatic retry')
    def upload(segment):
        record(dict(event='segment_before',address=hex(segment.address),bytes=len(segment.data),sha256=digest(segment.data)))
        out(1,segment.address)
        out(2,len(segment.data))
        for offset in range(0,len(segment.data),65536):
            check()
            chunk=segment.data[offset:offset+65536]
            count=usb.bulk_out(chunk)
            check()
            record(dict(event='ram_chunk_completed',address=hex(segment.address+offset),expected=len(chunk),actual=count))
            if count!=len(chunk):
                raise RuntimeError('Partial RAM transfer; do not retry')
    ready()
    upload(plan[0]); upload(plan[1])
    out(4,0xb2401800)
    pause(1)
    ready()
    for segment in plan[2:]:
        upload(segment)
    out(3,0)
    record(dict(event='conditional_ram_handoff_requested',entry='0x81000000'))
    out(5,0x81000000)


def source_hashes():
    paths=['apps/reader-shell/deploy/ram_boot.py','apps/reader-shell/stage_ram.py',
           'apps/reader-shell/deploy/sdio_guard/ram_capsule.py','apps/reader-shell/deploy/sdio_guard/pid1-ram.sh',
           'apps/reader-shell/deploy/sdio_guard/evidence/build-manifest.json',
           'apps/reader-shell/tests/test_ram_boot.py','apps/reader-shell/tests/test_stage_profiles.py',
           'apps/reader-shell/tests/test_stage_ram.py',str(TRANSPORT.relative_to(PROJECT))]
    result={p:digest((PROJECT/p).read_bytes()) for p in paths}
    result.update({'apps/reader-shell/deploy/sdio_guard/'+name:digest(_read(ROOT/'sdio_guard'/name,expected)) for name,expected in CAPSULE_SOURCES.items()})
    result['reference/readback-guard/usb_access.py']=digest(_read(USB_LOCK,USB_LOCK_SHA))
    return result


def verify_readiness(path, now=None):
    raw=path.read_bytes()
    if path.is_symlink() or len(raw)>65536:
        raise ValueError('Invalid readiness file')
    data=json.loads(raw)
    now=time.time() if now is None else now
    reviewed=data.get('reviewed_epoch')
    if (data.get('profile')!=PROFILE or data.get('scope')!='one bounded RAM diagnostic attempt' or
        data.get('review_verdict')!='no actionable defects remain' or
        type(reviewed) is not int or not 0<=now-reviewed<=1800 or
        data.get('source_sha256')!=source_hashes()):
        raise ValueError('Fresh root review/readiness does not cover current profile sources')
    # Real accepted artifacts are revalidated; metadata cannot open an old gate.
    load_plan()
    return data


def open_attempt(path):
    return os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-once',action='store_true')
    parser.add_argument('--readiness',type=Path)
    args=parser.parse_args()
    plan=load_plan()
    if not args.execute_once:
        print(json.dumps(dict(status='local verified plan only; USB untouched',profile=PROFILE,
            source_sha256=source_hashes(),segments=[dict(address=hex(s.address),bytes=len(s.data),sha256=digest(s.data)) for s in plan]),indent=2))
        return
    if args.readiness is None:
        parser.error('--execute-once requires a fresh root-reviewed --readiness file')
    readiness=verify_readiness(args.readiness)
    directory=APP/'evidence'
    directory.mkdir(exist_ok=True)
    with open_attempt(directory/'msc1-ram-attempt-1.jsonl') as journal:
        def record(event):
            event['time']=datetime.datetime.now().astimezone().isoformat()
            journal.write(json.dumps(event)+'\n');journal.flush();os.fsync(journal.fileno())
        record(dict(event='monitor_started',profile=PROFILE,readiness=readiness,automatic_retry=False))
        # Execute only captured, pinned lock source. A busy lease consumes this
        # attempt and stops before opening USB, rather than waiting indefinitely.
        namespace={'__file__':str(USB_LOCK)}
        exec(compile(_read(USB_LOCK,USB_LOCK_SHA),str(USB_LOCK),'exec'),namespace)
        try:
            with namespace['usb_access']('Reviewed MSC1-profile bounded RAM handoff',blocking=False) as lease:
                if lease is None:
                    raise RuntimeError('Shared USB lock busy; no automatic retry')
                with LibUSB() as usb:
                    run_plan(usb,plan,record)
            record(dict(event='transport_completed',interpretation='conditional handoff requested; Linux/USB/readonly not proven'))
        except Exception as error:
            record(dict(event='stopped',error=str(error),automatic_retry=False))
            raise
    print('Conditional RAM handoff requested once. Verify boot, serial and runtime protection separately.')


if __name__=='__main__':
    main()
