import pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class RuntimeTests(unittest.TestCase):
 def test_own_code_runtime(self):
  with tempfile.TemporaryDirectory() as tmp:
   tmp=pathlib.Path(tmp);out=tmp/'cases';inbox=tmp/'inbox';inbox.mkdir(mode=0o700)
   p=subprocess.run(['cc','-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror','-I'+str(ROOT),str(ROOT/'tests/cases.c'),str(ROOT/'runtime.c'),str(ROOT.parent/'policy.c'),str(ROOT.parents[2]/'third_party/sha256/sha256.c'),'-o',str(out)],capture_output=True,text=True)
   self.assertEqual(p.returncode,0,p.stdout+p.stderr)
   p=subprocess.run([str(out),str(inbox)],capture_output=True,text=True,timeout=5)
   self.assertEqual(p.returncode,0,p.stdout+p.stderr);print(p.stdout,end='')
 def test_own_code_local_ipc(self):
  with tempfile.TemporaryDirectory() as tmp:
   tmp=pathlib.Path(tmp);out=tmp/'cases';runtime=tmp/'runtime';runtime.mkdir(mode=0o700)
   p=subprocess.run(['cc','-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror','-I'+str(ROOT),str(ROOT/'tests/ipc_cases.c'),str(ROOT/'ipc.c'),str(ROOT/'runtime.c'),str(ROOT.parent/'policy.c'),str(ROOT.parents[2]/'third_party/sha256/sha256.c'),'-o',str(out)],capture_output=True,text=True)
   self.assertEqual(p.returncode,0,p.stdout+p.stderr)
   p=subprocess.run([str(out),str(runtime)],capture_output=True,text=True,timeout=5)
   self.assertEqual(p.returncode,0,p.stdout+p.stderr);print(p.stdout,end='')
 def test_stale_ack_delivery_generation(self):
  with tempfile.TemporaryDirectory() as tmp:
   tmp=pathlib.Path(tmp);out=tmp/'cases';runtime=tmp/'runtime';runtime.mkdir(mode=0o700)
   p=subprocess.run(['cc','-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror','-I'+str(ROOT),str(ROOT/'tests/delivery_cases.c'),str(ROOT/'ipc.c'),str(ROOT/'runtime.c'),str(ROOT.parent/'policy.c'),str(ROOT.parents[2]/'third_party/sha256/sha256.c'),'-o',str(out)],capture_output=True,text=True)
   self.assertEqual(p.returncode,0,p.stdout+p.stderr)
   p=subprocess.run([str(out),str(runtime)],capture_output=True,text=True,timeout=10)
   self.assertEqual(p.returncode,0,p.stdout+p.stderr);print(p.stdout,end='')
if __name__=='__main__':unittest.main()
