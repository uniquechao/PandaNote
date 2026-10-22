import os
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
class DhcpTests(unittest.TestCase):
    def invoke(self,event,**values):
        source=ROOT/'deploy/radio_dhcp.sh'
        self.assertTrue(source.exists(),'volatile DHCP callback missing')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as name:
            root=Path(name);(root/'bin').mkdir();log=root/'calls'
            for tool in ('ifconfig','route'):
                f=root/'bin'/tool;f.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$TRACE"\ncase "$*" in del*) exit 1;; esac\n');f.chmod(0o700)
            env=dict(os.environ,PATH=str(root/'bin')+':/usr/bin:/bin',TRACE=str(log),interface='wlan0',ip='192.0.2.4',subnet='255.255.255.0',router='192.0.2.1',dns='192.0.2.53')
            env.update(values)
            lib=source.read_text().split('# RUN DHCP',1)[0]
            p=subprocess.run(['/bin/sh','-c',lib+'\nRADIO_RUNTIME=$1\nradio_dhcp_event "$2"','test',str(root),event],env=env,capture_output=True)
            return p.returncode,log.read_text() if log.exists() else '',(root/'resolv.conf').read_text() if (root/'resolv.conf').exists() else ''
    def test_bound_configures_owned_interface_and_volatile_resolver_only(self):
        rc,log,resolver=self.invoke('bound')
        self.assertEqual(rc,0);self.assertIn('wlan0 192.0.2.4 netmask 255.255.255.0',log)
        self.assertIn('add default gw 192.0.2.1 dev wlan0',log)
        self.assertEqual(resolver,'nameserver 192.0.2.53\n')
    def test_invalid_or_foreign_lease_has_no_side_effects(self):
        for fields in ({'interface':'eth0'},{'ip':'1.2.3.4;touch BAD'},{'router':'bad'},{'dns':'1.2.3.999'},{'subnet':'255.255.0.256'}):
            rc,log,resolver=self.invoke('bound',**fields)
            self.assertNotEqual(rc,0);self.assertEqual(log,'');self.assertEqual(resolver,'')
    def test_deconfig_clears_only_owned_interface_and_dns(self):
        rc,log,resolver=self.invoke('deconfig')
        self.assertEqual(rc,0);self.assertIn('wlan0 0.0.0.0',log);self.assertEqual(resolver,'')
if __name__=='__main__':unittest.main()
