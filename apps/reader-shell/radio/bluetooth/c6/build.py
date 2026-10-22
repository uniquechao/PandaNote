#!/usr/bin/env python3
"""Strict target compile/link only; no physical serial/vendor execution."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent;BT=ROOT.parent;SHELL=BT.parents[1];OUT=BT/'build/c6';E=ROOT/'evidence';WORK='/work/pandanote-bluetooth-c6/candidate';C1='/work/pandanote-bluetooth-c1';CONTAINER='pandanote-mips-dev';commands=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args):
 p=subprocess.run([str(x) for x in args],capture_output=True,text=True,timeout=60);commands.append({'argv':[str(x) for x in args],'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
 if p.returncode:raise RuntimeError(p.stdout+p.stderr)
 return p.stdout

def main():
 OUT.mkdir(parents=True,exist_ok=True);manifest=E/'target-manifest.json'
 if manifest.exists():raise FileExistsError('freeze existing target manifest before rebuild')
 c2=json.loads((BT/'c2/evidence/target-manifest.json').read_text());c3=json.loads((BT/'c3/evidence/target-manifest.json').read_text());c4path=BT/'c4/evidence/target-manifest.json'
 if sha(c4path)!='d57d655d7a1fecbb68ef9dc77f8eaca4afd3e6fb6605963e8e565825d07fb229':raise ValueError('C4 approved manifest')
 c4=json.loads(c4path.read_text());runtime=json.loads((BT/'c1/inputs.json').read_text())['runtime'];wanted=['libc.so.6','ld-linux-mipsn8.so.1']
 for n in wanted:
  if run(['docker','exec',CONTAINER,'sha256sum',C1+'/runtime/'+n]).split()[0]!=runtime[n][1]:raise ValueError('runtime '+n)
 run(['docker','exec',CONTAINER,'mkdir','-p',WORK+'/radio/bluetooth/c6',WORK+'/radio/bluetooth/c4',WORK+'/radio/bluetooth/c2',WORK+'/third_party/sha256',WORK+'/startup'])
 used={}
 def copy(p,dest):used[str(p.relative_to(SHELL))]=sha(p);run(['docker','cp',p,CONTAINER+':'+WORK+'/'+dest])
 for n in ['main.c','runner.c','runner.h','preflight.c','preflight.h','controller.c','controller.h']:copy(ROOT/n,'radio/bluetooth/c6/'+n)
 for n in ['supervisor.c','supervisor.h']:
  if sha(BT/'c4'/n)!=c4['source_sha256'][n]:raise ValueError('frozen C4 '+n)
  copy(BT/'c4'/n,'radio/bluetooth/c4/'+n)
 for n in ['core.c','core.h']:
  if sha(BT/'c2'/n)!=c2['source_sha256'][n]:raise ValueError('frozen C2 '+n)
  copy(BT/'c2'/n,'radio/bluetooth/c2/'+n)
 if sha(BT/'c1/compat-stat.h')!=c2['stat_adapter_sha256'] or sha(BT/'c3/compat-stat-at.h')!=c3['source_sha256']['compat-stat-at.h']:raise ValueError('frozen stat adapters')
 copy(BT/'c1/compat-stat.h','compat-stat.h');copy(BT/'c3/compat-stat-at.h','compat-stat-at.h')
 for n,pin in c2['startup_sha256'].items():
  if sha(SHELL/'build-support'/n)!=pin:raise ValueError('startup '+n)
  copy(SHELL/'build-support'/n,'startup/'+n)
 for n,pin in c2['sha256_source_sha256'].items():
  if sha(SHELL/'third_party/sha256'/n)!=pin:raise ValueError('SHA source '+n)
  copy(SHELL/'third_party/sha256'/n,'third_party/sha256/'+n)
 def inside(args):return run(['docker','exec','-w',WORK,CONTAINER,*args])
 abi=['-EL','-march=mips32r2','-mabi=32','-mhard-float','-mfp64','-mnan=2008','-fPIC'];flags=abi+['-O2','-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror','-fstack-protector-strong','-include','compat-stat.h','-include','compat-stat-at.h','-Ithird_party/sha256','-isystem','/usr/mipsisa32r6el-linux-gnu/include'];objects=[]
 for name,src in [('main','radio/bluetooth/c6/main.c'),('runner','radio/bluetooth/c6/runner.c'),('preflight','radio/bluetooth/c6/preflight.c'),('controller','radio/bluetooth/c6/controller.c'),('supervisor','radio/bluetooth/c4/supervisor.c'),('core','radio/bluetooth/c2/core.c'),('sha256','third_party/sha256/sha256.c')]:inside(['mipsel-linux-gnu-gcc',*flags,'-c',src,'-o',name+'.o']);objects.append(name+'.o')
 for src,obj,compiler in [('start.S','start.o','gcc'),('libio-init.c','libio.o','gcc'),('csu.cpp','csu.o','g++')]:inside(['mipsel-linux-gnu-'+compiler,*abi,'-O2','-Istartup','-c','startup/'+src,'-o',obj])
 lib=C1+'/runtime';out='pandanote-bt-transport-session.mipsel';inside(['mipsel-linux-gnu-ld','-EL','-m','elf32ltsmip','-e','__start','--dynamic-linker','/lib/ld-linux-mipsn8.so.1','-rpath-link',lib,'-L',lib,'--no-allow-shlib-undefined','-z','noexecstack','-z','relro','-z','now','start.o',*objects,'csu.o','libio.o','-l:libc.so.6','-l:ld-linux-mipsn8.so.1','-o',out]);elf=inside(['mipsel-linux-gnu-readelf','-h','-l','-A','-d','-V','--dyn-syms','--wide',out])
 for marker in ['ELF32','little endian','mips32r2','nan2008','o32','/lib/ld-linux-mipsn8.so.1','Hard float (32-bit CPU, 64-bit FPU)']:
  if marker not in elf:raise ValueError('ABI '+marker)
 for marker in ['GLIBC_2.3'+str(n) for n in range(10)]+['(INIT_ARRAY)','(FINI_ARRAY)']:
  if marker in elf:raise ValueError('unsupported '+marker)
 imports={line.split()[-1].split('@')[0] for line in elf.splitlines() if ' UND ' in line and len(line.split())>7}
 if imports&{'socket','ioctl','tcsetattr','system','popen','sendto','init_module','delete_module','mount','umount','reboot','killpg'}:raise ValueError('unexpected direct interface')
 artifact=OUT/out;run(['docker','cp',CONTAINER+':'+WORK+'/'+out,artifact]);artifact.chmod(0o600);(E/'target-elf.txt').write_text('\n'.join(x.rstrip() for x in elf.splitlines()).rstrip()+'\n')
 value={'schema':1,'target_execution':False,'vendor_execution':False,'activation':False,'artifact':{'name':out,'bytes':artifact.stat().st_size,'sha256':sha(artifact)},'compiled_source_sha256':used,'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in ROOT.rglob('*') if p.is_file() and 'evidence' not in p.parts and '__pycache__' not in p.parts},'frozen_c4_manifest_sha256':sha(c4path),'runtime_sha256':{n:runtime[n][1] for n in wanted}}
 manifest.write_text(json.dumps(value,indent=2)+'\n');print('PASS strict target compile/link only '+json.dumps(value['artifact']))
if __name__=='__main__':
 try:main()
 finally:E.mkdir(exist_ok=True);(E/'target-build-commands.json').write_text(json.dumps(commands,indent=2)+'\n')
