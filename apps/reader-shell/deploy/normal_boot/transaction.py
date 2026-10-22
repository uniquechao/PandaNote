#!/usr/bin/env python3
"""Durable LOCAL CLONE transaction only. Default prints plan; no device transport.

Only listed regular files and final /etc/inittab are changed. No erase, format,
partition image restore, USB, mount or execution API is present.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[3]
MARKER=b'pandanote-normal-boot-local-clone-v1\n'
def sha(b):return hashlib.sha256(b).hexdigest()
def canon(x):return (json.dumps(x,sort_keys=True,indent=2)+'\n').encode()
def safe(base,name):
 p=PurePosixPath(name)
 if not p.is_absolute() or str(p)!=name or '..' in p.parts or str(p)=='/':raise ValueError('unsafe target')
 target=base
 for part in p.parts[1:]:
  target=target/part
  if target.is_symlink():raise ValueError('symlink target')
  if target.exists():
   s=target.lstat()
   if not stat.S_ISDIR(s.st_mode) and not(stat.S_ISREG(s.st_mode) and s.st_nlink==1):raise ValueError('special or hardlink target')
 return target

def syncdir(path):
 fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
 try:os.fsync(fd)
 finally:os.close(fd)
def mkdir(path):
 if path.exists():
  if not path.is_dir() or path.is_symlink():raise ValueError('unsafe parent')
  return
 mkdir(path.parent);path.mkdir(mode=0o700);syncdir(path.parent)
def write(path,data,mode):
 mkdir(path.parent);fd,name=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fchmod(f.fileno(),mode);os.fsync(f.fileno())
  os.replace(name,path);syncdir(path.parent)
 finally:
  if os.path.lexists(name):os.unlink(name)

def capture(package):
 raw=(package/'manifest.json').read_bytes();m=json.loads(raw)
 if m.get('schema')!=1 or m.get('profile')!='normal-persistent-v1' or m.get('device_apply_supported') is not False:raise ValueError('not offline normal candidate')
 if not re.fullmatch('[a-f0-9]{24}',m.get('boot_id','')) or not re.fullmatch('[a-f0-9]{64}',m.get('native_sha256','')):raise ValueError('bad version')
 if 'upgrade_from' in m:
  import importlib.util
  spec=importlib.util.spec_from_file_location('normal_exact_profile',ROOT/'upgrade_profile.py');profile=importlib.util.module_from_spec(spec);spec.loader.exec_module(profile);profile.validate(m['upgrade_from'],m['old_inittab_sha256'])
 files={};roles=[]
 for f in m['files']:
  path=f['path'];role=f['role']
  if role=='system':allowed=path.startswith('/etc/pandanote-system/'+m['boot_id']+'/')
  elif role=='release':allowed=path.startswith('/user/pandanote/apps/releases/'+m['native_sha256']+'/')
  elif role=='pointer':allowed=path=='/user/pandanote/apps/current'
  elif role=='entry':allowed=path=='/etc/inittab'
  else:allowed=False
  if not allowed or path in files:raise ValueError('unreviewed path/role')
  safe(package,path) # canonical shape only, package root independent
  for prior in files:
   if PurePosixPath(path) in PurePosixPath(prior).parents or PurePosixPath(prior) in PurePosixPath(path).parents:raise ValueError('shadowed path')
  if (role=='entry' and f['mode']!=0o644) or (role in ('system','pointer') and f['mode']!=0o600):raise ValueError('unexpected target mode')
  if f['source']!='files/'+path.lstrip('/'):raise ValueError('source mapping changed')
  data=safe(package,'/'+f['source']).read_bytes()
  if sha(data)!=f['sha256'] or len(data)!=f['bytes'] or f['mode'] not in (0o600,0o644,0o700):raise ValueError('payload changed')
  files[path]=(f,data);roles.append(role)
 if roles.count('entry')!=1 or roles.count('pointer')!=1:raise ValueError('exact commit/pointer required')
 return m,sha(raw),files

def upgrade_existing(root,m):
 if 'upgrade_from' not in m:return
 for f in m['upgrade_from']['old_files']:
  p=safe(root,f['path'])
  if sha(p.read_bytes())!=f['sha256'] or p.stat().st_size!=f['bytes'] or stat.S_IMODE(p.stat().st_mode)!=f['mode']:raise ValueError('old NORMAL closure changed')

def clone(root):
 root=Path(root).absolute()
 if root!=root.resolve() or not root.is_relative_to(PROJECT) or root==PROJECT:raise ValueError('clone must be inside worktree')
 if safe(root,'/.pandanote-normal-clone').read_bytes()!=MARKER:raise ValueError('missing clone marker')
 return root
@contextmanager
def lock(root):
 p=safe(root,'/.pandanote-normal-lock');fd=os.open(p,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);yield
 finally:os.close(fd)
def locations(root,key):return safe(root,'/home/pandanote-system/transactions/'+key)
def plan(package):
 m,key,files=capture(package)
 return dict(manifest_sha256=key,device_apply_supported=False,files=m['files'],commit_last='/etc/inittab',
  pending=m.get('pending',[]),bytes=sum(len(d) for f,d in files.values()))

def apply_clone(root,package,*,available=None,fault=lambda stage:None):
 root=clone(root);m,key,files=capture(package)
 with lock(root):
  upgrade_existing(root,m)
  entry=safe(root,'/etc/inittab');old=entry.read_bytes();oldmode=stat.S_IMODE(entry.stat().st_mode)
  if oldmode!=0o644:raise ValueError('old inittab mode changed')
  if sha(old)!=m['old_inittab_sha256']:raise ValueError('old inittab identity changed')
  pointer=safe(root,'/user/pandanote/apps/current');oldpointer=pointer.read_bytes() if pointer.exists() else None
  if 'upgrade_from' in m and (oldpointer is None or sha(oldpointer)!=m['upgrade_from']['old_current_sha256']):raise ValueError('old NORMAL current changed')
  if pointer.exists() and stat.S_IMODE(pointer.stat().st_mode)!=0o600:raise ValueError('untrusted current mode')
  for path,(f,data) in files.items():
   target=safe(root,path)
   if f['role'] in ('system','release') and target.exists() and (target.read_bytes()!=data or stat.S_IMODE(target.stat().st_mode)!=f['mode']):raise ValueError('immutable version collision')
  required={'root':1048576,'home':1048576+len(old),'user':1048576}
  for path,(f,data) in files.items():required['user' if path.startswith('/user/') else 'root']+=len(data)+4096
  for partition,need in required.items():
   have=available[partition] if available is not None else os.statvfs(root).f_bavail*os.statvfs(root).f_frsize
   if have<need:raise ValueError('insufficient '+partition+' free bytes')
  backup=locations(root,key)
  if backup.exists():raise ValueError('preserve existing attempt; rollback/review before new attempt')
  mkdir(backup)
  write(backup/'old-inittab',old,0o600)
  if oldpointer is not None:write(backup/'old-current',oldpointer,0o600)
  state=dict(schema=1,manifest_sha256=key,old_inittab_sha256=sha(old),old_inittab_mode=oldmode,
   old_current_sha256=None if oldpointer is None else sha(oldpointer),
   new_inittab_sha256=sha(files['/etc/inittab'][1]),new_current_sha256=sha(files['/user/pandanote/apps/current'][1]),state='prepared')
  write(backup/'journal.json',canon(state),0o600);fault('backup-durable')
  for path,(f,data) in files.items():
   if f['role'] in ('system','release'):
    write(safe(root,path),data,f['mode']);fault('after-write:'+path)
  state['state']='payload-durable';write(backup/'journal.json',canon(state),0o600)
  write(pointer,files['/user/pandanote/apps/current'][1],0o600);fault('pointer-durable')
  state['state']='commit-ready';write(backup/'journal.json',canon(state),0o600)
  fault('before-entry')
  write(entry,files['/etc/inittab'][1],files['/etc/inittab'][0]['mode']);fault('after-entry')
  state['state']='committed';write(backup/'journal.json',canon(state),0o600)
  return dict(state='committed',manifest_sha256=key,device_apply_supported=False)

def rollback_clone(root,package,*,fault=lambda stage:None):
 root=clone(root);m,key,files=capture(package)
 with lock(root):
  upgrade_existing(root,m)
  backup=locations(root,key);state=json.loads(safe(backup,'/journal.json').read_bytes())
  if (state.get('manifest_sha256')!=key or state.get('new_inittab_sha256')!=sha(files['/etc/inittab'][1]) or
      state.get('new_current_sha256')!=sha(files['/user/pandanote/apps/current'][1]) or state.get('old_inittab_mode')!=0o644 or
      state.get('state') not in ('prepared','payload-durable','commit-ready','committed','rolled-back')):raise ValueError('backup journal mismatch')
  old=safe(backup,'/old-inittab').read_bytes()
  if sha(old)!=m['old_inittab_sha256'] or sha(old)!=state['old_inittab_sha256']:raise ValueError('old backup mismatch')
  oldpointer=None if state['old_current_sha256'] is None else safe(backup,'/old-current').read_bytes()
  if 'upgrade_from' in m and (oldpointer is None or sha(oldpointer)!=m['upgrade_from']['old_current_sha256']):raise ValueError('old NORMAL pointer backup changed')
  if oldpointer is not None and sha(oldpointer)!=state['old_current_sha256']:raise ValueError('pointer backup mismatch')
  entry=safe(root,'/etc/inittab');pointer=safe(root,'/user/pandanote/apps/current')
  if sha(entry.read_bytes()) not in (sha(old),state['new_inittab_sha256']):raise ValueError('unexpected live entry')
  if pointer.exists() and sha(pointer.read_bytes()) not in (state['old_current_sha256'],state['new_current_sha256']):raise ValueError('unexpected live pointer')
  if oldpointer is None:
   if pointer.exists():pointer.unlink();syncdir(pointer.parent)
  else:write(pointer,oldpointer,0o600)
  fault('old-pointer-durable')
  write(entry,old,state['old_inittab_mode']);fault('old-entry-durable')
  state['state']='rolled-back';write(backup/'journal.json',canon(state),0o600)
  return dict(state='rolled-back',retained_versions=True,whole_disk_restore=False)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',type=Path,required=True)
 p.add_argument('--clone',type=Path);p.add_argument('--apply-clone',action='store_true');p.add_argument('--rollback-clone',action='store_true')
 a=p.parse_args()
 if a.apply_clone and a.rollback_clone:raise ValueError('one operation')
 if a.apply_clone or a.rollback_clone:
  if a.clone is None:raise ValueError('explicit clone required')
  result=(apply_clone if a.apply_clone else rollback_clone)(a.clone,a.package)
 else:result=plan(a.package)
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
