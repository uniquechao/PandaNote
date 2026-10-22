#!/usr/bin/env python3
"""Standalone C3 own-code cases, only in the approved immutable disposable lab."""
import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent;BT=ROOT.parent;OUT=BT/'build/c3/lab';E=ROOT/'evidence';commands=[]
BASE='sha256:20ecae4195e6336bf3453516a52af3ba33fecd3052332d6094399a0a354e6cb0';TAG='pandanote-qt-graphics-master:20261020'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args):
 p=subprocess.run([str(x) for x in args],capture_output=True,timeout=60);commands.append({'argv':[str(x) for x in args],'exit':p.returncode,'stdout':p.stdout.decode(errors='replace'),'stderr':p.stderr.decode(errors='replace')})
 if p.returncode:raise RuntimeError(p.stdout.decode(errors='replace')+p.stderr.decode(errors='replace'))
 return p.stdout.decode().strip()
def main():
 label=sys.argv[1] if len(sys.argv)==2 else 'cases'
 if label not in ['cases','address-red','address-green','bus','bus-green','bus-file','final-cases','bus-final','review-cases','bus-review','fix1-cases','bus-fix1','fix1-final','bus-fix1-final']:raise ValueError('fixed evidence labels only')
 prefix=E/('offline-'+label)
 if prefix.with_suffix('.pre-run.json').exists():raise FileExistsError('preserve immutable evidence')
 out=OUT if not label.startswith('bus') else OUT.parent/'lab-bus'
 case=out/'case';(case/'bin').mkdir(parents=True,exist_ok=True);(case/'runtime/lib').mkdir(parents=True,exist_ok=True)
 manifest=json.loads((E/'target-manifest.json').read_text())
 for name,pin in manifest['source_sha256'].items():
  if sha(ROOT/name)!=pin:raise ValueError('C3 source drift '+name)
 names=['bus-cases.mipsel'] if label.startswith('bus') else ['runtime-cases.mipsel','ipc-cases.mipsel','service-cases.mipsel','delivery-cases.mipsel']
 for name in names:
  data=(BT/'build/c3'/name).read_bytes();p=case/'bin'/name;p.write_bytes(data)
  if sha(p)!=manifest['artifacts'][name]['sha256']:raise ValueError('case artifact pin '+name)
 inputs=json.loads((BT/'c1/inputs.json').read_text())
 for name,(_,pin) in inputs['runtime'].items():
  p=case/'runtime/lib'/name;run(['docker','cp','pandanote-mips-dev:/work/pandanote-bluetooth-c1/runtime/'+name,p])
  if sha(p)!=pin:raise ValueError('runtime pin '+name)
 if label.startswith('bus'):
  p=case/'bin/dbus-daemon';run(['docker','cp','pandanote-mips-dev:/work/pandanote-bluetooth-c1/dbus-daemon',p])
  if sha(p)!=inputs['tools']['dbus-daemon'][1]:raise ValueError('private bus artifact pin')
  (case/'private-bus.conf').write_bytes((BT/'c1/private-bus.conf').read_bytes())
 (out/'entry.py').write_bytes((ROOT/('tests/bus_entry.py' if label.startswith('bus') else 'tests/offline_entry.py')).read_bytes())
 (out/'Dockerfile').write_text('FROM '+TAG+'\nCOPY --chmod=0555 case /case\nCOPY --chmod=0444 entry.py /entry.py\nENTRYPOINT ["/usr/bin/timeout","35","/usr/bin/python3","/entry.py"]\n')
 allowed={'bin/'+n for n in names}|{'runtime/lib/'+n for n in inputs['runtime']}
 if label.startswith('bus'):allowed|={'bin/dbus-daemon','private-bus.conf'}
 assert {str(p.relative_to(case)) for p in case.rglob('*') if p.is_file()}==allowed and not any(p.is_symlink() for p in case.rglob('*'))
 base=json.loads(run(['docker','image','inspect',TAG]))[0];assert base['Id']==BASE and set(x.split('=',1)[0] for x in base['Config'].get('Env',[]))=={'PATH'}
 run(['docker','build','--network=none','--pull=false','-t','pandanote-bluetooth-c3-cases:20261021',out]);image=run(['docker','image','inspect','pandanote-bluetooth-c3-cases:20261021','--format','{{.Id}}'])
 layers=json.loads(run(['docker','image','inspect',image,'--format','{{json .RootFS.Layers}}']));assert layers[:len(base['RootFS']['Layers'])]==base['RootFS']['Layers']
 args=['docker','create','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--pids-limit','32','--memory','128m','--memory-swap','128m','--cpus','1','--ulimit','core=0','--ulimit','nofile=64:64','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777',image]
 cid=run(args);inspection=json.loads(run(['docker','inspect',cid]))[0];h=inspection['HostConfig'];c=inspection['Config']
 assert h['NetworkMode']=='none' and h['ReadonlyRootfs'] and h['CapDrop']==['ALL'] and not h['Devices'] and not inspection['Mounts'] and not h.get('Binds') and not h.get('PortBindings') and c['User']=='65534:65534' and 'no-new-privileges' in h['SecurityOpt'] and not h['Privileged'] and not h.get('DeviceRequests') and h['PidsLimit']==32 and h['Memory']==128*1024*1024 and h['MemorySwap']==h['Memory'] and h['NanoCpus']==1000000000 and h['Tmpfs']=={'/tmp':'rw,nosuid,nodev,noexec,size=32m,mode=1777'} and {'Name':'nofile','Soft':64,'Hard':64} in h['Ulimits']
 prefix.with_suffix('.pre-run.json').write_text(json.dumps({'base':BASE,'image':image,'inspect':inspection,'argv':args,'input_sha256':{str(p.relative_to(case)):sha(p) for p in case.rglob('*') if p.is_file()},'entry_sha256':sha(out/'entry.py'),'manifest_sha256':sha(E/'target-manifest.json'),'manifest':manifest},indent=2)+'\n')
 try:p=subprocess.run(['docker','start','-a',cid],capture_output=True,timeout=45)
 except subprocess.TimeoutExpired:run(['docker','stop','-t','1',cid]);raise
 prefix.with_suffix('.stdout.json').write_bytes(p.stdout);prefix.with_suffix('.stderr.txt').write_bytes(p.stderr)
 final=json.loads(run(['docker','inspect',cid]))[0];payload=json.loads(p.stdout);errors=[]
 for name in (['bus'] if label.startswith('bus') else ['runtime','ipc','service','delivery']):
  record=payload.get(name,{})
  if record.get('exit')!=0 or 'PASS ' not in record.get('stdout','') or not record.get('trace') or len(record['trace'].encode())>=2*1024*1024:errors.append('failed actual target case '+name)
  prefix.with_name(prefix.name+'-'+name+'.trace').write_text(record.get('trace',''))
 if final['State']['ExitCode']!=0 or payload.get('all_children_reaped') is not True:errors.append('guest cleanup failed')
 summary={'errors':errors,'target_case_execution':not errors,'production_activation':False,'hardware_access':False,'image':image,'result':payload}
 prefix.with_suffix('.result.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='result'},indent=2));return 1 if errors else 0
if __name__=='__main__':
 try:raise SystemExit(main())
 finally:(E/'offline-commands.json').write_text(json.dumps(commands,indent=2)+'\n')
