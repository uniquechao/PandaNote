"""Native own helper and shell policy fixtures. Never access hardware or signal host PIDs."""
import hashlib,os,shutil,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class SuspendHelperTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  (ROOT/'build').mkdir(exist_ok=True);cls.binary=ROOT/'build/suspend.fixture';sha=ROOT.parents[1]/'third_party/sha256'
  r=subprocess.run(['cc','-std=c99','-DPANDANOTE_SUSPEND_FIXTURE','-I'+str(sha),str(ROOT/'suspend_helper.c'),str(sha/'sha256.c'),'-o',str(cls.binary)],capture_output=True,text=True)
  if r.returncode:raise AssertionError(r.stderr)
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=ROOT/'build');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.run=self.root/'run/pandanote-normal';self.run.mkdir(parents=True);self.run.chmod(0o700);(self.root/'.fixture').mkdir()
  self.put('/sys/power/state','freeze mem\n');self.put('/sys/power/wakeup_count','7\n');self.put('/sys/devices/platform/md-gpio-keys/power/wakeup','enabled\n')
  for n in ('key_down','touch_down','input_activity','fail_mem','changed_wakeup'):self.put('/.fixture/'+n,'0\n')
  self.put('/sys/class/rtc/rtc0/name','10003000.rtc\n');self.put('/sys/devices/platform/apb/10003000.rtc/power/wakeup','enabled\n')
  for n,v in {'rtc.now':'1700000000\n','rtc.alarm':'0 0 0\n','rtc.irq':'0\n','rtc.after':'1700000001\n','rtc.elapsed':'1000\n','rtc.post-input':'0\n','rtc.set-mismatch':'0\n','rtc.fail-cleanup':'0\n'}.items():self.put('/.fixture/'+n,v)
  self.put('/.fixture/input.auto-allow','1\n')
  self.generation='100-10000';self.token='203-1';self.release='/user/pandanote/apps/releases/'+'a'*64
  self.proc(100,1,1,1,10000);self.proc(202,100,202,202,1202);self.proc(203,202,202,202,1203,self.release+'/reader-shell.mipsel')
 def put(self,name,data,mode=0o600):
  p=self.root/name.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data.encode() if isinstance(data,str) else data);p.chmod(mode);return p
 def proc(self,pid,ppid,pgid,sid,start,exe=None,cmd=None):
  fields=['S',str(ppid),str(pgid),str(sid)]+['0']*15+[str(start)];self.put('/proc/'+str(pid)+'/stat',str(pid)+' (owned) '+' '.join(fields)+'\n')
  if exe:
   p=self.root/'proc'/str(pid)/'exe';p.unlink(missing_ok=True);p.symlink_to(exe)
  if cmd:self.put('/proc/'+str(pid)+'/cmdline',b'\0'.join(x.encode() for x in cmd)+b'\0')
 def helper(self,*args):return subprocess.run([str(self.binary),*args],capture_output=True,text=True,env=dict(os.environ,PANDANOTE_SUSPEND_FIXTURE_ROOT=str(self.root),PANDANOTE_SUSPEND_FIXTURE_PARENT='100'))
 def request(self,gen=None,token=None):return self.put('/run/pandanote-normal/suspend.request','suspend-v2 '+(gen or self.generation)+' '+(token or self.token)+'\n')
 def claim(self):return self.helper('claim',self.generation,'202',self.release)
 def test_setup_and_canonical_request_claim_finish(self):
  r=self.helper('setup',self.generation);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((self.run/'suspend.ready').read_text(),'suspend-v2 '+self.generation+'\n')
  self.request();r=self.claim();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout,self.token+'\n');self.assertFalse((self.run/'suspend.request').exists());self.assertTrue((self.run/'suspend.active').exists())
  r=self.helper('finish',self.generation,self.token,'resumed');self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((self.run/'resume.status').read_text(),'resume-v2 '+self.generation+' '+self.token+' resumed\n');self.assertFalse((self.run/'suspend.active').exists())
 def test_duplicate_request_is_consumed_without_second_cycle(self):
  self.request();self.assertEqual(self.claim().returncode,0);self.assertEqual(self.helper('finish',self.generation,self.token,'resumed').returncode,0)
  self.request();self.assertEqual(self.claim().returncode,10);self.assertFalse((self.run/'suspend.request').exists());self.assertFalse((self.run/'suspend.active').exists())
 def test_symlink_hardlink_oversize_and_bad_grammar_never_claimed(self):
  for kind in ('symlink','hardlink','oversize','grammar'):
   with self.subTest(kind=kind):
    p=self.request();other=self.put('/outside','suspend-v2 '+self.generation+' '+self.token+'\n')
    if kind=='symlink':p.unlink();p.symlink_to(other)
    elif kind=='hardlink':p.unlink();os.link(other,p)
    elif kind=='oversize':p.write_bytes(b'x'*512)
    else:p.write_text('suspend-v2 '+self.generation+' '+self.token+' extra\n')
    self.assertNotEqual(self.claim().returncode,0);self.assertFalse((self.run/'suspend.active').exists());p.unlink();other.unlink()
 def test_wrong_generation_and_unowned_native_refuse_with_terminal(self):
  self.request(gen='100-9999');self.assertEqual(self.claim().returncode,10);self.assertIn('unsafe',(self.run/'resume.status').read_text())
  self.request();self.proc(203,999,202,202,1203,self.release+'/reader-shell.mipsel');self.assertEqual(self.claim().returncode,10);self.assertIn('unsafe',(self.run/'resume.status').read_text())
 def test_mem_requires_wakeup_release_no_activity_and_radio_absence(self):
  self.request();self.assertEqual(self.claim().returncode,0)
  self.assertEqual(self.helper('mem',self.generation,self.token,'202',self.release).returncode,0)
  for field in ('key_down','touch_down','input_activity','changed_wakeup'):
   self.setUp();self.request();self.assertEqual(self.claim().returncode,0);self.put('/.fixture/'+field,'1\n');self.assertNotEqual(self.helper('mem',self.generation,self.token,'202',self.release).returncode,0,field)
  self.put('/sys/devices/platform/md-gpio-keys/power/wakeup','disabled\n');self.assertNotEqual(self.helper('mem',self.generation,self.token,'202',self.release).returncode,0)
 def test_claim_never_overwrites_active_or_terminal_symlink(self):
  self.request();self.put('/run/pandanote-normal/suspend.active','prior\n');self.assertNotEqual(self.claim().returncode,0);self.assertTrue((self.run/'suspend.request').exists())
 def test_radio_ownership_capture_stop_checks_starttime_and_exact_argv(self):
  self.radio();self.assertEqual(self.helper('radio-capture').returncode,0)
  self.proc(301,1,301,301,99999,'/usr/sbin/wpa_supplicant',self.wpa);r=self.helper('radio-stop');self.assertNotEqual(r.returncode,0);self.assertFalse((self.root/'.fixture/signals').exists())
 def radio(self):
  self.wpa=['/usr/sbin/wpa_supplicant','-i','wlan0','-D','wext','-c','/tmp/pandanote-connectivity/wpa.conf'];self.dhcp=['/sbin/udhcpc','-f','-i','wlan0','-s','/tmp/pandanote-connectivity/dhcp.sh','-p','/tmp/pandanote-connectivity/dhcp.pid','-t','3','-T','3','-A','5']
  for pid,exe,args,h in [(301,'/usr/sbin/wpa_supplicant',self.wpa,'628778a588da366c5790c928c172fb56463ab60d65222641ac9ad6cc5377e385'),(302,'/bin/busybox',self.dhcp,'38081195a5342faafac704f96bec8fb5b4de7a706f74dab88e5c184374f9a593')]:
   self.proc(pid,1,pid,pid,pid+1000,exe,args);self.put('/.fixture/exe-sha.'+str(pid),h+'\n')
  self.put('/tmp/pandanote-connectivity/wpa.pid','301\n');self.put('/tmp/pandanote-connectivity/udhcpc.pid','302\n')
 def test_radio_stop_targets_only_two_verified_PIDs_and_cleanup_after_gone(self):
  self.radio();self.assertEqual(self.helper('radio-capture').returncode,0);self.assertEqual(self.helper('radio-stop').returncode,0);self.assertEqual((self.root/'.fixture/signals').read_text().splitlines(),['302','301']);self.assertEqual(self.helper('radio-clean').returncode,0)
  self.assertFalse((self.root/'tmp/pandanote-connectivity/wpa.pid').exists());self.assertFalse((self.root/'tmp/pandanote-connectivity/udhcpc.pid').exists())
 def test_radio_timeout_never_escalates_to_kill_and_records_only_owned_PIDs(self):
  self.radio();self.assertEqual(self.helper('radio-capture').returncode,0)
  self.put('/.fixture/ignore.301','1\n');self.put('/.fixture/ignore.302','1\n');r=self.helper('radio-stop');self.assertNotEqual(r.returncode,0)
  self.assertEqual((self.root/'.fixture/signals').read_text().splitlines(),['302','301']);self.assertEqual(self.helper('radio-state').returncode,0)
 def test_radio_wrong_argv_or_session_refuses_capture_before_signal(self):
  self.radio();self.proc(301,1,301,301,1301,'/usr/sbin/wpa_supplicant',self.wpa+['extra']);self.assertNotEqual(self.helper('radio-capture').returncode,0);self.assertFalse((self.root/'.fixture/signals').exists())
 def test_same_active_token_can_enter_mem_only_once_and_poweroff_preempts_it(self):
  self.request();self.assertEqual(self.claim().returncode,0)
  args=('mem',self.generation,self.token,'202',self.release);self.assertEqual(self.helper(*args).returncode,0);self.assertNotEqual(self.helper(*args).returncode,0)
  self.setUp();self.request();self.assertEqual(self.claim().returncode,0);self.put('/run/pandanote-normal/poweroff.request','poweroff-v1\n');self.assertNotEqual(self.helper('mem',self.generation,self.token,'202',self.release).returncode,0)
 def test_abort_claimed_request_emits_failed_terminal_without_mem(self):
  self.request();self.assertEqual(self.claim().returncode,0);self.assertEqual(self.helper('abort',self.generation).returncode,0);self.assertIn('failed',(self.run/'resume.status').read_text());self.assertFalse((self.run/'suspend.active').exists());self.assertFalse((self.run/'suspend.entered').exists())
 def test_mem_diagnostics_are_private_and_do_not_change_result(self):
  self.request();self.assertEqual(self.claim().returncode,0);self.assertEqual(self.helper('mem',self.generation,self.token,'202',self.release).returncode,0)
  p=self.run/'suspend.last';self.assertEqual(p.stat().st_mode&0o777,0o600);parts=p.read_text().split();self.assertEqual(parts[:4],['suspend-last-v1',self.generation,self.token,'resumed']);self.assertTrue(all(int(x.split('=')[1])>=0 for x in parts[4:]))
 def test_diagnostic_publish_failure_never_blocks_resume_result(self):
  outside=self.put('/outside-diag','untouched');(self.run/'suspend.last').symlink_to(outside);self.request();self.assertEqual(self.claim().returncode,0)
  self.assertEqual(self.helper('mem',self.generation,self.token,'202',self.release).returncode,0);self.assertEqual(outside.read_text(),'untouched')
 def test_generation_and_claim_work_from_nested_shell_without_parent_override(self):
  self.request();env=dict(os.environ,PANDANOTE_SUSPEND_FIXTURE_ROOT=str(self.root));env.pop('PANDANOTE_SUSPEND_FIXTURE_PARENT',None)
  script='generation=$("$1" generation 100) || exit 71; token=$("$1" claim "$generation" 202 "$2") || exit 72; printf "%s %s\\n" "$generation" "$token"'
  r=subprocess.run(['/bin/sh','-c',script,'fixture',str(self.binary),self.release],capture_output=True,text=True,env=env)
  self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout,self.generation+' '+self.token+'\n')

class SuspendPolicyTests(unittest.TestCase):
 setUpClass=classmethod(SuspendHelperTests.setUpClass.__func__)
 setUp=SuspendHelperTests.setUp
 put=SuspendHelperTests.put
 proc=SuspendHelperTests.proc
 request=SuspendHelperTests.request
 claim=SuspendHelperTests.claim
 helper=SuspendHelperTests.helper
 # Reuse only fixture construction; policy tests invoke actual shell functions.
 def policy(self,sleep_rc=0,wake_rc=0,extra='',call='normal_suspend_cycle'):
  trace=self.root/'trace';lock=self.root/'user/pandanote/state/normal-install.lock';lock.parent.mkdir(parents=True,exist_ok=True)
  source=(ROOT/'suspend.in').read_text()
  stubs=r'''
trace(){ printf '%s\n' "$*" >> "$TRACE"; }
normal_runtime_ok(){ return 0; }
normal_child_running(){ return 0; }
normal_private_file(){ [ -f "$1" ] && [ ! -L "$1" ]; }
normal_radio_sleep(){ trace radio-sleep;return SLEEP_RC; }
normal_radio_wake(){ trace radio-wake;return WAKE_RC; }
bb(){
 case "$1" in
  flock) python3 -c 'import fcntl;fcntl.flock(9,fcntl.LOCK_EX|fcntl.LOCK_NB)' ;;
  sync) trace sync;;
  *) "$@";;
 esac
}
'''.replace('SLEEP_RC',str(sleep_rc)).replace('WAKE_RC',str(wake_rc))
  env=dict(os.environ,PANDANOTE_SUSPEND_FIXTURE_ROOT=str(self.root),PANDANOTE_SUSPEND_FIXTURE_PARENT='100',TRACE=str(trace),DEV_RUN=str(self.run),DEV_PID_app='202',NORMAL_SUSPEND_HELPER=str(self.binary),NORMAL_SUSPEND_GENERATION=self.generation,NORMAL_SUSPEND_LOCK=str(lock),release=self.release)
  return subprocess.run(['/bin/sh','-c',source+stubs+'\n'+extra+'\n'+call+'\n'],capture_output=True,text=True,env=env)
 def test_policy_success_orders_radio_sync_mem_restore_and_terminal(self):
  self.request();r=self.policy();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((self.root/'trace').read_text().splitlines(),['radio-sleep','sync','radio-wake']);self.assertIn('resumed',(self.run/'resume.status').read_text())
 def test_policy_timer_result_is_published_only_after_radio_restored(self):
  self.put('/.fixture/rtc.irq','416\n');self.put('/.fixture/rtc.after','1700001800\n');self.put('/.fixture/rtc.elapsed','1800000\n')
  self.request();r=self.policy();self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((self.run/'resume.status').read_text(),'resume-v2 '+self.generation+' '+self.token+' timer\n')
  self.assertEqual((self.root/'trace').read_text().splitlines(),['radio-sleep','sync','radio-wake'])
 def test_policy_timer_radio_restore_failure_is_terminal_failed(self):
  self.put('/.fixture/rtc.irq','416\n');self.put('/.fixture/rtc.after','1700001800\n');self.put('/.fixture/rtc.elapsed','1800000\n')
  self.request();r=self.policy(wake_rc=1);self.assertEqual(r.returncode,0,r.stderr);self.assertIn(' failed\n',(self.run/'resume.status').read_text())
 def test_key_tap_during_radio_stop_forces_restore_and_skips_mem(self):
  self.request()
  extra='normal_radio_sleep(){ trace radio-sleep; (umask 077; printf "wake-v2 %s %s\n" "$NORMAL_SUSPEND_GENERATION" 203-1 > "$DEV_RUN/suspend.wake-203-1"); return 0; }'
  r=self.policy(extra=extra);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((self.root/'trace').read_text().splitlines(),['radio-sleep','sync','radio-wake']);self.assertIn(' unsafe\n',(self.run/'resume.status').read_text());self.assertFalse((self.root/'.fixture/rtc.trace').exists());self.assertFalse((self.run/'suspend.wake-203-1').exists())
 def test_policy_radio_sleep_failure_attempts_restore_and_never_mem(self):
  self.request();r=self.policy(sleep_rc=1);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((self.root/'trace').read_text().splitlines(),['radio-sleep','radio-wake']);self.assertIn('failed',(self.run/'resume.status').read_text());self.assertFalse((self.run/'suspend.entered').exists())
 def test_policy_poweroff_priority_does_not_sleep_or_stop_ui(self):
  self.request();self.put('/run/pandanote-normal/poweroff.request','poweroff-v1\n');r=self.policy();self.assertEqual(r.returncode,0,r.stderr);self.assertFalse((self.root/'trace').exists());self.assertIn('busy',(self.run/'resume.status').read_text())
 def test_policy_install_lock_busy_returns_terminal_without_radio_actions(self):
  import fcntl
  lock=self.root/'user/pandanote/state/normal-install.lock';lock.parent.mkdir(parents=True,exist_ok=True);lock.write_text('');lock.chmod(0o600)
  with lock.open('r+') as fd:
   fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);self.request();r=self.policy();self.assertEqual(r.returncode,0,r.stderr)
  self.assertFalse((self.root/'trace').exists());self.assertFalse((self.run/'resume.status').exists());self.assertTrue((self.run/'suspend.request').exists());self.assertFalse((self.run/'suspend.active').exists())

 def test_cancel_under_busy_lease_prevents_any_late_claim_or_mem(self):
  import fcntl
  lock=self.root/'user/pandanote/state/normal-install.lock';lock.parent.mkdir(parents=True);lock.write_text('');lock.chmod(0o600)
  self.request()
  with lock.open('r+') as fd:
   fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);r=self.policy();self.assertEqual(r.returncode,0,r.stderr)
   self.assertTrue((self.run/'suspend.request').exists());self.assertFalse((self.run/'suspend.active').exists())
   (self.run/'suspend.request').unlink();directory=os.open(self.run,os.O_RDONLY);os.fsync(directory);os.close(directory)
  r=self.policy();self.assertEqual(r.returncode,0,r.stderr);self.assertFalse((self.root/'trace').exists());self.assertFalse((self.run/'suspend.entered').exists())
 def test_cancelled_active_is_rechecked_before_any_radio_action(self):
  self.request();self.assertEqual(self.claim().returncode,0);(self.run/'suspend.active').unlink()
  r=self.policy(extra='NORMAL_SUSPEND_TOKEN='+self.token,call='normal_suspend_perform');self.assertEqual(r.returncode,0,r.stderr);self.assertFalse((self.root/'trace').exists());self.assertFalse((self.run/'suspend.entered').exists())
 def test_radio_restarted_child_has_no_lease_fd_but_service_retains_it(self):
  runtime=self.root/'runtime';runtime.mkdir();tool=runtime/'pandanote-radio.mipsel';tool.write_text('#!/bin/sh\ncat >/dev/null\nprintf "code=saved_network_absent\\n"\nexit 1\n');tool.chmod(0o700)
  child=self.root/'child-fd';lock=self.root/'lock';source=(ROOT/'suspend.in').read_text()
  script=r'''
helper(){ case "$1" in radio-state) return 10;;radio-clean|radio-capture) return 0;;*) return 99;;esac; }
radio_verify_inputs(){ return 0; }
radio_session_tools_ready(){ return 0; }
radio_load_wifi(){ return 0; }
radio_start_children(){
 python3 -c 'import os,pathlib
try: os.fstat(9); result="inherited"
except OSError: result="closed"
pathlib.Path(os.environ["CHILD_CHECK"]).write_text(result)' &
 wait "$!"
}
bb(){ "$@"; }
exec 9>> "$LOCK"
python3 -c 'import fcntl;fcntl.flock(9,fcntl.LOCK_EX|fcntl.LOCK_NB)' || exit 91
normal_radio_wake || exit 92
python3 -c 'import os;os.fstat(9)' || exit 93
exec 9>&-
'''
  r=subprocess.run(['/bin/sh','-c',source+script],capture_output=True,text=True,env=dict(os.environ,NORMAL_SUSPEND_HELPER='helper',RADIO_RUNTIME=str(runtime),DEV_RUN=str(self.run),CHILD_CHECK=str(child),LOCK=str(lock)))
  self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(child.read_text(),'closed')
 def test_cancelled_cached_finish_does_not_poison_following_request(self):
  self.request();self.assertEqual(self.claim().returncode,0)
  self.assertEqual(self.helper('mem',self.generation,self.token,'202',self.release).returncode,0)
  # Simulate terminal publication failure; UI cancellation has acquired the
  # same lease after the helper ended and removed only matching active.
  (self.run/'suspend.active').unlink();self.request(token='203-2')
  r=self.policy(extra='NORMAL_SUSPEND_TOKEN=203-1\nNORMAL_SUSPEND_RESULT=resumed')
  self.assertEqual(r.returncode,0,r.stderr);self.assertTrue((self.run/'resume.status').exists());self.assertEqual((self.run/'resume.status').read_text(),'resume-v2 '+self.generation+' 203-2 resumed\n');self.assertFalse((self.run/'suspend.entered').exists())

if __name__=='__main__':unittest.main(verbosity=2)
