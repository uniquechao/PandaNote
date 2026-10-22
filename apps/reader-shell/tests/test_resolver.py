import pathlib,subprocess,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class ResolverTests(unittest.TestCase):
 def test_exec_isolation_and_nonblocking_cancel(self):
  out=ROOT/'build/resolver-host';out.mkdir(parents=True,exist_ok=True);binary=out/'resolver-cases'
  r=subprocess.run(['c++','-std=c++98','-Wall','-Wextra','-Werror',str(ROOT/'resolver.cpp'),str(ROOT/'tests/resolver_cases.cpp'),'-o',str(binary)],capture_output=True,text=True)
  self.assertEqual(r.returncode,0,r.stdout+r.stderr)
  r=subprocess.run([str(binary)],capture_output=True,text=True,timeout=8)
  (out/'result.txt').write_text(r.stdout+r.stderr);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
if __name__=='__main__':unittest.main()
