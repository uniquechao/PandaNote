"""Actual owned C installer on native ordinary-file fixtures, no device mounts."""
import importlib.util
import os
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('test_transaction',ROOT/'tests/test_transaction.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
spec=importlib.util.spec_from_file_location('normal_bundle',ROOT/'bundle.py');bundle=importlib.util.module_from_spec(spec);spec.loader.exec_module(bundle)
class ApplyToolTests(unittest.TestCase):
 save=fixture.TransactionTests.save
 readentry=fixture.TransactionTests.readentry
 @classmethod
 def setUpClass(cls):
  # Build our native clone-only program on a fresh checkout. This macro excludes
  # the real device identity, remount and supervisor-signal implementation.
  (ROOT/'build').mkdir(exist_ok=True)
  sha=ROOT.parents[1]/'third_party/sha256'
  r=subprocess.run(['cc','-std=c99','-DPANDANOTE_FIXTURE','-I',str(sha),
   str(ROOT/'apply_tool.c'),str(sha/'sha256.c'),'-o',str(ROOT/'build/apply-tool.fixture')],capture_output=True,text=True)
  if r.returncode:raise AssertionError('clone fixture compilation failed: '+r.stderr)
 def setUp(self):
  fixture.TransactionTests.setUp(self);(self.root/'home').mkdir();(self.root/'user/pandanote/state').mkdir();self.bin=ROOT/'build/apply-tool.fixture'
  self.data,_=bundle.capture(self.package,fixture.tx.sha((self.package/'manifest.json').read_bytes()));self.key=fixture.tx.sha(self.data);self.wire=self.base/'wire';self.wire.write_bytes(self.data)
 def apply(self,**kw):
  if kw: self.skipTest('Python transaction-specific callback/space fixture')
  r=self.run_c();self.assertEqual(r.returncode,0,(r.stdout,r.stderr));return {'state':'committed'}
 def run_c(self,fail=None):
  env=dict(os.environ)
  if fail:env['PANDANOTE_FAIL_PHASE']=fail
  return subprocess.run([str(self.bin),'--clone',str(self.root),str(self.wire),self.key],capture_output=True,text=True,env=env)
 # Only these tests invoke the C protocol; inherited Python-only tests disabled.
 def test_c_commit_writes_exact_list_and_final_entry(self):
  r=self.run_c();self.assertEqual(r.returncode,0,(r.stdout,r.stderr))
  for f in self.m['files']:self.assertEqual(fixture.tx.sha(fixture.tx.safe(self.root,f['path']).read_bytes()),f['sha256'])
  self.assertIn('committed-root-ro',r.stdout)
 def test_c_failures_restore_entry_and_pointer(self):
  for stage in ('root-rw','payload-file-durable','payload-durable','pointer-durable','before-entry','entry-durable'):
   if stage!='root-rw':self.tearDown();self.setUp()
   r=self.run_c(stage);self.assertNotEqual(r.returncode,0,(stage,r.stdout));self.assertEqual(self.readentry(),self.old)
   self.assertEqual((self.root/'user/pandanote/apps/current').read_bytes(),self.pointer)
   self.assertIn('root_rw=0',r.stdout)
 def test_c_explicit_rollback_restores_persistent_backup(self):
  self.assertEqual(self.run_c().returncode,0)
  r=subprocess.run([str(self.bin),'--clone',str(self.root),'--rollback',str(self.wire),self.key],capture_output=True,text=True)
  self.assertEqual(r.returncode,0,(r.stdout,r.stderr));self.assertEqual(self.readentry(),self.old)
  self.assertEqual((self.root/'user/pandanote/apps/current').read_bytes(),self.pointer)
 def test_c_new_process_rollback_after_commit_crash(self):
  env=dict(os.environ,PANDANOTE_CRASH_PHASE='entry-durable')
  r=subprocess.run([str(self.bin),'--clone',str(self.root),str(self.wire),self.key],capture_output=True,text=True,env=env)
  self.assertEqual(r.returncode,99)
  r=subprocess.run([str(self.bin),'--clone',str(self.root),'--rollback',str(self.wire),self.key],capture_output=True,text=True)
  self.assertEqual(r.returncode,0,(r.stdout,r.stderr));self.assertEqual(self.readentry(),self.old)
 def test_c_corrupt_persistent_backup_refused(self):
  self.assertEqual(self.run_c().returncode,0)
  (self.root/'home/pandanote-system/transactions'/self.key/'old-inittab').write_bytes(b'corrupt')
  r=subprocess.run([str(self.bin),'--clone',str(self.root),'--rollback',str(self.wire),self.key],capture_output=True,text=True)
  self.assertNotEqual(r.returncode,0);self.assertNotEqual(self.readentry(),self.old)
 def test_c_individual_file_and_directory_fsync_failures_preserve_old_entry(self):
  failures=0
  for number in range(1,65):
   if number>1:self.setUp()
   env=dict(os.environ,PANDANOTE_FSYNC_FAIL_AT=str(number))
   r=subprocess.run([str(self.bin),'--clone',str(self.root),str(self.wire),self.key],capture_output=True,text=True,env=env)
   if r.returncode:
    failures+=1;self.assertEqual(self.readentry(),self.old,(number,r.stdout,r.stderr))
    self.assertEqual((self.root/'user/pandanote/apps/current').read_bytes(),self.pointer)
  self.assertGreater(failures,25)
 def test_c_bad_bundle_hash_or_scope_cannot_mutate_entry(self):
  self.key='0'*64;r=self.run_c();self.assertNotEqual(r.returncode,0);self.assertEqual(self.readentry(),self.old)
 def test_c_symlink_parent_and_duplicate_attempt_refused(self):
  path=self.root/'etc/pandanote-system';path.symlink_to(self.base)
  r=self.run_c();self.assertNotEqual(r.returncode,0);self.assertEqual(self.readentry(),self.old)
  path.unlink();self.assertEqual(self.run_c().returncode,0);self.assertNotEqual(self.run_c().returncode,0)
if __name__=='__main__':unittest.main(verbosity=2)
