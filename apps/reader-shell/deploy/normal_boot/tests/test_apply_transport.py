"""Fake ADB only. No daemon/socket/USB access."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('apply_transport',ROOT/'apply_transport.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Fake:
 def __init__(self):self.files={};self.commands=[];self.badpid=False;self.badstage=False;self.called=False
 def target(self):pass
 def shell(self,cmd,timeout=15):
  self.commands.append(cmd)
  if '/proc/mounts' in cmd:
   return (('0'*64 if self.badpid else m.PID1)+'  /tmp/pid1\n'+m.CMDLINE+'  /proc/cmdline\n/dev/root / ext4 ro,noload 0 0\n/dev/mmcblk0p3 /home ext4 rw,nosuid,nodev 0 0\n/dev/mmcblk0p9 /user ext4 rw,nosuid,nodev 0 0\n/dev/mmcblk0p5 /run/pandanote-opt ext4 ro,noload 0 0\n')
  if cmd.startswith('/bin/busybox sha256sum '):
   out=[]
   for name in cmd.split()[2:]:out.append(('0'*64 if self.badstage else m.SHA(self.files[name]))+'  '+name)
   return '\n'.join(out)+'\n'
  if '/apply.mipsel ' in cmd and not cmd.startswith('/bin/busybox '):self.called=True;return 'phase=committed-root-ro\nresult=committed root_rw=0\n'
  return ''
 def push(self,p,target):self.files[target]=p.read_bytes()
class ApplyTransportTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(dir=ROOT/'build');self.addCleanup(self.temp.cleanup);self.p=Path(self.temp.name)
  self.wire=b'captured ordinary files';self.tool=b'owned reviewed binary'
  self.report=dict(bundle_sha256=m.SHA(self.wire),tool_sha256=m.SHA(self.tool));self.adb=Fake()
 def runfake(self):return m.execute(self.adb,self.wire,self.tool,self.report,'fixture',self.p/'audit.jsonl')
 def test_exact_capture_stage_then_execute_and_postcheck(self):
  result=self.runfake();self.assertTrue(self.adb.called);self.assertFalse(result['boot_performed'])
  lines=[json.loads(s)['event'] for s in (self.p/'audit.jsonl').read_text().splitlines()]
  self.assertEqual(lines[-1],'postcheck-root-ro')
  self.assertEqual((self.p/'audit.jsonl').stat().st_mode&0o777,0o600)
  self.assertFalse(any('mount ' in c or 'dd ' in c for c in self.adb.commands))
 def test_wrong_current_ram_identity_no_staging(self):
  self.adb.badpid=True
  with self.assertRaises(ValueError):self.runfake()
  self.assertFalse(self.adb.files);self.assertFalse(self.adb.called)
 def test_staged_short_or_changed_bytes_never_executed(self):
  self.adb.badstage=True
  with self.assertRaises(ValueError):self.runfake()
  self.assertFalse(self.adb.called)
 def test_audit_attempt_never_reused(self):
  self.runfake()
  with self.assertRaises(FileExistsError):self.runfake()
 def test_mutated_plan_bytes_refused_before_audit_or_adb(self):
  self.wire+=b'changed'
  with self.assertRaises(ValueError):self.runfake()
  self.assertFalse(self.adb.commands);self.assertFalse((self.p/'audit.jsonl').exists())
if __name__=='__main__':unittest.main(verbosity=2)
