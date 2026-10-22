"""Production pure C safety boundaries with owned bytes, no process signals."""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
ADBD=b'/bin/busybox\0sh\0/tmp/pandanote-development/boot-child.sh\0/tmp/pandanote-development\0adbd\0/usr/bin/adbd\0'
RUNTIME=b'/bin/busybox\0sh\0/tmp/pandanote-development/child-supervisor.sh\0/tmp/pandanote-development\0runtime\0/bin/busybox\0sh\0/tmp/pandanote-development/runtime.sh\0'
class ApplySafetyTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.bin=ROOT/'build/safety-check.fixture'
  subprocess.run(['cc','-std=c11','-I'+str(ROOT.parents[1]/'third_party/sha256'),str(ROOT/'tests/safety_check.c'),str(ROOT.parents[1]/'third_party/sha256/sha256.c'),'-o',str(cls.bin)],capture_output=True,check=True)
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=ROOT/'build');self.addCleanup(self.temp.cleanup);self.p=Path(self.temp.name)
 def sb(self,state=1,compat=0x3c,incompat=0x242,rocompat=0x46b,clean=1):
  b=bytearray(1024);struct.pack_into('<I',b,4,131072);struct.pack_into('<H',b,56,0xef53);struct.pack_into('<H',b,58,state)
  for pos,value in ((92,compat),(96,incompat),(100,rocompat)):struct.pack_into('<I',b,pos,value)
  p=self.p/'sb';p.write_bytes(b);return subprocess.run([str(self.bin),'superblock',str(p),str(clean)],capture_output=True).returncode
 def supervisor(self,role=1,cmd=ADBD,exe='/bin/busybox',start='777',expected='777',state='S',parent=1,pgid=123,sid=123,prefix=123):
  stat=f'{prefix} (busybox) {state} {parent} {pgid} {sid} '+'0 '*15+start+' 0 0\n'
  (self.p/'stat').write_text(stat);(self.p/'cmd').write_bytes(cmd)
  return subprocess.run([str(self.bin),'supervisor','123',str(role),str(self.p/'stat'),exe,str(self.p/'cmd'),expected],capture_output=True,text=True).returncode
 def test_only_exact_clean_superblock_and_features_can_begin_rw(self):
  self.assertEqual(self.sb(),0)
  for state in (0,2,3,4,5,0x101):self.assertNotEqual(self.sb(state=state),0,state)
  for kwargs in (dict(incompat=0x246),dict(incompat=0x342),dict(compat=0x3d),dict(rocompat=0x46f)):
   self.assertNotEqual(self.sb(**kwargs),0,kwargs)
 def test_active_rw_context_may_have_recovery_bit_but_never_error_state(self):
  self.assertEqual(self.sb(state=0,incompat=0x246,clean=0),0)
  self.assertNotEqual(self.sb(state=3,incompat=0x246,clean=0),0)
 def test_distinct_pid_is_hard_boundary_before_group_signal(self):
  self.assertEqual(subprocess.run([str(self.bin),'distinct','123','456']).returncode,0)
  for pair in (('123','123'),('1','456'),('-1','456')):
   self.assertNotEqual(subprocess.run([str(self.bin),'distinct',*pair]).returncode,0)
 def test_exact_adbd_and_runtime_supervisor_are_separately_bound(self):
  self.assertEqual(self.supervisor(),0);self.assertEqual(self.supervisor(role=2,cmd=RUNTIME),0)
  self.assertNotEqual(self.supervisor(role=2,cmd=ADBD),0);self.assertNotEqual(self.supervisor(role=1,cmd=RUNTIME),0)
 def test_correct_session_with_wrong_argv_exe_or_reused_starttime_is_rejected(self):
  for kw in (dict(exe='/usr/bin/adbd'),dict(cmd=ADBD+b'\0'),dict(cmd=ADBD.replace(b'adbd\0',b'runtime\0')),dict(start='778'),dict(start='18446744073709551616'),dict(prefix=124)):
   self.assertNotEqual(self.supervisor(**kw),0,kw)
 def test_parent_session_and_zombie_rejected(self):
  for kw in (dict(parent=7),dict(pgid=9),dict(sid=9),dict(state='Z'),dict(state='X')):
   self.assertNotEqual(self.supervisor(**kw),0,kw)
if __name__=='__main__':unittest.main(verbosity=2)
