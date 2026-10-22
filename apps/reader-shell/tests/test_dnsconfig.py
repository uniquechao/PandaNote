import pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class DnsConfigTests(unittest.TestCase):
 def test_private_dhcp_file_and_resolver_state(self):
  with tempfile.TemporaryDirectory(dir=(ROOT/'build').resolve(),prefix='dnsconfig-') as tmp:
   base=pathlib.Path(tmp);private=base/'private';private.mkdir(mode=0o700);binary=base/'fixture'
   built=subprocess.run(['c++','-std=c++98','-Wall','-Wextra','-Werror','-DPANDANOTE_DNSCONFIG_TEST',str(ROOT/'dnsconfig.cpp'),str(ROOT/'tests/dnsconfig_cases.cpp'),'-o',str(binary)],capture_output=True,text=True)
   self.assertEqual(built.returncode,0,built.stdout+built.stderr)
   result=subprocess.run([str(binary),str(private.resolve())],capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stdout+result.stderr);print(result.stdout.strip())
if __name__=='__main__':unittest.main()
