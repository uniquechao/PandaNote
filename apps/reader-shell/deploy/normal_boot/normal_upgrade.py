#!/usr/bin/env python3
"""Exact NORMAL ordinary-file upgrade. Default offline; separate from RAM transport."""
import argparse,datetime,fcntl,hashlib,importlib.util,json,os,re,shlex,stat,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[3]
def load(name):
 spec=importlib.util.spec_from_file_location('upgrade_'+name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
tx=load('transaction');profile=load('upgrade_profile');ram=load('apply_transport')
SHA=tx.sha;Q=shlex.quote;SERIAL='PANDANOTE966U2_NORMAL'
SOURCES=('apply_tool.c','upgrade_wire.h','upgrade_target.h','build_apply.py','normal_upgrade.py','upgrade_profile.py','transaction.py','bundle.py','apply_transport.py')
def capture_bundle(package,expected):
 raw=tx.safe(package,'/manifest.json').read_bytes()
 if SHA(raw)!=profile.digest(expected):raise ValueError('not exact reviewed candidate')
 m,key,files=tx.capture(package)
 if key!=profile.digest(expected):raise ValueError('not exact reviewed candidate')
 base=profile.validate(m.get('upgrade_from'),m['old_inittab_sha256'])
 if m['boot_id']==base['old_boot_id'] or m['native_sha256']==base['old_native_sha256']:raise ValueError('upgrade requires distinct immutable versions')
 body=bytearray(f"PANDANOTE-UPGRADE-1 {m['boot_id']} {m['native_sha256']} {m['old_inittab_sha256']} {len(files)}\n".encode())
 body.extend(f"BASE {base['old_package_sha256']} {base['old_native_sha256']} {base['old_boot_id']} {base['old_current_sha256']} {base['live_superblock_sha256']} {len(base['old_files'])}\n".encode())
 for f in base['old_files']:body.extend(f"CHECK {f['mode']:o} {f['bytes']} {f['sha256']} {f['path']}\n".encode())
 for path,(f,data) in files.items():
  if not re.fullmatch('[A-Za-z0-9/._-]+',path):raise ValueError('unsupported wire path')
  body.extend(f"{f['role']} {f['mode']:o} {len(data)} {SHA(data)} {path}\n".encode());body.extend(data);body.extend(b'\n')
 if len(body)>24*1024*1024:raise ValueError('bounded upgrade wire exceeded')
 return bytes(body),m

def proof_bytes(proof,model,rollback=False):
 if proof.get('schema')!=1 or proof.get('profile')!='normal-exact-upgrade-proof-v1' or proof.get('active') not in ('old','new'):raise ValueError('exact NORMAL proof required')
 active=proof['active']
 if not rollback and active!='old':raise ValueError('forward requires active old system')
 profile.digest(proof['cmdline_sha256']);records=proof['processes']
 if set(records)!=set(('service','adbd','supervisor','native')):raise ValueError('four exact process identities required')
 native=model['upgrade_from']['old_native_sha256'] if active=='old' else model['native_sha256']
 closure=model['upgrade_from']['old_files'] if active=='old' else model['files']
 elf=next(f['sha256'] for f in closure if f['path']=='/user/pandanote/apps/releases/'+native+'/reader-shell.mipsel')
 for role,r in records.items():
  for key in ('pid','ppid','pgid','sid','starttime'):
   if type(r[key]) is not int or not 0<r[key]<(1<<63):raise ValueError('invalid process identity')
  if not 1<r['pid']<=4194304 or any(r[k]>4194304 for k in ('ppid','pgid','sid')):raise ValueError('PID bound')
  for key in ('exe_sha256','cmdline_sha256'):profile.digest(r[key])
  if r['exe_sha256']!=(elf if role=='native' else profile.BUSYBOX_SHA):raise ValueError('executable identity mismatch')
 s,a,u,n=(records[k] for k in ('service','adbd','supervisor','native'))
 if len({r['pid'] for r in records.values()})!=4 or s['ppid']!=1:raise ValueError('distinct PID1 owned service required')
 for r in (a,u):
  if (r['ppid'],r['pgid'],r['sid'])!=(s['pid'],r['pid'],r['pid']):raise ValueError('owned independent supervisor required')
 if (n['ppid'],n['pgid'],n['sid'])!=(u['pid'],u['pid'],u['pid']):raise ValueError('native ownership mismatch')
 out=f"PANDANOTE-NORMAL-PROOF-1 {active} {proof['cmdline_sha256']}\n"
 for role in ('service','adbd','supervisor','native'):
  r=records[role];out+=role+' '+' '.join(str(r[k]) for k in ('pid','ppid','pgid','sid','starttime','exe_sha256','cmdline_sha256'))+'\n'
 return out.encode('ascii')

def capture(package,candidate_sha,tool_dir,tool_manifest_sha):
 wire,m=capture_bundle(package,candidate_sha);raw=ram.readfile(tool_dir/'manifest.json')
 if SHA(raw)!=profile.digest(tool_manifest_sha):raise ValueError('not exact reviewed upgrade tool manifest')
 tool=json.loads(raw)
 if tool.get('application')!='pandanote-normal-upgrade' or tool.get('execution_performed') is not False or tool.get('profile')!='normal-exact-upgrade-v1':raise ValueError('wrong tool profile')
 binary=ram.readfile(tool_dir/'pandanote-normal-upgrade.mipsel')
 if SHA(binary)!=tool['artifact_sha256'] or len(binary)!=tool['artifact_bytes']:raise ValueError('upgrade tool changed')
 if set(tool['source_sha256'])!=set(SOURCES)|{'sha256.c','sha256.h'}:raise ValueError('upgrade source closure incomplete')
 for name,digest in tool['source_sha256'].items():
  path=ROOT/name if name in SOURCES else ROOT.parents[1]/'third_party/sha256'/name
  if SHA(ram.readfile(path))!=digest:raise ValueError('upgrade source changed '+name)
 for name,digest in tool['startup_sha256'].items():
  if SHA(ram.readfile(ROOT.parents[1]/'build-support'/name))!=digest:raise ValueError('startup changed')
 if set(tool['startup_sha256'])!=set(('start.S','entry.h','csu.cpp','libio-init.c')):raise ValueError('startup closure incomplete')
 for name,digest in m['sources'].items():
  path=package/('files/user/pandanote/apps/releases/'+m['native_sha256']+'/radio/radio-stage-inputs.sha256') if name=='reviewed-radio-stage-inputs.sha256' else ROOT/name
  if SHA(ram.readfile(path))!=digest:raise ValueError('candidate source changed '+name)
 return wire,binary,m,dict(candidate_sha256=candidate_sha,bundle_sha256=SHA(wire),bundle_bytes=len(wire),tool_manifest_sha256=tool_manifest_sha,tool_sha256=SHA(binary),old_package_sha256=m['upgrade_from']['old_package_sha256'],live_superblock_sha256=m['upgrade_from']['live_superblock_sha256'],target_serial=SERIAL,physical_acceptance=False,boot_performed=False,backup_path='/home/pandanote-system/transactions/'+SHA(wire))

class Adb(ram.Adb):
 def __init__(self,serial,port):
  if serial!=SERIAL or port not in (5037,5039):raise ValueError('explicit NORMAL USB target required')
  self.serial=serial;self.base=['/opt/homebrew/bin/adb','-P',str(port)];self.env=dict(os.environ,ADB_MDNS_AUTO_CONNECT='',ADB_LOCAL_TRANSPORT_MAX_PORT='0')
def inspect_target(adb,proof,rollback=False):
 adb.target()
 for path,digest in [('/bin/busybox',profile.BUSYBOX_SHA),('/proc/1/exe',profile.BUSYBOX_SHA),('/proc/cmdline',proof['cmdline_sha256'])]:
  if adb.shell('/bin/busybox sha256sum '+Q(path)).strip()!=digest+'  '+path:raise ValueError('NORMAL live identity changed '+path)
 rescued=False
 if rollback:
  rescued=adb.shell('if [ ! -L /run/pandanote-normal/rescue.reason ] && [ -f /run/pandanote-normal/rescue.reason ]; then /bin/busybox cat /run/pandanote-normal/rescue.reason; fi')=='app-exited\n'
 for role,r in proof['processes'].items():
  prefix='/proc/'+str(r['pid'])
  if rescued and role in ('supervisor','native'):
   adb.shell('[ ! -e '+prefix+' ] && [ ! -e /run/pandanote-normal/app.pid ] && [ ! -L /run/pandanote-normal/app.pid ]');continue
  output=adb.shell('/bin/busybox cat '+prefix+'/stat; /bin/busybox sha256sum '+prefix+'/exe '+prefix+'/cmdline').splitlines()
  if len(output)!=3:raise ValueError('live process proof unavailable')
  head,sep,tail=output[0].rpartition(') ');fields=tail.split()
  if not sep or head.split(' ',1)[0]!=str(r['pid']) or len(fields)<20 or fields[0] in ('Z','X','T','t') or tuple(int(fields[i]) for i in (1,2,3,19))!=tuple(r[k] for k in ('ppid','pgid','sid','starttime')):raise ValueError('live process tuple changed '+role)
  if output[1:]!=[r['exe_sha256']+'  '+prefix+'/exe',r['cmdline_sha256']+'  '+prefix+'/cmdline']:raise ValueError('live process bytes changed '+role)
 return dict(serial=SERIAL,processes=proof['processes'])

def capture_proof(adb,model,active='old'):
 """Read only; output needs explicit hash review before any upgrade invocation."""
 if active not in ('old','new'):raise ValueError('active profile')
 adb.target();native=model['upgrade_from']['old_native_sha256'] if active=='old' else model['native_sha256']
 rows=model['upgrade_from']['old_files'] if active=='old' else model['files'];expected=next(r['sha256'] for r in rows if r['path']=='/user/pandanote/apps/releases/'+native+'/reader-shell.mipsel')
 def pidfile(path):
  raw=adb.shell('/bin/busybox cat '+path)
  if not re.fullmatch('[1-9][0-9]{0,6}\n',raw):raise ValueError('invalid live pidfile')
  pid=int(raw)
  if not 1<pid<=4194304:raise ValueError('invalid live PID')
  return pid
 def process(pid):
  prefix='/proc/'+str(pid);out=adb.shell('/bin/busybox cat '+prefix+'/stat; /bin/busybox sha256sum '+prefix+'/exe '+prefix+'/cmdline').splitlines()
  if len(out)!=3:raise ValueError('live proc capture incomplete')
  head,sep,tail=out[0].rpartition(') ');fields=tail.split()
  if not sep or head.split(' ',1)[0]!=str(pid) or len(fields)<20 or fields[0] in ('Z','X','T','t'):raise ValueError('not active process')
  result=dict(zip(('ppid','pgid','sid','starttime'),(int(fields[i]) for i in (1,2,3,19))));result['pid']=pid
  for i,key,suffix in [(1,'exe_sha256','/exe'),(2,'cmdline_sha256','/cmdline')]:
   parts=out[i].split()
   if len(parts)!=2 or parts[1]!=prefix+suffix:raise ValueError('unexpected proc digest path')
   result[key]=profile.digest(parts[0])
  return result
 supervisor=process(pidfile('/run/pandanote-normal/app.pid'));service=process(supervisor['ppid']);adbd=process(pidfile('/run/pandanote-normal/adbd.pid'))
 # Kernel 4.4 may omit CONFIG_PROC_CHILDREN. Enumerate only PID stat files,
 # cap work on the target, then bound/parse the inventory again on the host.
 scan="""procstat_count=0; /bin/busybox printf 'PANDANOTE_PROC_SCAN_V1\\n'; for procstat_file in /proc/[0-9]*/stat; do procstat_count=$((procstat_count+1)); [ "$procstat_count" -le 512 ] || exit 1; procstat_text=$(/bin/busybox cat "$procstat_file" 2>/dev/null) || { [ ! -e "$procstat_file" ] && continue; exit 1; }; /bin/busybox printf '%s\\n' "$procstat_text"; done"""
 inventory=adb.shell(scan)
 if len(inventory)>512*4096+64:raise ValueError('bounded proc inventory bytes exceeded')
 lines=inventory.splitlines()
 if not lines or lines[0]!='PANDANOTE_PROC_SCAN_V1' or len(lines)>513:raise ValueError('bounded proc inventory records exceeded')
 children=[];seen=set()
 for line in lines[1:]:
  if len(line)>4096:raise ValueError('bounded proc stat bytes exceeded')
  head,sep,tail=line.rpartition(') ');fields=tail.split();reported=head.split(' ',1)[0]
  if not sep or len(fields)<20 or not re.fullmatch('[1-9][0-9]{0,6}',reported) or not re.fullmatch('[0-9]{1,7}',fields[1]):raise ValueError('invalid proc stat inventory')
  pid=int(reported);ppid=int(fields[1])
  if pid>4194304 or ppid>4194304 or pid in seen:raise ValueError('invalid/duplicate proc inventory PID')
  seen.add(pid)
  if ppid==supervisor['pid']:children.append(pid)
 if not children or len(children)>16:raise ValueError('bounded owned children required')
 matches=[]
 for pid in children:
  record=process(pid)
  if record['ppid']!=supervisor['pid']:raise ValueError('owned child parent changed during capture')
  if record['exe_sha256']==expected:matches.append(record)
 if len(matches)!=1:raise ValueError('exactly one owned native required')
 raw=adb.shell('/bin/busybox sha256sum /proc/cmdline').split()
 if len(raw)!=2 or raw[1]!='/proc/cmdline':raise ValueError('cmdline digest path')
 proof=dict(schema=1,profile='normal-exact-upgrade-proof-v1',active=active,cmdline_sha256=profile.digest(raw[0]),processes=dict(service=service,adbd=adbd,supervisor=supervisor,native=matches[0]))
 proof_bytes(proof,model,active=='new');inspect_target(adb,proof);return proof

def execute(adb,wire,binary,report,proof,model,attempt,journal,rollback=False):
 if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,47}',attempt):raise ValueError('fresh attempt id required')
 proofraw=proof_bytes(proof,model,rollback);wire=bytes(wire);binary=bytes(binary)
 if SHA(wire)!=report['bundle_sha256'] or SHA(binary)!=report['tool_sha256']:raise ValueError('captured bytes changed')
 journal.parent.mkdir(parents=True,exist_ok=True);fd=os.open(journal,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);lease=None
 def record(event,**extra):
  data=(json.dumps(dict(event=event,time=datetime.datetime.now(datetime.timezone.utc).isoformat(),**extra),sort_keys=True)+'\n').encode()
  while data:
   n=os.write(fd,data)
   if n<=0:raise OSError('short audit write')
   data=data[n:]
  os.fsync(fd)
 try:
  record('attempt-created',**dict(report,proof_sha256=SHA(proofraw),rollback=rollback))
  lease=os.open(ROOT/'build/normal-upgrade-transport.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
  record('normal-processes-inspected',**inspect_target(adb,proof,rollback))
  remote='/tmp/pandanote-normal-upgrade-'+attempt;adb.shell('/bin/busybox mkdir -m 0700 '+Q(remote));record('private-stage-created',path=remote)
  payload={'upgrade.mipsel':binary,'bundle':wire,'proof':proofraw}
  with tempfile.TemporaryDirectory(dir=ROOT/'build',prefix='upgrade-captured-') as temp:
   for name,data in payload.items():
    p=Path(temp)/name;p.write_bytes(data);p.chmod(0o600);adb.push(p,remote+'/'+name)
  output=adb.shell('/bin/busybox sha256sum '+' '.join(Q(remote+'/'+n) for n in payload))
  if output.splitlines()!=[SHA(data)+'  '+remote+'/'+name for name,data in payload.items()]:raise ValueError('staged bytes changed')
  adb.shell('/bin/busybox chmod 0700 '+Q(remote+'/upgrade.mipsel'));record('staged-bytes-verified')
  command='/bin/busybox env -i PATH=/sbin:/bin:/usr/sbin:/usr/bin '+Q(remote+'/upgrade.mipsel')+(' --rollback' if rollback else '')+' '+Q(remote+'/bundle')+' '+SHA(wire)+' '+Q(remote+'/proof')+' '+SHA(proofraw)
  output=adb.shell(command,timeout=180);record('transaction-completed',stdout=output)
  if ('result='+('rolled-back' if rollback else 'committed')+' root_rw=0') not in output:raise ValueError('missing root-ro completion')
  if not any(line.split()[1:3]==['/','ext4'] and 'ro' in line.split()[3].split(',') for line in adb.shell('/bin/busybox cat /proc/mounts').splitlines() if len(line.split())==6):raise ValueError('postcheck root is not RO')
  record('postcheck-root-ro');return dict(status='rolled-back-root-ro' if rollback else 'committed-root-ro',boot_performed=False,journal=str(journal),rescue_usb_retained=True)
 except BaseException as error:record('attempt-stopped',error=type(error).__name__,detail=str(error)[:2000]);raise
 finally:
  if lease is not None:os.close(lease)
  os.close(fd)
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--package',type=Path,required=True);p.add_argument('--candidate-sha256',required=True);p.add_argument('--tool-dir',type=Path,default=ROOT/'build/upgrade-tool');p.add_argument('--tool-manifest-sha256',required=True)
 group=p.add_mutually_exclusive_group(required=True);group.add_argument('--proof',type=Path);group.add_argument('--capture-proof',type=Path);p.add_argument('--active',choices=('old','new'),default='old');p.add_argument('--proof-sha256');p.add_argument('--rollback',action='store_true');p.add_argument('--serial',choices=(SERIAL,),required=True);p.add_argument('--adb-port',type=int,choices=(5037,5039),default=5039)
 p.add_argument('--inspect-target',action='store_true');p.add_argument('--execute-once',action='store_true');p.add_argument('--attempt-id');p.add_argument('--journal',type=Path)
 a=p.parse_args();wire,binary,m,report=capture(a.package,a.candidate_sha256,a.tool_dir,a.tool_manifest_sha256)
 if a.capture_proof is not None:
  if a.execute_once or a.inspect_target:raise ValueError('proof capture is a separate read-only operation')
  data=tx.canon(capture_proof(Adb(a.serial,a.adb_port),m,a.active))
  with a.capture_proof.open('xb') as output:output.write(data)
  a.capture_proof.chmod(0o600);print(json.dumps(dict(status='read-only proof captured; review before apply',proof_sha256=SHA(data),path=str(a.capture_proof)),indent=2));return
 if a.proof_sha256 is None:raise ValueError('explicit reviewed proof SHA required')
 raw=ram.readfile(a.proof)
 if SHA(raw)!=profile.digest(a.proof_sha256):raise ValueError('not exact reviewed live proof')
 proof=json.loads(raw);proofraw=proof_bytes(proof,m,a.rollback);report['proof_sha256']=SHA(proofraw)
 if not a.execute_once:
  if a.inspect_target:report['readonly_target']=inspect_target(Adb(a.serial,a.adb_port),proof,a.rollback)
  print(json.dumps(dict(status='read-only target inspection' if a.inspect_target else 'offline dry run; no device access',**report),indent=2));return
 if not a.attempt_id or a.journal is None:raise ValueError('explicit attempt and exclusive journal required')
 print(json.dumps(execute(Adb(a.serial,a.adb_port),wire,binary,report,proof,m,a.attempt_id,a.journal,a.rollback),indent=2))
if __name__=='__main__':main()
