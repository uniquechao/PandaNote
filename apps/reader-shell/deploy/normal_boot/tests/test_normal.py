"""Owned normal-policy behavior and actual generated package checks; no vendor execution."""
import hashlib
import importlib.util
import json
import os
import signal
import time
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
class NormalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'build');self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)
  self.manifest=json.loads((ROOT/'build/candidate/manifest.json').read_text())
  self.system=ROOT/'build/candidate/files/etc/pandanote-system'/self.manifest['boot_id']
  (self.p/'sys/kernel').mkdir(parents=True)
  (self.p/'sys/kernel/modprobe').write_text('/sbin/modprobe\n');(self.p/'sys/kernel/hotplug').write_text('/sbin/mdev\n')
 def shell(self,code,input=None):
  source='. "$1/policy.sh"\nbb(){ [ "$1" != stat ] || return 127; "$@"; }\nN_PROC=$2;N_SYS=$2;N_DEV=$2\n'
  return subprocess.run(['/bin/sh','-c',source+code,'fixture',str(self.system),str(self.p)],capture_output=True,text=True,input=input)
 def test_helpers_cleared_and_verified(self):
  self.assertNotEqual(self.shell('normal_helpers_empty').returncode,0)
  self.assertEqual(self.shell('normal_helpers_off && normal_helpers_empty').returncode,0)
  self.assertEqual((self.p/'sys/kernel/modprobe').read_text().strip(),'')
  (self.p/'sys/kernel/hotplug').unlink();self.assertNotEqual(self.shell('normal_helpers_off').returncode,0)
 def test_proc_style_zero_size_stream_with_module_content_is_rejected(self):
  (self.p/'modules').symlink_to('/dev/stdin')
  self.assertEqual(self.shell('normal_modules_empty',input='').returncode,0)
  self.assertNotEqual(self.shell('normal_modules_empty',input='stock_touch 1 0 - Live 0x0\n').returncode,0)
 def test_rescue_stops_and_reaps_owned_app_before_keeping_adbd(self):
  source=(self.system/'service.sh').read_text().split('normal_usb(){',1)[0]
  source=source.replace('/run/pandanote-normal/rescue.reason',str(self.p/'reason'))
  script=source+"""
bb(){ "$@"; }
/bin/sleep 60 & DEV_PID_app=$!
normal_stop(){ [ "$1" = app ] || exit 88; kill "$DEV_PID_app";wait "$DEV_PID_app";DEV_PID_app=;printf reaped > "$1/reaped"; }
""".replace('"$1/reaped"',"'"+str(self.p/'reaped')+"'")+"\nnormal_rescue runtime-context-failed\n"
  unrelated=subprocess.Popen(['/bin/sleep','60'])
  child=subprocess.Popen(['/bin/sh','-c',script],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  try:
   for _ in range(100):
    if (self.p/'reaped').exists() and (self.p/'reason').exists() and (self.p/'reason').stat().st_size:break
    time.sleep(0.01)
   self.assertTrue((self.p/'reaped').exists());self.assertIsNone(child.poll());self.assertIsNone(unrelated.poll())
   self.assertIn('runtime-context-failed',(self.p/'reason').read_text())
  finally:
   os.killpg(child.pid,signal.SIGKILL);child.wait();unrelated.terminate();unrelated.wait()
 def test_module_read_error_is_failure_even_when_output_is_empty(self):
  (self.p/'modules').write_text('')
  source=(ROOT/'policy.in').read_text()
  function=re.search(r'normal_modules_empty\(\)\{.*?^}',source,re.S|re.M)[0]
  result=subprocess.run(['/bin/sh','-c',function+'\nbb(){ return 1; }\nN_PROC=$1\nnormal_modules_empty','fixture',str(self.p)],capture_output=True)
  self.assertNotEqual(result.returncode,0)
 def test_exact_boot_entry_and_root_no_duplicate_override(self):
  good='console=ttyS2,115200 init=/linuxrc root=/dev/mmcblk0p2 rootwait ro\n'
  for text,okay in ((good,True),(good+'rw',False),(good+'root=/dev/mmcblk0p3',False),(good+'init=/linuxrc',False),(good.replace('init=/linuxrc','init=/tmp/pid1'),False)):
   (self.p/'cmdline').write_text(text);self.assertEqual(self.shell('normal_bootargs').returncode==0,okay,text)
 def test_normal_ro_allows_journal_replay_without_fake_noload_claim(self):
  base='/dev/root / ext4 ro,relatime 0 0\ntmpfs /tmp tmpfs rw,nosuid,nodev 0 0\ntmpfs /run tmpfs rw,nosuid,nodev 0 0\n'
  (self.p/'mounts').write_text(base);(self.p/'swaps').write_text('Filename Type Size Used Priority\n')
  self.assertEqual(self.shell('normal_mounts pre').returncode,0)
  (self.p/'mounts').write_text(base+'/dev/mmcblk0p9 /wrong ext4 rw 0 0\n');self.assertNotEqual(self.shell('normal_mounts pre').returncode,0)
  post=base+'/dev/mmcblk0p3 /home ext4 rw,nosuid,nodev 0 0\n/dev/mmcblk0p9 /user ext4 rw,nosuid,nodev 0 0\n/dev/mmcblk0p5 /run/pandanote-opt ext4 ro,noload 0 0\n'
  (self.p/'mounts').write_text(post);self.assertEqual(self.shell('normal_mounts post').returncode,0)
  for bad in (post.replace('p9 /user','p8 /user'),post.replace('/user ext4 rw,','/user ext4 ro,'),post.replace('/run/pandanote-opt ext4 ro,noload','/run/pandanote-opt ext4 ro')):
   (self.p/'mounts').write_text(bad);self.assertNotEqual(self.shell('normal_mounts post').returncode,0)
 def test_early_helper_disable_precedes_sysfs_and_all_driver_loading(self):
  early=(self.system/'early.sh').read_text()
  self.assertLess(early.index('> /proc/sys/kernel/modprobe'),early.index('mount -t sysfs'))
  self.assertLess(early.index('> /proc/sys/kernel/hotplug'),early.index('mount -t sysfs'))
  self.assertNotIn('insmod',early)
  hardware=(self.system/'hardware.sh').read_text()
  body=hardware.split('normal_hardware(){',1)[1]
  self.assertLess(body.index('normal_runtime_ok'),body.index('bb insmod'))
  self.assertLess(body.index('[ ! -d /sys/module/focaltech_touch ]'),body.index('bb insmod "$release/hardware/'))
  trace=self.p/'hardware.trace';sysfs=str(self.p/'fake-sys')
  dither=Path(sysfs)/'devices/platform/jz-spi1.1/spi_master/spi1/spi1.0/eink_dither'
  dither.parent.mkdir(parents=True);dither.write_text('0\n')
  # Source the actual generated functions. Only external boundaries are fake;
  # no modules, sysfs writes or real device files are accessed.
  source=hardware.replace('/sys/',sysfs+'/')
  stubs="""
trace(){ printf '%s\\n' "$*" >> "$TRACE"; }
normal_runtime_ok(){ trace runtime; return "$GUARD_RC"; }
normal_modules_empty(){ trace modules; return 0; }
normal_helpers_empty(){ trace helpers; return 0; }
normal_power_hardware(){ trace power; return 0; }
bb(){
 case "$1" in
  insmod) trace "insmod:$2";;
  sha256sum) trace factory;;
  printf) shift; printf "$@";;
  cat) case "$2" in
   */eink_dither) cat "$2";;
   */virtual_size) printf '800,960\\n';; */bits_per_pixel) printf '16\\n';;
   */stride) printf '1600\\n';; */graphics/fb0/name) printf 'spi_fb\\n';;
   */input/event0/device/name) printf 'fts_ts\\n';; *) trace unexpected-cat;return 99;;
  esac;;
  *) trace unexpected-command;return 99;;
 esac
}
"""
  for guard_rc in (1,0):
   if trace.exists():trace.unlink()
   result=subprocess.run(['/bin/sh','-c',source+stubs+'\nnormal_hardware\n'],capture_output=True,text=True,env=dict(os.environ,TRACE=str(trace),GUARD_RC=str(guard_rc),release=str(self.p/'fake-release')))
   calls=trace.read_text().splitlines()
   if guard_rc:
    self.assertNotEqual(result.returncode,0,result.stderr);self.assertEqual(calls,['runtime'])
   else:
    self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(calls[-1],'power');self.assertEqual(calls.count('power'),1)
    self.assertEqual(calls[:3],['runtime','modules','factory']);self.assertEqual(sum(c.startswith('insmod:') for c in calls),7 if self.manifest.get('adc_module_sha256') else 6)

 def test_inittab_no_factory_actions_and_all_shells_parse(self):
  entry=(ROOT/'build/candidate/files/etc/inittab').read_text()
  commands=[l for l in entry.splitlines() if l and not l.startswith('#')]
  self.assertEqual(len(commands),3)
  self.assertNotRegex('\n'.join(commands),r'rcS|rcK|mount -a|swapon|factory')
  for f in self.system.glob('*.sh'):
   r=subprocess.run(['/bin/sh','-n',str(f)],capture_output=True);self.assertEqual(r.returncode,0,(f,r.stderr))
 def test_exact_release_and_system_indexes_match_all_generated_bytes(self):
  for index in [self.system/'SHA256SUMS',ROOT/'build/candidate/files/user/pandanote/apps/releases'/self.manifest['native_sha256']/'release.sha256']:
   for line in index.read_text().splitlines():
    digest,name=line.split();self.assertEqual(hashlib.sha256((index.parent/name).read_bytes()).hexdigest(),digest)
 def test_native_fallback_not_future_current_is_pinned_in_old_boot(self):
  text=(self.system/'service.sh').read_text()
  self.assertIn('release_id='+self.manifest['native_sha256'],text)
  self.assertIn('[ "$current" != "$release_id" ] || release_id=$current',text)
  self.assertIn('--workspace-dir /user/pandanote',text);self.assertNotIn('--developer-timeout',text)
 def test_usb_rescue_before_persistent_mount_and_app_owned_supervision(self):
  text=(self.system/'service.sh').read_text();main=text.split('main(){',1)[1]
  self.assertLess(main.index('normal_usb ||'),main.index('normal_mount_persistent ||'))
  self.assertIn('normal_spawn app',main);self.assertIn('normal_child_running app',main);self.assertIn('normal_stop app',main)
 def test_wifi_opt_in_and_absent_restore_are_explicit_normal_init(self):
  native=self.manifest['native_sha256']
  radio=(ROOT/'build/candidate/files/user/pandanote/apps/releases'/native/'radio/radio-normal-init.sh').read_text()
  self.assertIn('normal_wifi_store && radio_prepare_volatile_runtime && normal_wifi_pointer',radio)
  self.assertIn('saved_network_absent) exit 0',radio)
  self.assertLess(radio.index('radio_initialize_wifi || exit 1'),radio.index("action=wifi-restore"))
  self.assertIn('restore_status=$?',radio)
  policy=(self.system/'policy.sh').read_text()
  self.assertIn("schema=1\\nstore=/user/pandanote/config/wifi\\n",policy)
  self.assertIn('[ "$1:$3" = drwx------:0 ]',policy)
  self.assertNotIn('chmod 0700 "$path"',policy)
 def test_wifi_absent_exit_one_is_not_radio_boot_failure(self):
  native=self.manifest['native_sha256']
  radio=(ROOT/'build/candidate/files/user/pandanote/apps/releases'/native/'radio/radio-normal-init.sh').read_text()
  tail=radio.split('radio_initialize_wifi || exit 1',1)[1]
  tail=tail.replace('/tmp/pandanote-connectivity/pandanote-radio.mipsel','fixture_helper').replace('/run/pandanote-normal/wifi-restore.status',str(self.p/'restore.status'))
  for code,helper_rc,okay in [('saved_network_absent',1,True),('association_requested',0,True),('persistence_uncertain',1,False)]:
   helper='fixture_helper(){ cat >/dev/null;printf "code='+code+'\\n";return '+str(helper_rc)+'; }\n'
   result=subprocess.run(['/bin/sh','-c',helper+tail],capture_output=True)
   self.assertEqual(result.returncode==0,okay,(code,result.stderr))
 def test_generated_applets_exist_in_actual_historical_busybox(self):
  history=(Path(__import__('os').environ.get('PANDANOTE_REFERENCE_ROOT', 'external-inputs')) / 'pandanote-analysis/app-development-research/ram-linux-research/busybox-list-stdout.txt')
  names=set(re.findall(r'write\(2,0x[0-9a-f]+,\d+\)([^\s]+) = \d+',history.read_text()))
  required=set()
  for path in self.system.glob('*.sh'):required.update(re.findall(r'\bbb ([a-z][a-z0-9_-]*)',path.read_text()))
  self.assertFalse(required-names,required-names);self.assertNotIn('stat',required)
if __name__=='__main__':unittest.main(verbosity=2)
