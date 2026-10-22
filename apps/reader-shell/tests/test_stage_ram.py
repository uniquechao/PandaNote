"""Host-only safety tests. Fake transport is required to prohibit hardware writes."""
import hashlib
import importlib.util
import json
import re
import shlex
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import stage_ram as stage
except ImportError:
    stage = None


class StageTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(stage, 'RAM stager implementation is missing')
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'build')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.build = self.base / 'release'
        manifest_bytes = stage.safe_file(ROOT/'build', 'manifest.json').read_bytes()
        self.build.mkdir()
        (self.build/'manifest.json').write_bytes(manifest_bytes)
        for item in json.loads(manifest_bytes)['artifacts']:
            name = item['path']
            original = stage.safe_file(ROOT/'build', name)
            copied = self.build/name
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, copied)
        # Bind this test's original input, not the deployment allowlist. Keep
        # the real verifier so later manifest/artifact mutations still fail.
        pin = patch.object(stage, 'REVIEWED_MANIFEST_SHA', hashlib.sha256(manifest_bytes).hexdigest())
        self.addCleanup(pin.stop)
        pin.start()
        self.adb = FakeAdb()

    def execute(self, run=False):
        return stage.execute(self.adb, self.build, ROOT, self.base / 'evidence', run=run)

    def test_adb_wrapper_preserves_generated_shell_syntax(self):
        transport = stage.ExistingAdb()
        def syntax_only(args, timeout=10):
            parsed = subprocess.run(['sh','-n'],input=args[1],text=True,capture_output=True)
            self.assertEqual(parsed.returncode,0,parsed.stderr)
            return subprocess.CompletedProcess(args,0,'ok\nPANDANOTE_SHELL_EXIT=0\n','')
        transport.run = syntax_only
        self.assertEqual(transport.shell(stage.launch_command('/tmp/reader-shell-run-EXAMPLE',2000)), 'ok')

    def test_clean_launch_disables_shared_fonts_without_changing_ui_or_input(self):
        state = '/tmp/reader-shell-run-20261020T182130496166'
        command = stage.launch_command(state, 300000)
        app = command.split('exec ', 1)[1].split(' ) >', 1)[0]
        words = shlex.split(app)
        target = words.index(stage.TARGET+'/reader-shell.mipsel')
        self.assertEqual(words[:3], ['/bin/busybox', 'env', '-i'])
        actual = dict(word.split('=', 1) for word in words[3:target])
        expected = {'PATH':'/bin:/usr/bin', 'HOME':state+'/home', 'TMPDIR':state,
            'XDG_CACHE_HOME':state+'/cache', 'XDG_CONFIG_HOME':state+'/config',
            'LD_LIBRARY_PATH':stage.TARGET+'/lib:/lib:/usr/lib', 'QTDIR':stage.TARGET+'/',
            'QT_QWS_FONTDIR':stage.TARGET+'/assets', 'QT_PLUGIN_PATH':state+'/empty-plugins',
            'POINTERCAL_FILE':state+'/pointercal',
            'QWS_DISPLAY':'Transformed:Rot270:LinuxFb:mmWidth200:mmHeight120:0',
            'QWS_KEYBOARD':'none', 'QWS_MOUSE_PROTO':'evdevtouch:/dev/input/event0',
            'QWS_NO_SHARE_FONTS':'1'}
        self.assertEqual(actual, expected)
        self.assertEqual(words[target+1:], ['--qws-server', '--developer-mode',
            '--developer-timeout-ms', '300000'])
        self.assertLessEqual(len(stage.wrap_shell(command).encode('utf-8')), 3808)

    def test_monitor_retains_cma_metrics_without_changing_resource_thresholds(self):
        command = stage.launch_command('/tmp/reader-shell-run-EXAMPLE', 2000)
        line = next(line.strip() for line in command.splitlines() if 'grep -E' in line and '/proc/meminfo' in line)
        fixture = self.base/'meminfo'
        fixture.write_text('MemAvailable: 15832 kB\nMemFree: 15672 kB\nShmem: 27112 kB\nCmaTotal: 16384 kB\nCmaFree: 14876 kB\nOther: 1 kB\n')
        parsed = subprocess.run(['sh', '-c', line.replace('/bin/busybox ', '').replace('/proc/meminfo', shlex.quote(str(fixture)))], text=True, capture_output=True)
        self.assertEqual(parsed.returncode, 0, parsed.stderr)
        self.assertEqual(parsed.stdout, fixture.read_text().split('Other:')[0])
        for guard in ('"$free_kb" -lt 1024', '"$ram_kb" -lt 4096', '"$state_kb" -gt 3072'):
            self.assertIn(guard, command)

    def test_check_only_has_no_remote_mutation(self):
        report = self.execute()
        self.assertEqual(report['status'], 'check_only_passed')
        self.assertFalse(report['copied_to_device'])
        self.assertFalse(report['app_executed'])
        self.assertEqual(self.adb.mutations, [])

    def test_wrong_serial_stops_before_upload_or_execution(self):
        self.adb.serial = 'OTHER'
        with self.assertRaisesRegex(ValueError, 'serial'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_missing_protection_stops_before_upload_or_execution(self):
        self.adb.protection['disk_ro'] = ''
        with self.assertRaisesRegex(ValueError, 'protection'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_artifact_hash_failure_stops_before_device_access(self):
        (self.build / 'reader-shell.mipsel').write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError, 'artifact'):
            self.execute(True)
        self.assertEqual(self.adb.calls, [])

    def test_changed_manifest_unknown_path_stops_before_device_access(self):
        data = json.loads((self.build / 'manifest.json').read_text())
        data['artifacts'].append({'path': '../bad', 'sha256': '0'*64, 'bytes': 1})
        (self.build / 'manifest.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'reviewed manifest'):
            self.execute(True)
        self.assertEqual(self.adb.calls, [])

    def test_symlink_artifact_stops_before_device_access(self):
        font = self.build / 'assets/wqy-microhei.ttc'
        font.unlink()
        font.symlink_to(ROOT / 'assets/wqy-microhei.ttc')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.execute(True)
        self.assertEqual(self.adb.calls, [])

    def test_unknown_remote_directory_is_rejected_even_with_valid_files(self):
        _, files, _ = stage.verify_release(self.build, ROOT)
        self.adb.extra['stage_tree'] = ''.join(stage.sha(file)+'  '+stage.TARGET+'/'+name+'\n' for name,file in files.items())+'DIR /tmp/reader-shell/unexpected\n'
        with self.assertRaisesRegex(ValueError, 'stage'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_verified_existing_payload_is_reused_without_retransfer(self):
        _, files, _ = stage.verify_release(self.build, ROOT)
        directories = {stage.TARGET}
        for name in files:
            part = Path(stage.TARGET+'/'+name).parent
            while str(part).startswith(stage.TARGET):
                directories.add(str(part))
                if str(part)==stage.TARGET:
                    break
                part = part.parent
        self.adb.extra['stage_tree'] = ''.join(stage.sha(file)+'  '+stage.TARGET+'/'+name+'\n' for name,file in files.items())+''.join('DIR '+name+'\n' for name in sorted(directories))
        report = self.execute(True)
        self.assertTrue(report['reused_verified_payload'])
        self.assertFalse(any(isinstance(call,list) and call[0]=='push' for call in self.adb.mutations))

    def test_qws_mapping_stops_before_mutation(self):
        self.adb.extra['exclusive'] = 'QT_PROCESS=45\n'
        with self.assertRaisesRegex(ValueError, 'QWS'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_tmp_capacity_is_required_before_mutation(self):
        self.adb.extra['capacity'] = '1024\n'
        with self.assertRaisesRegex(ValueError, 'capacity'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_unknown_remote_stage_tree_stops_before_mutation(self):
        self.adb.extra['stage_tree'] = 'UNTRUSTED\n'
        with self.assertRaisesRegex(ValueError, 'stage'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_wrong_root_dependency_stops_before_mutation(self):
        self.adb.extra['libraries'] = 'libc.so.6 ' + '0'*64 + '\n'
        with self.assertRaisesRegex(ValueError, 'library'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_live_28mib_tmpfs_fits_four_missing_stock_libraries(self):
        self.adb.extra['capacity'] = '28946432\n'
        for name in stage.STOCK_STAGED:
            item = next(x for x in json.loads((ROOT/'build/manifest.json').read_text())['stock_libraries'] if x['name']==name)
            self.adb.extra['libraries'] = self.adb.extra['libraries'].replace(name+' '+item['sha256'], name+' MISSING')
        report = self.execute()
        self.assertLessEqual(report['capacity']['required_bytes'], 28946432)
        self.assertEqual(self.adb.mutations, [])

    def test_artifact_changed_during_preflight_stops_before_first_mutation(self):
        self.adb.before_transfer = lambda: (self.build/'reader-shell.mipsel').write_bytes(b'changed during preflight')
        with self.assertRaisesRegex(ValueError, 'changed before transfer'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_elf_changed_during_first_diagnostic_stops_before_any_mutation(self):
        self.adb.first_diagnostic = lambda: (self.build/'reader-shell.mipsel').write_bytes(b'changed in initial diagnostic')
        with self.assertRaisesRegex(ValueError, 'changed before transfer'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_elf_changed_during_extra_scan_stops_before_any_mutation(self):
        self.adb.first_extra = lambda: (self.build/'reader-shell.mipsel').write_bytes(b'changed in extra scan')
        with self.assertRaisesRegex(ValueError, 'changed before transfer'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_same_size_elf_change_during_first_diagnostic_uses_pinned_digest(self):
        def mutate():
            file = self.build/'reader-shell.mipsel'
            content = bytearray(file.read_bytes())
            content[0] ^= 1
            file.write_bytes(content)
        self.adb.first_diagnostic = mutate
        with self.assertRaisesRegex(ValueError, 'changed before transfer'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_sdk_change_before_first_mutation_uses_pinned_library_digest(self):
        sdk = self.base/'sdk'
        sdk.mkdir()
        name = 'libfreetype.so.6'
        shutil.copyfile(stage.SDK/name, sdk/name)
        item = next(x for x in json.loads((ROOT/'build/manifest.json').read_text())['stock_libraries'] if x['name']==name)
        self.adb.extra['libraries'] = self.adb.extra['libraries'].replace(name+' '+item['sha256'],name+' MISSING')
        self.adb.before_transfer = lambda: (sdk/name).write_bytes(b'changed SDK library')
        with patch.object(stage, 'SDK', sdk):
            with self.assertRaisesRegex(ValueError, 'changed before transfer'):
                self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_malformed_unix_record_stops_before_any_mutation(self):
        self.adb.extra['exclusive'] = 'PANDANOTE_UNIX_TABLE\nNum RefCount Protocol Flags Type St Inode Path\nnot-a-record\nPANDANOTE_QWS_SCAN_COMPLETE\n'
        with self.assertRaisesRegex(ValueError, 'malformed QWS'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_valid_unrelated_unix_socket_does_not_block(self):
        self.adb.extra['exclusive'] = self.adb.extra['exclusive'].replace('PANDANOTE_QWS_SCAN_COMPLETE', '00000000: 00000002 00000000 00010000 0001 01 1603 /dev/socket/adbd\nPANDANOTE_QWS_SCAN_COMPLETE')
        report = self.execute()
        self.assertEqual(report['status'], 'check_only_passed')
        self.assertEqual(self.adb.mutations, [])

    def test_qws_unix_socket_stops_before_any_mutation(self):
        self.adb.extra['exclusive'] = self.adb.extra['exclusive'].replace('PANDANOTE_QWS_SCAN_COMPLETE', '00000000: 00000002 00000000 00010000 0001 01 1603 /tmp/QtEmbedded-0\nPANDANOTE_QWS_SCAN_COMPLETE')
        with self.assertRaisesRegex(ValueError, 'QWS Unix socket'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_symlink_replacement_during_first_diagnostic_stops_before_any_mutation(self):
        def replace():
            file = self.build/'reader-shell.mipsel'
            file.unlink()
            file.symlink_to(ROOT/'build/reader-shell.mipsel')
        self.adb.first_diagnostic = replace
        with self.assertRaisesRegex(ValueError, 'symlink|changed before transfer'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_missing_unix_scan_evidence_stops_before_any_mutation(self):
        self.adb.extra['exclusive'] = ''
        with self.assertRaisesRegex(ValueError, 'QWS'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_malformed_unix_scan_evidence_stops_before_any_mutation(self):
        self.adb.extra['exclusive'] = 'PANDANOTE_UNIX_TABLE\ninvalid table\nPANDANOTE_QWS_SCAN_COMPLETE\n'
        with self.assertRaisesRegex(ValueError, 'QWS'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_unix_read_failure_stops_before_any_mutation(self):
        self.adb.unix_error = RuntimeError('Unix table unreadable')
        with self.assertRaisesRegex(RuntimeError, 'unreadable'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_missing_unix_table_is_not_a_completed_successful_remote_scan(self):
        transport = stage.ExistingAdb()
        def host_read_only(args, timeout=10):
            command = args[1].replace('/bin/busybox ', '').replace('/proc/net/unix', str(self.base/'missing-unix-table'))
            return subprocess.run(['sh','-c',command],text=True,capture_output=True,timeout=timeout)
        transport.run = host_read_only
        with self.assertRaisesRegex(RuntimeError, 'remote command failed'):
            transport.shell(stage.EXTRA_COMMANDS['exclusive'])

    def test_unreadable_unix_table_is_not_a_completed_successful_remote_scan(self):
        table = self.base/'unreadable-unix-table'
        table.write_text('Num RefCount Protocol Flags Type St Inode Path\n')
        table.chmod(0)
        self.addCleanup(lambda: table.chmod(0o600))
        transport = stage.ExistingAdb()
        def host_read_only(args, timeout=10):
            command = args[1].replace('/bin/busybox ', '').replace('/proc/net/unix', str(table))
            return subprocess.run(['sh','-c',command],text=True,capture_output=True,timeout=timeout)
        transport.run = host_read_only
        with self.assertRaisesRegex(RuntimeError, 'remote command failed'):
            transport.shell(stage.EXTRA_COMMANDS['exclusive'])

    def test_complete_bounded_flow_fits_legacy_transport_ceiling(self):
        self.adb = LegacyAdb()
        for item in json.loads((ROOT/'build/manifest.json').read_text())['stock_libraries']:
            if item['name'] in stage.STOCK_STAGED:
                self.adb.extra['libraries']=self.adb.extra['libraries'].replace(item['name']+' '+item['sha256'],item['name']+' MISSING')
        report = stage.execute(self.adb,self.build,ROOT,self.base/'evidence',run=True,timeout_ms=300000)
        self.assertEqual(report['status'], 'bounded_timeout_verified')
        self.assertGreater(len(self.adb.verifications),1)
        self.assertTrue(self.adb.launch)
        self.assertTrue(all(count<=3808 for count in self.adb.command_bytes))

    def test_existing_stage_verifies_in_batches_without_retransmission(self):
        self.adb = LegacyAdb()
        _, files, _ = stage.verify_release(self.build,ROOT)
        dirs = {stage.TARGET}
        for name in files:
            dirs.update(str(parent) for parent in (Path(stage.TARGET)/name).parents if str(parent).startswith(stage.TARGET))
        self.adb.extra['stage_tree'] = ''.join(stage.sha(file)+'  '+stage.TARGET+'/'+name+'\n' for name,file in files.items())+''.join('DIR '+name+'\n' for name in sorted(dirs))
        report = self.execute(True)
        self.assertTrue(report['reused_verified_payload'])
        self.assertGreater(len(self.adb.verifications),1)
        self.assertFalse(any(isinstance(call,list) and call[0]=='push' for call in self.adb.mutations))

    def test_all_pinned_files_are_verified_exactly_once_across_batches(self):
        manifest, _, records = stage.verify_release(self.build,ROOT)
        for item in manifest['stock_libraries']:
            if item['name'] in stage.STOCK_STAGED:
                records['lib/'+item['name']]=item
        expected = {stage.TARGET+'/'+name:record['sha256'] for name,record in records.items()}
        commands=stage.verification_commands({name:record['sha256'] for name,record in records.items()})
        pairs=re.findall(r'sha256sum ([^ ]+) \| /bin/busybox cut -d " " -f1\)" = ([0-9a-f]{64})', '\n'.join(commands))
        self.assertEqual(dict(pairs),expected)
        self.assertEqual(len(pairs),len(expected))
        self.assertTrue(all(len(stage.wrap_shell(command).encode())<=3808 for command in commands))

    def test_later_verification_batch_failure_never_launches_application(self):
        self.adb = LegacyAdb()
        self.adb.fail_verification = 2
        with self.assertRaisesRegex(RuntimeError, 'verification batch failed'):
            self.execute(True)
        self.assertEqual(self.adb.launch,'')
        self.assertEqual(len(self.adb.verifications),2)

    def test_multibyte_command_is_rejected_before_transport_by_utf8_bytes(self):
        transport = stage.ExistingAdb()
        calls=[]
        transport.run = lambda args, timeout=10: (calls.append(args) or subprocess.CompletedProcess(args,0,'ok\nPANDANOTE_SHELL_EXIT=0\n',''))
        with self.assertRaisesRegex(ValueError, 'legacy ADB'):
            transport.shell(': #'+'汉'*1300)
        self.assertEqual(calls,[])

    def test_wrapped_command_boundary_includes_completed_exit_trailer(self):
        transport = stage.ExistingAdb()
        calls=[]
        transport.run = lambda args, timeout=10: (calls.append(args) or subprocess.CompletedProcess(args,0,'ok\nPANDANOTE_SHELL_EXIT=0\n',''))
        trailer='\npandanote_shell_status=$?; /bin/busybox printf "\\nPANDANOTE_SHELL_EXIT=%s\\n" "$pandanote_shell_status"'
        command=': #'+'x'*(3808-len(trailer.encode())-3)
        self.assertEqual(transport.shell(command),'ok')
        with self.assertRaisesRegex(ValueError, 'legacy ADB'):
            transport.shell(command+'x')
        self.assertEqual(len(calls),1)
        self.assertEqual(len(calls[0][1].encode()),3808)

    def test_explicit_existing_adb_port_is_bound_without_fallback(self):
        transport = stage.ExistingAdb(5037)
        self.assertEqual(transport.base[transport.base.index('-P')+1], '5037')
        calls=[]
        transport.run = lambda args, timeout=10: (calls.append(args) or subprocess.CompletedProcess(args,1,'','server absent'))
        with self.assertRaisesRegex(RuntimeError, 'server absent'):
            transport.shell(':')
        self.assertEqual(len(calls),1)
        self.assertEqual(transport.base[transport.base.index('-P')+1], '5037')

    def test_invalid_adb_port_rejects_before_connection(self):
        with self.assertRaisesRegex(ValueError, 'port'):
            stage.ExistingAdb(5000)

    def test_selected_adb_port_is_retained_in_evidence(self):
        self.adb.port=5037
        self.assertEqual(self.execute()['adb_port'],5037)

    def test_guarded_touch_hash_is_required(self):
        self.adb.extra['hardware'] = self.adb.extra['hardware'].replace(stage.TOUCH_SHA, '0'*64)
        with self.assertRaisesRegex(ValueError, 'hardware'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_explicit_bounded_run_retains_real_frame_and_timeout(self):
        report = self.execute(True)
        self.assertTrue(report['app_executed'])
        self.assertEqual(report['status'], 'bounded_timeout_verified')
        self.assertEqual((self.base/'evidence/framebuffer.rgb565').stat().st_size, 768000)
        self.assertTrue((self.base/'evidence/framebuffer.png').is_file())
        self.assertFalse(report['physical_navigation_accepted'])
        self.assertIn('before', report['protections'])
        self.assertIn('after', report['protections'])
        self.assertIn('--qws-server', self.adb.launch)
        self.assertNotIn('simulated', self.adb.launch)
        self.assertGreater(len(self.adb.mutations), 0)

    def test_resource_guard_stop_cannot_pass_as_developer_timeout(self):
        self.adb.guard = 'tmpfs_low\n'
        with self.assertRaisesRegex(ValueError, 'resource guard'):
            self.execute(True)
        report = json.loads((self.base/'evidence/report.json').read_text())
        self.assertEqual(report['resource_guard'], 'tmpfs_low\n')
        self.assertIn('after', report['protections'])

    def test_framebuffer_geometry_mismatch_stops_before_mutation(self):
        self.adb.extra['hardware'] = self.adb.extra['hardware'].replace('1600', '3200')
        with self.assertRaisesRegex(ValueError, 'hardware'):
            self.execute(True)
        self.assertEqual(self.adb.mutations, [])

    def test_missing_developer_exit_does_not_pass(self):
        self.adb.app_log = '{"event":"CONTENT_LOADED","success":false}\n'
        with self.assertRaisesRegex(ValueError, 'developer_timeout'):
            self.execute(True)
        self.assertIn('after', json.loads((self.base/'evidence/report.json').read_text())['protections'])

    def test_navigation_reports_observed_events_without_claiming_human_acceptance(self):
        data = stage.navigation_observation([
            {'event':'NAVIGATION','source':'release','from':0,'to':1},
            {'event':'NAVIGATION','source':'idle','from':2,'to':0}])
        self.assertEqual(data['release_count'], 1)
        self.assertEqual(data['idle_count'], 1)
        self.assertFalse(data['human_proof_accepted'])


    def packet(self):
        target = self.base/'content-package'
        shutil.copytree(ROOT.parents[0]/'shared/fixtures/producer-shared', target)
        return target

    def test_optional_package_captured_bytes_survive_original_path_change(self):
        packet = self.packet()
        expected = {p.name:p.read_bytes() for p in packet.iterdir()}
        self.adb = PacketAdb()
        self.adb.first_diagnostic = lambda: (packet/'content.ini').write_bytes(b'changed after capture')
        report = stage.execute(self.adb, self.build, ROOT, self.base/'evidence', run=True,
                               content_package=packet, simulated_epoch=1792458000)
        self.assertEqual(report['status'], 'bounded_timeout_verified')
        self.assertEqual(self.adb.content, expected)
        self.assertIn('--content-dir', self.adb.launch)
        self.assertIn('--developer-simulated-epoch 1792458000', self.adb.launch)
        self.assertEqual(report['development_time']['source'], 'SIMULATED')
        self.assertLessEqual(report['content_package']['reserved_state_bytes'], 215040)
        self.assertTrue(all(size<=3808 for size in self.adb.command_bytes))
        for name, data in expected.items():
            self.assertEqual((self.base/'evidence/content-snapshot'/name).read_bytes(), data)
        self.assertEqual((self.base/'evidence').stat().st_mode & 0o777, 0o700)

    def test_optional_oversized_or_corrupt_packet_fails_before_device_access(self):
        packet = self.packet()
        (packet/'background.png').write_bytes(b'x'*220000)
        self.adb = PacketAdb()
        with self.assertRaisesRegex(ValueError, 'packet'):
            stage.execute(self.adb, self.build, ROOT, self.base/'evidence', run=True,
                          content_package=packet, simulated_epoch=1792458000)
        self.assertEqual(self.adb.calls, [])

    def test_optional_packet_requires_explicit_development_time_before_device_access(self):
        packet = self.packet()
        with self.assertRaisesRegex(ValueError, 'together'):
            stage.execute(self.adb, self.build, ROOT, self.base/'evidence', run=True, content_package=packet)
        self.assertEqual(self.adb.calls, [])


class FakeAdb:
    def __init__(self):
        self.serial = stage.preflight.SERIAL
        self.calls = []
        self.mutations = []
        self.launch = ''
        self.guard = ''
        self.before_transfer = None
        self.first_diagnostic = None
        self.first_extra = None
        self.unix_error = None
        self.serial_reads = 0
        self.app_log = '{"event":"EXIT_REASON","reason":"developer_timeout","code":0}\n'
        self.protection = {
            'status': stage.preflight.SERIAL+'\n',
            'mounts': '/dev/root / ext4 ro,norecovery 0 0\ntmpfs /tmp tmpfs rw 0 0\n',
            'disk_ro': '1\n', 'swaps':'Filename Type Size Used Priority\n',
            'network': '/sys/class/net/lo/flags 0x9\n',
            'tcp':'sl local_address rem_address st\n','tcp6':'PANDANOTE_TCP6_ABSENT\n',
            'uid':'0\n','kernel':'Linux mips\n','modules':'','memory':'MemAvailable: 47000 kB\n'}
        self.extra = {'exclusive':'PANDANOTE_UNIX_TABLE\nNum RefCount Protocol Flags Type St Inode Path\nPANDANOTE_QWS_SCAN_COMPLETE\n', 'capacity':str(28*1024*1024)+'\n', 'stage_tree':'ABSENT\n',
                      'hardware':'fb=800,960\n16\n1600\nspi_fb\nfts_ts\n'+stage.TOUCH_SHA+'\n',
                      'libraries': ''.join(x['name']+' '+x['sha256']+'\n' for x in json.loads((ROOT/'build/manifest.json').read_text())['stock_libraries'])}
    def run(self, args, timeout=10):
        self.calls.append(args)
        if args == ['get-serialno']:
            self.serial_reads += 1
            if self.serial_reads==2 and self.before_transfer:
                self.before_transfer()
            return subprocess.CompletedProcess(args, 0, self.serial+'\n', '')
        if args[0] == 'push':
            self.mutations.append(args)
            return subprocess.CompletedProcess(args,0,'','')
        raise AssertionError(args)
    def shell(self, command):
        self.calls.append(command)
        for name, cmd in stage.preflight.COMMANDS.items():
            if command == cmd:
                if self.first_diagnostic:
                    action, self.first_diagnostic = self.first_diagnostic, None
                    action()
                return self.protection[name]
        for name, cmd in stage.EXTRA_COMMANDS.items():
            if command == cmd:
                if self.first_extra:
                    action, self.first_extra = self.first_extra, None
                    action()
                if name=='exclusive' and self.unix_error:
                    raise self.unix_error
                return self.extra[name]
        if command == stage.library_command(json.loads((ROOT/'build/manifest.json').read_text())):
            return self.extra['libraries']
        if command.startswith('# VERIFY_FILES\n'):
            return ''
        if command.startswith(('# STAGE_FILES\n', '# RUNTIME_STATE\n')):
            self.mutations.append(command)
            return ''
        if command.startswith('# BOUNDED_RUN\n'):
            self.launch = command
            self.mutations.append(command)
            return 'PANDANOTE_APP_EXIT=0\nFRAME_EXIT=0\n'
        if command.startswith('# COLLECT\n'):
            import base64
            return '\n'.join(k+'='+base64.b64encode(v).decode() for k,v in {'stdout':self.app_log.encode(),'rss':b'VmRSS: 12000 kB\n','dd':b'480 records','guard':self.guard.encode(),'frame':bytes(768000)}.items())
        raise AssertionError(command)


class LegacyAdb(FakeAdb):
    """Measured conservative transport budget, including the real exit trailer."""
    def __init__(self):
        super().__init__()
        self.command_bytes=[]
        self.verifications=[]
        self.fail_verification=None
    def shell(self,command):
        trailer='\npandanote_shell_status=$?; /bin/busybox printf "\\nPANDANOTE_SHELL_EXIT=%s\\n" "$pandanote_shell_status"'
        count=len((command.rstrip()+trailer).encode('utf-8'))
        self.command_bytes.append(count)
        if count>3808:
            raise RuntimeError('legacy shell command too long')
        if command.startswith('# VERIFY_FILES\n'):
            self.verifications.append(command)
            if len(self.verifications)==self.fail_verification:
                raise RuntimeError('verification batch failed')
        return super().shell(command)


class PacketAdb(LegacyAdb):
    def __init__(self):
        super().__init__()
        self.content = {}
    def shell(self, command):
        if command.startswith(('# CONTENT_PACKAGE\n', '# VERIFY_CONTENT\n')):
            import base64
            self.calls.append(command)
            self.mutations.append(command)
            self.command_bytes.append(len(stage.wrap_shell(command).encode('utf-8')))
            for encoded, op, target in re.findall(r'printf %s ([A-Za-z0-9+/=]+) \| .*? (>>|>) ([^ \n]+)', command):
                name=Path(shlex.split(target)[0]).name
                self.content[name]=(self.content.get(name,b'') if op=='>>' else b'')+base64.b64decode(encoded)
            return ''
        return super().shell(command)


if __name__ == '__main__':
    unittest.main()
