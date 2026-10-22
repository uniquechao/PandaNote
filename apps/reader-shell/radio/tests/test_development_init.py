"""Development profile entry tests; inert shell fixtures never load a module."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location('development_radio',ROOT/'deploy/build_development_radio.py')

class DevelopmentInitTests(unittest.TestCase):
    def module(self):
        self.assertTrue(Path(SPEC.origin).exists(),'independent development entry missing')
        mod=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(mod);return mod
    def test_exact_current_inputs_generate_separate_entry(self):
        m=self.module();blob=m.render();self.assertIn(b'--wifi-development',blob)
        self.assertIn(b'75618371be37d51ffe56a295188f16322f58eaceba0c6f79def628238ca8a3cd',blob)
        self.assertNotIn(b'touch /tmp/pandanote-sdio-host1-guard',blob)
    def test_modified_common_or_guard_source_is_rejected(self):
        m=self.module()
        for source in ('common','guard'):
            values={'common':m.COMMON.read_bytes(),'guard':m.GUARD.read_bytes()}
            values[source]+=b'\n# drift\n'
            with self.assertRaises(ValueError):m.render(**values)
    def invoke(self,failed=None,busy=False):
        m=self.module();lib=m.render().decode().split('# RUN DEVELOPMENT INIT',1)[0]
        script=lib+'\nid(){ printf 0; };radio_session_tools_ready(){ return 0; }\n'
        for name in ('radio_check_storage','radio_check_network','radio_check_memory'):
            script+=name+'(){ return '+('1' if failed==name else '0')+'; }\n'
        script+='pidof(){ return '+('0' if busy else '1')+'; }\nradio_guard_ready\n'
        return subprocess.run(['/bin/sh','-c',script],capture_output=True,timeout=2)
    def test_new_profile_uses_rw_checks_without_old_marker_files(self):
        p=self.invoke();self.assertEqual(p.returncode,0,p.stderr)
    def test_each_actual_development_guard_required(self):
        for failed in ('radio_check_storage','radio_check_network','radio_check_memory'):
            self.assertNotEqual(self.invoke(failed).returncode,0,failed)
        self.assertNotEqual(self.invoke(busy=True).returncode,0)

if __name__=='__main__':unittest.main()
