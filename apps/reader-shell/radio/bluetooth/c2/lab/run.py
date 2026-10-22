#!/usr/bin/env python3
"""Compile-only on trusted compiler; target execution ONLY in pinned C1 lab."""
import hashlib,json,subprocess,sys
from pathlib import Path
from proof import errors
BT=Path(__file__).resolve().parents[2];C2=BT/'c2';OUT=BT/'build/c2/lab-prerequisite';EVIDENCE=C2/'evidence/runtime-completion'
BASE='sha256:20ecae4195e6336bf3453516a52af3ba33fecd3052332d6094399a0a354e6cb0'
TAG='pandanote-qt-graphics-master:20261020';COMPILER='pandanote-mips-dev';WORK='/work/pandanote-bluetooth-c2'
COMMANDS=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args,**kwargs):
 p=subprocess.run([str(x) for x in args],capture_output=True,timeout=60,**kwargs)
 COMMANDS.append({'argv':[str(x) for x in args],'exit':p.returncode,'stdout':p.stdout.decode(errors='replace'),'stderr':p.stderr.decode(errors='replace')})
 if p.returncode:raise RuntimeError(p.stdout.decode(errors='replace')+p.stderr.decode(errors='replace'))
 return p.stdout.decode().strip()
def main():
 prefix=EVIDENCE/'offline-prerequisite-nofile64'
 if prefix.with_suffix('.pre-run.json').exists():raise FileExistsError('preserve immutable evidence')
 OUT.mkdir(parents=True,exist_ok=True);case=OUT/'case';(case/'bin').mkdir(parents=True,exist_ok=True);(case/'runtime/lib').mkdir(parents=True,exist_ok=True)
 manifest=json.loads((C2/'evidence/target-manifest.json').read_text())
 for n in ['core.c','core.h','main.c','inputs.h','capability.c','capability.h','inspect.c','inspect.h']:
  if sha(C2/n)!=manifest['source_sha256'][n]:raise ValueError('production source drift '+n)
  if run(['docker','exec',COMPILER,'sha256sum',WORK+'/'+n]).split()[0]!=sha(C2/n):raise ValueError('compiler source drift '+n)
 artifact=BT/'build/c2/pandanote-bt-lifecycle.mipsel'
 if sha(artifact)!=manifest['artifact']['sha256']:raise ValueError('production artifact pin')
 # core.o is rebuilt from the exact unchanged source with the recorded C2 flags.
 abi=['-EL','-march=mips32r2','-mabi=32','-mhard-float','-mfp64','-mnan=2008','-fPIC']
 flags=abi+['-O2','-std=c11','-Wall','-Wextra','-Werror','-fstack-protector-strong','-D_GNU_SOURCE','-include','compat-stat.h','-I.','-isystem','/usr/mipsisa32r6el-linux-gnu/include']
 run(['docker','cp',C2/'lab/exec_probe.c',COMPILER+':'+WORK+'/exec_probe.c'])
 def inside(args):return run(['docker','exec','-w',WORK,COMPILER,*args])
 inside(['mipsel-linux-gnu-gcc',*flags,'-c','core.c','-o','lab-core.o'])
 inside(['mipsel-linux-gnu-gcc',*flags,'-c','exec_probe.c','-o','exec_probe.o'])
 lib='/work/pandanote-bluetooth-c1/runtime'
 inside(['mipsel-linux-gnu-ld','-EL','-m','elf32ltsmip','-e','__start','--dynamic-linker','/lib/ld-linux-mipsn8.so.1','-rpath-link',lib,'-L',lib,'--no-allow-shlib-undefined','-z','noexecstack','-z','relro','-z','now','start.o','lab-core.o','exec_probe.o','sha256.o','csu.o','libio.o','-l:libc.so.6','-l:ld-linux-mipsn8.so.1','-o','exec-probe.mipsel'])
 for remote,name in [(WORK+'/exec-probe.mipsel','exec-probe.mipsel'),(WORK+'/pandanote-bt-lifecycle.mipsel','pandanote-bt-lifecycle.mipsel'),('/work/pandanote-bluetooth-c1/bluetoothd-5.87-stripped.mipsel','bluetoothd')]:
  run(['docker','cp',COMPILER+':'+remote,case/'bin'/name])
 if sha(case/'bin/pandanote-bt-lifecycle.mipsel')!=sha(artifact) or sha(case/'bin/bluetoothd')!='df339547c56d352f50b609a487b062903cdc97e9ba23eb456114b5b87ec4f449':raise ValueError('copied target pin')
 inputs=json.loads((BT/'c1/inputs.json').read_text())
 for name,(_,pin) in inputs['runtime'].items():
  path=case/'runtime/lib'/name;run(['docker','cp',COMPILER+':'+lib+'/'+name,path])
  if sha(path)!=pin:raise ValueError('runtime pin '+name)
 allowed={'bin/exec-probe.mipsel','bin/pandanote-bt-lifecycle.mipsel','bin/bluetoothd'}|{'runtime/lib/'+n for n in inputs['runtime']}
 if {str(p.relative_to(case)) for p in case.rglob('*') if p.is_file()}!=allowed or any(p.is_symlink() for p in case.rglob('*')):raise ValueError('unexpected lab input')
 (OUT/'entry.py').write_bytes((C2/'lab/entry.py').read_bytes())
 (OUT/'Dockerfile').write_text('FROM '+TAG+'\nCOPY --chmod=0555 case /case\nCOPY --chmod=0444 entry.py /entry.py\nENTRYPOINT ["/usr/bin/timeout","35","/usr/bin/python3","/entry.py"]\n')
 base=json.loads(run(['docker','image','inspect',TAG]))[0]
 assert base['Id']==BASE and set(x.split('=',1)[0] for x in base['Config'].get('Env',[]))=={'PATH'}
 run(['docker','build','--network=none','--pull=false','-t','pandanote-bluetooth-c2-prerequisite:20261021',OUT])
 image=run(['docker','image','inspect','pandanote-bluetooth-c2-prerequisite:20261021','--format','{{.Id}}'])
 layers=json.loads(run(['docker','image','inspect',image,'--format','{{json .RootFS.Layers}}']))
 assert layers[:len(base['RootFS']['Layers'])]==base['RootFS']['Layers']
 args=['docker','create','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--pids-limit','32','--memory','128m','--memory-swap','128m','--cpus','1','--ulimit','core=0','--ulimit','nofile=64:64','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777',image]
 cid=run(args);inspection=json.loads(run(['docker','inspect',cid]))[0];h=inspection['HostConfig'];c=inspection['Config']
 assert h['NetworkMode']=='none' and h['ReadonlyRootfs'] and h['CapDrop']==['ALL'] and not h['Devices'] and not inspection['Mounts'] and not h.get('Binds') and not h.get('PortBindings') and c['User']=='65534:65534' and 'no-new-privileges' in h['SecurityOpt'] and not h['Privileged'] and not h.get('DeviceRequests') and h['PidsLimit']==32 and h['Memory']==128*1024*1024 and h['MemorySwap']==h['Memory'] and h['NanoCpus']==1000000000 and h['Tmpfs']=={'/tmp':'rw,nosuid,nodev,noexec,size=32m,mode=1777'} and {'Name':'nofile','Soft':64,'Hard':64} in h['Ulimits']
 pins={str(p.relative_to(case)):sha(p) for p in case.rglob('*') if p.is_file()}
 prefix.with_suffix('.pre-run.json').write_text(json.dumps({'base':BASE,'image':image,'inspect':inspection,'argv':args,'input_sha256':pins,'entry_sha256':sha(OUT/'entry.py'),'lab_entry_source_sha256':sha(C2/'lab/exec_probe.c'),'production_manifest_sha256':sha(C2/'evidence/target-manifest.json'),'lab_source_sha256':{n:sha(C2/'lab'/n) for n in ['run.py','entry.py','exec_probe.c','proof.py','plan.txt']}},indent=2)+'\n')
 try:p=subprocess.run(['docker','start','-a',cid],capture_output=True,timeout=45)
 except subprocess.TimeoutExpired:
  run(['docker','stop','-t','1',cid]);raise
 prefix.with_suffix('.stdout.json').write_bytes(p.stdout);prefix.with_suffix('.stderr.txt').write_bytes(p.stderr)
 final=json.loads(run(['docker','inspect',cid]))[0]
 payload=json.loads(p.stdout);failures=errors(payload)
 if final['State']['ExitCode']!=0:failures.append('guest entry failed')
 # Independently audit actual traces; no guest success flags alone.
 sys.path.insert(0,str(BT/'c1'));from audit_trace import violations
 for n in ['production','probe','child']:
  trace=payload.get(n+'_trace','') if n!='child' else payload.get('child_stdout','')
  if len(trace.encode())>=2*1024*1024 or violations(trace):failures.append('trace bound/path audit failed: '+n)
  prefix.with_name(prefix.name+'-'+n+'.trace').write_text(trace)
 summary={'proof_errors':failures,'nested_exec_proven':not failures,'hardware_access':False,'result':payload,'container_exit':final['State']['ExitCode'],'image':image}
 prefix.with_suffix('.result.json').write_text(json.dumps(summary,indent=2)+'\n')
 print(json.dumps({k:v for k,v in summary.items() if k!='result'},indent=2));return 1 if failures else 0
if __name__=='__main__':
 try:raise SystemExit(main())
 finally:
  EVIDENCE.mkdir(exist_ok=True);(EVIDENCE/'commands.json').write_text(json.dumps(COMMANDS,indent=2)+'\n')
