"""Run the actual runtime wake/maintenance methods with syscall/UI boundaries replaced."""
import pathlib,subprocess,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class StandbyRuntimeTests(unittest.TestCase):
 def test_timer_wake_key_priority_and_maintenance_pipeline(self):
  out=ROOT/'build/standby-runtime-host';out.mkdir(parents=True,exist_ok=True)
  source=(ROOT/'main.cpp').read_text();self.assertTrue('    void observeSuspendedPower()' in source,'runtime has no safe timer/human wake dispatch yet')
  methods=source[source.index('    void observeSuspendedPower()'):source.index('    void timerEvent(')]
  text=(ROOT/'tests/standby_runtime_fixture.cpp').read_text().replace('/* ACTUAL METHODS */',methods)
  target=out/'runtime.cpp';target.write_text(text);binary=out/'runtime'
  result=subprocess.run(['c++','-std=c++98','-Wall','-Wextra','-Werror','-I'+str(ROOT),str(target),'-o',str(binary)],capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
  result=subprocess.run([str(binary)],capture_output=True,text=True);(out/'stdout.txt').write_text(result.stdout);(out/'stderr.txt').write_text(result.stderr);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
if __name__=='__main__':unittest.main()
