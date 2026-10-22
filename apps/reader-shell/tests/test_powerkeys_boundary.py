"""Actual policy + POSIX boundary; controlled evdev clients model GETKEY's flush."""
import pathlib,subprocess,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
HEADER=r'''
#ifndef TEST_LINUX_INPUT_H
#define TEST_LINUX_INPUT_H
#include <sys/time.h>
#define EV_SYN 0
#define EV_KEY 1
#define EV_MAX 31
#define KEY_MAX 767
#define KEY_F11 87
#define SYN_DROPPED 3
#define EVIOCGKEY(n) (0x10000|(n))
#define EVIOCGBIT(e,n) (0x20000|((e)<<8)|(n))
#define EVIOCGNAME(n) (0x30000|(n))
#define EVIOCSCLOCKID 0x40000
struct input_event{struct timeval time;unsigned short type,code;int value;};
#endif
'''
PREFIX=r'''
#include "powerkeys.h"
#include <linux/input.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <limits>
#include <stddef.h>
#include <deque>
static const int original=100;
static std::deque<input_event> queue;
static const char*scenario;
static bool resetting=false,injected=false,deviceHeld=false,snapshotted=false,devicePrevious=false,deviceNext=false;
static int opens=0,closes=0,oldGetkey=0,oldReads=0,oldClosed=0,freshGetkey=0;
static bool is(const char*s){return !strcmp(scenario,s);}
static void putbit(unsigned long*b,unsigned n){b[n/(8*sizeof *b)]|=1UL<<(n%(8*sizeof *b));}
static void event(unsigned type,unsigned code,int value,int ms){input_event e;memset(&e,0,sizeof e);e.type=type;e.code=code;e.value=value;e.time.tv_sec=ms/1000;e.time.tv_usec=ms%1000*1000;queue.push_back(e);if(type==EV_KEY&&code==KEY_F11&&value!=2)deviceHeld=value!=0;if(type==EV_KEY&&code==104&&value!=2)devicePrevious=value!=0;if(type==EV_KEY&&code==109&&value!=2)deviceNext=value!=0;}
static void tap(){event(EV_KEY,KEY_F11,1,100);event(EV_KEY,KEY_F11,0,110);}
static void injectSnapshot(){
 if(injected)return;
 if(is("during-snapshot")||is("after-snapshot")){tap();injected=true;}
 else if(is("held-release")){event(EV_KEY,KEY_F11,0,110);injected=true;}
 else if(is("page-reset-release")){event(EV_KEY,109,0,110);injected=true;}
 else if(is("page-tap-during-snapshot")){event(EV_KEY,104,1,100);event(EV_KEY,104,0,110);injected=true;}
 else if(is("unrelated")){event(EV_KEY,116,1,100);event(EV_KEY,116,0,110);injected=true;}
 else if(is("overflow")){for(unsigned i=0;i<2049;i++)event(EV_KEY,KEY_F11,2,i);injected=true;}
 else if(is("dropped-after-snapshot")){event(EV_SYN,SYN_DROPPED,0,100);injected=true;}
 else if(is("invalid-key-value")){event(EV_KEY,KEY_F11,3,100);injected=true;}
}
static int fakeOpen(const char*p,int flags,...){
 int index=-1;char extra;if(sscanf(p,"/dev/input/event%d%c",&index,&extra)!=1||index!=3){errno=ENOENT;return -1;}
 if((flags&(O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC))!=(O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC)){errno=EINVAL;return -1;}
 if(!resetting)return original;
 if(is("snapshot-open-error")){errno=EIO;return -1;}return 200+opens++;
}
static int fakeStat(int fd,struct stat*s){
 memset(s,0,sizeof *s);s->st_mode=S_IFCHR|0600;s->st_rdev=67;s->st_dev=4;s->st_ino=19;
 if(resetting&&fd!=original&&is("foreign-identity"))s->st_ino=20;
 if(resetting&&fd==original&&snapshotted&&is("changed-old-identity"))s->st_ino=21;
 if(is("stat-error")&&resetting){errno=EIO;return -1;}return 0;
}
static int fakeIoctl(int fd,unsigned long op,const void*pointer){
 void*out=const_cast<void*>(pointer);
 if((op&0xf0000)==0x30000){memset(out,0,op&0xffff);strcpy((char*)out,resetting&&is("foreign-name")?"foreign":"md-gpio-keys");return 0;}
 if((op&0xf0000)==0x20000){unsigned e=(op>>8)&255;memset(out,0,op&255);if(resetting&&is("missing-f11"))return 0;if(e==0)putbit((unsigned long*)out,EV_KEY);else if(e==EV_KEY){putbit((unsigned long*)out,KEY_F11);putbit((unsigned long*)out,104);putbit((unsigned long*)out,109);}return 0;}
 if(op==EVIOCSCLOCKID){if(resetting&&is("clock-error")){errno=EINVAL;return -1;}return 0;}
 if((op&0xf0000)==0x10000){
  if(resetting){if(fd==original)oldGetkey++;else freshGetkey++;}
  if(resetting&&is("during-snapshot"))injectSnapshot();
  memset(out,0,op&0xffff);if(deviceHeld)putbit((unsigned long*)out,KEY_F11);if(devicePrevious)putbit((unsigned long*)out,104);if(deviceNext)putbit((unsigned long*)out,109);
  /* Only this independent client's EV_KEY queue may be flushed. */
  if(fd==original)queue.clear();
  if(resetting){snapshotted=true;if(!is("during-snapshot"))injectSnapshot();}
  if(resetting&&is("snapshot-error")){errno=EIO;return -1;}return 0;
 }
 errno=EINVAL;return -1;
}
static ssize_t fakeRead(int fd,void*out,size_t bytes){
 if(fd!=original){errno=EINVAL;return -1;}oldReads++;
 if(snapshotted&&is("read-error")){errno=EIO;return -1;}
 if(snapshotted&&is("partial-read"))return 1;
 if(queue.empty()){
  if(resetting&&!snapshotted&&!injected&&is("between-eagain-snapshot")){tap();injected=true;}
  errno=EAGAIN;return -1;
 }
 unsigned count=0;input_event*events=(input_event*)out;while(!queue.empty()&&(count+1)*sizeof(input_event)<=bytes){events[count++]=queue.front();queue.pop_front();}return count*sizeof(input_event);
}
static int fakeClose(int fd){if(fd==original)oldClosed++;else closes++;return 0;}
static int fakeClock(int,struct timespec*t){t->tv_sec=10;t->tv_nsec=0;return 0;}
#define open fakeOpen
#define fstat fakeStat
#define ioctl fakeIoctl
#define read fakeRead
#define close fakeClose
#define clock_gettime fakeClock
'''
MAIN=r'''
#undef open
#undef fstat
#undef ioctl
#undef read
#undef close
#undef clock_gettime
int main(int argc,char**argv){
 if(argc!=2)return 90;scenario=argv[1];if(is("page-held-open"))devicePrevious=true;PowerKeys keys;if(!keys.open())return 91;
 resetting=true;if(is("held-release"))deviceHeld=true;if(is("page-reset-release"))deviceNext=true;
 if(is("bool-wrapper")){bool held=true;bool ok=powerKeySnapshotHeld(original,&held);bool pass=ok&&!held&&oldGetkey==0&&freshGetkey==1&&opens==1&&closes==1;printf("%s bool-wrapper fresh_getkey=%d\n",pass?"PASS":"FAIL",freshGetkey);return pass?0:1;}
 bool ok=keys.resetAfterResume(),activity=keys.takeActivity();bool expectedFailure=is("overflow")||is("read-error")||is("partial-read")||is("foreign-identity")||is("changed-old-identity")||is("snapshot-open-error")||is("foreign-name")||is("missing-f11")||is("clock-error")||is("snapshot-error")||is("stat-error")||is("dropped-after-snapshot")||is("invalid-key-value");
 int failed=0;
 if(expectedFailure){if(ok||keys.available())failed=1;}
 else{
  bool expectedActivity=is("between-eagain-snapshot")||is("during-snapshot")||is("after-snapshot")||is("held-release");
  if(!ok||!keys.available()||activity!=expectedActivity||!queue.empty()||keys.poll()!=NoPowerAction)failed=1;
  if(is("page-held-open")){event(EV_KEY,104,1,200);event(EV_KEY,104,2,210);keys.poll();if(keys.takeListNavigation())failed=1;event(EV_KEY,104,0,220);event(EV_KEY,104,1,230);keys.poll();if(keys.takeListNavigation()!=-1||keys.takeListNavigation()||keys.takeActivity())failed=1;}
  if(is("page-reset-release")){event(EV_KEY,109,1,200);keys.poll();if(keys.takeListNavigation()!=1||keys.takeActivity())failed=1;}
  if(is("page-tap-during-snapshot")){if(keys.takeListNavigation())failed=1;event(EV_KEY,104,1,200);keys.poll();if(keys.takeListNavigation()!=-1||keys.takeActivity())failed=1;}
  if(is("after-final-drain")||is("held-release")){tap();if(keys.poll()!=ShortPowerPress||keys.poll()!=NoPowerAction)failed=1;}
 }
 if(oldGetkey||opens!=closes||(!expectedFailure&&opens!=1))failed=1;
 printf("%s reset=%d activity=%d old_getkey=%d fresh_open=%d fresh_close=%d old_reads=%d old_closed=%d\n",failed?"FAIL":"PASS",int(ok),int(activity),oldGetkey,opens,closes,oldReads,oldClosed);return failed;
}
'''
class PowerKeysBoundaryTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.out=ROOT/'build/powerkeys-boundary-host';(cls.out/'include/linux').mkdir(parents=True,exist_ok=True);(cls.out/'include/linux/input.h').write_text(HEADER)
  source=cls.out/'boundary.cpp';source.write_text(PREFIX+(ROOT/'powerkeys_posix.cpp').read_text()+MAIN);cls.binary=cls.out/'boundary'
  r=subprocess.run(['c++','-std=c++98','-Wall','-Wextra','-Werror','-I'+str(ROOT),'-I'+str(cls.out/'include'),str(ROOT/'powerkeys.cpp'),str(source),'-o',str(cls.binary)],capture_output=True,text=True)
  if r.returncode:raise AssertionError(r.stderr)
  symbols=subprocess.run(['nm','-u',str(cls.binary)],capture_output=True,text=True,check=True).stdout
  for forbidden in ('_ioctl','_open','_read','_close','_clock_gettime','_dup','_reboot'):
   if forbidden in symbols:raise AssertionError('fixture unexpectedly imports a real device syscall: '+forbidden)
 def check(self,scenario):
  r=subprocess.run([str(self.binary),scenario],capture_output=True,text=True,timeout=2);self.assertEqual(r.returncode,0,scenario+': '+r.stdout+r.stderr);return r.stdout
 def test_initial_eagain_to_snapshot_complete_tap_preserves_human_activity(self):self.check('between-eagain-snapshot')
 def test_complete_tap_during_or_after_snapshot_is_drained_without_action_replay(self):
  for s in ('during-snapshot','after-snapshot'):
   with self.subTest(s=s):self.check(s)
 def test_tap_after_final_drain_remains_for_next_poll(self):self.check('after-final-drain')
 def test_snapshot_held_then_drained_release_rearms_only_fresh_actions(self):self.check('held-release')
 def test_unrelated_key_is_not_human_power_activity(self):self.check('unrelated')
 def test_new_client_identity_full_driver_validation_and_close_on_failure(self):
  for s in ('foreign-identity','changed-old-identity','snapshot-open-error','foreign-name','missing-f11','clock-error','snapshot-error','stat-error'):
   with self.subTest(s=s):self.check(s)
 def test_post_snapshot_stream_overflow_dropped_invalid_or_read_error_fail_closed(self):
  for s in ('overflow','read-error','partial-read','dropped-after-snapshot','invalid-key-value'):
   with self.subTest(s=s):self.check(s)
 def test_page_baseline_and_raced_edges_preserve_no_power_activity(self):
  for s in ('page-held-open','page-reset-release','page-tap-during-snapshot'):
   with self.subTest(s=s):self.check(s)
 def test_legacy_bool_snapshot_wrapper_queries_fresh_client_only_once(self):self.check('bool-wrapper')
 def test_idle_snapshot_uses_fresh_open_and_never_old_getkey(self):self.check('idle')
