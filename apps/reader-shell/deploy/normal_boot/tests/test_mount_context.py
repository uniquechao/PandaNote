"""Native invocation of exact production mount_table C predicate, no mounts."""
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
BASE='''/dev/root / ext4 ro,noload 0 0
/dev/mmcblk0p3 /home ext4 rw,nosuid,nodev 0 0
/dev/mmcblk0p9 /user ext4 rw,nosuid,nodev 0 0
/dev/mmcblk0p5 /run/pandanote-opt ext4 ro,noload 0 0
tmpfs /tmp tmpfs rw,nosuid,nodev 0 0
tmpfs /run tmpfs rw,nosuid,nodev 0 0
proc /proc proc rw,nosuid,nodev,noexec 0 0
sysfs /sys sysfs rw,nosuid,nodev,noexec 0 0
devtmpfs /dev devtmpfs rw,nosuid 0 0
devpts /dev/pts devpts rw,nosuid,noexec 0 0
configfs /sys/kernel/config configfs rw,nosuid,nodev,noexec 0 0
adb /dev/usb-ffs/adb functionfs rw,nosuid,nodev,noexec 0 0
'''
class MountContextTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.binary=ROOT/'build/mount-check.fixture'
  subprocess.run(['cc','-std=c11','-I'+str(ROOT.parents[1]/'third_party/sha256'),str(ROOT/'tests/mount_check.c'),str(ROOT.parents[1]/'third_party/sha256/sha256.c'),'-o',str(cls.binary)],capture_output=True,check=True)
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=ROOT/'build');self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)/'mounts'
 def check(self,text,rw=0):
  self.path.write_text(text);return subprocess.run([str(self.binary),str(self.path),str(rw)],capture_output=True,text=True)
 def test_current_ram_baseline_and_single_rw_window(self):
  self.assertEqual(self.check(BASE).returncode,0)
  self.assertEqual(self.check(BASE.replace('/ ext4 ro,noload','/ ext4 rw,noload'),1).returncode,0)
 def test_shadow_install_ancestor_and_descendant_mounts_rejected(self):
  for path in ('/etc','/etc/pandanote-system','/user/pandanote','/user/pandanote/apps','/user/pandanote/apps/releases/new','/home/pandanote-system','/tmp/pandanote-normal-install-fixture'):
   self.assertNotEqual(self.check(BASE+f'tmpfs {path} tmpfs rw 0 0\n').returncode,0,path)
 def test_duplicate_wrong_source_or_persistent_flags_rejected(self):
  for bad in (BASE+'tmpfs /run tmpfs rw,nosuid,nodev 0 0\n',BASE.replace('p9 /user','p3 /user'),BASE.replace('/user ext4 rw,nosuid,nodev','/user ext4 rw,nosuid,nodev,noexec'),BASE.replace('/run/pandanote-opt ext4 ro,noload','/run/pandanote-opt ext4 ro'),BASE.replace('/ ext4 ro,noload','/ ext4 ro,rw,noload')):
   self.assertNotEqual(self.check(bad).returncode,0)
 def test_missing_tmp_run_partial_record_long_line_and_extra_fields_rejected(self):
  for bad in (BASE.replace('tmpfs /run tmpfs rw,nosuid,nodev 0 0\n',''),BASE.rstrip('\n'),BASE+'partial',BASE+'x'*9000+'\n',BASE.replace('ro,noload 0 0','ro,noload 0 0 extra',1)):
   self.assertNotEqual(self.check(bad).returncode,0)
 def test_actual_stream_read_error_does_not_equal_clean_eof(self):
  r=subprocess.run([str(self.binary),str(self.path.parent),'0'],capture_output=True,text=True)
  self.assertNotEqual(r.returncode,0)
  self.assertIn('mountcontext_result=-1',r.stdout)
if __name__=='__main__':unittest.main(verbosity=2)
