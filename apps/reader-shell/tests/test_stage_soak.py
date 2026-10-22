"""Host-only soak controller tests; no USB, ADB, native ELF or network access."""
import base64
import hashlib
import json
import re
import os
import signal
import tempfile
import time
import shlex
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import stage_ram as stage

class SoakTests(unittest.TestCase):
    state='/tmp/reader-shell-run-20261021T123456789000'
    def test_separate_fixed_controller_and_legacy_limit(self):
        script=stage.soak_script(self.state)
        self.assertIn('--qws-server',script)
        self.assertNotIn('--developer-',script)
        self.assertIn('start+1800',script)
        self.assertIn('sleep 1808',script)
        self.assertIn('ulimit -f 4096',script)
        self.assertIn('ulimit -f 1536',script)
        self.assertIn('ulimit -f 512',script)
        self.assertIn('CmaFree',script)
        self.assertIn('/tmp/pandanote-reader-cache',script)
        self.assertIn('sleep 1',script)
        syntax=subprocess.run(['sh','-n'],input=script,text=True,capture_output=True)
        self.assertEqual(syntax.returncode,0,syntax.stderr)
        for command in stage.soak_commands(self.state)+[stage.soak_launch_command(self.state)]:
            self.assertLessEqual(len(stage.wrap_shell(command).encode()),3808)
        with self.assertRaisesRegex(ValueError,'300000'):
            stage.execute(None,None,None,None,timeout_ms=1800000)
    def test_soak_preconditions_before_device_access(self):
        for options in ({},{'profile':stage.NETWORK_PROFILE},{'profile':stage.NETWORK_PROFILE,'opt_libraries':True,'content_package':Path('bad'),'simulated_epoch':1700000000}):
            with self.subTest(options=options),self.assertRaisesRegex(ValueError,'soak'):
                stage.execute(None,None,None,None,run_soak=True,**options)
    def test_transport_extension_only_for_exact_soak_entry(self):
        transport=stage.ExistingAdb();timeouts=[]
        def run(args,timeout):
            timeouts.append(timeout)
            return subprocess.CompletedProcess(args,0,'ok\nPANDANOTE_SHELL_EXIT=0\n','')
        transport.run=run
        transport.shell(stage.soak_launch_command(self.state))
        transport.shell('# SOAK_RUN_SECONDS=999999\ntrue')
        transport.shell('# SOAK_RUN_SECONDS=1800\n/bin/busybox sh /tmp/arbitrary.sh')
        self.assertEqual(timeouts,[1840,20,20])
    def test_classification_requires_controlled_stop_measured_duration_and_frame(self):
        control='START_UPTIME=10\nSTOP_UPTIME=1810\nCONTROL_STOP=term_at_deadline\nEND_UPTIME=1811\n'
        trailer='PANDANOTE_APP_EXIT=143\nFRAME_EXIT=0\n'
        samples=''.join('t=%d RSS=1 Peak=2 Size=3 MemAvailable=5000 MemFree=6000 Shmem=1 CmaTotal=2 CmaFree=1 tmp=2000 state=10\n'%t for t in range(10,1811,5))
        valid_frames=''.join('FRAME_UPTIME=%d\n'%t for t in range(20,1810,300))
        result=stage.validate_soak(control,trailer,[],samples,valid_frames,False)
        self.assertEqual(result['termination'],'intentional_controller_SIGTERM')
        self.assertFalse(result['normal_native_exit'])
        for ctl,exit,events,memory,frame,watchdog in [
            ('',trailer,[],samples,'FRAME_UPTIME=20\n',False),
            (control.replace('1810','310'),trailer,[],samples,'FRAME_UPTIME=20\n',False),
            (control,trailer.replace('143','0'),[],samples,'FRAME_UPTIME=20\n',False),
            (control,trailer,[{'event':'EXIT_REASON','reason':'event_loop_return','code':0}],samples,'FRAME_UPTIME=20\n',False),
            (control,trailer,[],samples,'',False),
            (control,trailer,[],samples,'FRAME_UPTIME=20\n',True),
            (control,trailer,[],'','FRAME_UPTIME=20\n',False),
            (control,trailer,[],samples.replace('RSS=1','RSS=not-a-number'),valid_frames,False),
            (control,trailer,[],samples,'FRAME_UPTIME=20\nFRAME_UPTIME=19\nFRAME_UPTIME=1810\n',False),
        ]:
            with self.subTest(control=ctl,exit=exit),self.assertRaisesRegex(ValueError,'soak'):
                stage.validate_soak(ctl,exit,events,memory,frame,watchdog)
    def test_monitor_worst_case_fits_target_cap(self):
        budget=stage.soak_monitor_budget()
        self.assertEqual(budget['sample_interval_seconds'],5)
        self.assertLess(budget['worst_case_bytes'],262144)
        self.assertGreaterEqual(budget['maximum_samples'],362)
        self.assertLessEqual(budget['maximum_line_bytes'],512)


    def run_fixture(self,mode='normal'):
        """Execute generated supervisor in real sh, with explicit fixture paths.

        Only fixture clock/delays/I/O/app are substituted; PID/wait/kill/traps,
        monitoring loops and artifact writes are the generated shell itself.
        This deliberately short run cannot count as a device1800s soak.
        """
        tmp=tempfile.TemporaryDirectory(dir=ROOT/'build');self.addCleanup(tmp.cleanup)
        base=Path(tmp.name);state=base/'state';state.mkdir()
        (base/'meminfo').write_text('MemAvailable: 9000 kB\nMemFree: 10000 kB\nShmem: 1 kB\nCmaTotal: 16384 kB\nCmaFree: 16000 kB\n')
        (base/'status').write_text('VmRSS: 10 kB\nVmPeak: 20 kB\nVmSize: 30 kB\n')
        app=base/'app.py'
        app.write_text('import os,signal,time\nopen('+repr(str(base/'app-pid'))+',"w").write(str(os.getpid()))\n'+
                       ('raise SystemExit(7)\n' if mode=='crash' else
                        'signal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(20)\n' if mode=='ignore_term' else 'time.sleep(20)\n'))
        script=stage.soak_script(self.state)
        script=script.replace('cd '+self.state, 'cd '+shlex.quote(str(state)))
        script=script.replace(stage.application_command(self.state,opt_libraries=True),shlex.quote(sys.executable)+' '+shlex.quote(str(app)))
        # Actual host wall clock and2s deadline; no fabricated1800s pass.
        script=re.sub(r'uptime_s\(\) \{[^\n]+', 'uptime_s() { '+shlex.quote(sys.executable)+' -c \"import time; print(int(time.time()))\"; }',script)
        script=script.replace('start+1800','start+2').replace('start+1808','start+8').replace('sleep 1808','sleep 8')
        script=script.replace('sleep 10','sleep 0.1').replace('sleep 300','sleep 0.3').replace('sleep 1','sleep 0.1').replace('sleep 5','sleep 0.5').replace('now+5','now+1')
        script=script.replace('/proc/meminfo',str(base/'meminfo')).replace('/proc/"$app_pid"/status',str(base/'status'))
        # Real file writes/caps; only hardware measurement producers substituted.
        shim=r'''b() {
 case "$1" in
 df) printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\nfixture 28000 1000 27000 1%% /tmp\n';;
 du) printf '100 .\n';;
 dd) @FRAME@;;
 *) command "$@";;
 esac
}'''
        if mode in ('monitor_hang','measurement_hang','measurement_death'):
            leaf=base/'leaf.py'
            leaf.write_text('import os,time\nopen('+repr(str(base/'leaf-pid'))+',\"w\").write(str(os.getpid()))\ntime.sleep(30)\n')
            shim=shim.replace("df) printf",'df) '+shlex.quote(sys.executable)+' '+shlex.quote(str(leaf))+'; return;; unused) printf')
        if mode=='partial_du':
            shim=shim.replace("du) printf '100 .\\n';;","du) printf '100 .\\n'; return 1;;")
        frame='return 1' if mode=='frame_failure' else 'dd if=/dev/zero of=framebuffer.rgb565 bs=1600 count=480'
        script=script.replace('b() { /bin/busybox "$@"; }',shim.replace('@FRAME@',frame))
        script=script.replace('/bin/busybox sleep ', 'sleep ').replace('/bin/busybox \"$@\" & owned=$!', '\"$@\" & owned=$!').replace('child_wait dd if=/dev/fb0', 'child_wait dd if=/dev/zero')
        if mode=='frame_failure':
            script=script.replace('child_wait dd if=/dev/zero', 'child_wait false if=/dev/zero')
        cache=base/'cache'
        if mode!='absent_cache': cache.mkdir()
        script=script.replace('/tmp/pandanote-reader-cache',str(cache))
        wrapper=base/'monitor-leaf.py'
        wrapper.write_text('#!'+sys.executable+'\n'+
            'import os,sys,time\ncmd=sys.argv[1];args=sys.argv[2:]\n'+
            'if cmd=="df":\n'+
            (' open('+repr(str(base/'leaf-pid'))+',"w").write(str(os.getpid()));time.sleep(30)\n' if mode in ('monitor_hang','measurement_hang','measurement_death') else
             ' print("Filesystem 1024-blocks Used Available Capacity Mounted on\\nfixture 28000 1000 27000 1% /tmp")\n')+
            'elif cmd=="du":\n print("100 .")\n'+
            (' raise SystemExit(1)\n' if mode=='partial_du' else '' if mode=='incomplete_du' else ' if len(args)>2: print("100 "+args[-1])\n')+
            'else: os.execvp(cmd,[cmd]+args)\n')
        wrapper.chmod(0o700)
        # Exact generated leaf spawn is executed as one real executable process.
        script=script.replace('/bin/busybox "$@" > "$output"',shlex.quote(str(wrapper))+' "$@" > "$output"')

        if mode=='measurement_death':
            script=script.replace('heartbeat_failure=\nwhile', 'while [ ! -f '+shlex.quote(str(base/'leaf-pid'))+' ]; do sleep 0.01; done\nb kill -KILL \"$monitor_pid\"\nheartbeat_failure=\nwhile')
        if mode=='monitor_death':
            script=script.replace('heartbeat_failure=\nwhile', 'b kill -KILL "$monitor_pid"\nheartbeat_failure=\nwhile')
        if mode=='log_failure':
            script=script.replace("b printf 't=%s %s tmp=%s state=%s\\n'","false 't=%s %s tmp=%s state=%s\\n'")
        if mode=='memory_low':
            (base/'meminfo').write_text((base/'meminfo').read_text().replace('9000','1000'))
        process=subprocess.run(['sh','-c',script],text=True,capture_output=True,timeout=12)
        leaf_pidfile=base/'leaf-pid'
        if leaf_pidfile.exists():
            leaf_pid=int(leaf_pidfile.read_text())
            try:
                os.kill(leaf_pid,0)
            except ProcessLookupError: pass
            else:
                (state/'leaf-survived-controller').write_text(str(leaf_pid))
                os.kill(leaf_pid,signal.SIGKILL)
        pidfile=base/'app-pid'
        if pidfile.exists():
            pid=int(pidfile.read_text())
            with self.assertRaises(ProcessLookupError):os.kill(pid,0)
        return process,state

    def test_real_shell_deadline_stops_only_owned_child_and_short_is_not_soak(self):
        other=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'])
        self.addCleanup(lambda:(other.terminate(),other.wait(timeout=2)))
        process,state=self.run_fixture()
        self.assertIn('PANDANOTE_APP_EXIT=143',process.stdout,process.stderr)
        self.assertIn('FRAME_EXIT=0',process.stdout)
        self.assertIn('CONTROL_STOP=term_at_deadline',(state/'controller.txt').read_text())
        self.assertIsNone(other.poll())
        with self.assertRaisesRegex(ValueError,'soak'):
            stage.validate_soak((state/'controller.txt').read_text(),process.stdout,[],(state/'memory.txt').read_text(),(state/'frames.txt').read_text(),False)

    def test_real_shell_failures_kill_owned_app_and_cannot_classify_as_soak(self):
        for mode in ('crash','frame_failure','memory_low','monitor_death','monitor_hang','log_failure','ignore_term'):
            with self.subTest(mode=mode):
                process,state=self.run_fixture(mode)
                if mode=='crash': self.assertIn('PANDANOTE_APP_EXIT=7',process.stdout)
                elif mode=='ignore_term':
                    self.assertIn('PANDANOTE_APP_EXIT=137',process.stdout)
                    self.assertEqual((state/'watchdog.txt').read_text(),'STOP_ESCALATION\n')
                else: self.assertTrue((state/'resource-guard.txt').exists())
                with self.assertRaisesRegex(ValueError,'soak'):
                    stage.validate_soak((state/'controller.txt').read_text(),process.stdout,[],(state/'memory.txt').read_text() if (state/'memory.txt').exists() else '',(state/'frames.txt').read_text() if (state/'frames.txt').exists() else '',(state/'watchdog.txt').exists())

    def test_real_transfer_commands_restore_exact_script_bytes(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            state=Path(directory)
            for command in stage.soak_commands(self.state):
                command=command.replace(self.state,str(state)).replace('/bin/busybox ','')
                result=subprocess.run(['sh','-c',command],text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((state/'soak-controller.sh').read_bytes(),stage.soak_script(self.state).encode())


    def test_maximum_numeric_sample_log_real_write_fits_measured_target_cap(self):
        # Enforce the measured target byte limit explicitly; host ulimit units
        # differ. Real write of full maximum361+2 sample window, no truncation.
        import resource
        budget=stage.soak_monitor_budget()
        line=('t=4294967295 RSS=4294967295 Peak=4294967295 Size=4294967295 '
              'MemAvailable=4294967295 MemFree=4294967295 Shmem=4294967295 '
              'CmaTotal=4294967295 CmaFree=4294967295 tmp=4294967295 state=4294967295\n')
        self.assertLessEqual(len(line.encode()),budget['maximum_line_bytes'])
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            path=Path(directory)/'maximum-memory.txt'
            child=subprocess.run([sys.executable,'-c',
                'import resource,sys;resource.setrlimit(resource.RLIMIT_FSIZE,(262144,262144));'
                'open(sys.argv[1],"w").write(sys.argv[2]*363)',str(path),line],capture_output=True,text=True)
            self.assertEqual(child.returncode,0,child.stderr)
            self.assertEqual(path.stat().st_size,len(line)*363)

    def test_complete_soak_staging_uses_real_pinned_inputs_with_private_evidence(self):
        pin=patch.object(stage,'REVIEWED_MANIFEST_SHA',hashlib.sha256((ROOT/'build/manifest.json').read_bytes()).hexdigest())
        self.addCleanup(pin.stop)
        pin.start()
        from test_stage_ram import FakeAdb
        from test_stage_profiles import diagnostics
        manifest=json.loads((ROOT/'build/manifest.json').read_bytes())
        control='START_UPTIME=10\nSTOP_UPTIME=1810\nCONTROL_STOP=term_at_deadline\nEND_UPTIME=1811\n'
        memory=''.join('t=%d RSS=1 Peak=2 Size=3 MemAvailable=5000 MemFree=6000 Shmem=1 CmaTotal=2 CmaFree=1 tmp=2000 state=10\n'%t for t in range(10,1810,5))
        frames=''.join('FRAME_UPTIME=%d\n'%t for t in range(20,1810,300))
        class SoakAdb(FakeAdb):
            def shell(inner,command):
                stage.wrap_shell(command)
                for key,cmd in stage.PROFILE_COMMANDS.items():
                    if command==cmd:return inner.protection[key]
                if command in stage.library_commands(manifest,opt_libraries=True):
                    return ''.join(x['name']+' '+x['sha256']+'\n' for x in manifest['stock_libraries'] if '\"$d/'+x['name']+'\"' in command)
                if command.startswith(('# SOAK_SCRIPT\n','# VERIFY_SOAK_SCRIPT\n')):
                    inner.mutations.append(command);return ''
                if command.startswith('# SOAK_RUN_SECONDS=1800\n'):
                    inner.launch=command;inner.mutations.append(command)
                    return 'PANDANOTE_APP_EXIT=143\nFRAME_EXIT=0\n'
                if command.startswith('# COLLECT\n'):
                    return '\n'.join(k+'='+base64.b64encode(v).decode() for k,v in dict(stdout=b'',rss=memory.encode(),dd=b'480 records',guard=b'',frame=bytes(768000),control=control.encode(),frames=frames.encode(),cleanup=b'MONITOR_CLEANUP=verified\n',reaped=b'REAPED=10 STATUS=0 COUNT=100\n').items())
                return super().shell(command)
        adb=SoakAdb();adb.protection.update(diagnostics());adb.protection['receipt']=stage.boot_receipt_literal()
        adb.protection['memory']='MemAvailable: 47000 kB\n'
        adb.protection['mounts']+='/dev/mmcblk0p5 /run/pandanote-opt ext4 ro,noload 0 0\n'
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            evidence=Path(directory)/'evidence'
            report=stage.execute(adb,ROOT/'build',ROOT,evidence,run_soak=True,profile=stage.NETWORK_PROFILE,opt_libraries=True)
            self.assertEqual(report['status'],'soak_controlled_stop_verified')
            self.assertFalse(report['soak']['normal_native_exit'])
            self.assertFalse(report['soak']['event_boundary_accepted'])
            self.assertEqual(evidence.stat().st_mode&0o777,0o700)
            self.assertTrue(all(f.stat().st_mode&0o777==0o600 for f in evidence.iterdir() if f.is_file()))
            self.assertEqual(report['manifest_sha256'],stage.REVIEWED_MANIFEST_SHA)
            self.assertIn('after',report['protections'])
            real_shell=adb.shell
            def fail_launch(command):
                if command.startswith('# SOAK_RUN_SECONDS=1800\n'):
                    raise RuntimeError('fixture missing controller completion trailer')
                return real_shell(command)
            adb.shell=fail_launch
            failed=evidence.parent/'failed-evidence'
            with self.assertRaisesRegex(RuntimeError,'fixture missing controller'):
                stage.execute(adb,ROOT/'build',ROOT,failed,run_soak=True,profile=stage.NETWORK_PROFILE,opt_libraries=True)
            self.assertTrue((failed/'controller.txt').exists())
            self.assertTrue((failed/'frames.txt').exists())
            failed_report=json.loads((failed/'report.json').read_text())
            self.assertEqual(failed_report['status'],'stopped')
            self.assertFalse(failed_report['app_executed'])


    def test_measurement_descendant_is_gone_after_heartbeat_or_monitor_death(self):
        sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
        self.addCleanup(lambda:(sentinel.terminate(),sentinel.wait(timeout=2)))
        for mode in ('monitor_hang','measurement_hang','measurement_death'):
            with self.subTest(mode=mode):
                process,state=self.run_fixture(mode)
                self.assertFalse((state/'leaf-survived-controller').exists(),
                    'measurement leaf survived controller; fixture explicitly killed it')
                self.assertTrue((state/'resource-guard.txt').exists())
                self.assertIsNone(sentinel.poll())

    def test_partial_du_producer_failure_stops_owned_app(self):
        for mode in ('partial_du','incomplete_du'):
            with self.subTest(mode=mode):
                process,state=self.run_fixture(mode)
                self.assertTrue((state/'resource-guard.txt').exists(),
                                'failed or incomplete du producer was accepted')
                self.assertNotIn('CONTROL_STOP=term_at_deadline',(state/'controller.txt').read_text())

    def test_explicit_absent_cache_counts_only_successful_runtime_root(self):
        process,state=self.run_fixture('absent_cache')
        self.assertIn('PANDANOTE_APP_EXIT=143',process.stdout)
        self.assertFalse((state/'resource-guard.txt').exists())
        self.assertIn('state=100',(state/'memory.txt').read_text())
        self.assertEqual((state/'monitor-cleanup.txt').read_text(),'MONITOR_CLEANUP=verified\n')

if __name__=='__main__': unittest.main()
