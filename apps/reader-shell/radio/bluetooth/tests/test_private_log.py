from pathlib import Path
import subprocess,unittest
ROOT=Path(__file__).resolve().parents[1]
class PrivateLogTests(unittest.TestCase):
    def test_diagnostics_stay_on_owned_stderr_with_hard_byte_budget(self):
        out=ROOT/'build/c1';out.mkdir(parents=True,exist_ok=True);binary=out/'log-fixture'
        subprocess.run(['cc','-std=c99','-Wall','-Wextra','-Werror',str(ROOT/'c1/private_log.c'),str(ROOT/'tests/private_log_cases.c'),'-o',str(binary)],check=True,timeout=10)
        with (out/'log-fixture.stderr').open('wb') as f:subprocess.run([str(binary)],stderr=f,check=True,timeout=2)
        data=(out/'log-fixture.stderr').read_bytes()
        self.assertIn(b'synthetic failure 7',data)
        self.assertIn(b'direct diagnostic 8',data)
        self.assertLessEqual(len(data),8192)
        self.assertTrue(data.endswith(b'\n'))
if __name__=='__main__':unittest.main()
