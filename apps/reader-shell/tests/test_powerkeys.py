"""Host TDD for portable power-key policy and bounded evdev stream handling."""
import pathlib,subprocess,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class PowerKeysTests(unittest.TestCase):
 def test_policy_and_stream_with_syscall_fixture(self):
  output=ROOT/'build/powerkeys-host';output.mkdir(parents=True,exist_ok=True)
  binary=output/'powerkeys-cases'
  result=subprocess.run(['c++','-std=c++98','-Wall','-Wextra','-Werror',str(ROOT/'powerkeys.cpp'),str(ROOT/'tests/powerkeys_fixture.cpp'),'-o',str(binary)],capture_output=True,text=True)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
  symbols=subprocess.run(['nm','-u',str(binary)],capture_output=True,text=True,check=True).stdout
  for forbidden in ('_ioctl','_clock_gettime','_reboot','_system','_execve'):
   self.assertNotIn(forbidden,symbols)
  result=subprocess.run([str(binary)],capture_output=True,text=True)
  (output/'stdout.txt').write_text(result.stdout);(output/'stderr.txt').write_text(result.stderr)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
if __name__=='__main__':unittest.main()
