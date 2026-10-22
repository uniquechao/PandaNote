"""Real owned C fixtures; no radio, vendor ELF, private data, or services."""
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/host-tests'
class BluetoothTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):OUT.mkdir(parents=True,exist_ok=True)
    def fixture(self,name,sources):
        binary=OUT/name
        subprocess.run(['cc','-std=c99','-Wall','-Wextra','-Werror',*[str(ROOT/p) for p in sources],'-o',str(binary)],check=True,capture_output=True,timeout=10)
        result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return result.stdout
    def test_capability_wire_validation(self):
        self.fixture('probe-cases',['capability.c','tests/probe_cases.c'])
    def test_nonblocking_deadline_and_real_datagram_exchange(self):
        self.fixture('io-cases',['probe_io.c','tests/io_cases.c'])
    def test_authorization_replay_and_bounded_file_transfer(self):
        self.fixture('policy-cases',['policy.c','../../third_party/sha256/sha256.c','tests/policy_cases.c'])
if __name__=='__main__':unittest.main()
