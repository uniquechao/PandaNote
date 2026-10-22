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
WORK='/work/pandanote-normal-apply'
LIB='/work/pandanote/app-development-research/qt-stock-sysroot'
OUT=ROOT/'build/apply-tool'
COMMANDS=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args):
    p=subprocess.run([str(a) for a in args],capture_output=True,text=True,timeout=45)
    COMMANDS.append({'argv':[str(a) for a in args],'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
    if p.returncode:raise RuntimeError(p.stderr or p.stdout)
    return p.stdout
def inside(args):return run(['docker','exec','-w',WORK,CONTAINER,*args])
def main(normal_upgrade=False):
    global WORK,OUT
    binary_name='pandanote-normal-upgrade' if normal_upgrade else 'pandanote-normal-apply'
    if normal_upgrade:WORK='/work/pandanote-normal-upgrade';OUT=ROOT/'build/upgrade-tool'
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
        run(['docker','cp',ROOT/'apply_tool.c',CONTAINER+':'+WORK+'/apply_tool.c'])
        if normal_upgrade:
            for header in ('upgrade_wire.h','upgrade_target.h'):run(['docker','cp',ROOT/header,CONTAINER+':'+WORK+'/'+header])
        for name in ('sha256.c','sha256.h'):run(['docker','cp',SHELL/'third_party/sha256'/name,CONTAINER+':'+WORK+'/'+name])
        abi=['-EL','-march=mips32r2','-mabi=32','-mhard-float','-mfp64','-mnan=2008','-fPIC']
        for source,obj,compiler in [('apply_tool.c','apply_tool.o','mipsel-linux-gnu-gcc'),('sha256.c','sha256.o','mipsel-linux-gnu-gcc'),('build-support/start.S','start.o','mipsel-linux-gnu-gcc'),('build-support/libio-init.c','libio.o','mipsel-linux-gnu-gcc'),('build-support/csu.cpp','csu.o','mipsel-linux-gnu-g++')]:
            inside([compiler,*abi,*(['-DPANDANOTE_NORMAL_UPGRADE'] if normal_upgrade else []),'-O2','-D_POSIX_C_SOURCE=200809L','-Ibuild-support','-isystem','/usr/mipsisa32r6el-linux-gnu/include','-c',source,'-o',obj])
        inside(['mipsel-linux-gnu-ld','-EL','-m','elf32ltsmip','-e','__start','--dynamic-linker','/lib/ld-linux-mipsn8.so.1','-rpath-link',LIB,'-L',LIB,'--no-allow-shlib-undefined','-z','noexecstack','-z','relro','-z','now','start.o','apply_tool.o','sha256.o','csu.o','libio.o','-l:libc.so.6','-o',binary_name+'.mipsel'])
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
        (OUT/'manifest.json').write_text(json.dumps({'schema':1,'application':binary_name,'profile':'normal-exact-upgrade-v1' if normal_upgrade else 'ram-to-normal-v1','execution_performed':False,'source_sha256':{**({n:sha(ROOT/n) for n in ('upgrade_wire.h','upgrade_target.h','normal_upgrade.py','upgrade_profile.py')} if normal_upgrade else {}),'apply_tool.c':sha(ROOT/'apply_tool.c'),'sha256.c':sha(SHELL/'third_party/sha256/sha256.c'),'sha256.h':sha(SHELL/'third_party/sha256/sha256.h'),'build_apply.py':sha(ROOT/'build_apply.py'),'apply_transport.py':sha(ROOT/'apply_transport.py'),'bundle.py':sha(ROOT/'bundle.py'),'transaction.py':sha(ROOT/'transaction.py')},'startup_sha256':{name:sha(SHELL/'build-support'/name) for name in startup},'stock_runtime_sha256':checked,'artifact_sha256':sha(OUT/(binary_name+'.mipsel')),'artifact_bytes':(OUT/(binary_name+'.mipsel')).stat().st_size},indent=2)+'\n')
        print('PASS trusted compile and ELF inspection only:',OUT/(binary_name+'.mipsel'))
        return 0
    except Exception as e:print('FAIL',str(e));return 1
    finally:(OUT/'commands.json').write_text(json.dumps(COMMANDS,indent=2)+'\n')
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--normal-upgrade',action='store_true');args=parser.parse_args();raise SystemExit(main(args.normal_upgrade))
