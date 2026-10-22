"""Execute actual TimeAnchor methods with only the clock syscall replaced."""
import pathlib,subprocess,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class TimeAnchorTests(unittest.TestCase):
 def test_authenticated_epoch_includes_suspended_time_and_rejects_bad_clock(self):
  out=ROOT/'build/timeanchor-host';out.mkdir(parents=True,exist_ok=True)
  header=(ROOT/'content.h').read_text();begin=header.index('class TimeAnchor {');end=header.index('\n};',begin)+3
  source=(ROOT/'content.cpp').read_text();methods=source[source.index('bool TimeAnchor::establish('):]
  fixture=(ROOT/'tests/timeanchor_fixture.cpp').read_text();target=out/'timeanchor.cpp';target.write_text(fixture.replace('/* ACTUAL CLASS */',header[begin:end]).replace('/* ACTUAL METHODS */',methods))
  binary=out/'timeanchor';built=subprocess.run(['c++','-std=c++98','-Wall','-Wextra','-Werror',str(target),'-o',str(binary)],capture_output=True,text=True)
  self.assertEqual(built.returncode,0,built.stdout+built.stderr)
  run=subprocess.run([str(binary)],capture_output=True,text=True);(out/'stdout.txt').write_text(run.stdout);(out/'stderr.txt').write_text(run.stderr)
  self.assertEqual(run.returncode,0,run.stdout+run.stderr)
if __name__=='__main__':unittest.main()
