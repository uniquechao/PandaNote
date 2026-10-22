"""Compile the actual evdev idle gate with controlled ioctl/read boundaries."""
import subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#define EV_SYN 0
#define EV_KEY 1
#define EV_ABS 3
#define SYN_DROPPED 3
#define KEY_MAX 767
#define KEY_F11 87
#define BTN_TOUCH 330
#define ABS_MAX 63
#define ABS_MT_SLOT 47
#define ABS_MT_POSITION_X 53
#define ABS_MT_POSITION_Y 54
#define ABS_MT_TRACKING_ID 57
#define EVIOCGKEY(n) (0x10000|(n))
#define EVIOCGBIT(e,n) (0x20000|((e)<<8)|(n))
#define EVIOCGABS(a) (0x30000|(a))
#define EVIOCGMTSLOTS(n) (0x40000|(n))
struct input_event{long seconds,micros;unsigned short type,code;int value;};
struct input_absinfo{int value,minimum,maximum,fuzz,flat,resolution;};
static const char*scenario;static int emitted,slot_reads,phase,flushed,final_getkey;
static int is(const char*s){return !strcmp(scenario,s);}
static void bit(unsigned long*b,unsigned n){b[n/(8*sizeof *b)]|=1UL<<(n%(8*sizeof *b));}
static int fixture_ioctl(int fd,unsigned long request,void*out){
 unsigned category=request&0xf0000;
 if(category==0x10000){
  if(phase){final_getkey++;if(is("after-allow-complete-tap"))flushed=1;if(is("final-getkey-unavailable")){errno=EINVAL;return -1;}}
  memset(out,0,request&0xffff);if(fd==101&&is("type-a-held"))bit(out,BTN_TOUCH);if(fd==100&&is("key-held"))bit(out,KEY_F11);return 0;}
 if(category==0x20000){unsigned event=(request>>8)&255;memset(out,0,request&255);
  if(event==EV_KEY){if(!is("missing-btn-cap"))bit(out,BTN_TOUCH);}
  else if(event==EV_ABS){if(!is("missing-x-cap"))bit(out,ABS_MT_POSITION_X);if(!is("missing-y-cap"))bit(out,ABS_MT_POSITION_Y);if(!is("missing-id-cap"))bit(out,ABS_MT_TRACKING_ID);if(!strncmp(scenario,"type-b",6))bit(out,ABS_MT_SLOT);}
  else{errno=EINVAL;return -1;}return 0;
 }
 if(category==0x30000){struct input_absinfo*a=out;memset(a,0,sizeof *a);a->maximum=is("type-b-third-held")?2:is("type-b-too-many")?99:1;return 0;}
 if(category==0x40000){slot_reads++;if(strncmp(scenario,"type-b",6)||is("type-b-io-error")){errno=EINVAL;return -1;}int32_t*slots=out;unsigned count=(request&0xffff)/sizeof *slots-1;for(unsigned i=1;i<=count;i++)slots[i]=-1;if(is("type-b-held"))slots[1]=5;if(is("type-b-third-held")&&count>=3)slots[3]=7;return 0;}
 errno=EINVAL;return -1;
}
static ssize_t fixture_read(int fd,void*out,size_t n){
 if(!phase){errno=EAGAIN;return -1;}
 /* Linux 4.4 EVIOCGKEY snapshots and flushes this client's queued EV_KEY.
  * Both edges arrived after the fresh-ready/allow handoff, on the same FD. */
 if(fd==100&&is("after-allow-complete-tap")&&!emitted&&!flushed){
  struct input_event events[2];memset(events,0,sizeof events);for(unsigned i=0;i<2;i++){events[i].type=EV_KEY;events[i].code=KEY_F11;events[i].value=i?0:1;}
  if(n<sizeof events)return -1;memcpy(out,events,sizeof events);emitted=1;return sizeof events;
 }
 if(fd==101&&!emitted&&(is("abs-activity")||is("key-activity")||is("syn-dropped"))){struct input_event e;memset(&e,0,sizeof e);e.type=is("abs-activity")?EV_ABS:is("key-activity")?EV_KEY:EV_SYN;e.code=is("syn-dropped")?SYN_DROPPED:is("abs-activity")?ABS_MT_POSITION_X:BTN_TOUCH;e.value=1;if(n<sizeof e)return -1;memcpy(out,&e,sizeof e);emitted=1;return sizeof e;}
 errno=EAGAIN;return -1;
}
#define ioctl fixture_ioctl
#define read fixture_read
@INPUT_IDLE@
int main(int argc,char**argv){if(argc!=2)return 90;scenario=argv[1];int fds[2]={100,101};int r=input_idle(fds,0);if(!r){phase=1;r=input_idle(fds,1);}printf("idle=%d slot_reads=%d final_getkey=%d\n",r,slot_reads,final_getkey);return r?22:0;}
'''
class SuspendInputTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  source=(ROOT/'suspend_helper.c').read_text();start=source.index('static int input_idle(int fds[2],int final){unsigned long keys[');end=source.index('\n#endif',start)
  cls.binary=ROOT/'build/suspend-input.fixture';p=ROOT/'build/suspend-input.fixture.c';p.write_text(HARNESS.replace('@INPUT_IDLE@',source[start:end]))
  r=subprocess.run(['cc','-std=c99',str(p),'-o',str(cls.binary)],capture_output=True,text=True)
  if r.returncode:raise AssertionError(r.stderr)
 def check(self,scenario,expected):
  r=subprocess.run([str(self.binary),scenario],capture_output=True,text=True);self.assertEqual(r.returncode,expected,scenario+': '+r.stdout+r.stderr)
 def test_type_a_without_slots_accepts_released_BTN_TOUCH(self):self.check('type-a-idle',0)
 def test_type_a_held_touch_or_power_key_refuses(self):
  for scenario in ('type-a-held','key-held'):
   with self.subTest(scenario=scenario):self.check(scenario,22)
 def test_missing_explicit_type_a_capability_refuses(self):
  for scenario in ('missing-btn-cap','missing-x-cap','missing-y-cap','missing-id-cap'):
   with self.subTest(scenario=scenario):self.check(scenario,22)
 def test_type_b_all_slots_must_be_idle_and_query_must_succeed(self):
  for scenario,expected in [('type-b-idle',0),('type-b-held',22),('type-b-io-error',22),('type-b-third-held',22),('type-b-too-many',22)]:
   with self.subTest(scenario=scenario):self.check(scenario,expected)
 def test_after_allow_complete_power_tap_is_never_flushed_by_state_snapshot(self):
  self.check('after-allow-complete-tap',22)
 def test_final_drain_never_calls_snapshot_ioctl_after_fresh_ready(self):
  r=subprocess.run([str(self.binary),'final-getkey-unavailable'],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertIn('final_getkey=0',r.stdout)
 def test_type_a_final_drain_rejects_new_touch_key_or_dropped_events(self):
  for scenario in ('abs-activity','key-activity','syn-dropped'):
   with self.subTest(scenario=scenario):self.check(scenario,22)
if __name__=='__main__':unittest.main(verbosity=2)
