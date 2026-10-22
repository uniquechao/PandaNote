#!/usr/bin/env python3
"""Compile owned sources in existing trusted compiler; never run target ELF."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SHELL=ROOT.parents[1]
REFERENCE=(Path(__import__('os').environ.get('PANDANOTE_REFERENCE_ROOT', 'external-inputs')))
STOCK=REFERENCE/'pandanote-analysis/app-development-research/qt-stock-sysroot'
CONTAINER='pandanote-mips-dev';WORK='/work/pandanote-bluetooth/build';LIB='/work/pandanote/app-development-research/qt-stock-sysroot'
OUT=ROOT/'build';COMMANDS=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args):
    p=subprocess.run([str(x) for x in args],capture_output=True,text=True,timeout=45)
    COMMANDS.append({'argv':[str(x) for x in args],'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
    if p.returncode:raise RuntimeError(p.stderr or p.stdout)
    return p.stdout
def inside(args):return run(['docker','exec','-w',WORK,CONTAINER,*args])
def main():
    OUT.mkdir(exist_ok=True);(OUT/'manifest.json').unlink(missing_ok=True)
    try:
        if run(['docker','inspect',CONTAINER,'--format','{{.State.Status}}']).strip()!='running':raise RuntimeError('trusted compiler unavailable')
        provenance=json.loads((STOCK/'original-library-provenance.json').read_text());checked={}
        for item in provenance:
            if item['name'] in ('libc.so.6','ld-linux-mipsn8.so.1'):
                name=item['name'];digest=sha(STOCK/name)
                if digest!=item['sha256'] or run(['docker','exec',CONTAINER,'sha256sum',LIB+'/'+name]).split()[0]!=digest:raise RuntimeError('runtime mismatch')
                checked[name]=digest
        if len(checked)!=2:raise RuntimeError('incomplete runtime provenance')
        startup=['start.S','entry.h','csu.cpp','libio-init.c']
        baseline=REFERENCE/'pandanote-analysis/app-development-research/minimal-qt/build-support'
        for name in startup:
            if sha(SHELL/'build-support'/name)!=sha(baseline/name):raise RuntimeError('startup baseline differs')
        run(['docker','exec',CONTAINER,'mkdir','-p',WORK+'/build-support',WORK+'/third_party/sha256'])
        for name in startup:run(['docker','cp',SHELL/'build-support'/name,CONTAINER+':'+WORK+'/build-support/'+name])
        sources=['probe.c','probe_io.c','probe_io.h','capability.c','capability.h','policy.c','policy.h']
        for name in sources:run(['docker','cp',ROOT/name,CONTAINER+':'+WORK+'/'+name])
        # Keep the checked-in relative dependency layout in a source-specific subdir.
        run(['docker','exec',CONTAINER,'mkdir','-p',WORK+'/radio/bluetooth'])
        for name in ['policy.c','policy.h']:run(['docker','cp',ROOT/name,CONTAINER+':'+WORK+'/radio/bluetooth/'+name])
        for name in ['sha256.c','sha256.h']:run(['docker','cp',SHELL/'third_party/sha256'/name,CONTAINER+':'+WORK+'/third_party/sha256/'+name])
        abi=['-EL','-march=mips32r2','-mabi=32','-mhard-float','-mfp64','-mnan=2008','-fPIC']
        units=[('probe.c','probe.o'),('probe_io.c','probe_io.o'),('capability.c','capability.o'),('radio/bluetooth/policy.c','policy.o'),('third_party/sha256/sha256.c','sha256.o'),('build-support/start.S','start.o'),('build-support/libio-init.c','libio.o'),('build-support/csu.cpp','csu.o')]
        for source,obj in units:
            compiler='mipsel-linux-gnu-g++' if source.endswith('.cpp') else 'mipsel-linux-gnu-gcc'
            inside([compiler,*abi,'-O2','-Wall','-Wextra','-Werror','-D_POSIX_C_SOURCE=200809L','-Ibuild-support','-isystem','/usr/mipsisa32r6el-linux-gnu/include','-c',source,'-o',obj])
        inside(['mipsel-linux-gnu-ld','-EL','-m','elf32ltsmip','-e','__start','--dynamic-linker','/lib/ld-linux-mipsn8.so.1','-rpath-link',LIB,'-L',LIB,'--no-allow-shlib-undefined','-z','noexecstack','-z','relro','-z','now','start.o','probe.o','probe_io.o','capability.o','csu.o','libio.o','-l:libc.so.6','-o','pandanote-bt-probe.mipsel'])
        inside(['mipsel-linux-gnu-ar','rcs','libpandanote-bt-policy.a','policy.o','sha256.o'])
        elf=inside(['mipsel-linux-gnu-readelf','-h','-l','-A','pandanote-bt-probe.mipsel']);dyn=inside(['mipsel-linux-gnu-readelf','-d','-V','--dyn-syms','--wide','pandanote-bt-probe.mipsel'])
        for marker in ['ELF32','little endian','mips32r2','nan2008','o32','/lib/ld-linux-mipsn8.so.1','Hard float (32-bit CPU, 64-bit FPU)']:
            if marker not in elf:raise RuntimeError('ABI marker missing '+marker)
        for marker in ['GLIBC_2.34','(INIT_ARRAY)','(FINI_ARRAY)']:
            if marker in dyn:raise RuntimeError('unsupported ABI '+marker)
        for symbol in ['system','popen','execve','fork','ioctl']:
            if any(line.split()[-1].split('@')[0]==symbol for line in dyn.splitlines() if ' UND ' in line):raise RuntimeError('unexpected mutation/process import '+symbol)
        artifacts={}
        for name in ['pandanote-bt-probe.mipsel','libpandanote-bt-policy.a']:
            run(['docker','cp',CONTAINER+':'+WORK+'/'+name,OUT/name]);(OUT/name).chmod(0o600)
            artifacts[name]={'bytes':(OUT/name).stat().st_size,'sha256':sha(OUT/name)}
        (OUT/'elf.txt').write_text(elf+dyn)
        manifest={'schema':1,'execution_performed':False,'artifacts':artifacts,'source_sha256':{name:sha(ROOT/name) for name in sources+['build.py']},'startup_sha256':{name:sha(SHELL/'build-support'/name) for name in startup},'dependency_sha256':{name:sha(SHELL/'third_party/sha256'/name) for name in ['sha256.c','sha256.h']},'stock_runtime_sha256':checked}
        (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('PASS trusted compile / ELF inspection; no target execution');return 0
    except Exception as e:print('FAIL',str(e));return 1
    finally:(OUT/'commands.json').write_text(json.dumps(COMMANDS,indent=2)+'\n')
if __name__=='__main__':raise SystemExit(main())
