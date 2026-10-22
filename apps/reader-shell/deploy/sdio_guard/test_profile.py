"""Fixture execution of owned policy only; hardware entry is never run."""
import os,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SOURCE=Path(os.environ.get('SDIO_PID1',str(ROOT/'pid1-ram.sh')))
class ProfileTests(unittest.TestCase):
    def policy(self,command,mounts=None,nets=None):
        source=SOURCE.read_text().split('# END POLICY LIBRARY\n')[0]
        guest=os.environ.get('PANDANOTE_POLICY_GUEST_SHELL')=='1'
        if guest and os.environ.get('PANDANOTE_OFFLINE_GUARD_TEST')!='1': raise RuntimeError('gate')
        with tempfile.TemporaryDirectory(dir='/tmp' if guest else ROOT/'build') as d:
            p=Path(d); (p/'mounts').write_text(mounts or '/dev/root / ext4 ro,noload 0 0\n')
            for net,flags in (nets or {'lo':'0x49','wlan0':'0x1003'}).items():
                (p/net).mkdir(); (p/net/'flags').write_text(flags)
            script=source+'\nMOUNTS_FILE=$1/mounts; NET_BASE=$1; bb() { "$@"; }; '+command
            shell=['/usr/bin/qemu-mipsel','-cpu','P5600','-L','/sample-qt/sysroot','/sample-root/busybox','sh'] if guest else ['/bin/sh']
            return subprocess.run(shell+['-c',script,'fixture',d],capture_output=True,timeout=3).returncode
    def test_wlan0_up_and_loopback_allowed(self):
        self.assertEqual(self.policy('check_network_down'),0)
    def test_other_up_interface_and_bad_flags_refused(self):
        for nets in ({'lo':'0x49','eth0':'0x1'},{'lo':'0x49','wlan0':'no'},{'wlan0':'0x1'},{'lo':'0x49','eth0':'0x100000000'}):
            self.assertNotEqual(self.policy('check_network_down',nets=nets),0)
    def test_exact_optional_opt_mount(self):
        base='/dev/root / ext4 ro,noload 0 0\n'
        for options in ('ro,noload','ro,norecovery'):
            self.assertEqual(self.policy('check_mounts',base+'/dev/mmcblk0p5 /run/pandanote-opt ext4 '+options+' 0 0\n'),0)
    def test_opt_mount_bad_source_target_fs_rw_recovery_and_duplicate(self):
        base='/dev/root / ext4 ro,noload 0 0\n'
        good='/dev/mmcblk0p5 /run/pandanote-opt ext4 ro,noload 0 0\n'
        for line in (good.replace('p5','p6'),good.replace('pandanote-opt','other'),good.replace('ext4','ext3'),good.replace('ro,','rw,'),good.replace('ro,','ro,rw,'),good.replace(',noload',''),good+good):
            self.assertNotEqual(self.policy('check_mounts',base+line),0)
if __name__=='__main__': unittest.main(verbosity=2)
