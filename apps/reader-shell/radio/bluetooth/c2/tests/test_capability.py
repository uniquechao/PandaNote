import pathlib, subprocess, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class CapabilityTests(unittest.TestCase):
 def test_owner_and_hci0_interfaces_and_bounds(self):
  with tempfile.TemporaryDirectory() as t:
   out=pathlib.Path(t)/'cases'
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I'+str(ROOT),str(ROOT/'tests/capability_cases.c'),str(ROOT/'capability.c'),'-o',str(out)],check=True)
   p=subprocess.run([str(out)],capture_output=True,text=True,timeout=3)
   self.assertEqual(p.returncode,0,p.stderr)
