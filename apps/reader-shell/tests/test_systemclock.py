"""Run our portable production policy with a syscall-only fixture, never MIPS ELF."""
import pathlib,subprocess,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class SystemClockTests(unittest.TestCase):
 def test_authenticated_policy_with_no_real_clock_syscall(self):
  output=ROOT/'build/systemclock-host';output.mkdir(parents=True,exist_ok=True)
  binary=output/'systemclock-cases'
  compile_result=subprocess.run(['c++','-std=c++98','-Wall','-Wextra','-Werror',str(ROOT/'systemclock.cpp'),str(ROOT/'tests/systemclock_cases.cpp'),'-o',str(binary)],capture_output=True,text=True)
  self.assertEqual(compile_result.returncode,0,compile_result.stdout+compile_result.stderr)
  symbols=subprocess.run(['nm','-u',str(binary)],capture_output=True,text=True,check=True).stdout
  self.assertNotIn('clock_settime',symbols,'fixture must not import any real clock setter')
  result=subprocess.run([str(binary)],capture_output=True,text=True,check=False)
  (output/'stdout.txt').write_text(result.stdout);(output/'stderr.txt').write_text(result.stderr)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
if __name__=='__main__':unittest.main()
