import pathlib, subprocess, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class CoreTests(unittest.TestCase):
 def test_native_lifecycle_and_private_files(self):
  with tempfile.TemporaryDirectory() as tmp:
   tmp=pathlib.Path(tmp)
   common=['cc','-std=c11','-Wall','-Wextra','-Werror','-I'+str(ROOT)]
   subprocess.run(common+[str(ROOT/'tests/fixture.c'),'-o',str(tmp/'fixture')],check=True)
   subprocess.run(common+[str(ROOT/'tests/cases.c'),str(ROOT/'core.c'),str(ROOT.parents[2]/'third_party/sha256/sha256.c'),'-I'+str(ROOT.parents[2]/'third_party/sha256'),'-o',str(tmp/'cases')],check=True)
   (tmp/'runtime').mkdir(mode=0o700)
   p=subprocess.run([str(tmp/'cases'),str(tmp/'fixture'),str(tmp/'runtime')],capture_output=True,text=True,timeout=10)
   self.assertEqual(p.returncode,0,p.stdout+p.stderr)
   print(p.stdout,end='')
if __name__=='__main__':unittest.main()
