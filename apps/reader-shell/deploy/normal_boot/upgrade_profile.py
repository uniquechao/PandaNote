"""Exact old NORMAL closure; offline, with no implicit deployment pins."""
import hashlib,importlib.util,json,re
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('upgrade_transaction',ROOT/'transaction.py');tx=importlib.util.module_from_spec(spec);spec.loader.exec_module(tx)
BUSYBOX_SHA='38081195a5342faafac704f96bec8fb5b4de7a706f74dab88e5c184374f9a593'
def digest(value):
 if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):raise ValueError('explicit SHA256 required')
 return value
def capture_old(package,expected):
 digest(expected)
 raw=tx.safe(package,'/manifest.json').read_bytes()
 if tx.sha(raw)!=expected:raise ValueError('old NORMAL manifest pin mismatch')
 m,key,files=tx.capture(package)
 if key!=expected:raise ValueError('old NORMAL manifest changed during capture')
 oldroot='/user/pandanote/apps/releases/'+m['native_sha256']+'/'
 required=['/etc/pandanote-system/'+m['boot_id']+'/'+name for name in ('service.sh','policy.sh','child-supervisor.sh','SHA256SUMS')]
 required += [oldroot+'manifest.json',oldroot+'reader-shell.mipsel',oldroot+'release.sha256']
 if any(p not in files for p in required):raise ValueError('incomplete old NORMAL closure')
 if files['/user/pandanote/apps/current'][1]!=(m['native_sha256']+'\n').encode():raise ValueError('old current mismatch')
 if ('/etc/pandanote-system/'+m['boot_id']+'/').encode() not in files['/etc/inittab'][1]:raise ValueError('old entry does not bind system')
 native_raw=files[oldroot+'manifest.json'][1]
 if tx.sha(native_raw)!=m['native_sha256']:raise ValueError('old native manifest mismatch')
 native=json.loads(native_raw)
 for artifact in native['artifacts']:
  f,data=files[oldroot+artifact['path']]
  if artifact['sha256']!=f['sha256'] or artifact['bytes']!=len(data):raise ValueError('old native artifact mismatch')
 # Validate both native and system indexes instead of accepting unindexed bytes.
 for index,base in [(oldroot+'release.sha256',oldroot),('/etc/pandanote-system/'+m['boot_id']+'/SHA256SUMS','/etc/pandanote-system/'+m['boot_id']+'/')]:
  seen=set()
  for line in files[index][1].decode('ascii').splitlines():
   h,name=line.split('  ',1);p=base+name
   if p not in files or p in seen or tx.sha(files[p][1])!=digest(h):raise ValueError('old index mismatch')
   seen.add(p)
  want={p for p,(f,_) in files.items() if p.startswith(base) and p!=index}
  if seen!=want:raise ValueError('old index incomplete')
 closure=[{k:f[k] for k in ('path','mode','bytes','sha256')} for f,data in files.values() if f['role'] in ('system','release')]
 if len(closure)>128:raise ValueError('old closure exceeded')
 return m,closure
def bind(package,expected,superblock_sha):
 digest(superblock_sha);m,closure=capture_old(package,expected)
 files={f['path']:f for f in m['files']}
 return dict(schema=1,profile='normal-exact-upgrade-v1',old_package_sha256=expected,old_native_sha256=m['native_sha256'],old_boot_id=m['boot_id'],old_inittab_sha256=files['/etc/inittab']['sha256'],old_current_sha256=files['/user/pandanote/apps/current']['sha256'],live_superblock_sha256=superblock_sha,old_files=closure)
def validate(value,entry_sha):
 if not isinstance(value,dict) or value.get('schema')!=1 or value.get('profile')!='normal-exact-upgrade-v1':raise ValueError('exact NORMAL upgrade profile required')
 for key in ('old_package_sha256','old_native_sha256','old_inittab_sha256','old_current_sha256','live_superblock_sha256'):digest(value[key])
 if value['old_inittab_sha256']!=entry_sha or not re.fullmatch('[0-9a-f]{24}',value['old_boot_id']):raise ValueError('old entry/system binding mismatch')
 oldnative=value['old_native_sha256'];oldboot=value['old_boot_id'];seen=set()
 for f in value['old_files']:
  p=f['path'];shape=PurePosixPath(p)
  if not shape.is_absolute() or str(shape)!=p or '..' in shape.parts or not re.fullmatch('[A-Za-z0-9/._-]+',p):raise ValueError('old closure shape')
  digest(f['sha256'])
  if not(p.startswith('/etc/pandanote-system/'+oldboot+'/') or p.startswith('/user/pandanote/apps/releases/'+oldnative+'/')) or p in seen:raise ValueError('old closure path')
  if type(f['mode']) is not int or f['mode'] not in (0o600,0o700) or type(f['bytes']) is not int or not 0<=f['bytes']<=24*1024*1024:raise ValueError('old closure metadata')
  if p.startswith('/etc/') and f['mode']!=0o600:raise ValueError('old system mode')
  seen.add(p)
 if len(seen)<4 or len(seen)>128:raise ValueError('bounded old closure required')
 for p in ('/etc/pandanote-system/'+oldboot+'/service.sh','/etc/pandanote-system/'+oldboot+'/SHA256SUMS','/user/pandanote/apps/releases/'+oldnative+'/reader-shell.mipsel'):
  if p not in seen:raise ValueError('old runtime closure missing')
 return value
