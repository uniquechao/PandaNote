"""Deterministic /proc lifetime races through the actual suspend helper.
Only libc reads on the private fixture filesystem are intercepted; no host
processes are signalled and production code contains no race-test hooks.
"""
import os,subprocess,unittest
from pathlib import Path
import test_suspend as base
ROOT=base.ROOT

RACE_C = r'''#define _GNU_SOURCE
#define _DARWIN_C_SOURCE
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdarg.h>
static int fired,stat_reads,delayed;
static int transition(const char *stage){
 const char *spec=getenv("PANDANOTE_RADIO_RACE"),*root=getenv("PANDANOTE_SUSPEND_FIXTURE_ROOT");
 if(!spec||fired||strncmp(spec,stage,strlen(stage))||spec[strlen(stage)]!=':')return 0;
 const char *action=spec+strlen(stage)+1;char name[4096];
 if(getenv("PANDANOTE_RADIO_AFTER_SIGNAL")){
  snprintf(name,sizeof name,"%s/.fixture/signals",root);FILE*log=fopen(name,"r");char lines[128]={0};if(!log)return 0;fread(lines,1,sizeof lines-1,log);fclose(log);if(!strstr(lines,"301\n"))return 0;
 }
 fired=1;
 snprintf(name,sizeof name,"%s/.fixture/race-fired",root);FILE*f=fopen(name,"w");if(!f)exit(91);fputs(spec,f);fclose(f);
 snprintf(name,sizeof name,"%s/proc/301/stat",root);
 if(!strcmp(action,"gone")){if(unlink(name))exit(92);}
 else if(!strcmp(action,"delayed-gone")){delayed=2;}
 else if(strcmp(action,"live-missing")){
  char state=!strcmp(action,"running")?'R':!strcmp(action,"stopped")?'T':!strncmp(action,"zombie",6)?'Z':'S';
  unsigned start=strstr(action,"reused")?9999:1301;
  f=fopen(name,"w");if(!f)exit(93);fprintf(f,"301 (owned) %c 1 301 301",state);for(int i=0;i<15;i++)fputs(" 0",f);fprintf(f," %u\n",start);fclose(f);
 }
 return !strcmp(action,"gone")||!strncmp(action,"zombie",6)||!strcmp(action,"live-missing")||!strcmp(action,"delayed-gone");
}
static int race_open(const char *p,int flags,...){
 mode_t mode=0;if(flags&O_CREAT){va_list ap;va_start(ap,flags);mode=(mode_t)va_arg(ap,int);va_end(ap);}
 if(strstr(p,"/proc/301/stat")){
  if(delayed&&!--delayed){if(unlink(p))exit(94);}
  if(++stat_reads==2)transition("final-stat");
 }
 if(strstr(p,"/.fixture/exe-sha.301")&&transition("hash")){errno=ENOENT;return -1;}
 if(strstr(p,"/proc/301/cmdline")&&transition("cmdline")){errno=ENOENT;return -1;}
 return open(p,flags,mode);
}
static ssize_t race_readlink(const char*p,char*b,size_t cap){
 if(strstr(p,"/proc/301/exe")&&transition("exe")){errno=ENOENT;return -1;}
 return readlink(p,b,cap);
}
static int race_unlink(const char*p){
 if(getenv("PANDANOTE_RADIO_AFTER_SIGNAL")&&strstr(p,"/proc/301/stat"))return 0;
 return unlink(p);
}
#define unlink race_unlink
#define open race_open
#define readlink race_readlink
#include "@SOURCE@"
'''

class SuspendRadioRaceTests(unittest.TestCase):
 setUp=base.SuspendHelperTests.setUp
 put=base.SuspendHelperTests.put
 proc=base.SuspendHelperTests.proc
 radio=base.SuspendHelperTests.radio
 helper=base.SuspendHelperTests.helper
 @classmethod
 def setUpClass(cls):
  cls.binary=ROOT/'build/suspend-races.fixture';source=ROOT/'build/suspend-races.fixture.c'
  source.write_text(RACE_C.replace('@SOURCE@',str(ROOT/'suspend_helper.c')))
  sha=ROOT.parents[1]/'third_party/sha256'
  r=subprocess.run(['cc','-std=c99','-DPANDANOTE_SUSPEND_FIXTURE','-I'+str(sha),str(source),str(sha/'sha256.c'),'-o',str(cls.binary)],capture_output=True,text=True)
  if r.returncode:raise AssertionError(r.stderr)
 def race(self,stage,action,command='radio-state',after_signal=False):
  result=subprocess.run([str(self.binary),command],capture_output=True,text=True,env=dict(os.environ,PANDANOTE_SUSPEND_FIXTURE_ROOT=str(self.root),PANDANOTE_SUSPEND_FIXTURE_PARENT='100',PANDANOTE_RADIO_RACE=stage+':'+action,**({'PANDANOTE_RADIO_AFTER_SIGNAL':'1'} if after_signal else {})))
  self.assertTrue((self.root/'.fixture/race-fired').exists(),result.stderr)
  return result
 def capture(self):
  self.radio();self.assertEqual(self.helper('radio-capture').returncode,0)
 def test_running_state_change_during_identity_read_is_not_foreign(self):
  self.capture();self.assertEqual(self.race('final-stat','running').returncode,0)
 def test_owned_exit_between_stat_and_exe_hash_or_cmdline_is_gone(self):
  for stage in ('exe','hash','cmdline','final-stat'):
   for action in ('gone','zombie'):
    with self.subTest(stage=stage,action=action):
     self.setUp();self.capture();self.assertEqual(self.race(stage,action).returncode,11)
 def test_metadata_can_disappear_before_stat_becomes_zombie_or_absent(self):
  self.capture();self.assertEqual(self.race('exe','delayed-gone').returncode,11)
 def test_stop_wait_poll_handles_exit_metadata_loss_after_actual_TERM(self):
  self.capture();self.assertEqual(self.race('exe','gone','radio-stop',after_signal=True).returncode,0)
  self.assertEqual((self.root/'.fixture/signals').read_text().splitlines(),['302','301'])
 def test_stop_completes_when_owned_process_exits_during_identity_read(self):
  self.capture();self.assertEqual(self.race('cmdline','gone','radio-stop').returncode,0)
  self.assertEqual((self.root/'.fixture/signals').read_text().splitlines(),['302'])
 def test_stop_is_success_when_both_captured_processes_already_exited(self):
  self.capture()
  for pid in (301,302):(self.root/('proc/'+str(pid)+'/stat')).unlink()
  self.assertEqual(self.helper('radio-stop').returncode,0);self.assertFalse((self.root/'.fixture/signals').exists())
 def test_missing_exe_hash_or_cmdline_on_live_identity_is_still_foreign(self):
  for stage in ('exe','hash','cmdline'):
   with self.subTest(stage=stage):
    self.setUp();self.capture();self.assertEqual(self.race(stage,'live-missing','radio-stop').returncode,12)
    self.assertFalse((self.root/'.fixture/signals').exists())
 def test_reused_or_stopped_process_during_read_is_refused_before_signals(self):
  for stage,action in [('final-stat','reused'),('final-stat','stopped'),('exe','zombie-reused'),('hash','zombie-reused'),('cmdline','zombie-reused')]:
   with self.subTest(stage=stage,action=action):
    self.setUp();self.capture();self.assertEqual(self.race(stage,action,'radio-stop').returncode,12)
    self.assertFalse((self.root/'.fixture/signals').exists())

if __name__=='__main__':unittest.main(verbosity=2)
