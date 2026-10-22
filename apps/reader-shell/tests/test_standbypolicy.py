"""Host execution of the actual bounded standby maintenance policy."""
import pathlib,subprocess,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class StandbyPolicyTests(unittest.TestCase):
 def test_timer_maintenance_waits_for_pipeline_and_has_hard_deadline(self):
  out=ROOT/'build/standby-policy-host';out.mkdir(parents=True,exist_ok=True);binary=out/'standby-policy'
  result=subprocess.run(['c++','-std=c++98','-Wall','-Wextra','-Werror',str(ROOT/'tests/standbypolicy_fixture.cpp'),'-o',str(binary)],capture_output=True,text=True)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
  result=subprocess.run([str(binary)],capture_output=True,text=True);(out/'stdout.txt').write_text(result.stdout);(out/'stderr.txt').write_text(result.stderr);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
if __name__=='__main__':unittest.main()
