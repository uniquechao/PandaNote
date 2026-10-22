"""Owned local clone only; never mount or contact a reader."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('normal_transaction',ROOT/'transaction.py');tx=importlib.util.module_from_spec(spec);spec.loader.exec_module(tx)
class Crash(BaseException):pass
class TransactionTests(unittest.TestCase):
 def setUp(self):
  (ROOT/'build').mkdir(exist_ok=True)
  self.temp=tempfile.TemporaryDirectory(dir=ROOT/'build');self.addCleanup(self.temp.cleanup)
  self.base=Path(self.temp.name);self.root=self.base/'clone';self.root.mkdir();(self.root/'.pandanote-normal-clone').write_bytes(tx.MARKER)
  self.package=self.base/'package';self.package.mkdir();self.old=b'::sysinit:/old-valid-init\n';self.pointer=b'previous-reviewed-release\n'
  (self.root/'etc').mkdir();(self.root/'etc/inittab').write_bytes(self.old);(self.root/'etc/inittab').chmod(0o644)
  (self.root/'user/pandanote/apps').mkdir(parents=True);(self.root/'user/pandanote/apps/current').write_bytes(self.pointer);(self.root/'user/pandanote/apps/current').chmod(0o600)
  self.native='a'*64;self.boot='b'*24
  entries=[('/user/pandanote/apps/releases/'+self.native+'/reader-shell.mipsel',b'owned fake ELF',0o700,'release'),('/etc/pandanote-system/'+self.boot+'/early.sh',b'owned new boot',0o600,'system'),('/user/pandanote/apps/current',(self.native+'\n').encode(),0o600,'pointer'),('/etc/inittab',b'::sysinit:/new-reviewed-init\n',0o644,'entry')]
  self.m=dict(schema=1,profile='normal-persistent-v1',boot_id=self.boot,native_sha256=self.native,device_apply_supported=False,old_inittab_sha256=tx.sha(self.old),files=[])
  for path,data,mode,role in entries:
   source='files/'+path.lstrip('/');p=self.package/source;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
   self.m['files'].append(dict(path=path,source=source,sha256=tx.sha(data),bytes=len(data),mode=mode,role=role))
  self.save()
 def save(self):(self.package/'manifest.json').write_bytes(tx.canon(self.m))
 def readentry(self):return (self.root/'etc/inittab').read_bytes()
 def apply(self,**kw):return tx.apply_clone(self.root,self.package,**kw)
 def crash(self,stage):
  def fault(name):
   if name==stage:raise Crash(name)
  with self.assertRaises(Crash):self.apply(fault=fault)
 def test_commit_last_all_payload_and_pointer_durable(self):
  seen=[]
  def fault(stage):
   seen.append(stage)
   if stage=='before-entry':
    self.assertEqual(self.readentry(),self.old)
    for f in self.m['files']:
     if f['role']!='entry':self.assertEqual(tx.sha(tx.safe(self.root,f['path']).read_bytes()),f['sha256'])
  self.assertEqual(self.apply(fault=fault)['state'],'committed');self.assertEqual(seen[-1],'after-entry')
 def test_exact_rollback_restores_entry_pointer_and_modes(self):
  self.apply();result=tx.rollback_clone(self.root,self.package)
  self.assertEqual(self.readentry(),self.old);self.assertEqual((self.root/'user/pandanote/apps/current').read_bytes(),self.pointer)
  self.assertEqual(stat.S_IMODE((self.root/'etc/inittab').stat().st_mode),0o644);self.assertFalse(result['whole_disk_restore'])
 def test_backup_interruption_leaves_old_boot(self):
  self.crash('backup-durable');self.assertEqual(self.readentry(),self.old);tx.rollback_clone(self.root,self.package)
 def test_payload_interruption_leaves_old_boot(self):
  self.crash('after-write:'+self.m['files'][0]['path']);self.assertEqual(self.readentry(),self.old);tx.rollback_clone(self.root,self.package)
 def test_pointer_interruption_retains_old_boot_entry(self):
  self.crash('pointer-durable');self.assertEqual(self.readentry(),self.old);tx.rollback_clone(self.root,self.package)
 def test_crash_after_atomic_entry_has_complete_new_release_and_rollback(self):
  self.crash('after-entry');self.assertNotEqual(self.readentry(),self.old);tx.rollback_clone(self.root,self.package);self.assertEqual(self.readentry(),self.old)
 def test_bad_pin_fails_before_backup_or_entry_mutation(self):
  (self.package/self.m['files'][0]['source']).write_bytes(b'changed')
  with self.assertRaises(ValueError):self.apply()
  self.assertEqual(self.readentry(),self.old);self.assertFalse((self.root/'home').exists())
 def test_each_partition_space_budget_is_separate(self):
  for part in ('root','home','user'):
   available=dict(root=10**9,home=10**9,user=10**9);available[part]=0
   with self.assertRaisesRegex(ValueError,'insufficient '+part):self.apply(available=available)
  self.assertFalse((self.root/'home').exists())
 def test_symlink_and_hardlink_targets_refused(self):
  current=self.root/'user/pandanote/apps/current';current.unlink();current.symlink_to(self.root/'etc/inittab')
  with self.assertRaisesRegex(ValueError,'symlink'):self.apply()
  current.unlink();current.write_bytes(self.pointer);current.chmod(0o600);os.link(current,self.root/'alias')
  with self.assertRaisesRegex(ValueError,'hardlink'):self.apply()
 def test_immutable_version_collision_refused(self):
  p=tx.safe(self.root,self.m['files'][0]['path']);p.parent.mkdir(parents=True);p.write_bytes(b'other')
  with self.assertRaisesRegex(ValueError,'immutable'):self.apply()
 def test_wrong_old_entry_and_external_modified_rollback_refused(self):
  (self.root/'etc/inittab').write_bytes(b'unknown')
  with self.assertRaisesRegex(ValueError,'old inittab'):self.apply()
  (self.root/'etc/inittab').write_bytes(self.old);self.apply();(self.root/'etc/inittab').write_bytes(b'external edit')
  with self.assertRaisesRegex(ValueError,'unexpected live entry'):tx.rollback_clone(self.root,self.package)
 def test_no_old_pointer_rollback_removes_only_managed_pointer(self):
  (self.root/'user/pandanote/apps/current').unlink();self.apply();tx.rollback_clone(self.root,self.package)
  self.assertFalse((self.root/'user/pandanote/apps/current').exists());self.assertEqual(self.readentry(),self.old)
 def test_corrupt_journal_cannot_authorize_an_unrelated_live_entry(self):
  result=self.apply();backup=tx.locations(self.root,result['manifest_sha256'])
  state=json.loads((backup/'journal.json').read_text());state['new_inittab_sha256']=tx.sha(b'external edit')
  (backup/'journal.json').write_bytes(tx.canon(state));(self.root/'etc/inittab').write_bytes(b'external edit')
  with self.assertRaisesRegex(ValueError,'journal mismatch'):tx.rollback_clone(self.root,self.package)
 def test_unexpected_entry_mode_refused(self):
  (self.root/'etc/inittab').chmod(0o666)
  with self.assertRaisesRegex(ValueError,'mode changed'):self.apply()
 def test_default_plan_does_not_create_clone_targets(self):
  report=tx.plan(self.package);self.assertFalse(report['device_apply_supported']);self.assertFalse((self.root/'home').exists())
 def test_paths_outside_exact_scope_and_traversal_rejected(self):
  self.m['files'][0]['path']='/dev/mmcblk0';self.save()
  with self.assertRaises(ValueError):self.apply()
if __name__=='__main__':unittest.main(verbosity=2)
