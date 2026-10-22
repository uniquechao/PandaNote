"""Regression for factory BusyBox without stat. No vendor code executed here."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
HISTORY=(Path(__import__('os').environ.get('PANDANOTE_REFERENCE_ROOT', 'external-inputs')) / 'pandanote-analysis/app-development-research/ram-linux-research')


class BusyboxCompatibilityTests(unittest.TestCase):
    def test_new_runtime_applets_exist_in_actual_historical_list(self):
        path=HISTORY/'busybox-list-stdout.txt'
        if not path.exists():self.skipTest('historical restricted-lab log absent')
        names=set(re.findall(r'write\(2,0x[0-9a-f]+,\d+\)([^\s]+) = \d+',path.read_text()))
        self.assertIn('netstat',names)
        self.assertNotIn('stat',names)
        required={'ls','setsid','sh','cat','chmod','dd','echo','env','grep','ifconfig','kill','ln',
            'mkdir','mount','mv','printf','readlink','rm','sha256sum','sleep','sync','tr','umount','wc','base64','zcat'}
        self.assertFalse(required-names,required-names)
        for name in ('pid1.in','policy.sh','radio_guard.in'):
            self.assertNotRegex((ROOT/name).read_text(),r'(?:\bbb|/bin/busybox)[ \t]+stat(?:[ \t]|$)')


if __name__=='__main__':unittest.main(verbosity=2)
