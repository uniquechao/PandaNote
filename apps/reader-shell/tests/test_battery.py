"""Native battery policy tests: no hardware file, ioctl, clock or GPIO access."""
import pathlib,subprocess,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class BatteryTests(unittest.TestCase):
 def test_policy_uses_only_the_syscall_fixture(self):
  output=ROOT/'build/battery-host';output.mkdir(parents=True,exist_ok=True);binary=output/'battery-cases'
  result=subprocess.run(['c++','-std=c++98','-Wall','-Wextra','-Werror',str(ROOT/'battery.cpp'),str(ROOT/'tests/battery_fixture.cpp'),'-o',str(binary)],capture_output=True,text=True)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
  symbols=subprocess.run(['nm','-u',str(binary)],capture_output=True,text=True,check=True).stdout
  for forbidden in ('_ioctl','_read','_open','_fork','_kill','_reboot','_system','_execve'):
   self.assertNotIn(forbidden,symbols)
  result=subprocess.run([str(binary)],capture_output=True,text=True)
  (output/'stdout.txt').write_text(result.stdout);(output/'stderr.txt').write_text(result.stderr)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
 def test_real_parent_deadline_with_fake_worker(self):
  output=ROOT/'build/battery-host';output.mkdir(parents=True,exist_ok=True);binary=output/'battery-posix-cases'
  result=subprocess.run(['c++','-std=c++98','-Wall','-Wextra','-Werror','-DPANDANOTE_BATTERY_POSIX_FIXTURE',str(ROOT/'battery_posix.cpp'),str(ROOT/'tests/battery_posix_fixture.cpp'),'-o',str(binary)],capture_output=True,text=True)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
  result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=3)
  (output/'posix-stdout.txt').write_text(result.stdout);(output/'posix-stderr.txt').write_text(result.stderr)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
if __name__=='__main__':unittest.main()
