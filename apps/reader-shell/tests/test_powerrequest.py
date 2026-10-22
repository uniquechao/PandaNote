import pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class PowerRequestTests(unittest.TestCase):
 def test_atomic_private_publication_and_failures(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'build',prefix='powerrequest-') as tmp:
   base=pathlib.Path(tmp);private=base/'private';private.mkdir(mode=0o700)
   binary=base/'fixture'
   subprocess.run(['c++','-std=c++98','-Wall','-Wextra','-Werror','-DPANDANOTE_POWERREQUEST_TEST',str(ROOT/'powerrequest.cpp'),str(ROOT/'tests/powerrequest_fixture.cpp'),'-o',str(binary)],check=True,capture_output=True,text=True)
   result=subprocess.run([str(binary),str(private)],capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stdout+result.stderr)
   self.assertIn('PASS POWER_REQUEST',result.stdout);print(result.stdout.strip())
if __name__=='__main__':unittest.main()
