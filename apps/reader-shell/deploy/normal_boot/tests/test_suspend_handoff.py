"""Actual mem boundary waits for a fresh UI input drain while retaining input FDs."""
import os,subprocess,time,unittest
import test_suspend as fixture
class SuspendInputHandoffTests(unittest.TestCase):
 setUpClass=classmethod(fixture.SuspendHelperTests.setUpClass.__func__)
 setUp=fixture.SuspendHelperTests.setUp
 put=fixture.SuspendHelperTests.put
 proc=fixture.SuspendHelperTests.proc
 request=fixture.SuspendHelperTests.request
 claim=fixture.SuspendHelperTests.claim
 helper=fixture.SuspendHelperTests.helper
 def marker(self,kind,wire,token=None,generation=None):return self.put('/run/pandanote-normal/suspend.'+kind+'-'+(token or self.token),wire+' '+(generation or self.generation)+' '+(token or self.token)+'\n')
 def start(self):
  self.put('/.fixture/input.auto-allow','0\n');self.request();self.assertEqual(self.claim().returncode,0)
  p=subprocess.Popen([str(self.binary),'mem',self.generation,self.token,'202',self.release],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=dict(os.environ,PANDANOTE_SUSPEND_FIXTURE_ROOT=str(self.root),PANDANOTE_SUSPEND_FIXTURE_PARENT='100'))
  def close_child():
   if p.poll() is None:p.kill()
   p.communicate(timeout=1)
  self.addCleanup(close_child);return p
 def wait_ready(self,p):
  ready=self.run/('suspend.input-ready-'+self.token);deadline=time.monotonic()+1
  while time.monotonic()<deadline and not ready.exists() and p.poll() is None:time.sleep(.005)
  self.assertTrue(ready.exists(),'helper must publish ready with FDs open before mem');self.assertIsNone(p.poll());return ready
 def result(self,p):
  _,err=p.communicate(timeout=4);return p.returncode,err
 def test_mem_waits_for_fresh_ui_drain_ack_before_arming_rtc(self):
  p=self.start();self.wait_ready(p);self.assertFalse((self.root/'.fixture/rtc.trace').exists());self.assertEqual((self.root/'sys/power/state').read_text(),'freeze mem\n')
  self.marker('input-allow','input-allow-v2');self.assertEqual(self.result(p)[0],0)
  self.assertTrue((self.root/'sys/power/state').read_text().startswith('mem\n'))
 def test_early_complete_key_tap_wake_intent_refuses_before_radio_or_mem(self):
  self.request();self.assertEqual(self.claim().returncode,0);self.marker('wake','wake-v2')
  self.assertEqual(self.helper('check',self.generation,self.token,'202',self.release).returncode,12)
  self.assertEqual(self.helper('mem',self.generation,self.token,'202',self.release).returncode,22);self.assertFalse((self.root/'.fixture/rtc.trace').exists())
 def test_key_tap_observed_after_ready_but_before_ack_cannot_sleep(self):
  p=self.start();self.wait_ready(p);self.marker('wake','wake-v2');self.marker('input-allow','input-allow-v2');self.assertEqual(self.result(p)[0],22);self.assertFalse((self.root/'.fixture/rtc.trace').exists())
 def test_post_ready_fd_activity_refuses_even_with_ui_ack(self):
  p=self.start();self.wait_ready(p);self.put('/.fixture/input_activity','1\n');self.marker('input-allow','input-allow-v2');self.assertEqual(self.result(p)[0],22)
 def test_missing_ack_is_bounded_and_never_arms_alarm(self):
  before=time.monotonic();p=self.start();self.wait_ready(p);self.assertEqual(self.result(p)[0],22);elapsed=time.monotonic()-before;self.assertGreaterEqual(elapsed,2.8);self.assertLess(elapsed,4);self.assertFalse((self.root/'.fixture/rtc.trace').exists())
 def test_stale_allow_before_fresh_ready_is_rejected(self):
  self.marker('input-allow','input-allow-v2');p=self.start();self.assertEqual(self.result(p)[0],22);self.assertFalse((self.run/('suspend.input-ready-'+self.token)).exists())
 def test_wrong_generation_or_malformed_ack_never_grants_permission(self):
  for raw in ('input-allow-v2 100-9999 203-1\n','input-allow-v2 100-10000 203-1 extra\n'):
   with self.subTest(raw=raw):
    self.setUp();p=self.start();self.wait_ready(p);self.put('/run/pandanote-normal/suspend.input-allow-'+self.token,raw);self.assertEqual(self.result(p)[0],22)
 def test_finish_cleans_only_own_handshake_and_late_old_marker_is_pruned(self):
  self.request();self.assertEqual(self.claim().returncode,0);self.marker('wake','wake-v2');self.marker('input-ready','input-ready-v2');self.marker('input-allow','input-allow-v2');foreign=self.marker('wake','wake-v2',token='204-1')
  self.assertEqual(self.helper('finish',self.generation,self.token,'unsafe').returncode,0)
  for kind in ('wake','input-ready','input-allow'):self.assertFalse((self.run/('suspend.'+kind+'-'+self.token)).exists())
  self.assertTrue(foreign.exists());self.marker('wake','wake-v2');self.request(token='203-2');self.assertEqual(self.claim().returncode,0);self.assertFalse((self.run/('suspend.wake-'+self.token)).exists());self.assertTrue(foreign.exists())
