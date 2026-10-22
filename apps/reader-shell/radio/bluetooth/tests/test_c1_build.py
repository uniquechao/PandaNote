"""Fail-closed target header/profile generation; no target binaries execute."""
import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('c1_build',ROOT/'c1/build_daemon.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class ConfigTests(unittest.TestCase):
    def test_unknown_template_variable_is_rejected(self):
        with self.assertRaises(ValueError):mod.render('@unreviewed@',{})
    def test_target_header_generation_rejects_64bit_abi(self):
        with self.assertRaises(ValueError):mod.validate_abi({'pointer':8,'long':8,'int':4,'short':2,'long_long':8,'endian':'little'})
    def test_daemon_config_cannot_redirect_state_outside_private_tmpfs(self):
        with self.assertRaises(ValueError):mod.config('/var/lib/bluetooth')
    def test_selected_sources_reject_unresolved_build_variables(self):
        with self.assertRaises(ValueError):mod.expand('$(unknown)',{})
if __name__=='__main__':unittest.main()
