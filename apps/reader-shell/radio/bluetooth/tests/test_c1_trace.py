import importlib.util,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('audit',ROOT/'c1/audit_trace.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class TraceAuditTests(unittest.TestCase):
    def test_rejects_global_write_and_state_rename(self):
        text='15 openat(AT_FDCWD,"/var/lib/bluetooth/info",O_WRONLY|O_CREAT) = 4\n15 rename("/tmp/pandanote-connectivity/bluetooth/a","/var/lib/bluetooth/info") = 0\n'
        self.assertEqual(len(mod.violations(text)),2)
    def test_rejects_ambiguous_relative_write(self):
        self.assertTrue(mod.violations('15 open("relative",O_RDWR) = 4\n'))
    def test_rejects_traversal_and_ambiguous_paths_without_normalizing(self):
        root='/tmp/pandanote-connectivity/bluetooth'
        for path in [root+'/../outside',root+'/run/../../outside',root+'/./run/bus',
                     root+'//run/bus',root+'/',root+'-other/run/bus',
                     root+'/run/\\056\\056/outside',root+'/run/\\x2e\\x2e/outside',
                     root+'/run/%2e%2e/outside','//tmp/pandanote-connectivity/bluetooth/run/bus',
                     '/dev/null/../outside']:
            with self.subTest(path=path):
                self.assertTrue(mod.violations('15 mkdir("'+path+'",0700) = 0\n'))
    def test_accepts_readonly_system_data_and_private_mutations(self):
        text='15 openat(AT_FDCWD,"/etc/passwd",O_RDONLY|O_CLOEXEC) = 4\n15 open("/dev/null",O_RDWR) = 3\n15 chmod("/tmp/pandanote-connectivity/bluetooth/run/bus",0777) = 0\n15 unlink("/tmp/pandanote-connectivity/bluetooth/run/bus") = 0\n'
        self.assertEqual(mod.violations(text),[])
if __name__=='__main__':unittest.main()
