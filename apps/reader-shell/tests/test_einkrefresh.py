import subprocess,tempfile,unittest
from pathlib import Path
class EinkRefreshTests(unittest.TestCase):
 def test_restoration_and_exclusive_mode_policy(self):
  root=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory(dir=root/'build',prefix='eink-policy-') as tmp:
   binary=Path(tmp)/'fixture'
   subprocess.run(['c++','-std=c++98','-Wall','-Wextra','-Werror',str(root/'einkrefresh.cpp'),str(root/'tests/einkrefresh_fixture.cpp'),'-o',str(binary)],check=True,capture_output=True,text=True)
   result=subprocess.run([str(binary)],check=True,capture_output=True,text=True)
   self.assertIn('PASS EINK_POLICY',result.stdout)
   print(result.stdout.strip())
