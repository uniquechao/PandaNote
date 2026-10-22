#!/usr/bin/env python3
"""Explicit ordinary-file RAM-to-normal install. Default is fully offline dry run."""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import tempfile
import time
import fcntl

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[3]
spec=importlib.util.spec_from_file_location('normal_bundle',ROOT/'bundle.py');bundle=importlib.util.module_from_spec(spec);spec.loader.exec_module(bundle)
SERIAL='PANDANOTE966U2_DEVELOPMENT'
PID1='16ee0bac0ce0f10e9338847b87a6c4ac64d35c1c062c19f4cbcf28e46a61de6d'
CMDLINE='99056ed5ca547a6badf698ae3195d48c031c795ae53918c03b0377fd6a01e73f'
SHA=lambda b:hashlib.sha256(b).hexdigest()
Q=shlex.quote

def readfile(path):
 s=path.lstat()
 if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1:raise ValueError('not a single regular input')
 return path.read_bytes()

def capture(package,candidate_sha,tool_dir,tool_manifest_sha):
 wire,m=bundle.capture(package,candidate_sha)
 raw=readfile(tool_dir/'manifest.json')
 if SHA(raw)!=tool_manifest_sha:raise ValueError('not exact reviewed tool manifest')
 tool=json.loads(raw)
 if tool.get('application')!='pandanote-normal-apply' or tool.get('execution_performed') is not False:raise ValueError('unexpected apply-tool provenance')
 binary=readfile(tool_dir/'pandanote-normal-apply.mipsel')
 if SHA(binary)!=tool['artifact_sha256'] or len(binary)!=tool['artifact_bytes']:raise ValueError('apply tool changed')
 for name,digest in tool['source_sha256'].items():
  path=ROOT/name if name in ('apply_tool.c','build_apply.py','apply_transport.py','bundle.py','transaction.py') else ROOT.parents[1]/'third_party/sha256'/name
  if SHA(readfile(path))!=digest:raise ValueError('apply source changed '+name)
 for name,digest in tool['startup_sha256'].items():
  if SHA(readfile(ROOT.parents[1]/'build-support'/name))!=digest:raise ValueError('startup source changed')
 for name,digest in m['sources'].items():
  if name=='reviewed-radio-stage-inputs.sha256':path=package/('files/user/pandanote/apps/releases/'+m['native_sha256']+'/radio/radio-stage-inputs.sha256')
  else:path=ROOT/name
  if SHA(readfile(path))!=digest:raise ValueError('normal boot source changed '+name)
 return wire,binary,dict(candidate_sha256=candidate_sha,tool_manifest_sha256=tool_manifest_sha,
  tool_sha256=SHA(binary),bundle_sha256=SHA(wire),bundle_bytes=len(wire),files=len(m['files']),
  target_serial=SERIAL,physical_acceptance=False,normal_boot_performed=False,
  scope='listed regular files; current pointer; p3 transaction backup; inittab last; one p2 RW attempt',
  forbidden=['block raw writes','bootloader','kernel','GPT','format','fsck','swap','automatic reset'])

class Adb:
 def __init__(self,serial,port):
  if serial!=SERIAL or port not in (5037,5039):raise ValueError('explicit known USB RAM target and server required')
  self.serial=serial;self.base=['/opt/homebrew/bin/adb','-P',str(port)]
  self.env=dict(os.environ,ADB_MDNS_AUTO_CONNECT='',ADB_LOCAL_TRANSPORT_MAX_PORT='0')
 def run(self,args,timeout=15):
  r=subprocess.run(self.base+args,capture_output=True,text=True,env=self.env,timeout=timeout)
  if r.returncode:raise RuntimeError('ADB failed: '+r.stderr[:300])
  return r.stdout
 def target(self):
  lines=self.run(['devices']).splitlines()
  matching=[line for line in lines if line.split()[:1]==[self.serial]]
  if len(matching)!=1 or matching[0].split()!=[self.serial,'device']:raise ValueError('target absent, duplicate or not device')
  if self.run(['-s',self.serial,'get-serialno']).strip()!=self.serial:raise ValueError('target serial mismatch')
 def shell(self,command,timeout=15):
  wrapped=command+'; normal_apply_status=$?; /bin/busybox printf "\\nPANDANOTE_APPLY_SHELL_EXIT=%s\\n" "$normal_apply_status"'
  output=self.run(['-s',self.serial,'shell',wrapped],timeout).replace('\r\n','\n')
  body,marker,status=output.rpartition('\nPANDANOTE_APPLY_SHELL_EXIT=')
  if not marker or status!='0\n':raise RuntimeError('remote failure or missing completion trailer: '+body[-1500:])
  return body
 def push(self,path,target):self.run(['-s',self.serial,'push','-Z',str(path),target],timeout=45)

def inspect_target(adb,allow_root_rw=False):
 adb.target()
 output=adb.shell('/bin/busybox sha256sum /tmp/pid1 /proc/cmdline; /bin/busybox cat /proc/mounts')
 lines=output.splitlines()
 if lines[:2]!=[PID1+'  /tmp/pid1',CMDLINE+'  /proc/cmdline']:raise ValueError('not reviewed current writable RAM identity')
 mounts={}
 for line in lines[2:]:
  fields=line.split()
  if len(fields)!=6 or fields[1] in mounts:raise ValueError('invalid/duplicate mount')
  mounts[fields[1]]=fields
 for path,device,option in [('/',('/dev/root','/dev/mmcblk0p2'),'ro'),('/home',('/dev/mmcblk0p3',),'rw'),('/user',('/dev/mmcblk0p9',),'rw'),('/run/pandanote-opt',('/dev/mmcblk0p5',),'ro')]:
  f=mounts.get(path,[])
  if len(f)!=6 or f[0] not in device or f[2]!='ext4' or (option not in f[3].split(',') and not(path=='/' and allow_root_rw and 'rw' in f[3].split(','))):raise ValueError('unexpected persistent mount '+path)
 return dict(pid1_sha256=PID1,cmdline_sha256=CMDLINE,mounts=lines[2:])

def execute(adb,wire,binary,report,attempt,journal,rollback=False):
 if not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}',attempt):raise ValueError('invalid attempt id')
 wire=bytes(wire);binary=bytes(binary);report=json.loads(json.dumps(report))
 if SHA(wire)!=report['bundle_sha256'] or SHA(binary)!=report['tool_sha256']:raise ValueError('captured plan bytes changed')
 journal.parent.mkdir(parents=True,exist_ok=True)
 fd=os.open(journal,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 def record(event,**extra):
  data=json.dumps(dict(event=event,time=datetime.datetime.now(datetime.timezone.utc).isoformat(),**extra),sort_keys=True)+'\n';remaining=data.encode()
  while remaining:
   n=os.write(fd,remaining)
   if n<=0:raise OSError('short audit write')
   remaining=remaining[n:]
  os.fsync(fd)
 lease=None
 try:
  record('attempt-created',**report,rollback=rollback)
  lease_path=ROOT/'build/apply-transport.lock';lease=os.open(lease_path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
  record('target-inspected',**inspect_target(adb,allow_root_rw=rollback))
  remote='/tmp/pandanote-normal-install-'+attempt
  # mkdir is exclusive; never adopt, delete or reuse a prior device staging path.
  adb.shell('/bin/busybox mkdir -m 0700 '+Q(remote))
  record('private-stage-created',path=remote)
  with tempfile.TemporaryDirectory(dir=ROOT/'build',prefix='transport-captured-') as temp:
   p=Path(temp);tool=p/'apply.mipsel';image=p/'bundle';tool.write_bytes(binary);image.write_bytes(wire);tool.chmod(0o600);image.chmod(0o600)
   adb.push(tool,remote+'/apply.mipsel');adb.push(image,remote+'/bundle')
  output=adb.shell('/bin/busybox sha256sum '+Q(remote+'/apply.mipsel')+' '+Q(remote+'/bundle'))
  if output.splitlines()!=[report['tool_sha256']+'  '+remote+'/apply.mipsel',report['bundle_sha256']+'  '+remote+'/bundle']:raise ValueError('staged captured bytes mismatch')
  adb.shell('/bin/busybox chmod 0700 '+Q(remote+'/apply.mipsel'))
  record('staged-bytes-verified',path=remote)
  # The C helper checks geometry/node/GPT and owns guard handoff, RW/RO, fsync
  # and rollback. No host shell remount or unguarded ordinary file application.
  command=Q(remote+'/apply.mipsel')+(' --rollback' if rollback else '')+' '+Q(remote+'/bundle')+' '+report['bundle_sha256']
  output=adb.shell(command,timeout=180)
  record('ordinary-file-transaction-completed',stdout=output)
  post=inspect_target(adb)
  record('postcheck-root-ro',**post)
  return dict(status='ordinary-file-rollback-completed' if rollback else 'ordinary-file-install-completed',
    boot_performed=False,display_acceptance=False,journal=str(journal))
 except BaseException as error:
  record('attempt-stopped',error=type(error).__name__,detail=str(error)[:2000])
  raise
 finally:
  if lease is not None:os.close(lease)
  os.close(fd)

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--package',type=Path,required=True);p.add_argument('--candidate-sha256',required=True)
 p.add_argument('--tool-dir',type=Path,default=ROOT/'build/apply-tool');p.add_argument('--tool-manifest-sha256',required=True)
 p.add_argument('--serial',required=True,choices=(SERIAL,));p.add_argument('--adb-port',type=int,choices=(5037,5039),default=5039)
 p.add_argument('--inspect-target',action='store_true');p.add_argument('--execute-once',action='store_true');p.add_argument('--rollback',action='store_true');p.add_argument('--attempt-id');p.add_argument('--journal',type=Path)
 a=p.parse_args();wire,binary,report=capture(a.package,a.candidate_sha256,a.tool_dir,a.tool_manifest_sha256)
 if not a.execute_once:
  if a.inspect_target:report['readonly_target']=inspect_target(Adb(a.serial,a.adb_port))
  print(json.dumps(dict(status='read-only target inspection' if a.inspect_target else 'offline dry run; no ADB or hardware accessed',**report),indent=2));return
 if not a.attempt_id or a.journal is None:raise ValueError('explicit fresh attempt id and exclusive audit journal required')
 print(json.dumps(execute(Adb(a.serial,a.adb_port),wire,binary,report,a.attempt_id,a.journal,a.rollback),indent=2))
if __name__=='__main__':main()
