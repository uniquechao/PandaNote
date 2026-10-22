"""Actual helper RTC ownership/cause policy; only physical I/O is controlled."""
import unittest
import test_suspend as fixture
class SuspendRTCTests(unittest.TestCase):
 setUpClass=classmethod(fixture.SuspendHelperTests.setUpClass.__func__)
 setUp=fixture.SuspendHelperTests.setUp
 put=fixture.SuspendHelperTests.put
 proc=fixture.SuspendHelperTests.proc
 request=fixture.SuspendHelperTests.request
 claim=fixture.SuspendHelperTests.claim
 helper=fixture.SuspendHelperTests.helper
 def mem(self):
  self.request();self.assertEqual(self.claim().returncode,0)
  return self.helper('mem',self.generation,self.token,'202',self.release)
 def timer(self):
  self.put('/.fixture/rtc.irq','416\n');self.put('/.fixture/rtc.after','1700001800\n');self.put('/.fixture/rtc.elapsed','1800000\n')
 def test_alarm_uses_rtc_epoch_not_os_time_and_cleans_owned_alarm(self):
  self.assertEqual(self.mem().returncode,0)
  self.assertEqual((self.root/'.fixture/rtc.alarm').read_text(),'0 0 1700001800\n')
  self.assertEqual((self.root/'.fixture/rtc.trace').read_text().splitlines(),['arm 1700001800','disable 1700001800'])
  self.assertFalse((self.run/'suspend.rtc').exists())
 def test_foreign_enabled_alarm_is_untouched_and_mem_never_written(self):
  self.put('/.fixture/rtc.alarm','1 0 1700000100\n');self.assertEqual(self.mem().returncode,22)
  self.assertEqual((self.root/'.fixture/rtc.alarm').read_text(),'1 0 1700000100\n');self.assertFalse((self.root/'.fixture/rtc.trace').exists())
  self.assertEqual((self.root/'sys/power/state').read_text(),'freeze mem\n')
 def test_timer_requires_alarm_irq_rtc_target_and_full_boottime_interval(self):
  self.timer();self.assertEqual(self.mem().returncode,24)
  self.assertEqual((self.root/'.fixture/rtc.alarm').read_text(),'0 0 1700001800\n')
 def test_unknown_pending_or_early_irq_never_becomes_timer(self):
  for irq,now,elapsed in [('0','1700001800','999999999'),('416','1700001799','1800000'),('416','1700001800','1798999'),('144','1700001800','1800000'),('448','1700001800','1800000')]:
   with self.subTest(irq=irq,now=now,elapsed=elapsed):
    self.setUp();self.put('/.fixture/rtc.irq',irq+'\n');self.put('/.fixture/rtc.after',now+'\n');self.put('/.fixture/rtc.elapsed',elapsed+'\n');self.assertEqual(self.mem().returncode,0)
 def test_key_or_touch_activity_dominates_matching_timer(self):
  self.timer();self.put('/.fixture/rtc.post-input','1\n');self.assertEqual(self.mem().returncode,0)
 def test_changed_alarm_after_resume_is_never_disabled(self):
  self.timer();self.put('/.fixture/rtc.external','1 0 1700001900\n');self.assertEqual(self.mem().returncode,23)
  self.assertEqual((self.root/'.fixture/rtc.alarm').read_text(),'1 0 1700001900\n');self.assertEqual((self.root/'.fixture/rtc.trace').read_text().splitlines(),['arm 1700001800'])
 def test_set_readback_mismatch_rejects_mem_and_preserves_foreign_value(self):
  self.put('/.fixture/rtc.set-mismatch','1\n');self.assertEqual(self.mem().returncode,23)
  self.assertEqual((self.root/'sys/power/state').read_text(),'freeze mem\n');self.assertNotIn('disable',(self.root/'.fixture/rtc.trace').read_text())
 def test_mem_error_still_disables_only_owned_alarm(self):
  self.put('/.fixture/fail_mem','1\n');self.assertEqual(self.mem().returncode,23)
  self.assertEqual((self.root/'.fixture/rtc.alarm').read_text(),'0 0 1700001800\n');self.assertFalse((self.run/'suspend.rtc').exists())
 def test_foreign_owner_marker_prevents_alarm_write(self):
  self.put('/run/pandanote-normal/suspend.rtc','rtc-owner-v2 100-10000 204-1 1700001800\n');self.assertEqual(self.mem().returncode,22)
  self.assertEqual((self.run/'suspend.rtc').read_text(),'rtc-owner-v2 100-10000 204-1 1700001800\n');self.assertFalse((self.root/'.fixture/rtc.trace').exists())
 def test_cleanup_failure_never_publishes_timer_success(self):
  self.timer();self.put('/.fixture/rtc.fail-cleanup','1\n');self.assertEqual(self.mem().returncode,23)
 def test_rtc_second_quantization_allows_1799000_only_with_full_alarm_evidence(self):
  self.timer();self.put('/.fixture/rtc.elapsed','1799000\n');self.assertEqual(self.mem().returncode,24)
 def test_unsupported_rtc_never_advertises_v2_ready(self):
  self.put('/sys/class/rtc/rtc0/name','foreign-rtc\n');self.assertNotEqual(self.helper('setup',self.generation).returncode,0);self.assertFalse((self.run/'suspend.ready').exists())
 def test_legacy_request_is_rejected_before_claim(self):
  self.put('/run/pandanote-normal/suspend.request','suspend-v1 '+self.generation+' '+self.token+'\n');self.assertEqual(self.claim().returncode,12);self.assertFalse((self.run/'suspend.active').exists())
