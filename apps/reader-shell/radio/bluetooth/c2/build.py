#!/usr/bin/env python3
"""C2 compile/static inspection only. Reuses pinned C1 headers/runtime, never runs ELF."""
import hashlib,json,subprocess,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BT=ROOT.parent;SHELL=BT.parents[1];OUT=BT/'build/c2';EVIDENCE=ROOT/'evidence'
WORK='/work/pandanote-bluetooth-c2';C1='/work/pandanote-bluetooth-c1';CONTAINER='pandanote-mips-dev'
COMMANDS=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args):
 p=subprocess.run([str(x) for x in args],capture_output=True,text=True,timeout=60)
 COMMANDS.append({'argv':[str(x) for x in args],'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
 if p.returncode:raise RuntimeError(p.stdout+p.stderr)
 return p.stdout
def inside(args):return run(['docker','exec','-w',WORK,CONTAINER,*args])
def cp(p,dest):run(['docker','cp',p,CONTAINER+':'+WORK+'/'+dest])
def main():
 OUT.mkdir(exist_ok=True);(OUT/'manifest.json').unlink(missing_ok=True)
 try:
  if run(['docker','inspect',CONTAINER,'--format','{{.State.Status}}']).strip()!='running':raise ValueError('compiler unavailable')
  daemon=BT/'build/c1/bluetoothd-5.87.mipsel'
  if sha(daemon)!='df339547c56d352f50b609a487b062903cdc97e9ba23eb456114b5b87ec4f449':raise ValueError('C1 daemon pin')
  inputs=json.loads((BT/'c1/inputs.json').read_text());runtime=inputs['runtime']
  for n,(_,pin) in runtime.items():
   if run(['docker','exec',CONTAINER,'sha256sum',C1+'/runtime/'+n]).split()[0]!=pin:raise ValueError('runtime pin '+n)
  archive=BT/'build/c1/dbus-1.12.16.tar.gz'
  if sha(archive)!='54a22d2fa42f2eb2a871f32811c6005b531b9613b1b93a0d269b05e7549fec80':raise ValueError('D-Bus header archive pin')
  run(['docker','exec',CONTAINER,'mkdir','-p',WORK+'/dbus',WORK+'/startup'])
  header_pins={}
  with tarfile.open(archive) as t:
   for item in t:
    parts=Path(item.name).parts
    if item.isfile() and len(parts)==3 and parts[:2]==('dbus-1.12.16','dbus') and parts[-1].endswith('.h'):
     data=t.extractfile(item).read();p=OUT/parts[-1];p.write_bytes(data);header_pins[parts[-1]]=sha(p);cp(p,'dbus/'+parts[-1])
  generated=BT/'evidence/c1/generated/dbus-arch-deps.h'
  if sha(generated)!=json.loads((BT/'evidence/c1/profile.json').read_text())['generated']['dbus-arch-deps.h']:raise ValueError('generated header pin')
  cp(generated,'dbus/dbus-arch-deps.h');header_pins['dbus-arch-deps.h']=sha(generated)
  expected={'C2_DAEMON_SHA':sha(daemon),'C2_BUS_SHA':inputs['tools']['dbus-daemon'][1]}
  for var,name in [('BUS_CONFIG','private-bus.conf'),('MAIN_CONFIG','main.conf')]:
   data=(BT/'c1'/name).read_text();expected['C2_'+var]=data;expected['C2_'+var+'_SHA']=hashlib.sha256(data.encode()).hexdigest()
  expected_text='/* Exact accepted C1 inputs; generated from checked-in bytes. */\n'+''.join('#define '+k+' '+json.dumps(v)+'\n' for k,v in expected.items())
  if (ROOT/'inputs.h').read_text()!=expected_text:raise ValueError('C1 config/input pins')
  startup={}
  for n in ['start.S','entry.h','csu.cpp','libio-init.c']:
   p=SHELL/'build-support'/n;reference=(Path(__import__('os').environ.get('PANDANOTE_REFERENCE_ROOT', 'external-inputs')) / 'pandanote-analysis/app-development-research/minimal-qt/build-support')/n
   if sha(p)!=sha(reference):raise ValueError('startup pin '+n)
   startup[n]=sha(p);cp(p,'startup/'+n)
  for n in ['core.c','core.h','capability.c','capability.h','inspect.c','inspect.h','main.c','inputs.h']:cp(ROOT/n,n)
  cp(BT/'c1/compat-stat.h','compat-stat.h')
  for n in ['sha256.c','sha256.h']:cp(SHELL/'third_party/sha256'/n,n)
  abi=['-EL','-march=mips32r2','-mabi=32','-mhard-float','-mfp64','-mnan=2008','-fPIC']
  flags=abi+['-O2','-std=c11','-Wall','-Wextra','-Werror','-fstack-protector-strong','-D_GNU_SOURCE','-include','compat-stat.h','-I.','-isystem','/usr/mipsisa32r6el-linux-gnu/include']
  for n in ['core','capability','inspect','main','sha256']:inside(['mipsel-linux-gnu-gcc',*flags,'-c',n+'.c','-o',n+'.o'])
  for src,obj,compiler in [('start.S','start.o','gcc'),('libio-init.c','libio.o','gcc'),('csu.cpp','csu.o','g++')]:inside(['mipsel-linux-gnu-'+compiler,*abi,'-O2','-Istartup','-c','startup/'+src,'-o',obj])
  lib=C1+'/runtime'
  inside(['mipsel-linux-gnu-ld','-EL','-m','elf32ltsmip','-e','__start','--dynamic-linker','/lib/ld-linux-mipsn8.so.1','-rpath-link',lib,'-L',lib,'--no-allow-shlib-undefined','-z','noexecstack','-z','relro','-z','now','start.o','core.o','capability.o','inspect.o','main.o','sha256.o','csu.o','libio.o','-l:libdbus-1.so.3','-l:libc.so.6','-l:ld-linux-mipsn8.so.1','-o','pandanote-bt-lifecycle.mipsel'])
  elf=inside(['mipsel-linux-gnu-readelf','-h','-l','-A','-d','-V','--dyn-syms','--wide','pandanote-bt-lifecycle.mipsel'])
  for marker in ['ELF32','little endian','mips32r2','nan2008','o32','/lib/ld-linux-mipsn8.so.1','Hard float (32-bit CPU, 64-bit FPU)']:
   if marker not in elf:raise ValueError('ABI missing '+marker)
  for marker in ['GLIBC_2.3'+str(n) for n in range(0,10)]+['(INIT_ARRAY)','(FINI_ARRAY)']:
   if marker in elf:raise ValueError('unsupported ABI '+marker)
  imports={line.split()[-1].split('@')[0] for line in elf.splitlines() if ' UND ' in line and len(line.split())>7}
  if imports&{'system','popen','ioctl','socket','connect','sendto'}:raise ValueError('unexpected direct interface '+str(imports))
  artifact=OUT/'pandanote-bt-lifecycle.mipsel';run(['docker','cp',CONTAINER+':'+WORK+'/'+artifact.name,artifact]);artifact.chmod(0o600)
  (EVIDENCE/'target-elf.txt').write_text('\n'.join(line.rstrip() for line in elf.splitlines()).rstrip()+'\n')
  manifest={'schema':1,'target_execution':False,'artifact':{'name':artifact.name,'bytes':artifact.stat().st_size,'sha256':sha(artifact)},'source_sha256':{p.name:sha(p) for p in sorted(ROOT.iterdir()) if p.is_file()},'startup_sha256':startup,'dbus_headers':header_pins,'runtime_sha256':{k:v[1] for k,v in runtime.items()},'stat_adapter_sha256':sha(BT/'c1/compat-stat.h'),'sha256_source_sha256':{n:sha(SHELL/'third_party/sha256'/n) for n in ['sha256.c','sha256.h']},'unchanged_daemon_sha256':sha(daemon)}
  (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');(EVIDENCE/'target-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
  print('PASS C2 strict compile/link/ABI; no target execution; '+str(manifest['artifact']));return 0
 except Exception as e:print('FAIL',e);return 1
 finally:(EVIDENCE/'build-commands.json').write_text(json.dumps(COMMANDS,indent=2)+'\n')
if __name__=='__main__':raise SystemExit(main())
