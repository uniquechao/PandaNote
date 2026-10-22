"""Page keys share evdev reads while keeping F11 actions and activity isolated."""
import pathlib,subprocess,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class ListKeysTests(unittest.TestCase):
 def test_page_edges_held_baseline_queue_and_power_isolation(self):
  out=ROOT/'build/listkeys-host';out.mkdir(parents=True,exist_ok=True);binary=out/'listkeys'
  r=subprocess.run(['c++','-std=c++98','-Wall','-Wextra','-Werror',str(ROOT/'powerkeys.cpp'),str(ROOT/'tests/listkeys_fixture.cpp'),'-o',str(binary)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
  symbols=subprocess.run(['nm','-u',str(binary)],capture_output=True,text=True,check=True).stdout
  for forbidden in ('_ioctl','_clock_gettime','_reboot','_system','_execve'):self.assertNotIn(forbidden,symbols)
  r=subprocess.run([str(binary)],capture_output=True,text=True);(out/'stdout.txt').write_text(r.stdout);(out/'stderr.txt').write_text(r.stderr);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
