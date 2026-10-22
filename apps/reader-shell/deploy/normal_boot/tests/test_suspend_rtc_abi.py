"""Compile actual calendar and RTC IRQ reader; fake only the physical read syscall."""
import subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class RTCPrimitiveTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory(dir=ROOT/'build');cls.root=Path(cls.tmp.name)
  source=(ROOT/'suspend_helper.c').read_text();calendar=source[source.index('static int leap('):source.index('static int rtc_device(',source.index('static int leap('))]
  irq_start=source.index('static int rtc_irq(',source.index('static int leap('));irq=source[irq_start:source.index('static void rtc_after_mem(',irq_start)]
  prefix=r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
#include <sys/types.h>
struct rtc_time {int tm_sec,tm_min,tm_hour,tm_mday,tm_mon,tm_year,tm_wday,tm_yday,tm_isdst;};
struct rtc_owner {int fd;};
static int mode,calls;
static ssize_t physical_read(int fd,void*p,size_t n){
 (void)fd;++calls;if(mode==1){errno=EINTR;return -1;}if(mode==2)return n-1;
 if(mode==3||calls==1){unsigned long word=416;if(n!=sizeof word){errno=EINVAL;return -1;}memcpy(p,&word,n);return n;}
 errno=EAGAIN;return -1;
}
#define read physical_read
'''
  main=r'''
int main(int argc,char**argv){
 if(argc<3)return 90;
 if(!strcmp(argv[1],"epoch")){if(argc!=8)return 90;struct rtc_time t;memset(&t,0,sizeof t);t.tm_year=atoi(argv[2])-1900;t.tm_mon=atoi(argv[3])-1;t.tm_mday=atoi(argv[4]);t.tm_hour=atoi(argv[5]);t.tm_min=atoi(argv[6]);t.tm_sec=atoi(argv[7]);int64_t epoch=-1;int r=rtc_epoch(&t,&epoch);printf("%d %lld\n",r,(long long)epoch);return 0;}
 if(!strcmp(argv[1],"calendar")){struct rtc_time t;int r=rtc_calendar(strtoll(argv[2],NULL,10),&t);if(r)printf("%d\n",r);else printf("0 %04d-%02d-%02dT%02d:%02d:%02d\n",t.tm_year+1900,t.tm_mon+1,t.tm_mday,t.tm_hour,t.tm_min,t.tm_sec);return 0;}
 if(!strcmp(argv[1],"irq")){struct rtc_owner c={1};unsigned long flags;mode=atoi(argv[2]);int r=rtc_irq(&c,&flags);printf("%d %lu %d\n",r,flags,calls);return 0;}
 return 90;
}
'''
  path=cls.root/'rtc.c';path.write_text(prefix+calendar+irq+main);cls.binary=cls.root/'rtc'
  r=subprocess.run(['cc','-std=c99','-Wall','-Wextra','-Werror',str(path),'-o',str(cls.binary)],capture_output=True,text=True)
  if r.returncode:raise AssertionError(r.stderr)
 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()
 def run_rtc(self,*args):
  r=subprocess.run([str(self.binary),*map(str,args)],capture_output=True,text=True,timeout=2);self.assertEqual(r.returncode,0,r.stderr);return r.stdout.strip()
 def test_calendar_uses_utc_arithmetic_across_month_and_leap_boundaries(self):
  for fields,epoch in [((1970,1,1,0,0,0),0),((2000,2,29,0,0,0),951782400),((2023,11,14,22,13,20),1700000000),((2038,1,19,3,14,8),2147483648),((2099,12,31,23,59,59),4102444799)]:
   with self.subTest(fields=fields):self.assertEqual(self.run_rtc('epoch',*fields),'0 '+str(epoch));self.assertEqual(self.run_rtc('calendar',epoch),'0 %04d-%02d-%02dT%02d:%02d:%02d'%fields)
  self.assertEqual(self.run_rtc('calendar',1709251500),'0 2024-03-01T00:05:00')
 def test_invalid_calendar_and_supported_range_fail_closed(self):
  for fields in [(2023,2,29,0,0,0),(2024,2,30,0,0,0),(2026,0,1,0,0,0),(2026,1,1,24,0,0),(2026,1,1,0,0,60),(2100,1,1,0,0,0)]:
   with self.subTest(fields=fields):self.assertEqual(self.run_rtc('epoch',*fields),'-1 -1')
  self.assertEqual(self.run_rtc('calendar',-1),'-1');self.assertEqual(self.run_rtc('calendar',4102444800),'-1');self.assertEqual(self.run_rtc('calendar',4294967296),'-1')
 def test_irq_read_preserves_full_native_word_and_drains_to_eagain(self):
  self.assertEqual(self.run_rtc('irq',0),'0 416 2')
 def test_irq_partial_read_and_unbounded_event_or_eintr_stream_fail_closed(self):
  self.assertEqual(self.run_rtc('irq',1),'-1 0 8');self.assertEqual(self.run_rtc('irq',2),'-1 0 1');self.assertEqual(self.run_rtc('irq',3),'-1 416 8')
