import pathlib,subprocess,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class TlsClockTests(unittest.TestCase):
 def test_time_floor_boottime_and_fail_closed(self):
  out=ROOT/'build/tlsclock-host';out.mkdir(parents=True,exist_ok=True);b=out/'cases'
  r=subprocess.run(['c++','-std=c++98','-Wall','-Wextra','-Werror',str(ROOT/'tlsclock.cpp'),str(ROOT/'tests/tlsclock_cases.cpp'),'-o',str(b)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
  r=subprocess.run([str(b)],capture_output=True,text=True);(out/'result.txt').write_text(r.stdout+r.stderr);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
if __name__=='__main__':unittest.main()
