import pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class PowerServiceTests(unittest.TestCase):
 def invoke(self,request,stop_ok=True,linked=False):
  source=(ROOT/'service.in').read_text();start=source.index('normal_poweroff(){');end=source.index('\nnormal_release(){',start);function=source[start:end]
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp);marker=root/'poweroff.request'
   if linked:
    (root/'real').write_text(request);marker.symlink_to(root/'real')
   else:marker.write_text(request)
   policy=(ROOT.parent/'writable_boot/policy.sh').read_text();begin=policy.index('dev_log() {');finish=policy.index('\ndev_child_identity()',begin)
   log_function=policy[begin:finish].replace('dev_log','normal_log').replace('dev_private_file','normal_private_file')
   script="""bb(){ op="$1";shift;case "$op" in cat) cat "$@";;wc) wc "$@";;mv) mv "$@";;printf) printf "$@";;sync|poweroff) echo "ACTION:$op";;*) return 1;;esac; }
normal_private_file(){ [ -f "$1" ] && [ ! -L "$1" ]; }
normal_stop(){ echo "STOP:$1"; return STOP_CODE; }
"""
   script=script.replace('STOP_CODE','0' if stop_ok else '1')+log_function+function+'\nDEV_RUN='+str(root)+'\nnormal_poweroff; result=$?; [ ! -f "$DEV_RUN/status.log" ] || sed "s/^/LOG:/" "$DEV_RUN/status.log"; exit $result\n'
   return subprocess.run(['/bin/sh','-c',script],capture_output=True,text=True)
 def test_valid_request_reaps_app_before_sync_and_pid1_poweroff(self):
  r=self.invoke('poweroff-v1\n');self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.splitlines(),['STOP:app','ACTION:sync','ACTION:poweroff','LOG:application-stopped'])
 def test_failed_owned_stop_never_requests_poweroff(self):
  r=self.invoke('poweroff-v1\n',False);self.assertNotEqual(r.returncode,0);self.assertNotIn('ACTION:',r.stdout)
 def test_invalid_request_and_symlink_never_stop_or_poweroff(self):
  for value,linked in [('reboot\n',False),('poweroff-v1\n',True)]:
   r=self.invoke(value,linked=linked);self.assertNotEqual(r.returncode,0);self.assertNotIn('STOP:',r.stdout);self.assertNotIn('ACTION:',r.stdout)
