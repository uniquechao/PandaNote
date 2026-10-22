#!/usr/bin/env python3
"""Strict target compile/link only; no target execution in trusted compiler."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent;BT=ROOT.parent;OUT=BT/'build/c3';E=ROOT/'evidence';WORK='/work/pandanote-bluetooth-c3';C2='/work/pandanote-bluetooth-c2';C1='/work/pandanote-bluetooth-c1';CONTAINER='pandanote-mips-dev';commands=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args):
 p=subprocess.run([str(x) for x in args],capture_output=True,text=True,timeout=60);commands.append({'argv':[str(x) for x in args],'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
 if p.returncode:raise RuntimeError(p.stdout+p.stderr)
 return p.stdout

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 previous=E/'target-manifest.json'
 if previous.exists():
  history=E/'manifests';history.mkdir(exist_ok=True);snapshot=history/(sha(previous)+'.json')
  if not snapshot.exists():snapshot.write_bytes(previous.read_bytes())
  previous.unlink()
 # Reuse only pinned reviewed headers/stat adapter/startup/runtime; no new packages.
 source=json.loads((BT/'c2/evidence/target-manifest.json').read_text());inputs=json.loads((BT/'c1/inputs.json').read_text())
 for n,pin in source['dbus_headers'].items():
  if run(['docker','exec',CONTAINER,'sha256sum',C2+'/dbus/'+n]).split()[0]!=pin:raise ValueError('DBus header pin '+n)
 for n,(_,pin) in inputs['runtime'].items():
  if run(['docker','exec',CONTAINER,'sha256sum',C1+'/runtime/'+n]).split()[0]!=pin:raise ValueError('runtime pin '+n)
 run(['docker','exec',CONTAINER,'mkdir','-p',WORK+'/radio/bluetooth/c3/tests',WORK+'/third_party/sha256',WORK+'/startup'])
 for name in ['runtime.c','runtime.h','ipc.c','ipc.h','service.c','service.h','compat-stat-at.h','main.c']:
  run(['docker','cp',ROOT/name,CONTAINER+':'+WORK+'/radio/bluetooth/c3/'+name])
 for name in ['cases.c','ipc_cases.c','service_cases.c','bus_cases.c','delivery_cases.c']:run(['docker','cp',ROOT/'tests'/name,CONTAINER+':'+WORK+'/radio/bluetooth/c3/tests/'+name])
 for name in ['policy.c','policy.h']:run(['docker','cp',BT/name,CONTAINER+':'+WORK+'/radio/bluetooth/'+name])
 shell=BT.parents[1]
 if sha(BT/'c1/compat-stat.h')!=source['stat_adapter_sha256']:raise ValueError('stat adapter pin')
 run(['docker','cp',BT/'c1/compat-stat.h',CONTAINER+':'+WORK+'/compat-stat.h'])
 for name,pin in source['startup_sha256'].items():
  if sha(shell/'build-support'/name)!=pin:raise ValueError('startup source pin '+name)
  run(['docker','cp',shell/'build-support'/name,CONTAINER+':'+WORK+'/startup/'+name])
 for name in ['sha256.c','sha256.h']:run(['docker','cp',shell/'third_party/sha256'/name,CONTAINER+':'+WORK+'/third_party/sha256/'+name])
 # Preserve original policy/sha source relative layout within this workspace.
 def inside(args):return run(['docker','exec','-w',WORK,CONTAINER,*args])
 abi=['-EL','-march=mips32r2','-mabi=32','-mhard-float','-mfp64','-mnan=2008','-fPIC']
 flags=abi+['-O2','-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror','-fstack-protector-strong','-include','compat-stat.h','-include','radio/bluetooth/c3/compat-stat-at.h','-I'+C2,'-Iradio/bluetooth/c3','-isystem','/usr/mipsisa32r6el-linux-gnu/include']
 for name,src in [('runtime','radio/bluetooth/c3/runtime.c'),('ipc','radio/bluetooth/c3/ipc.c'),('service','radio/bluetooth/c3/service.c'),('policy','radio/bluetooth/policy.c'),('sha256','third_party/sha256/sha256.c'),('cases','radio/bluetooth/c3/tests/cases.c'),('ipc_cases','radio/bluetooth/c3/tests/ipc_cases.c'),('service_cases','radio/bluetooth/c3/tests/service_cases.c'),('bus_cases','radio/bluetooth/c3/tests/bus_cases.c'),('main','radio/bluetooth/c3/main.c'),('delivery_cases','radio/bluetooth/c3/tests/delivery_cases.c')]:inside(['mipsel-linux-gnu-gcc',*flags,'-c',src,'-o',name+'.o'])
 for src,obj,compiler in [('start.S','start.o','gcc'),('libio-init.c','libio.o','gcc'),('csu.cpp','csu.o','g++')]:inside(['mipsel-linux-gnu-'+compiler,*abi,'-O2','-Istartup','-c','startup/'+src,'-o',obj])
 artifacts={}
 for name,objects in [('runtime-cases',['cases','runtime','policy','sha256']),('ipc-cases',['ipc_cases','ipc','runtime','policy','sha256']),('service-cases',['service_cases','runtime','policy','sha256']),('bus-cases',['bus_cases','runtime','policy','sha256']),('pandanote-bt-service',['main','service','ipc','runtime','policy','sha256']),('delivery-cases',['delivery_cases','ipc','runtime','policy','sha256'])]:
  lib=C1+'/runtime';out=name+'.mipsel';inside(['mipsel-linux-gnu-ld','-EL','-m','elf32ltsmip','-e','__start','--dynamic-linker','/lib/ld-linux-mipsn8.so.1','-rpath-link',lib,'-L',lib,'--no-allow-shlib-undefined','-z','noexecstack','-z','relro','-z','now','start.o',*[n+'.o' for n in objects],'csu.o','libio.o','-l:libdbus-1.so.3','-l:libc.so.6','-l:ld-linux-mipsn8.so.1','-o',out]);elf=inside(['mipsel-linux-gnu-readelf','-h','-l','-A','-d','-V','--dyn-syms','--wide',out]);(E/(name+'-elf.txt')).write_text('\n'.join(line.rstrip() for line in elf.splitlines()).rstrip()+'\n');p=OUT/out;run(['docker','cp',CONTAINER+':'+WORK+'/'+out,p]);p.chmod(0o600);artifacts[out]={'sha256':sha(p),'bytes':p.stat().st_size}
 # Link actual integration core, no executable main/activation caller installed.
 inside(['mipsel-linux-gnu-ld','-EL','-m','elf32ltsmip','-r','runtime.o','ipc.o','service.o','policy.o','sha256.o','-o','pandanote-bt-c3.o'])
 p=OUT/'pandanote-bt-c3.o';run(['docker','cp',CONTAINER+':'+WORK+'/'+p.name,p]);p.chmod(0o600);artifacts[p.name]={'sha256':sha(p),'bytes':p.stat().st_size}
 manifest={'schema':1,'production_activation':False,'target_execution':False,'artifacts':artifacts,'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in ROOT.rglob('*') if p.is_file() and 'evidence' not in p.parts and '__pycache__' not in p.parts},'policy_sha256':{n:sha(BT/n) for n in ['policy.c','policy.h']},'retained_c2_manifest_sha256':sha(BT/'c2/evidence/target-manifest.json'),'runtime_sha256':{n:v[1] for n,v in inputs['runtime'].items()}}
 (E/'target-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('PASS strict target compile/link; no activation; '+json.dumps(artifacts))
if __name__=='__main__':
 try:main()
 finally:E.mkdir(exist_ok=True);(E/'build-commands.json').write_text(json.dumps(commands,indent=2)+'\n')
