"""Real host PTY hangup tests; radio/socket work is replaced by inert fixtures.

The shell lifecycle and signals are real. No vendor binary, USB, DHCP packets or
host network settings are used. Removing DHCP session isolation must fail the
hangup test; removing cleanup must fail the interrupted-start test.
"""
import json
import os
from pathlib import Path
import pty
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
LIB = (ROOT / 'deploy/radio_init.sh').read_text().split('# RUN INIT', 1)[0]


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.03)
    raise AssertionError('bounded lifecycle observation timed out')


class ChildLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.directory.name).resolve()
        self.runtime = self.root / 'runtime'
        (self.runtime / 'wpa').mkdir(parents=True)
        (self.runtime / 'wpa.conf').write_text('ctrl_interface='+str(self.runtime / 'wpa')+'\n')
        self.parents = []
        self.children = []
        # Trusted Python stand-ins perform only process/socket/heartbeat work.
        # setsid is the real OS operation, not an assertion-producing mock.
        busybox = self.root / 'busybox'
        busybox.write_text('#!'+sys.executable+'\nimport os,sys\n'
                           'if sys.argv[1:] == ["--list"]:\n print("setsid");sys.exit(0)\n'
                           'assert sys.argv[1] == "setsid"\n'
                           'os.setsid();os.execv(sys.argv[2],sys.argv[2:])\n')
        busybox.chmod(0o700)
        for kind in ('wpa', 'dhcp'):
            program = self.root / kind
            program.write_text('#!'+sys.executable+'\n'+'''
import json,os,signal,socket,sys,time
from pathlib import Path
root=Path(__file__).parent
kind=Path(__file__).name
runtime=root/'runtime'
if kind=='wpa':
    assert sys.argv[1:]==['-i','wlan0','-D','wext','-c',str(runtime/'wpa.conf')]
    signal.signal(signal.SIGHUP,signal.SIG_IGN)
    sock=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
    os.chdir(runtime/'wpa')
    sock.bind('wlan0')
else:
    assert sys.argv[1:]==['-f','-i','wlan0','-s',str(runtime/'dhcp.sh'),'-p',str(runtime/'dhcp.pid'),'-t','3','-T','3','-A','5']
    if (root/'fail-dhcp').exists():sys.exit(19)
    signal.signal(signal.SIGHUP,signal.SIG_DFL)
(root/(kind+'.json')).write_text(json.dumps({'pid':os.getpid(),'sid':os.getsid(0),'pgid':os.getpgrp(),'tty':os.isatty(0)}))
while True:
    (root/(kind+'.beat.tmp')).write_text(str(time.monotonic_ns()))
    (root/(kind+'.beat.tmp')).replace(root/(kind+'.beat'))
    time.sleep(.04)
''')
            program.chmod(0o700)
        self.lib = LIB.replace('/usr/sbin/wpa_supplicant', str(self.root / 'wpa')).replace(
            '/sbin/udhcpc', str(self.root / 'dhcp')).replace('/bin/busybox', str(busybox))

    def tearDown(self):
        # Only exact fixture children recorded in this private test directory.
        for kind in ('wpa', 'dhcp'):
            receipt = self.root / (kind+'.json')
            if receipt.exists():
                self.children.append(json.loads(receipt.read_text())['pid'])
        for pid in set(self.children + self.parents):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for pid in self.parents:
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        self.directory.cleanup()

    def launch(self, tail):
        script = self.root / 'parent.sh'
        script.write_text(self.lib+'\nRADIO_RUNTIME='+str(self.runtime)+'\n'+tail)
        pid, master = pty.fork()
        if pid == 0:
            os.execl('/bin/sh', 'sh', str(script))
        self.parents.append(pid)
        return pid, master

    def test_dhcp_survives_parent_pty_hangup_without_inheriting_terminal(self):
        parent, master = self.launch('radio_start_children || exit 21\n'
                                     'touch '+str(self.root/'ready')+'\n'
                                     'while :; do sleep 1; done\n')
        try:
            wait_for(lambda: (self.root/'ready').exists())
            before = (self.root/'dhcp.beat').read_text()
        finally:
            os.close(master)
        time.sleep(.25)
        after = (self.root/'dhcp.beat').read_text()
        self.assertNotEqual(after, before, 'DHCP died when the controller PTY closed')
        dhcp = json.loads((self.root/'dhcp.json').read_text())
        self.assertNotEqual(dhcp['sid'], parent, 'DHCP still belongs to the controller session')
        self.assertFalse(dhcp['tty'], 'DHCP still reads from the controller terminal')
        for kind, pidfile in (('wpa', 'wpa.pid'), ('dhcp', 'udhcpc.pid')):
            child = json.loads((self.root/(kind+'.json')).read_text())
            self.assertEqual(int((self.runtime/pidfile).read_text()), child['pid'],
                             'recorded child PID no longer identifies the exec process')

    def test_failed_dhcp_start_cleans_only_its_created_supplicant(self):
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(20)'])
        self.children.append(unrelated.pid)
        (self.root/'fail-dhcp').touch()
        _, master = self.launch('radio_start_children\n'
                                'printf "%s" "$?" > '+str(self.root/'result')+'\n')
        try:
            wait_for(lambda: (self.root/'result').exists())
            self.assertNotEqual((self.root/'result').read_text(), '0')
            before = (self.root/'wpa.beat').read_text()
            time.sleep(.2)
            self.assertEqual((self.root/'wpa.beat').read_text(), before)
            self.assertIsNone(unrelated.poll(), 'startup cleanup touched an unowned process')
        finally:
            os.close(master)
            unrelated.terminate()
            unrelated.wait(timeout=3)

    def test_missing_session_applet_starts_neither_child(self):
        busybox = self.root/'busybox'
        busybox.write_text('#!'+sys.executable+'\nimport sys\n'
                           'assert sys.argv[1:]==["--list"]\nprint("sh")\n')
        busybox.chmod(0o700)
        result = subprocess.run(['/bin/sh', '-c', self.lib+'\nRADIO_RUNTIME=$1\nradio_start_children',
                                 'fixture', str(self.runtime)], capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/'wpa.json').exists())
        self.assertFalse((self.root/'dhcp.json').exists())

    def test_existing_runtime_refuses_second_initialization_without_replacing_children(self):
        _, master = self.launch('radio_start_children || exit 21\n'
                                'touch '+str(self.root/'ready')+'\n'
                                'while :; do sleep 1; done\n')
        try:
            wait_for(lambda: (self.root/'ready').exists())
            before = {kind: json.loads((self.root/(kind+'.json')).read_text())['pid']
                      for kind in ('wpa', 'dhcp')}
            result = subprocess.run(['/bin/sh', '-c', self.lib+'''
RADIO_RUNTIME=$1
radio_board_supported() { return 0; }
radio_verify_inputs() { return 0; }
radio_guard_ready() { return 0; }
radio_load_clock() { touch "$RADIO_RUNTIME/UNEXPECTED_MODULE_LOAD"; }
radio_initialize_wifi
''', 'fixture', str(self.runtime)], capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.runtime/'UNEXPECTED_MODULE_LOAD').exists())
            after = {kind: json.loads((self.root/(kind+'.json')).read_text())['pid']
                     for kind in ('wpa', 'dhcp')}
            self.assertEqual(after, before)
        finally:
            os.close(master)

    def test_missing_session_applet_refuses_initialization_before_module_side_effects(self):
        busybox = self.root/'busybox'
        busybox.write_text('#!'+sys.executable+'\nprint("sh")\n')
        busybox.chmod(0o700)
        network = self.root/'network-marker'
        sdio = self.root/'sdio-marker'
        network.write_text('wlan0-only-listeners-loopback-storage-ro-v1\n')
        sdio.write_text('msc1-only-sdio-cmd52-cmd53-emmc-filter-unchanged-v1\n')
        lib = self.lib.replace('/tmp/pandanote-network-profile-wlan0-v1', str(network)).replace(
            '/tmp/pandanote-sdio-host1-guard-v1', str(sdio))
        result = subprocess.run(['/bin/sh', '-c', lib+'''
RADIO_RUNTIME=$1/new-runtime
id() { printf 0; }
pidof() { return 1; }
radio_board_supported() { return 0; }
radio_verify_inputs() { return 0; }
radio_check_storage() { return 0; }
radio_check_network() { return 0; }
radio_check_memory() { return 0; }
radio_load_clock() { touch "$1"; return 1; }
'''.replace('touch "$1"', 'touch "'+str(self.root/'UNEXPECTED_MODULE_LOAD')+'"')+'''
radio_initialize_wifi
''', 'fixture', str(self.root)], capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/'UNEXPECTED_MODULE_LOAD').exists())
        self.assertFalse((self.root/'new-runtime').exists())


if __name__ == '__main__':
    unittest.main()
