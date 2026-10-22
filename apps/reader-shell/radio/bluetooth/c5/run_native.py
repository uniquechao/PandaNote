#!/usr/bin/env python3
"""Compile own native fixtures only, execute in immutable disposable C1 lab."""
import hashlib,json,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent;BT=ROOT.parent;SHELL=BT.parents[1];OUT=BT/'build/c5';E=ROOT/'evidence'
BASE='sha256:20ecae4195e6336bf3453516a52af3ba33fecd3052332d6094399a0a354e6cb0'
COMPILER='sha256:01efbcb1139e516a7714b0520831e5c9d74e8d62a2f573fa8aee4fb12b78e4fb'
commands=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args,check=True):
 p=subprocess.run([str(x) for x in args],capture_output=True,timeout=90);commands.append({'argv':[str(x) for x in args],'exit':p.returncode,'stdout':p.stdout.decode(errors='replace'),'stderr':p.stderr.decode(errors='replace')})
 if check and p.returncode:raise RuntimeError(p.stdout.decode(errors='replace')+p.stderr.decode(errors='replace'))
 return p

def main():
 label=sys.argv[1]
 if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}',label):raise ValueError('safe evidence label')
 prefix=E/('native-'+label)
 if prefix.with_suffix('.inputs.json').exists():raise FileExistsError('preserve evidence')
 context=OUT/('native-'+label);src=context/'src';src.mkdir(parents=True)
 files={str(p.relative_to(SHELL)):p for p in [ROOT/'runner.c',ROOT/'runner.h',ROOT/'tests/cases.c',BT/'c4/supervisor.c',BT/'c4/supervisor.h',BT/'c2/core.c',BT/'c2/core.h',SHELL/'third_party/sha256/sha256.c',SHELL/'third_party/sha256/sha256.h']}
 files['radio/bluetooth/c5/tests/fixture.c']=BT/'c4/tests/fixture.c'
 c4=json.loads((BT/'c4/evidence/target-manifest.json').read_text())
 for name in ['supervisor.c','supervisor.h']:assert sha(BT/'c4'/name)==c4['source_sha256'][name]

 for name,p in files.items():dest=src/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes())
 (context/'entry.py').write_bytes((ROOT/'tests/offline_entry.py').read_bytes())
 flags='-std=c11 -D_GNU_SOURCE -O2 -Wall -Wextra -Werror -fstack-protector-strong -I/src/radio/bluetooth/c5 -I/src/third_party/sha256'
 assert run(['docker','image','inspect','pandanote-qemu-master-build:20261020','--format','{{.Id}}']).stdout.decode().strip()==COMPILER
 assert run(['docker','image','inspect','pandanote-qt-graphics-master:20261020','--format','{{.Id}}']).stdout.decode().strip()==BASE
 (context/'Dockerfile').write_text('FROM pandanote-qemu-master-build:20261020 AS compiler\nCOPY src /src\nRUN mkdir /tmp/pandanote-c5-build && gcc '+flags+' /src/radio/bluetooth/c5/tests/fixture.c -o /tmp/pandanote-c5-build/fixture && gcc '+flags+' /src/radio/bluetooth/c5/tests/cases.c /src/radio/bluetooth/c5/runner.c /src/radio/bluetooth/c4/supervisor.c /src/radio/bluetooth/c2/core.c /src/third_party/sha256/sha256.c -o /tmp/pandanote-c5-build/cases\nFROM pandanote-qt-graphics-master:20261020\nCOPY --from=compiler --chmod=0555 /tmp/pandanote-c5-build/fixture /tmp/pandanote-c5-build/cases /case/\nCOPY --chmod=0444 entry.py /entry.py\nENTRYPOINT ["/usr/bin/timeout","25","/usr/bin/python3","/entry.py"]\n')
 prefix.with_suffix('.inputs.json').write_text(json.dumps({'compiler':COMPILER,'lab_base':BASE,'source_sha256':{n:sha(p) for n,p in files.items()},'entry_sha256':sha(context/'entry.py'),'dockerfile_sha256':sha(context/'Dockerfile')},indent=2)+'\n')
 image_tag='pandanote-bluetooth-c5-native:'+label
 build=run(['docker','build','--network=none','--pull=false','-t',image_tag,context],False)
 prefix.with_suffix('.build.txt').write_bytes(build.stdout+build.stderr)
 if build.returncode:return build.returncode
 image=run(['docker','image','inspect',image_tag,'--format','{{.Id}}']).stdout.decode().strip();base=json.loads(run(['docker','image','inspect',BASE]).stdout)[0];layers=json.loads(run(['docker','image','inspect',image,'--format','{{json .RootFS.Layers}}']).stdout)
 assert layers[:len(base['RootFS']['Layers'])]==base['RootFS']['Layers']
 args=['docker','create','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--pids-limit','32','--memory','128m','--memory-swap','128m','--cpus','1','--ulimit','core=0','--ulimit','nofile=256:256','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777',image]
 cid=run(args).stdout.decode().strip();inspect=json.loads(run(['docker','inspect',cid]).stdout)[0];h=inspect['HostConfig'];c=inspect['Config']
 assert h['NetworkMode']=='none' and h['ReadonlyRootfs'] and h['CapDrop']==['ALL'] and not h['Devices'] and not inspect['Mounts'] and not h.get('Binds') and not h.get('PortBindings') and c['User']=='65534:65534' and 'no-new-privileges' in h['SecurityOpt'] and not h['Privileged'] and not h.get('DeviceRequests') and h['PidsLimit']==32 and h['Memory']==128*1024*1024 and h['MemorySwap']==h['Memory'] and h['NanoCpus']==1000000000 and h['Tmpfs']=={'/tmp':'rw,nosuid,nodev,noexec,size=32m,mode=1777'}
 prefix.with_suffix('.pre-run.json').write_text(json.dumps({'image':image,'inspect':inspect,'argv':args},indent=2)+'\n')
 try:p=run(['docker','start','-a',cid],False)
 except subprocess.TimeoutExpired:
  run(['docker','stop','--time','2',cid],False)
  raise
 prefix.with_suffix('.stdout.json').write_bytes(p.stdout);prefix.with_suffix('.stderr.txt').write_bytes(p.stderr);final=json.loads(run(['docker','inspect',cid]).stdout)[0]
 try:payload=json.loads(p.stdout)
 except (ValueError,UnicodeDecodeError):payload={'unparseable_stdout':p.stdout.decode(errors='replace')}
 ok=final['State']['ExitCode']==0 and payload.get('exit')==0 and payload.get('reaped') is True and 'PASS C5 owned bounded attach core' in payload.get('stdout','')
 prefix.with_suffix('.result.json').write_text(json.dumps({'success':ok,'vendor_execution':False,'target_execution':False,'native_linux':True,'result':payload,'image':image},indent=2)+'\n');print(json.dumps({'success':ok,'result':payload},indent=2));return 0 if ok else 1
if __name__=='__main__':
 try:raise SystemExit(main())
 finally:E.mkdir(exist_ok=True);(E/('native-'+sys.argv[1]+'-commands.json')).write_text(json.dumps(commands,indent=2)+'\n')
