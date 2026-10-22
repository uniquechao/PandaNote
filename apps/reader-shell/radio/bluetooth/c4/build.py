#!/usr/bin/env python3
"""Compile/link target only in retained compiler; never execute target/vendor ELF."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent;BT=ROOT.parent;SHELL=BT.parents[1]
OUT=BT/'build/c4';E=ROOT/'evidence';WORK='/work/pandanote-bluetooth-c4';C2='/work/pandanote-bluetooth-c2';C1='/work/pandanote-bluetooth-c1';CONTAINER='pandanote-mips-dev';commands=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args):
 p=subprocess.run([str(x) for x in args],capture_output=True,text=True,timeout=60)
 commands.append({'argv':[str(x) for x in args],'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
 if p.returncode:raise RuntimeError(p.stdout+p.stderr)
 return p.stdout

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 previous=E/'target-manifest.json'
 if previous.exists():
  history=E/'manifests';history.mkdir(exist_ok=True);snapshot=history/(sha(previous)+'.json')
  if not snapshot.exists():snapshot.write_bytes(previous.read_bytes())
  previous.unlink()
 c2=json.loads((BT/'c2/evidence/target-manifest.json').read_text());c3path=BT/'c3/evidence/target-manifest.json'
 if sha(c3path)!='fae9c7e3b3c5da869b37b7307c915959c4adb18940a0ab1a29e7a1af61427b63':raise ValueError('reviewed C3 manifest')
 c3=json.loads(c3path.read_text());service=BT/'build/c3/candidate-fix1-fae9c7e3/pandanote-bt-service.mipsel'
 if not service.exists():service=BT/'build/c3/pandanote-bt-service.mipsel'
 if sha(service)!=c3['artifacts']['pandanote-bt-service.mipsel']['sha256']:raise ValueError('C3 artifact')
 runtime=json.loads((BT/'c1/inputs.json').read_text())['runtime']
 for n,(_,pin) in runtime.items():
  if run(['docker','exec',CONTAINER,'sha256sum',C1+'/runtime/'+n]).split()[0]!=pin:raise ValueError('runtime '+n)
 for n,pin in c2['dbus_headers'].items():
  if run(['docker','exec',CONTAINER,'sha256sum',C2+'/dbus/'+n]).split()[0]!=pin:raise ValueError('DBus header '+n)
 run(['docker','exec',CONTAINER,'mkdir','-p',WORK+'/radio/bluetooth/c4',WORK+'/radio/bluetooth/c2',WORK+'/radio/bluetooth/c3',WORK+'/third_party/sha256',WORK+'/startup'])
 used={}
 def copy(p,dest):
  used[str(p.relative_to(SHELL))]=sha(p);run(['docker','cp',p,CONTAINER+':'+WORK+'/'+dest])
 for n in ['main.c','session.c','session.h','supervisor.c','supervisor.h','inputs.h']:copy(ROOT/n,'radio/bluetooth/c4/'+n)
 for n in ['core.c','core.h','capability.c','capability.h','inspect.c','inspect.h','inputs.h']:
  if sha(BT/'c2'/n)!=c2['source_sha256'][n]:raise ValueError('frozen C2 '+n)
  copy(BT/'c2'/n,'radio/bluetooth/c2/'+n)
 if sha(BT/'c1/compat-stat.h')!=c2['stat_adapter_sha256']:raise ValueError('C1 adapter')
 copy(BT/'c1/compat-stat.h','compat-stat.h')
 if sha(BT/'c3/compat-stat-at.h')!=c3['source_sha256']['compat-stat-at.h']:raise ValueError('C3 adapter')
 copy(BT/'c3/compat-stat-at.h','radio/bluetooth/c3/compat-stat-at.h')
 for n,pin in c2['startup_sha256'].items():
  if sha(SHELL/'build-support'/n)!=pin:raise ValueError('startup '+n)
  copy(SHELL/'build-support'/n,'startup/'+n)
 for n,pin in c2['sha256_source_sha256'].items():
  if sha(SHELL/'third_party/sha256'/n)!=pin:raise ValueError('sha source '+n)
  copy(SHELL/'third_party/sha256'/n,'third_party/sha256/'+n)
 def inside(args):return run(['docker','exec','-w',WORK,CONTAINER,*args])
 abi=['-EL','-march=mips32r2','-mabi=32','-mhard-float','-mfp64','-mnan=2008','-fPIC']
 flags=abi+['-O2','-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror','-fstack-protector-strong','-include','compat-stat.h','-include','radio/bluetooth/c3/compat-stat-at.h','-I'+C2,'-Ithird_party/sha256','-isystem','/usr/mipsisa32r6el-linux-gnu/include']
 objects=[]
 for name,src in [('main','radio/bluetooth/c4/main.c'),('session','radio/bluetooth/c4/session.c'),('supervisor','radio/bluetooth/c4/supervisor.c'),('core','radio/bluetooth/c2/core.c'),('capability','radio/bluetooth/c2/capability.c'),('inspect','radio/bluetooth/c2/inspect.c'),('sha256','third_party/sha256/sha256.c')]:
  inside(['mipsel-linux-gnu-gcc',*flags,'-c',src,'-o',name+'.o']);objects.append(name+'.o')
 for src,obj,compiler in [('start.S','start.o','gcc'),('libio-init.c','libio.o','gcc'),('csu.cpp','csu.o','g++')]:inside(['mipsel-linux-gnu-'+compiler,*abi,'-O2','-Istartup','-c','startup/'+src,'-o',obj])
 lib=C1+'/runtime';out='pandanote-bt-supervisor.mipsel'
 inside(['mipsel-linux-gnu-ld','-EL','-m','elf32ltsmip','-e','__start','--dynamic-linker','/lib/ld-linux-mipsn8.so.1','-rpath-link',lib,'-L',lib,'--no-allow-shlib-undefined','-z','noexecstack','-z','relro','-z','now','start.o',*objects,'csu.o','libio.o','-l:libdbus-1.so.3','-l:libc.so.6','-l:ld-linux-mipsn8.so.1','-o',out])
 elf=inside(['mipsel-linux-gnu-readelf','-h','-l','-A','-d','-V','--dyn-syms','--wide',out])
 for marker in ['ELF32','little endian','mips32r2','nan2008','o32','/lib/ld-linux-mipsn8.so.1','Hard float (32-bit CPU, 64-bit FPU)']:
  if marker not in elf:raise ValueError('ABI '+marker)
 for marker in ['GLIBC_2.3'+str(n) for n in range(10)]+['(INIT_ARRAY)','(FINI_ARRAY)']:
  if marker in elf:raise ValueError('unsupported ABI '+marker)
 imports={line.split()[-1].split('@')[0] for line in elf.splitlines() if ' UND ' in line and len(line.split())>7}
 if imports&{'system','popen','execvp','execvpe','killpg','ioctl','sendto','alarm'}:raise ValueError('unexpected interface')
 artifact=OUT/out;run(['docker','cp',CONTAINER+':'+WORK+'/'+out,artifact]);artifact.chmod(0o600)
 (E/'target-elf.txt').write_text('\n'.join(x.rstrip() for x in elf.splitlines()).rstrip()+'\n')
 manifest={'schema':1,'target_execution':False,'production_activation':False,'artifact':{'name':out,'sha256':sha(artifact),'bytes':artifact.stat().st_size},'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sorted(ROOT.rglob('*')) if p.is_file() and 'evidence' not in p.parts and '__pycache__' not in p.parts},'compiled_source_sha256':used,'retained_c2_manifest_sha256':sha(BT/'c2/evidence/target-manifest.json'),'reviewed_c3_manifest_sha256':sha(c3path),'reviewed_c3_artifact_sha256':sha(service),'runtime_sha256':{n:v[1] for n,v in runtime.items()}}
 previous.write_text(json.dumps(manifest,indent=2)+'\n');print('PASS strict target compile/link only '+json.dumps(manifest['artifact']))
if __name__=='__main__':
 try:main()
 finally:E.mkdir(exist_ok=True);(E/'target-build-commands.json').write_text(json.dumps(commands,indent=2)+'\n')
