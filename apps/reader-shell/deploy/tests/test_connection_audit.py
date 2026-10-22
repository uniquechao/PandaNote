"""Host fixtures only: actual parser, command generation and protection validator."""
import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import unittest
from unittest.mock import patch

DEPLOY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOY))
try:
    import connection_audit as audit
except ImportError:
    audit = None

RAM = {'idVendor': 0x18d1, 'idProduct': 0xd002,
       'USB Serial Number': 'PANDANOTE966U2_RAM_RO', 'locationID': 0x3100000}
BOOT = {'idVendor': 0xa108, 'idProduct': 0xeaef, 'locationID': 0x3100000}


class Host:
    def __init__(self):
        self.usb = [dict(RAM)]
        self.devices = 'List of devices attached\nPANDANOTE966U2_RAM_RO\tdevice usb:3-1\n\n'
        self.commands = []
        self.diagnostics = dict(status='PANDANOTE966U2_RAM_RO\n',
            mounts='/dev/root / ext4 ro,noload 0 0\ntmpfs /tmp tmpfs rw 0 0\n',
            disk_ro='1\n', swaps='Filename Type Size Used Priority\n',
            network='/sys/class/net/lo/flags 0x9\n/sys/class/net/wlan0/flags 0x1002\n',
            tcp='sl local_address rem_address st\n', tcp6='PANDANOTE_TCP6_ABSENT\n',
            uid='0\n', kernel='fixture\n', modules='', memory='',
            profile='wlan0-only-listeners-loopback-storage-ro-v1\n',
            pid1='1ed1ef64aa71af447679e179efa69e6852902255e1ff056de9ee710b86cd354d  /tmp/pid1\n',
            receipt='profile=msc1-sdio-wlan0-opt-ro-v1\nmanifest=c17a4d133f7953ae54720611a378c1640cdd3cf427db1d4fcd680a9a80ec8a99\npid1=1ed1ef64aa71af447679e179efa69e6852902255e1ff056de9ee710b86cd354d\nbootstrap=d050610bd76deadf4d7ef8b4c6a265cd80fcba73f5538899dd0f1e2c6e36edac\n')
        self.missing_server = False
        self.change_after_shell = False
        self.bad_trailer = False
        self.change_during_enumeration = False

    def run(self, argv, **kwargs):
        self.commands.append((argv, kwargs))
        if argv[0] == '/usr/sbin/ioreg':
            return subprocess.CompletedProcess(argv, 0, plistlib.dumps(self.usb), b'')
        assert argv[:7] == ['/opt/homebrew/bin/adb', '-H', '127.0.0.1', '-P', '5039', '-s', 'PANDANOTE966U2_RAM_RO'], argv
        args = argv[7:]
        if self.missing_server:
            return subprocess.CompletedProcess(argv, 1, '', 'cannot connect to existing server')
        if args == ['devices', '-l']:
            if self.change_during_enumeration:
                self.usb = [dict(BOOT)]
            return subprocess.CompletedProcess(argv, 0, self.devices, '')
        if args == ['get-serialno']:
            return subprocess.CompletedProcess(argv, 0, 'PANDANOTE966U2_RAM_RO\n', '')
        if args == ['get-state']:
            return subprocess.CompletedProcess(argv, 0, 'device\n', '')
        assert args[0] == 'shell', argv
        for key, command in dict(audit.stage.preflight.COMMANDS, **audit.stage.PROFILE_COMMANDS).items():
            if args[1] == audit.stage.wrap_shell(command):
                if self.change_after_shell:
                    self.usb = [dict(BOOT)]
                trailer = '\nPANDANOTE_SHELL_EXIT=0\n' if not self.bad_trailer else ''
                return subprocess.CompletedProcess(argv, 0, self.diagnostics[key] + trailer, '')
        raise AssertionError('non-diagnostic command: ' + repr(args))


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(audit, 'connection audit implementation missing')
        self.host = Host()
        self.patch = patch('subprocess.run', self.host.run)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def check(self, **kwargs):
        return audit.audit_connection(adb_port=5039, **kwargs)

    def shell_calls(self):
        return [args for args, _ in self.host.commands if 'shell' in args]

    def test_exact_ram_reuses_protection_without_network_or_install_claim(self):
        state = self.check()
        self.assertEqual((state.mode, state.status), ('ram', 'readonly_runtime_verified'))
        self.assertTrue(state.runtime_verified)
        self.assertFalse(state.network_verified)
        self.assertFalse(state.persistently_installed)
        self.assertEqual(len(self.shell_calls()), 11)

    def test_no_explicit_port_collects_usb_without_adb(self):
        state = audit.audit_connection()
        self.assertEqual(state.status, 'adb_not_selected')
        self.assertFalse(state.runtime_verified)
        self.assertTrue(all(args[0] == '/usr/sbin/ioreg' for args, _ in self.host.commands))

    def test_unknown_or_duplicate_usb_serial_stops_before_adb(self):
        for devices in ([dict(RAM, **{'USB Serial Number':'OTHER'})], [RAM, RAM], [RAM, BOOT]):
            with self.subTest(devices=devices):
                self.host.usb = devices
                self.host.commands = []
                self.assertEqual(self.check().status, 'stopped')
                self.assertFalse(any('adb' in args[0] for args, _ in self.host.commands))

    def test_bootrom_is_only_ingenic_candidate_and_never_queries_adb(self):
        self.host.usb = [BOOT]
        state = self.check()
        self.assertEqual(state.mode, 'bootrom_candidate')
        self.assertEqual(state.identity, 'unverified')
        self.assertFalse(state.runtime_verified)
        self.assertFalse(any('adb' in args[0] for args, _ in self.host.commands))

    def test_unknown_usb_cannot_claim_normal_system_identity(self):
        self.host.usb = [{'idVendor':123, 'idProduct':456, 'USB Serial Number':'MTP'}]
        state = self.check()
        self.assertEqual(state.mode, 'unverified_usb')
        self.assertEqual(state.identity, 'unverified')
        self.assertEqual(self.shell_calls(), [])

    def test_retained_generic_mtp_ids_do_not_confirm_board_or_installation(self):
        self.host.usb = [{'idVendor':0x1d6b, 'idProduct':0x0100}]
        state = self.check()
        self.assertEqual(state.mode, 'normal_mtp_unverified')
        self.assertEqual(state.identity, 'unverified')
        self.assertFalse(state.persistently_installed)
        self.assertEqual(self.shell_calls(), [])

    def test_absent_usb_is_inaccessible(self):
        self.host.usb = []
        self.assertEqual(self.check().mode, 'inaccessible')
        self.assertEqual(self.shell_calls(), [])

    def test_adb_foreign_duplicate_offline_and_tcp_entries_stop_before_shell(self):
        for rows in ('OTHER\tdevice\n', 'PANDANOTE966U2_RAM_RO\tdevice\nPANDANOTE966U2_RAM_RO\tdevice\n',
                     'PANDANOTE966U2_RAM_RO\toffline\n', '127.0.0.1:5555\tdevice\n',
                     'PANDANOTE966U2_RAM_RO\tdevice\nOTHER\tdevice\n', '', 'garbage\n'):
            with self.subTest(rows=rows):
                self.host.devices = 'List of devices attached\n'+rows
                self.assertEqual(self.check().status, 'stopped')
                self.assertEqual(self.shell_calls(), [])

    def test_missing_server_is_not_started_replaced_or_connected(self):
        self.host.missing_server = True
        state = self.check()
        self.assertEqual(state.status, 'stopped')
        adb = [args for args, _ in self.host.commands if 'adb' in args[0]]
        self.assertEqual([args[7:] for args in adb], [['devices','-l']])

    def test_mode_change_between_diagnostics_stops_next_shell(self):
        self.host.change_after_shell = True
        self.assertEqual(self.check().status, 'stopped')
        self.assertEqual(len(self.shell_calls()), 1)

    def test_mode_change_during_adb_enumeration_stops_before_follow_on(self):
        self.host.change_during_enumeration = True
        self.assertEqual(self.check().status, 'stopped')
        adb = [args[7:] for args, _ in self.host.commands if 'adb' in args[0]]
        self.assertEqual(adb, [['devices','-l']])

    def test_allowlist_rejects_mutation_without_transport_or_host_calls(self):
        transport = audit.ReadOnlyAdb(5039, audit.UsbSnapshot((), 0))
        for args in (['push','anything','/tmp/x'],['connect','anything'],['start-server'],['reboot']):
            with self.subTest(args=args), self.assertRaises(ValueError):
                transport.run(args)
        for command in ('/bin/busybox mount -o remount,rw /', 'radio_init.sh', 'echo x > /tmp/x'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                transport.shell(command)
        self.assertEqual(self.host.commands, [])

    def test_incomplete_shell_trailer_stops_collection(self):
        self.host.bad_trailer = True
        self.assertEqual(self.check().status, 'stopped')
        self.assertEqual(len(self.shell_calls()), 1)

    def test_missing_ro_noload_swap_profile_or_listener_proof_fails_closed(self):
        cases = [('disk_ro',''),('mounts','/dev/root / ext4 ro 0 0\ntmpfs /tmp tmpfs rw 0 0\n'),
                 ('swaps','Filename Type Size Used Priority\n/swap file 1 0 0\n'),
                 ('tcp',''),('tcp','sl local_address rem_address st\n0: 00000000:22A0 00000000:0000 0A\n'),
                 ('tcp6',''), ('uid','1\n'),('status','OTHER\n')]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                original = self.host.diagnostics[key]
                self.host.diagnostics[key] = value
                self.assertEqual(self.check().status, 'stopped')
                self.host.diagnostics[key] = original

    def test_explicit_network_profile_allows_only_exact_opt_and_wlan(self):
        self.host.diagnostics['network'] = '/sys/class/net/lo/flags 0x9\n/sys/class/net/wlan0/flags 0x1003\n'
        self.host.diagnostics['mounts'] += '/dev/mmcblk0p5 /run/pandanote-opt ext4 ro,norecovery 0 0\n'
        kwargs = dict(profile='msc1-sdio-wlan0-opt-ro-v1', opt_libraries=True)
        self.assertEqual(self.check(**kwargs).status, 'readonly_runtime_verified')
        for key in ('receipt', 'profile', 'pid1'):
            old = self.host.diagnostics[key]
            self.host.diagnostics[key] = 'forged\n'
            self.assertEqual(self.check(**kwargs).status, 'stopped')
            self.host.diagnostics[key] = old
        receipt = self.host.diagnostics['receipt']
        self.host.diagnostics['receipt'] = receipt.replace(
            'manifest=c17a4d133f7953ae54720611a378c1640cdd3cf427db1d4fcd680a9a80ec8a99',
            'manifest=25e55d00d31dff42b2723218f8342a95d0171015dc612f9fade4c4a91b4584db')
        self.assertEqual(self.check(**kwargs).status, 'stopped')
        self.host.diagnostics['receipt'] = receipt
        self.host.diagnostics['network'] += '/sys/class/net/usb0/flags 0x1\n'
        self.assertEqual(self.check(**kwargs).status, 'stopped')

    def test_all_invocations_are_bounded_and_use_existing_local_server(self):
        self.check()
        for args, kwargs in self.host.commands:
            self.assertLessEqual(kwargs['timeout'], 20)
            if 'adb' in args[0]:
                self.assertEqual(kwargs['env']['ADB_MDNS_AUTO_CONNECT'], '')
                self.assertEqual(kwargs['env']['ADB_LOCAL_TRANSPORT_MAX_PORT'], '0')

    def test_malformed_or_stale_usb_snapshot_cannot_authorize_queries(self):
        with patch.object(audit, 'collect_usb', return_value=audit.UsbSnapshot((audit.UsbDevice(0x18d1,0xd002,'PANDANOTE966U2_RAM_RO',1),), -100)):
            self.assertEqual(self.check().status, 'stopped')
        self.assertEqual(self.shell_calls(), [])
        for raw in (b'garbage', plistlib.dumps({'status':'X2000','time':'now'}), plistlib.dumps([{'idVendor':'0xa108','idProduct':0xeaef}])):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                audit.parse_ioreg(raw)

    def test_invalid_profile_or_port_stops_without_host_observation(self):
        for kwargs in (dict(adb_port=5555),dict(profile='unknown'),dict(opt_libraries=True)):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(audit.audit_connection(**kwargs).status,'stopped')
        self.assertEqual(self.host.commands, [])

    def test_import_does_not_load_boot_transport_or_libusb(self):
        self.assertFalse(any(name in sys.modules for name in ('bootrom_ram_transport','usb.core','ram_boot')))


if __name__ == '__main__':
    unittest.main()
