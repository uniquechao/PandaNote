"""Exact NORMAL upgrade tests: own native clone helper and fake transport only."""
import hashlib,importlib.util,json,os,shutil,subprocess,tempfile,unittest
from unittest import mock
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OLD=Path(__import__('os').environ.get('PANDANOTE_UPGRADE_BASELINE', 'external-inputs/upgrade-baseline'))
OLD_SHA='82a7dfa3c9a78ebc18e2957b072f6828a94a180afd80ff1fc01fd731a0e957de'
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
class UpgradeTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.profile=module('upgrade_profile',ROOT/'upgrade_profile.py')
  cls.up=module('normal_upgrade',ROOT/'normal_upgrade.py')
  cls.tx=module('normal_tx',ROOT/'transaction.py')
  cls.old,cls.closure=cls.profile.capture_old(OLD,OLD_SHA)
  cls.oldentry=(OLD/'files/etc/inittab').read_bytes();cls.oldpointer=(OLD/'files/user/pandanote/apps/current').read_bytes()
  cls.elf=next(row['sha256'] for row in cls.closure if row['path'].endswith('/reader-shell.mipsel'))
  sha=ROOT.parents[1]/'third_party/sha256';cls.binary=ROOT/'build/upgrade.fixture'
  result=subprocess.run(['cc','-std=c99','-DPANDANOTE_FIXTURE','-DPANDANOTE_NORMAL_UPGRADE','-I'+str(sha),str(ROOT/'apply_tool.c'),str(sha/'sha256.c'),'-o',str(cls.binary)],capture_output=True,text=True)
  if result.returncode:raise AssertionError(result.stderr)
  cls.identity=ROOT/'build/upgrade-identity.fixture'
  result=subprocess.run(['cc','-std=c99','-I'+str(sha),str(ROOT/'tests/upgrade_identity_check.c'),str(sha/'sha256.c'),'-o',str(cls.identity)],capture_output=True,text=True)
  if result.returncode:raise AssertionError(result.stderr)
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'build');self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
  self.root=self.base/'clone';self.root.mkdir();(self.root/'.pandanote-normal-clone').write_text('pandanote-normal-boot-local-clone-v1\n')
  for row in self.old['files']:
   p=self.root/row['path'].lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((OLD/row['source']).read_bytes());p.chmod(row['mode'])
  (self.root/'user/pandanote/state').mkdir(exist_ok=True);(self.root/'home').mkdir(exist_ok=True)
  self.package=self.base/'candidate';self.package.mkdir();self.native='a'*64;self.boot='b'*24
  self.meta=dict(schema=1,profile='normal-persistent-v1',device_apply_supported=False,boot_id=self.boot,native_sha256=self.native,old_inittab_sha256=hashlib.sha256(self.oldentry).hexdigest(),sources={},files=[])
  for path,data,mode,role in [('/etc/pandanote-system/'+self.boot+'/service.sh',b'new own service\n',0o600,'system'),('/user/pandanote/apps/releases/'+self.native+'/reader-shell.mipsel',b'new own ELF fixture\n',0o700,'release'),('/user/pandanote/apps/current',(self.native+'\n').encode(),0o600,'pointer'),('/etc/inittab',b'new normal entry\n',0o644,'entry')]:
   p=self.package/'files'/path.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
   self.meta['files'].append(dict(path=path,source='files/'+path.lstrip('/'),mode=mode,role=role,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
  self.meta['upgrade_from']=self.profile.bind(OLD,OLD_SHA,'c'*64)
  (self.package/'manifest.json').write_bytes(self.tx.canon(self.meta));self.candidate=hashlib.sha256((self.package/'manifest.json').read_bytes()).hexdigest()
  self.proof=dict(schema=1,profile='normal-exact-upgrade-proof-v1',active='old',cmdline_sha256='d'*64,processes={})
  for role,pid,ppid,pgid,sid in [('service',101,1,1,1),('adbd',201,101,201,201),('supervisor',202,101,202,202),('native',203,202,202,202)]:
   self.proof['processes'][role]=dict(pid=pid,ppid=ppid,pgid=pgid,sid=sid,starttime=pid+1000,exe_sha256=self.elf if role=='native' else self.profile.BUSYBOX_SHA,cmdline_sha256='e'*64)
  self.wire,self.model=self.up.capture_bundle(self.package,self.candidate)
  self.key=hashlib.sha256(self.wire).hexdigest();self.wirepath=self.base/'wire';self.wirepath.write_bytes(self.wire)
  self.proofraw=self.up.proof_bytes(self.proof,self.model,False);self.proofpath=self.base/'proof';self.proofpath.write_bytes(self.proofraw)
 def run_c(self,rollback=False,env=None):
  args=[str(self.binary),'--clone',str(self.root)]+(['--rollback'] if rollback else [])+[str(self.wirepath),self.key,str(self.proofpath),hashlib.sha256(self.proofraw).hexdigest()]
  return subprocess.run(args,capture_output=True,text=True,env=dict(os.environ,**(env or {})))
 def test_actual_old_package_closure_and_new_wire_bind_current_system_and_sb(self):
  self.assertEqual(self.meta['upgrade_from']['old_inittab_sha256'],'841c80819c2a802eb6a858cd1de9bca4ba970040af10a7a8eda12bd7e95e22bc')
  self.assertTrue(self.wire.startswith(b'PANDANOTE-UPGRADE-1 '));self.assertIn(b'c'*64,self.wire)
  self.assertGreater(len(self.closure),40)
 def test_wrong_old_package_pin_is_rejected(self):
  with self.assertRaises(ValueError):self.profile.capture_old(OLD,'0'*64)
 def test_native_clone_commit_then_exact_rollback_keeps_old_release(self):
  r=self.run_c();self.assertEqual(r.returncode,0,(r.stdout,r.stderr))
  self.assertEqual((self.root/'etc/inittab').read_bytes(),b'new normal entry\n')
  r=self.run_c(True);self.assertEqual(r.returncode,0,(r.stdout,r.stderr))
  self.assertEqual((self.root/'etc/inittab').read_bytes(),self.oldentry);self.assertEqual((self.root/'user/pandanote/apps/current').read_bytes(),self.oldpointer)
  self.assertTrue((self.root/'user/pandanote/apps/releases'/self.old['native_sha256']/'reader-shell.mipsel').exists())
 def test_old_current_or_system_corruption_refused_before_backup(self):
  for path in ['user/pandanote/apps/current','etc/pandanote-system/'+self.old['boot_id']+'/policy.sh']:
   original=(self.root/path).read_bytes();(self.root/path).write_bytes(b'corrupt')
   r=self.run_c();self.assertNotEqual(r.returncode,0);self.assertEqual((self.root/'etc/inittab').read_bytes(),self.oldentry)
   self.assertFalse((self.root/'home/pandanote-system/transactions').exists());(self.root/path).write_bytes(original)
 def test_crash_after_entry_can_rollback_in_fresh_process(self):
  self.assertEqual(self.run_c(env={'PANDANOTE_CRASH_PHASE':'entry-durable'}).returncode,99)
  r=self.run_c(True);self.assertEqual(r.returncode,0,(r.stdout,r.stderr));self.assertEqual((self.root/'etc/inittab').read_bytes(),self.oldentry)
 def test_wrong_proof_identity_and_shared_supervisors_are_rejected(self):
  self.proof['processes']['adbd']['pid']=202
  with self.assertRaises(ValueError):self.up.proof_bytes(self.proof,self.model,False)
 def test_forward_profile_cannot_accept_new_active_system(self):
  self.proof['active']='new'
  with self.assertRaises(ValueError):self.up.proof_bytes(self.proof,self.model,False)

 def save_proof(self):
  self.proofraw=self.up.proof_bytes(self.proof,self.model,True);self.proofpath.write_bytes(self.proofraw)
 def test_all_durable_phase_failures_restore_entry_pointer_and_root_ro(self):
  for phase in ('root-rw','payload-file-durable','payload-durable','pointer-durable','before-entry','entry-durable','commit-ready-root-ro'):
   with self.subTest(phase=phase):
    self.setUp();r=self.run_c(env={'PANDANOTE_FAIL_PHASE':phase});self.assertNotEqual(r.returncode,0,(r.stdout,r.stderr))
    self.assertEqual((self.root/'etc/inittab').read_bytes(),self.oldentry);self.assertEqual((self.root/'user/pandanote/apps/current').read_bytes(),self.oldpointer);self.assertIn('root_rw=0',r.stdout)
 def test_individual_file_directory_fsync_failures_are_fail_closed(self):
  failures=0
  for index in range(1,65):
   with self.subTest(fsync=index):
    self.setUp();r=self.run_c(env={'PANDANOTE_FSYNC_FAIL_AT':str(index)})
    if r.returncode:
     failures+=1;self.assertEqual((self.root/'etc/inittab').read_bytes(),self.oldentry);self.assertEqual((self.root/'user/pandanote/apps/current').read_bytes(),self.oldpointer);self.assertIn('root_rw=0',r.stdout)
  self.assertGreater(failures,25)
 def test_signal_at_entry_boundary_restores_previous_pair(self):
  r=self.run_c(env={'PANDANOTE_SIGNAL_PHASE':'entry-durable'});self.assertNotEqual(r.returncode,0);self.assertEqual((self.root/'etc/inittab').read_bytes(),self.oldentry);self.assertEqual((self.root/'user/pandanote/apps/current').read_bytes(),self.oldpointer)
 def test_restart_with_fresh_new_system_process_proof_rolls_back_same_bundle(self):
  self.assertEqual(self.run_c().returncode,0)
  self.proof['active']='new';self.proof['processes']['native']['exe_sha256']=next(f['sha256'] for f in self.meta['files'] if f['path'].endswith('reader-shell.mipsel'))
  for r in self.proof['processes'].values():
   r['pid']+=1000
   if r['ppid']!=1:r['ppid']+=1000
   if r['pgid']!=1:r['pgid']+=1000
   if r['sid']!=1:r['sid']+=1000
   r['starttime']+=2000
  self.save_proof();r=self.run_c(True);self.assertEqual(r.returncode,0,(r.stdout,r.stderr));self.assertEqual((self.root/'etc/inittab').read_bytes(),self.oldentry)
 def test_old_pointer_backup_remains_bound_despite_self_consistent_tampering(self):
  self.assertEqual(self.run_c().returncode,0);backup=self.root/'home/pandanote-system/transactions'/self.key
  forged=b'forged pointer\n';(backup/'old-current').write_bytes(forged);(backup/'meta').write_text('current='+hashlib.sha256(forged).hexdigest()+'\n')
  r=self.run_c(True);self.assertNotEqual(r.returncode,0);self.assertEqual((self.root/'etc/inittab').read_bytes(),b'new normal entry\n')
 def test_closure_symlink_hardlink_mode_and_truncation_are_rejected(self):
  path=self.root/'user/pandanote/apps/releases'/self.old['native_sha256']/'reader-shell.mipsel';original=path.read_bytes()
  for kind in ('symlink','hardlink','mode','truncated'):
   with self.subTest(kind=kind):
    path.unlink();path.write_bytes(original);path.chmod(0o700)
    if kind in ('symlink','hardlink'):
     other=self.base/('outside-'+kind);other.write_bytes(original);other.chmod(0o700);path.unlink()
     if kind=='symlink':path.symlink_to(other)
     else:os.link(other,path)
    elif kind=='mode':path.chmod(0o600)
    else:path.write_bytes(original[:-1])
    r=self.run_c();self.assertNotEqual(r.returncode,0);self.assertEqual((self.root/'etc/inittab').read_bytes(),self.oldentry);self.assertFalse((self.root/'home/pandanote-system/transactions').exists())
 def test_c_independently_rejects_forged_proof_despite_matching_external_hash(self):
  original=self.proofraw
  for value in (original.replace(b'203 202 202 202',b'202 202 202 202'),original.replace(self.elf.encode(),b'0'*64),original.replace(b'old ',b'new '),original+b'trailing\n',original.replace(b'101 1 1 1',b'101 2 1 1')):
   with self.subTest(proof=value[:50]):
    self.proofraw=value;self.proofpath.write_bytes(value);r=self.run_c();self.assertNotEqual(r.returncode,0);self.assertFalse((self.root/'home/pandanote-system/transactions').exists())
 def test_production_stat_predicate_checks_pid_parent_session_starttime_and_state(self):
  path=self.base/'stat';fields=['S','101','202','202']+['0']*15+['1203']
  for change,good in [(None,True),('pid',False),('parent',False),('group',False),('session',False),('start',False),('stopped',False),('zombie',False),('negative',False),('short',False)]:
   row=list(fields);pid=203
   if change=='pid':pid=204
   for name,index,value in [('parent',1,'102'),('group',2,'201'),('session',3,'201'),('start',19,'1204'),('stopped',0,'T'),('zombie',0,'Z'),('negative',19,'-1203')]:
    if change==name:row[index]=value
   if change=='short':row=row[:10]
   path.write_text(str(pid)+' (owned name with ) punctuation) '+' '.join(row)+'\n')
   r=subprocess.run([str(self.identity),'stat',str(path),'203','101','202','202','1203']);self.assertEqual(r.returncode==0,good,change)
 def test_production_argv_rejects_unrelated_shell_and_wrong_system_even_with_valid_proof_hash(self):
  system='/etc/pandanote-system/'+self.old['boot_id'];native='/user/pandanote/apps/releases/'+self.old['native_sha256']+'/reader-shell.mipsel';path=self.base/'cmd'
  cases=[(0,['/bin/busybox','sh',system+'/service.sh'],True),(0,['/bin/busybox','sh','/tmp/service.sh'],False),(0,['/bin/busybox','sh',system+'/service.sh','extra'],False),(1,['/bin/busybox','sh',system+'/child-supervisor.sh','/run/pandanote-normal','adbd','command'],True),(1,['/bin/busybox','sh',system+'/child-supervisor.sh','/run/pandanote-normal','app'],False),(2,['/bin/busybox','sh',system+'/child-supervisor.sh','/run/pandanote-normal','app','command'],True),(3,[native,'--qws-server'],True),(3,['/tmp/reader-shell.mipsel'],False)]
  for role,args,good in cases:
   path.write_bytes(('\0'.join(args)+'\0').encode());r=subprocess.run([str(self.identity),'argv',str(path),str(role),self.old['boot_id'],self.old['native_sha256']]);self.assertEqual(r.returncode==0,good,args)
 def make_tool(self):
  tool=self.base/'tool';tool.mkdir();binary=b'own captured test tool; never executed';(tool/'pandanote-normal-upgrade.mipsel').write_bytes(binary)
  m=dict(schema=1,application='pandanote-normal-upgrade',profile='normal-exact-upgrade-v1',execution_performed=False,artifact_sha256=hashlib.sha256(binary).hexdigest(),artifact_bytes=len(binary),source_sha256={},startup_sha256={})
  for name in self.up.SOURCES:m['source_sha256'][name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
  for name in ('sha256.c','sha256.h'):m['source_sha256'][name]=hashlib.sha256((ROOT.parents[1]/'third_party/sha256'/name).read_bytes()).hexdigest()
  for name in ('start.S','entry.h','csu.cpp','libio-init.c'):m['startup_sha256'][name]=hashlib.sha256((ROOT.parents[1]/'build-support'/name).read_bytes()).hexdigest()
  (tool/'manifest.json').write_bytes(self.tx.canon(m));return tool,m
 def test_tool_and_source_capture_is_exact_and_rejects_ram_tool(self):
  tool,m=self.make_tool();pin=hashlib.sha256((tool/'manifest.json').read_bytes()).hexdigest();wire,binary,model,report=self.up.capture(self.package,self.candidate,tool,pin);self.assertEqual(wire,self.wire)
  m['application']='pandanote-normal-apply';(tool/'manifest.json').write_bytes(self.tx.canon(m));pin=hashlib.sha256((tool/'manifest.json').read_bytes()).hexdigest()
  with self.assertRaises(ValueError):self.up.capture(self.package,self.candidate,tool,pin)
 def test_fake_transport_captures_three_payloads_and_has_no_host_remount(self):
  tool,_=self.make_tool();wire,binary,model,report=self.up.capture(self.package,self.candidate,tool,hashlib.sha256((tool/'manifest.json').read_bytes()).hexdigest());fake=FakeAdb(self.proof);report['proof_sha256']=hashlib.sha256(self.proofraw).hexdigest()
  r=self.up.execute(fake,wire,binary,report,self.proof,model,'host-fixture',self.base/'audit.jsonl');self.assertEqual(r['status'],'committed-root-ro');self.assertEqual(len(fake.payloads),3);self.assertFalse(any('remount' in c or 'kill ' in c or 'reboot' in c for c in fake.commands))
  self.assertTrue(any('transaction-completed' in line for line in (self.base/'audit.jsonl').read_text().splitlines()))
 def test_fake_transport_refuses_changed_stage_before_execution(self):
  tool,_=self.make_tool();wire,binary,model,report=self.up.capture(self.package,self.candidate,tool,hashlib.sha256((tool/'manifest.json').read_bytes()).hexdigest());fake=FakeAdb(self.proof,corrupt=True)
  with self.assertRaises(ValueError):self.up.execute(fake,wire,binary,report,self.proof,model,'corrupt-fixture',self.base/'audit.jsonl')
  self.assertFalse(fake.executed);self.assertIn('attempt-stopped',(self.base/'audit.jsonl').read_text())
 def test_ram_wire_entry_cannot_capture_normal_upgrade(self):
  legacy=module('ram_bundle_entry',ROOT/'bundle.py')
  with self.assertRaises(ValueError):legacy.capture(self.package,self.candidate)
 def test_local_python_clone_enforces_old_closure_and_pointer(self):
  self.root.chmod(0o700);pointer=self.root/'user/pandanote/apps/current';pointer.write_bytes(b'other\n')
  with self.assertRaises(ValueError):self.tx.apply_clone(self.root,self.package)
  self.assertEqual((self.root/'etc/inittab').read_bytes(),self.oldentry)
 def test_capture_rejects_symlink_candidate_manifest_and_wrong_old_system_metadata(self):
  original=(self.package/'manifest.json').read_bytes();outside=self.base/'outside-manifest';outside.write_bytes(original);(self.package/'manifest.json').unlink();(self.package/'manifest.json').symlink_to(outside)
  with self.assertRaises(ValueError):self.up.capture_bundle(self.package,self.candidate)
  self.meta['upgrade_from']['old_files'][0]['path']='/etc/pandanote-system/'+self.old['boot_id']+'/../outside'
  with self.assertRaises(ValueError):self.profile.validate(self.meta['upgrade_from'],self.meta['old_inittab_sha256'])
 def test_readonly_proof_capture_follows_only_verified_owned_children(self):
  fake=FakeAdb(self.proof);proof=self.up.capture_proof(fake,self.model)
  self.assertEqual(proof,self.proof);self.assertFalse(fake.payloads);self.assertFalse(fake.executed);self.assertFalse(any('mkdir' in c or 'kill' in c for c in fake.commands))
 def test_readonly_proof_capture_rejects_wrong_owned_native_executable(self):
  fake=FakeAdb(json.loads(json.dumps(self.proof)));fake.proof['processes']['native']['exe_sha256']='0'*64
  with self.assertRaises(ValueError):self.up.capture_proof(fake,self.model)
  self.assertFalse(fake.payloads);self.assertFalse(fake.executed)
 def test_old_manifest_changed_between_reads_is_rejected(self):
  package=self.base/'retained-old';shutil.copytree(OLD,package);real=self.profile.tx.capture
  def changed(path):
   m=json.loads((path/'manifest.json').read_bytes());m['scope']='changed after reviewed hash check';(path/'manifest.json').write_bytes(self.tx.canon(m));return real(path)
  with mock.patch.object(self.profile.tx,'capture',side_effect=changed):
   with self.assertRaises(ValueError):self.profile.capture_old(package,OLD_SHA)
 def test_builder_rejects_native_without_power_sources_before_packaging(self):
  builder=module('upgrade_candidate_builder',ROOT/'build.py');native=self.base/'old-native';native.mkdir();raw=self.tx.canon(dict(sources={},artifacts=[]));(native/'manifest.json').write_bytes(raw)
  with self.assertRaisesRegex(ValueError,'power'):
   builder.build(native,hashlib.sha256(raw).hexdigest(),self.base/'no-reference',self.base/'no-radio',self.base/'output')
  self.assertFalse((self.base/'output').exists())
 def test_builder_power_feature_gate_preserves_real_source_hash_checks(self):
  builder=module('upgrade_builder_source_gate',ROOT/'build.py');native=self.base/'power-native';native.mkdir();source=self.base/'power-source';source.mkdir();sources={}
  for name in ('powerkeys.h','powerkeys.cpp','powerkeys_posix.cpp','powerrequest.h','powerrequest.cpp'):
   raw=(ROOT.parents[1]/name).read_bytes();(source/name).write_bytes(raw);sources[name]=hashlib.sha256(raw).hexdigest()
  sources['powerkeys.cpp']='0'*64;raw=self.tx.canon(dict(sources=sources,artifacts=[]));(native/'manifest.json').write_bytes(raw)
  with self.assertRaisesRegex(ValueError,'input changed: powerkeys.cpp'):
   builder.build(native,hashlib.sha256(raw).hexdigest(),self.base/'no-reference',self.base/'no-radio',self.base/'output',source)
  self.assertFalse((self.base/'output').exists())
 def test_readonly_proc_scan_refuses_oversized_or_malformed_inventory(self):
  for inventory in ('PANDANOTE_PROC_SCAN_V1\n'+('1 (init) S 0 1 1\n'*513),'PANDANOTE_PROC_SCAN_V1\nmalformed stat\n'):
   fake=FakeAdb(self.proof);fake.scan_override=inventory
   with self.assertRaises(ValueError):self.up.capture_proof(fake,self.model)
   self.assertFalse(fake.payloads);self.assertFalse(fake.executed)
class FakeAdb:
 def __init__(self,proof,corrupt=False):self.proof=proof;self.corrupt=corrupt;self.commands=[];self.payloads={};self.executed=False
 def target(self):pass
 def push(self,path,target):self.payloads[target]=path.read_bytes()
 def shell(self,command,timeout=15):
  import shlex
  self.commands.append(command);args=shlex.split(command)
  if command.startswith('/bin/busybox sha256sum '):
   lines=[]
   for path in args[2:]:
    digest=self.proof['cmdline_sha256'] if path=='/proc/cmdline' else UpgradeTests.profile.BUSYBOX_SHA
    if path in self.payloads:digest=hashlib.sha256(self.payloads[path]+(b'corrupt' if self.corrupt else b'')).hexdigest()
    lines.append(digest+'  '+path)
   return '\n'.join(lines)+'\n'
  if command=='/bin/busybox cat /run/pandanote-normal/app.pid':return str(self.proof['processes']['supervisor']['pid'])+'\n'
  if command=='/bin/busybox cat /run/pandanote-normal/adbd.pid':return str(self.proof['processes']['adbd']['pid'])+'\n'
  if command.endswith('/children'):raise RuntimeError('kernel 4.4 has no task children file')
  if command.startswith('procstat_count=0;'):
   if hasattr(self,'scan_override'):return self.scan_override
   rows=['PANDANOTE_PROC_SCAN_V1']
   for r in self.proof['processes'].values():
    fields=['S',str(r['ppid']),str(r['pgid']),str(r['sid'])]+['0']*15+[str(r['starttime'])];rows.append(str(r['pid'])+' (fixture) '+' '.join(fields))
   fields=['S','1','999','999']+['0']*15+['1999'];rows.append('999 (unrelated) '+' '.join(fields));return '\n'.join(rows)+'\n'
  if command.startswith('/bin/busybox cat /proc/') and '/stat;' in command:
   pid=int(args[2].split('/')[2]);r=next(r for r in self.proof['processes'].values() if r['pid']==pid);fields=['S',str(r['ppid']),str(r['pgid']),str(r['sid'])]+['0']*15+[str(r['starttime'])]
   return str(pid)+' (fixture) '+' '.join(fields)+'\n'+r['exe_sha256']+'  /proc/'+str(pid)+'/exe\n'+r['cmdline_sha256']+'  /proc/'+str(pid)+'/cmdline\n'
  if command.startswith('/bin/busybox mkdir ') or command.startswith('/bin/busybox chmod '):return ''
  if command=='/bin/busybox cat /proc/mounts':return '/dev/root / ext4 ro,relatime 0 0\n'
  if len(args)>4 and args[4].endswith('/upgrade.mipsel'):
   self.executed=True;return 'phase=committed-root-ro\nresult=committed root_rw=0 cleanup_ok=0\n'
  raise AssertionError('unexpected fake command '+command)
