"""Runtime profile policy uses synthetic diagnostics only."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import json
import hashlib
import tempfile
import subprocess
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import stage_ram as stage

def diagnostics():
    return dict(status=stage.preflight.SERIAL+'\n', mounts='/dev/root / ext4 ro,noload 0 0\ntmpfs /tmp tmpfs rw 0 0\n',
        disk_ro='1',swaps='Filename Type Size Used Priority\n',network='/sys/class/net/lo/flags 0x9\n/sys/class/net/wlan0/flags 0x1003\n',
        tcp='sl local_address rem_address st\n',tcp6='PANDANOTE_TCP6_ABSENT\n',uid='0',
        profile='wlan0-only-listeners-loopback-storage-ro-v1\n',pid1= '1ed1ef64aa71af447679e179efa69e6852902255e1ff056de9ee710b86cd354d  /tmp/pid1\n',
        receipt='')

class ProfileTests(unittest.TestCase):
    def bind_candidate_release(self):
        # Only tests consuming this build opt into its captured input hash;
        # production pin transition tests keep the deployment allowlist intact.
        pin=patch.object(stage,'REVIEWED_MANIFEST_SHA',hashlib.sha256((ROOT/'build/manifest.json').read_bytes()).hexdigest())
        self.addCleanup(pin.stop)
        pin.start()
    def test_explicit_profile_requires_exact_boot_receipt(self):
        d=diagnostics()
        with self.assertRaisesRegex(ValueError,'receipt'):
            stage.validate_profile(d,'msc1-sdio-wlan0-opt-ro-v1')
    def test_legacy_remains_network_down(self):
        with self.assertRaisesRegex(ValueError,'non-loopback'):
            stage.validate_profile(diagnostics(),'legacy-network-down')
    def test_unknown_profile_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'Unknown'):
            stage.validate_profile(diagnostics(),'other')
    def test_new_profile_only_allows_exact_wlan_and_readonly_mount(self):
        d=diagnostics();d['receipt']=stage.boot_receipt_literal()
        stage.validate_profile(d,'msc1-sdio-wlan0-opt-ro-v1')
        d['network']+='/sys/class/net/usb0/flags 0x1\n'
        with self.assertRaisesRegex(ValueError,'non-loopback'):
            stage.validate_profile(d,'msc1-sdio-wlan0-opt-ro-v1')
    def test_optional_p5_mount_requires_explicit_selection(self):
        d=diagnostics();d['receipt']=stage.boot_receipt_literal()
        d['mounts']+='/dev/mmcblk0p5 /run/pandanote-opt ext4 ro,norecovery 0 0\n'
        with self.assertRaisesRegex(ValueError,'persistent mount'):
            stage.validate_profile(d,'msc1-sdio-wlan0-opt-ro-v1')
        stage.validate_profile(d,'msc1-sdio-wlan0-opt-ro-v1',opt_libraries=True)
        d['mounts']=d['mounts'].replace('ro,norecovery','rw,norecovery')
        with self.assertRaisesRegex(ValueError,'mount'):
            stage.validate_profile(d,'msc1-sdio-wlan0-opt-ro-v1',opt_libraries=True)
    def test_new_manifest_pin_is_explicit_reviewed_transition(self):
        self.assertEqual(stage.REVIEWED_MANIFEST_SHA,'c17a4d133f7953ae54720611a378c1640cdd3cf427db1d4fcd680a9a80ec8a99')
        with patch.object(stage,'REVIEWED_MANIFEST_SHA','25e55d00d31dff42b2723218f8342a95d0171015dc612f9fade4c4a91b4584db'):
            with self.assertRaisesRegex(ValueError,'not the exact reviewed manifest'):
                stage.verify_release()
    def test_previous_boot_receipt_is_refused(self):
        d=diagnostics()
        d['receipt']=('profile='+stage.NETWORK_PROFILE+'\nmanifest=25e55d00d31dff42b2723218f8342a95d0171015dc612f9fade4c4a91b4584db\n'
            'pid1='+stage.PID1_SHA+'\nbootstrap=d050610bd76deadf4d7ef8b4c6a265cd80fcba73f5538899dd0f1e2c6e36edac\n')
        with self.assertRaisesRegex(ValueError,'reviewed boot receipt'):
            stage.validate_profile(d,stage.NETWORK_PROFILE)
    def test_optional_loader_checks_shadowing_of_all_dependencies(self):
        manifest=json.loads((ROOT/'build/manifest.json').read_bytes())
        command=stage.library_command(manifest,opt_libraries=True)
        self.assertEqual(command.count('for d in /run/pandanote-opt/opt/image/opt/Qtopia/lib'),len(manifest['stock_libraries']))
    def test_optional_library_queries_fit_each_legacy_shell_request(self):
        manifest=json.loads((ROOT/'build/manifest.json').read_bytes())
        commands=stage.library_commands(manifest,opt_libraries=True)
        self.assertGreater(len(commands),1)
        self.assertTrue(all(len(stage.wrap_shell(c).encode())<=3808 for c in commands))
        self.assertIn('readlink -f',commands[0])
        self.assertIn('/libQtGui.so.4.7.4',commands[0])
    def test_optional_library_launch_retains_300s_command_bound(self):
        command=stage.launch_command('/tmp/reader-shell-run-20261021T123456789000',300000,opt_libraries=True)
        self.assertIn('LD_LIBRARY_PATH=/run/pandanote-opt/opt/image/opt/Qtopia/lib:/lib:/usr/lib',command)
        self.assertLessEqual(len(stage.wrap_shell(command).encode()),3808)
        check=subprocess.run(['sh','-n'],input=command,text=True,capture_output=True)
        self.assertEqual(check.returncode,0,check.stderr)
    def test_changed_pid1_or_profile_marker_rejects(self):
        for key in ('pid1','profile'):
            d=diagnostics();d['receipt']=stage.boot_receipt_literal();d[key]='other\n'
            with self.assertRaisesRegex(ValueError,'PID1/network'):
                stage.validate_profile(d,stage.NETWORK_PROFILE)
    def test_wildcard_listener_and_swap_remain_forbidden(self):
        for key,value in [('tcp','sl local_address rem_address st\n0: 00000000:22A0 00000000:0000 0A\n'),('swaps','Filename Type Size Used Priority\n/swap file 1 0 0\n')]:
            d=diagnostics();d['receipt']=stage.boot_receipt_literal();d[key]=value
            with self.assertRaises(ValueError):
                stage.validate_profile(d,stage.NETWORK_PROFILE)
    def test_opt_checks_do_not_transfer_vendor_libraries(self):
        self.bind_candidate_release()
        manifest,files,records=stage.verify_release()
        class Adb:
            def shell(self,command):
                return ''.join(x['name']+' '+x['sha256']+'\n' for x in manifest['stock_libraries'] if 'for d in ' in command and '"$d/'+x['name']+'"' in command)
        data=dict(exclusive='PANDANOTE_UNIX_TABLE\nNum RefCount Protocol Flags Type St Inode Path\nPANDANOTE_QWS_SCAN_COMPLETE\n',hardware='fb=800,960\n16\n1600\nspi_fb\nfts_ts\n'+stage.TOUCH_SHA+'\n',stage_tree='ABSENT',capacity=str(stage.TMP_LIMIT))
        _,payload,_,budget=stage.inspect(Adb(),manifest,files,records,data,opt_libraries=True)
        self.assertFalse(any(n.startswith('lib/') for n in payload))
        self.assertLess(budget['payload_bytes'],8*1024*1024)
    def test_soname_symlink_must_resolve_to_manifest_real_file(self):
        import hashlib
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            base=Path(directory);lib=base/'lib';lib.mkdir()
            expected=b'owned synthetic library bytes'
            (lib/'libFixture.so.1.2').write_bytes(expected)
            (base/'foreign.so').write_bytes(expected)
            soname=lib/'libFixture.so.1';soname.symlink_to('libFixture.so.1.2')
            manifest={'stock_libraries':[dict(name=soname.name,source_path='/opt/image/opt/Qtopia/lib/libFixture.so.1.2',sha256=hashlib.sha256(expected).hexdigest())]}
            command=stage.library_command(manifest,opt_libraries=True).replace('/run/pandanote-opt/opt/image/opt/Qtopia/lib',str(lib)).replace('/bin/busybox ','')
            def run():
                return subprocess.run(['sh','-c',command],capture_output=True,text=True,check=True).stdout
            self.assertEqual(run(),soname.name+' '+hashlib.sha256(expected).hexdigest()+'\n')
            soname.unlink();soname.symlink_to(base/'foreign.so')
            self.assertEqual(run(),soname.name+' INVALID\n')
    def profile_adb(self):
        from test_stage_ram import FakeAdb
        class ProfileAdb(FakeAdb):
            def shell(self,command):
                for key,cmd in stage.PROFILE_COMMANDS.items():
                    if cmd==command:
                        self.calls.append(command)
                        return self.protection[key]
                return super().shell(command)
        adb=ProfileAdb();adb.protection.update(diagnostics());adb.protection['memory']='MemAvailable: 47000 kB\n'
        adb.protection['receipt']=stage.boot_receipt_literal()
        return adb
    def test_new_profile_checkonly_has_no_remote_mutation(self):
        self.bind_candidate_release()
        adb=self.profile_adb()
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            evidence=Path(directory)/'evidence'
            report=stage.execute(adb,ROOT/'build',ROOT,evidence,profile=stage.NETWORK_PROFILE)
            self.assertEqual(evidence.stat().st_mode&0o777,0o700)
            self.assertEqual((evidence/'report.json').stat().st_mode&0o777,0o600)
        self.assertEqual(report['status'],'check_only_passed')
        self.assertEqual(report['capacity']['runtime_budget_bytes'],12*1024*1024)
        self.assertEqual(report['capacity']['ordinary_ram_reserve_bytes'],24*1024*1024)
        self.assertEqual(adb.mutations,[])
    def test_network_monitor_includes_cache_in_combined_state_cap(self):
        command=stage.launch_command('/tmp/reader-shell-run-20261021T123456789000',300000,opt_libraries=True,network_profile=True)
        self.assertIn('/tmp/pandanote-reader-cache',command)
        self.assertIn('"$state_kb" -gt 12288',command)
        self.assertLessEqual(len(stage.wrap_shell(command).encode()),3808)
    def app_file_blocks(self,network_profile):
        import re
        command=stage.launch_command('/tmp/reader-shell-run-20261021T123456789000',300000,network_profile=network_profile)
        return int(re.search(r'\( ulimit -c 0; ulimit -f (\d+); exec ',command)[1])
    def write_child(self,blocks,size,unit_bytes):
        # Target BusyBox ulimit units were measured independently as512B. Host
        # shell uses1024B; set the target-equivalent kernel limit explicitly,
        # then exercise real child writes/EFBIG rather than imitating a QFile.
        code='''import errno,json,os,resource,signal,sys
limit=int(sys.argv[1]); wanted=int(sys.argv[2]); path=sys.argv[3]
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
resource.setrlimit(resource.RLIMIT_FSIZE,(limit,limit))
signal.signal(signal.SIGXFSZ,signal.SIG_IGN)
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);written=0;error=0
try:
 while written<wanted:
  written+=os.write(fd,b'x'*min(65536,wanted-written))
except OSError as failure:
 error=failure.errno
finally:
 os.close(fd)
print(json.dumps(dict(limit=resource.getrlimit(resource.RLIMIT_FSIZE),core=resource.getrlimit(resource.RLIMIT_CORE),written=written,bytes=os.stat(path).st_size,error=error)))
'''
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            child=subprocess.run([sys.executable,'-c',code,str(blocks*unit_bytes),str(size),str(Path(directory)/'resource.png')],text=True,capture_output=True,check=True)
        return json.loads(child.stdout)
    def test_network_app_admits_exact_contract_maximum_target_write(self):
        result=self.write_child(self.app_file_blocks(True),2097152,512)
        self.assertEqual(result['limit'],[2097152,2097152])
        self.assertEqual(result['core'],[0,0])
        self.assertEqual(result['error'],0)
        self.assertEqual(result['bytes'],2097152)
    def test_network_app_refuses_one_byte_over_target_file_limit(self):
        import errno
        result=self.write_child(self.app_file_blocks(True),2097153,512)
        self.assertEqual(result['error'],errno.EFBIG)
        self.assertEqual(result['bytes'],2097152)
    def test_actual_host_shell_directive_remains_bounded_without_assuming_its_units(self):
        import errno,re
        command=stage.launch_command('/tmp/reader-shell-run-EXAMPLE',2000,network_profile=True)
        directive=re.search(r'\( (ulimit -c 0; ulimit -f \d+); exec ',command)[1]
        code='''import errno,json,os,resource,signal,sys
limit=resource.getrlimit(resource.RLIMIT_FSIZE)[0]
signal.signal(signal.SIGXFSZ,signal.SIG_IGN)
def write(path,count):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);done=0;error=0
 try:
  while done<count:done+=os.write(fd,b'x'*min(65536,count-done))
 except OSError as failure:error=failure.errno
 finally:os.close(fd)
 return dict(bytes=os.stat(path).st_size,error=error)
print(json.dumps(dict(limit=limit,core=resource.getrlimit(resource.RLIMIT_CORE)[0],valid=write(sys.argv[1]+'/valid.png',2097152),over=write(sys.argv[1]+'/oversized.png',limit+1))))
'''
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            child=subprocess.run(['sh','-c',directive+'; exec "$@"','fsize-probe',sys.executable,'-c',code,directory],capture_output=True,text=True,check=True)
        result=json.loads(child.stdout)
        self.assertIn(result['limit'],(2097152,4194304))
        self.assertEqual(result['core'],0)
        self.assertEqual(result['valid'],dict(bytes=2097152,error=0))
        self.assertEqual(result['over'],dict(bytes=result['limit'],error=errno.EFBIG))
    def test_legacy_file_limit_retains_measured_256k_target_bound(self):
        import errno
        self.assertEqual(self.app_file_blocks(False),512)
        result=self.write_child(self.app_file_blocks(False),262145,512)
        self.assertEqual(result['error'],errno.EFBIG)
        self.assertEqual(result['bytes'],262144)
    def test_network_file_budget_covers_larger_stdout_plus_cache(self):
        self.bind_candidate_release()
        adb=self.profile_adb()
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            report=stage.execute(adb,ROOT/'build',ROOT,Path(directory)/'evidence',profile=stage.NETWORK_PROFILE)
        budget=report['capacity']
        self.assertEqual(budget['app_file_limit_bytes'],2097152)
        self.assertEqual(budget['monitor_file_limit_bytes'],262144)
        self.assertEqual(budget['worst_case_runtime_bytes'],768000+2097152+262144+1048576+65536+3*2240512+32768)
        self.assertLess(budget['worst_case_runtime_bytes'],budget['runtime_budget_bytes'])
    def test_network_preflight_refuses_capacity_between_old_and_new_reserve(self):
        self.bind_candidate_release()
        adb=self.profile_adb()
        _,_,records=stage.verify_release()
        adb.extra['capacity']=str(sum(r['bytes'] for r in records.values())+11*1024*1024)+'\n'
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            with self.assertRaisesRegex(ValueError,'capacity'):
                stage.execute(adb,ROOT/'build',ROOT,Path(directory)/'evidence',run=True,profile=stage.NETWORK_PROFILE)
        self.assertEqual(adb.mutations,[])
    def test_profile_change_at_final_guard_stops_before_any_mutation(self):
        self.bind_candidate_release()
        adb=self.profile_adb()
        adb.before_transfer=lambda:adb.protection.update(profile='wrong\n')
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            with self.assertRaisesRegex(ValueError,'PID1/network'):
                stage.execute(adb,ROOT/'build',ROOT,Path(directory)/'evidence',run=True,profile=stage.NETWORK_PROFILE)
        self.assertEqual(adb.mutations,[])
