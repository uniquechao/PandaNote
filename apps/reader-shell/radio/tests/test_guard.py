"""Host shell policy fixtures; never call init or real ifconfig/insmod."""
import subprocess
import tempfile
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
class GuardTests(unittest.TestCase):
    def policy(self,interfaces, mounts=None,ro='1',swaps='Filename Type Size Used Priority\n'):
        source=ROOT/'deploy/radio_guard.sh'
        self.assertTrue(source.exists(),'radio guard implementation missing')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as name:
            p=Path(name);(p/'net').mkdir();(p/'block/mmcblk0').mkdir(parents=True)
            for iface,flags in interfaces.items():
                (p/'net'/iface).mkdir();(p/'net'/iface/'flags').write_text(flags)
            (p/'block/mmcblk0/ro').write_text(ro)
            (p/'mounts').write_text(mounts or '/dev/root / ext4 ro,norecovery 0 0\ntmpfs /tmp tmpfs rw,nosuid,nodev 0 0\n')
            (p/'swaps').write_text(swaps)
            script='. "$1"\nNET_BASE="$2/net";BLOCK_BASE="$2/block";MOUNTS_FILE="$2/mounts";SWAPS_FILE="$2/swaps"\nradio_check_storage && radio_check_network\n'
            return subprocess.run(['/bin/sh','-c',script,'test',str(source),str(p)],capture_output=True).returncode
    def test_only_wlan0_can_be_up(self):
        self.assertEqual(self.policy({'lo':'0x49','wlan0':'0x1003','eth0':'0x1002'}),0)
        self.assertNotEqual(self.policy({'lo':'0x49','wlan0':'0x1003','eth0':'0x1003'}),0)
    def test_missing_loopback_or_bad_flags_fail_closed(self):
        for interfaces in ({'wlan0':'0x1003'},{'lo':'bad'},{'lo':'0x49','wlan0':'unsafe'}):
            self.assertNotEqual(self.policy(interfaces),0)
    def test_writable_disk_recovering_root_and_swap_rejected(self):
        self.assertNotEqual(self.policy({'lo':'0x49'},ro='0'),0)
        for mount in ('/dev/root / ext4 rw,norecovery 0 0\ntmpfs /tmp tmpfs rw 0 0\n','/dev/root / ext4 ro 0 0\ntmpfs /tmp tmpfs rw 0 0\n','/dev/root / ext4 ro,noload 0 0\n/dev/mmcblk0p3 /tmp ext4 rw 0 0\n'):
            self.assertNotEqual(self.policy({'lo':'0x49'},mounts=mount),0)
        self.assertNotEqual(self.policy({'lo':'0x49'},swaps='Filename Type Size Used Priority\n/dev/zram0 partition 12 0 -2\n'),0)
    def test_exact_optional_readonly_opt_mount(self):
        base='/dev/root / ext4 ro,noload 0 0\ntmpfs /tmp tmpfs rw 0 0\n'
        for options in ('ro,noload','ro,norecovery'):
            self.assertEqual(self.policy({'lo':'0x49','wlan0':'0x1003'},mounts=base+'/dev/mmcblk0p5 /run/pandanote-opt ext4 '+options+' 0 0\n'),0)
    def test_opt_mount_bad_source_target_fs_rw_recovery_duplicate_refused(self):
        base='/dev/root / ext4 ro,noload 0 0\ntmpfs /tmp tmpfs rw 0 0\n'
        good='/dev/mmcblk0p5 /run/pandanote-opt ext4 ro,noload 0 0\n'
        for bad in (good.replace('p5','p6'),good.replace('pandanote-opt','other'),good.replace('ext4','ext3'),good.replace('ro,','rw,'),good.replace('ro,','ro,rw,'),good.replace(',noload',''),good+good):
            self.assertNotEqual(self.policy({'lo':'0x49'},mounts=base+bad),0)
if __name__=='__main__':unittest.main()
