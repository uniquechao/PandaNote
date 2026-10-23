#!/usr/bin/env python3
"""Trusted compiler only. Does not run resulting MIPS/vendor ELF or use network."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parent
SHELL=ROOT.parents[1]
REFERENCE=(Path(__import__('os').environ.get('PANDANOTE_REFERENCE_ROOT', 'external-inputs')))
STOCK=REFERENCE/'pandanote-analysis/app-development-research/qt-stock-sysroot'
CONTAINER='pandanote-mips-dev'
WORK='/work/pandanote-normal-suspend'
LIB='/work/pandanote/app-development-research/qt-stock-sysroot'
OUT=ROOT/'build/suspend-helper'
COMMANDS=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args):
    args=list(map(str,args))
    if args[:2]==['docker','cp'] and __import__('os').environ.get('PANDANOTE_COMPILER_ARCHIVE_COPY')=='1':args.insert(2,'--archive')
    p=subprocess.run([str(a) for a in args],capture_output=True,text=True,timeout=45)
    COMMANDS.append({'argv':[str(a) for a in args],'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
    if p.returncode:raise RuntimeError(p.stderr or p.stdout)
    return p.stdout
def inside(args):return run(['docker','exec','-w',WORK,CONTAINER,*args])
def main():
    global WORK,OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rtc-probe',action='store_true',help='compile independent read-only RTC inventory, never execute it')
    parser.add_argument('--output',type=Path,help='dedicated artifact directory; preserve existing trusted releases')
    args=parser.parse_args()
    binary_name='pandanote-rtc-probe' if args.rtc_probe else 'pandanote-normal-suspend'
    source='rtc_probe.c' if args.rtc_probe else 'suspend_helper.c'
    WORK='/work/'+binary_name
    OUT=args.output or ROOT/('build/rtc-probe' if args.rtc_probe else 'build/suspend-helper')
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'manifest.json').unlink(missing_ok=True)
    try:
        if run(['docker','inspect',CONTAINER,'--format','{{.State.Status}}']).strip()!='running':raise RuntimeError('trusted compiler is not running')
        provenance=json.loads((STOCK/'original-library-provenance.json').read_text())
        required={'libc.so.6','ld-linux-mipsn8.so.1'}
        checked={}
        for item in provenance:
            if item['name'] in required:
                digest=sha(STOCK/item['name'])
                if digest!=item['sha256'] or run(['docker','exec',CONTAINER,'sha256sum',LIB+'/'+item['name']]).split()[0]!=digest:raise RuntimeError('stock runtime input mismatch')
                checked[item['name']]=digest
        if set(checked)!=required:raise RuntimeError('runtime provenance incomplete')
        startup=['start.S','entry.h','csu.cpp','libio-init.c']
        baseline=REFERENCE/'pandanote-analysis/app-development-research/minimal-qt/build-support'
        for name in startup:
            if sha(SHELL/'build-support'/name)!=sha(baseline/name):raise RuntimeError('startup differs from reviewed baseline')
        run(['docker','exec',CONTAINER,'mkdir','-p',WORK+'/build-support'])
        for name in startup:run(['docker','cp',SHELL/'build-support'/name,CONTAINER+':'+WORK+'/build-support/'+name])
        run(['docker','cp',ROOT/source,CONTAINER+':'+WORK+'/'+source])
        for name in ('sha256.c','sha256.h'):run(['docker','cp',SHELL/'third_party/sha256'/name,CONTAINER+':'+WORK+'/'+name])
        abi=['-EL','-march=mips32r2','-mabi=32','-mhard-float','-mfp64','-mnan=2008','-fPIC']
        for compile_source,obj,compiler in [(source,'suspend_helper.o','mipsel-linux-gnu-gcc'),('sha256.c','sha256.o','mipsel-linux-gnu-gcc'),('build-support/start.S','start.o','mipsel-linux-gnu-gcc'),('build-support/libio-init.c','libio.o','mipsel-linux-gnu-gcc'),('build-support/csu.cpp','csu.o','mipsel-linux-gnu-g++')]:
            inside([compiler,*abi,'-O2','-D_POSIX_C_SOURCE=200809L','-Ibuild-support','-isystem','/usr/mipsisa32r6el-linux-gnu/include','-c',compile_source,'-o',obj])
        inside(['mipsel-linux-gnu-ld','-EL','-m','elf32ltsmip','-e','__start','--dynamic-linker','/lib/ld-linux-mipsn8.so.1','-rpath-link',LIB,'-L',LIB,'--no-allow-shlib-undefined','-z','noexecstack','-z','relro','-z','now','start.o','suspend_helper.o','sha256.o','csu.o','libio.o','-l:libc.so.6','-o',binary_name+'.mipsel'])
        elf=inside(['mipsel-linux-gnu-readelf','-h','-l','-A',binary_name+'.mipsel'])
        dyn=inside(['mipsel-linux-gnu-readelf','-d','-V','--dyn-syms','--wide',binary_name+'.mipsel'])
        for marker in ['ELF32','little endian','mips32r2','nan2008','o32','/lib/ld-linux-mipsn8.so.1','Hard float (32-bit CPU, 64-bit FPU)']:
            if marker not in elf:raise RuntimeError('ABI marker missing: '+marker)
        for marker in ['GLIBC_2.34','(INIT_ARRAY)','(FINI_ARRAY)']:
            if marker in dyn:raise RuntimeError('unsupported ABI: '+marker)
        for symbol in ['system','popen']:
            if any(line.split()[-1].split('@')[0]==symbol for line in dyn.splitlines() if ' UND ' in line):raise RuntimeError('unexpected shell import')
        run(['docker','cp',CONTAINER+':'+WORK+'/'+binary_name+'.mipsel',OUT/(binary_name+'.mipsel')])
        (OUT/(binary_name+'.mipsel')).chmod(0o600)
        (OUT/'elf.txt').write_text(elf+dyn)
        manifest=dict(schema=1,application=binary_name,execution_performed=False,source_sha256={name:sha(ROOT/name) for name in ((source,'build_suspend.py') if args.rtc_probe else ('suspend_helper.c','suspend.in','build_suspend.py'))},startup_sha256={name:sha(SHELL/'build-support'/name) for name in startup},stock_runtime_sha256=checked,artifact_sha256=sha(OUT/(binary_name+'.mipsel')),artifact_bytes=(OUT/(binary_name+'.mipsel')).stat().st_size)
        manifest['source_sha256'].update({name:sha(SHELL/'third_party/sha256'/name) for name in ('sha256.c','sha256.h')})
        (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print('PASS trusted compile and ELF inspection only:',OUT/(binary_name+'.mipsel'))
        return 0
    except Exception as e:print('FAIL',str(e));return 1
    finally:(OUT/'commands.json').write_text(json.dumps(COMMANDS,indent=2)+'\n')
if __name__=='__main__':raise SystemExit(main())
