#!/usr/bin/env python3
"""Build/inspect an OFFLINE writable RAM candidate. No USB or apply operation.

Owned shell payloads are staged separately after USB enumeration. The pinned
bootstrap checks exact kernel/wrapper/argv bytes before starting the small PID1.
"""
import argparse
import base64
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess
import zlib

ROOT=Path(__file__).resolve().parent
KERNEL_SHA='c7afae1b766457df618fcb49b47736f27d10616baeddb6082a197094c53ba4d4'
BOOTSTRAP_SOURCE_SHA='0ee242bcf70b50bdf6eb4707fe7137638ddbe207c959d91e6cfeebbcd4fd2b6b'
PARAM_SHA='4c93fa36efc87fbf925e63a8779dd1ce817ab4c14fe1f42003559b12f716beb6'
SPL_SHA='61522b6712cf03616949b4415d8a292cff5c55e06b0088ab29e0ffe2f62abc91'
BASE=0x80010000
WRAPPER=0x84000000
ARGV=0x84001000
WORK='/work/pandanote-writable-boot-build'


def sha(blob):return hashlib.sha256(blob).hexdigest()


def capsule(kernel,pid1):
    if len(kernel)!=7815440 or sha(kernel)!=KERNEL_SHA:
        raise ValueError('unverified writable kernel')
    encoded=base64.b64encode(gzip.compress(pid1,mtime=0)).decode('ascii')
    seed=('umask 077; /bin/busybox mount -t tmpfs -o mode=0700,nosuid,nodev,size=24m tmpfs /tmp && '
          '/bin/busybox echo '+encoded+' | /bin/busybox base64 -d | /bin/busybox zcat > /tmp/pid1 && '
          '/bin/busybox sha256sum /tmp/pid1 | /bin/busybox grep -q ^'+sha(pid1)+
          ' && exec /bin/busybox sh /tmp/pid1; while :; do /bin/busybox sleep 3600; done')
    if any(value in seed for value in ('"','\n','\0')):
        raise ValueError('unsafe fixed boot seed')
    commandline=('root=/dev/mmcblk0p2 rootfstype=ext4 ro rootflags=noload '
                 'rootwait mem=64M@0 maxcpus=1 panic=0 init=/bin/busybox -- sh -c "'+seed+'"')
    command=commandline.encode('ascii')
    if len(command)>=4095:
        raise ValueError('writable PID1 commandline exceeds original PROM limit')
    name=b'pandanote-dev\0'
    argv=struct.pack('<III',ARGV+12,ARGV+12+len(name),0)+name+command+b'\0'
    if len(argv)>4096:
        raise ValueError('writable commandline argv page overflow')
    wrapper=struct.pack('<9I',0x24040002,0x3c058400,0x34a51000,0x00003025,
                        0x00003825,0x3c198056,0x373978a0,0x03200008,0)
    if not BASE+len(kernel)<=0x80806be0<0x84000000:
        raise ValueError('kernel/BSS exceeds retained Linux memory boundary')
    return dict(segments={BASE:kernel,WRAPPER:wrapper,ARGV:argv},commandline=commandline)


def crc_include(segments):
    lines=['crc_ranges:']
    for address,blob in segments.items():
        lines.append('    .word '+','.join(hex(value) for value in (
            address&0x1fffffff|0xa0000000,len(blob),zlib.crc32(blob))))
    lines+=['crc_ranges_end:','crc_table:']
    for value in range(256):
        for _ in range(8):value=(value>>1)^(0xedb88320 if value&1 else 0)
        lines.append('    .word '+hex(value))
    return '\n'.join(lines)+'\n'


def render(name,values):
    text=(ROOT/name).read_text()
    for key,value in values.items():text=text.replace('@'+key+'@',value)
    if re.search(r'@[A-Z_]+@',text):raise ValueError('unresolved template value')
    return text.encode()


def write(path,blob):
    path.write_bytes(blob);path.chmod(0o600)


def run(args):return subprocess.run(args,check=True,capture_output=True)


def build(reference):
    analysis=reference/'pandanote-analysis'
    spec=importlib.util.spec_from_file_location('writable_preparation',ROOT.parent/'writable_preparation.py')
    prep=importlib.util.module_from_spec(spec);spec.loader.exec_module(prep)
    original=(analysis/'factory-backup-20261020/inspection/kernel-decompressed.bin').read_bytes()
    guarded=(analysis/'app-development-research/ram-linux-research/kernel-RAM-ANALYSIS-ONLY-NOT-FOR-FLASH.bin').read_bytes()
    kernel=prep.derive_writable_kernel(original,guarded)
    policy=(ROOT/'policy.sh').read_bytes()
    supervisor=(ROOT/'child-supervisor.sh').read_bytes()
    runtime=render('runtime.in',dict(POLICY_SHA=sha(policy)))
    guard=render('radio_guard.in',dict(POLICY_SHA=sha(policy)))
    pid1=render('pid1.in',dict(POLICY_SHA=sha(policy),RUNTIME_SHA=sha(runtime),
        SUPERVISOR_SHA=sha(supervisor),SUPERVISOR_SOURCE=supervisor.decode().rstrip('\n')))
    result=capsule(kernel,pid1)
    out=ROOT/'build/candidate';out.mkdir(parents=True,exist_ok=True)
    payload=out/'payload';payload.mkdir(mode=0o700,exist_ok=True)
    for name,blob in {'policy.sh':policy,'runtime.sh':runtime,'child-supervisor.sh':supervisor,'radio-development-guard.sh':guard,
                      'payload.ready':b'writable-development-v1\n'}.items():write(payload/name,blob)
    write(out/'pid1.sh',pid1)
    bootstrap=(analysis/'app-development-research/ram-linux-research/bootstrap-selfcheck.S').read_bytes()
    if sha(bootstrap)!=BOOTSTRAP_SOURCE_SHA:raise ValueError('bootstrap source identity changed')
    write(out/'bootstrap-selfcheck.S',bootstrap)
    write(out/'bootstrap-capsule-inputs.inc',crc_include(result['segments']).encode())
    run(['docker','exec','pandanote-mips-dev','mkdir','-p',WORK])
    for name in ('bootstrap-selfcheck.S','bootstrap-capsule-inputs.inc'):
        run(['docker','cp',str(out/name),'pandanote-mips-dev:'+WORK+'/'+name])
    commands=[['mipsel-linux-gnu-as','-EL','-mips32r2','-mfp64','-mnan=2008','bootstrap-selfcheck.S','-o','bootstrap-selfcheck.o'],
              ['mipsel-linux-gnu-ld','-EL','-m','elf32ltsmip','-Ttext','0x81000000','-e','boot_selfcheck','bootstrap-selfcheck.o','-o','bootstrap-selfcheck.elf'],
              ['mipsel-linux-gnu-objcopy','-j','.text','-O','binary','bootstrap-selfcheck.elf','bootstrap-selfcheck.bin']]
    for command in commands:run(['docker','exec','-w',WORK,'pandanote-mips-dev']+command)
    for name in ('bootstrap-selfcheck.elf','bootstrap-selfcheck.bin'):
        run(['docker','cp','pandanote-mips-dev:'+WORK+'/'+name,str(out/name)]);(out/name).chmod(0o600)
    compiled=(out/'bootstrap-selfcheck.bin').read_bytes()
    symbols=run(['docker','exec','-w',WORK,'pandanote-mips-dev','mipsel-linux-gnu-nm','-n','bootstrap-selfcheck.elf']).stdout.decode()
    names={row.split()[2]:hex(int(row.split()[0],16)&0xffffffff) for row in symbols.splitlines()
           if len(row.split())==3 and row.split()[2] in ('boot_selfcheck','halt','crc32_ram','crc_ranges','crc_ranges_end','crc_table')}
    if len(compiled)>4096 or names.get('boot_selfcheck')!='0x81000000':raise ValueError('bootstrap placement failed')
    manifest=dict(schema=1,profile='writable-development-v1',scope='complete-boot-candidate-offline-only',
        hardware_execution_permitted=False,device_transport=None,device_apply_supported=False,
        normal_persistent_boot=False,flash_image=False,linux_memory='64M@0',emmc_write_filter=False,
        native_application_included=False,display_touch_radio_initialized=False,
        operator_handoff='required before persistent mount; operator assertion, not remote attestation',
        normal_boot_followup='must boot autonomously without Mac upload/receipt; this RAM checkpoint is not that implementation',
        kernel_sha256=KERNEL_SHA,pid1_sha256=sha(pid1),commandline_bytes=len(result['commandline']),
        commandline_sha256=sha(result['commandline'].encode()),
        proc_cmdline_sha256=sha(result['commandline'].encode()+b'\n'),
        segments=[],bootstrap=dict(file='bootstrap-selfcheck.bin',address='0x81000000',
            bytes=len(compiled),sha256=sha(compiled),symbols=names,status_address='0x8100f000'),
        payload=[],sources={},reused_inputs=[])
    for address,blob in result['segments'].items():
        name='ram-'+format(address,'08x')+'.bin';write(out/name,blob)
        manifest['segments'].append(dict(address=hex(address),file=name,bytes=len(blob),sha256=sha(blob)))
    for path in sorted(payload.iterdir()):
        blob=path.read_bytes();manifest['payload'].append(dict(file='payload/'+path.name,bytes=len(blob),sha256=sha(blob),mode='0600'))
    for name in ('build.py','policy.sh','runtime.in','pid1.in','radio_guard.in','child-supervisor.sh'):
        manifest['sources'][name]=sha((ROOT/name).read_bytes())
    manifest['sources']['../writable_preparation.py']=sha((ROOT.parent/'writable_preparation.py').read_bytes())
    for path,digest in [(analysis/'readback-guard/ginfo-MSC0-PD17-PD22-CANDIDATE.bin',PARAM_SHA),
                        (analysis/'cloner-2.5.50/cloner-2.5.50-ubuntu_alpha/firmwares/x2000/spl.bin',SPL_SHA)]:
        blob=path.read_bytes()
        if sha(blob)!=digest:raise ValueError('known DDR-only input changed')
        manifest['reused_inputs'].append(dict(file=str(path.relative_to(analysis)),bytes=len(blob),sha256=digest))
    write(out/'manifest.json',(json.dumps(manifest,indent=2)+'\n').encode())
    return manifest


def inspect():
    out=ROOT/'build/candidate';manifest=json.loads((out/'manifest.json').read_text())
    if manifest['profile']!='writable-development-v1' or manifest['hardware_execution_permitted'] is not False:
        raise ValueError('unexpected candidate state')
    for entry in manifest['segments']+[manifest['bootstrap']]+manifest['payload']:
        blob=(out/entry['file']).read_bytes()
        if len(blob)!=entry['bytes'] or sha(blob)!=entry['sha256']:raise ValueError('candidate artifact changed')
    for name,digest in manifest['sources'].items():
        if sha((ROOT/name).read_bytes())!=digest:raise ValueError('candidate source changed; rebuild required')
    return dict(profile=manifest['profile'],manifest_sha256=sha((out/'manifest.json').read_bytes()),
                status='offline-candidate-verified',hardware_execution_permitted=False,
                device_apply_supported=False,commandline_bytes=manifest['commandline_bytes'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-root',type=Path)
    parser.add_argument('--inspect',action='store_true')
    args=parser.parse_args()
    if args.inspect:result=inspect()
    else:
        if not args.reference_root:parser.error('--reference-root required for local build')
        build(args.reference_root);result=inspect()
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
