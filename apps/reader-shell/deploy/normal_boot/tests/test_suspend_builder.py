"""Offline helper/native capability closure. No compiler container or target calls."""
import hashlib,importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('suspend_candidate_builder',ROOT/'build.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
class SuspendBuilderTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'build');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.tool=self.root/'tool';self.tool.mkdir();self.elf=b'controlled own fixture; never executed';(self.tool/'pandanote-normal-suspend.mipsel').write_bytes(self.elf)
  self.meta=dict(application='pandanote-normal-suspend',execution_performed=False,artifact_sha256=b.sha(self.elf),artifact_bytes=len(self.elf),source_sha256={},startup_sha256={},stock_runtime_sha256={'libc.so.6':'0'*64,'ld-linux-mipsn8.so.1':'1'*64})
  for n in ('suspend_helper.c','suspend.in','build_suspend.py'):self.meta['source_sha256'][n]=b.sha((ROOT/n).read_bytes())
  for n in ('sha256.c','sha256.h'):self.meta['source_sha256'][n]=b.sha((ROOT.parents[1]/'third_party/sha256'/n).read_bytes())
  for n in ('start.S','entry.h','csu.cpp','libio-init.c'):self.meta['startup_sha256'][n]=b.sha((ROOT.parents[1]/'build-support'/n).read_bytes())
 def save(self):
  raw=b.canon(self.meta);(self.tool/'manifest.json').write_bytes(raw);return b.sha(raw)
 def test_exact_helper_manifest_source_startup_and_binary_capture(self):
  pin=self.save();raw,elf=b.suspend_capture(self.tool,pin);self.assertEqual(b.sha(raw),pin);self.assertEqual(elf,self.elf)
 def test_wrong_manifest_pin_artifact_and_missing_source_closure_rejected(self):
  pin=self.save()
  with self.assertRaises(ValueError):b.suspend_capture(self.tool,'f'*64)
  (self.tool/'pandanote-normal-suspend.mipsel').write_bytes(b'changed')
  with self.assertRaises(ValueError):b.suspend_capture(self.tool,pin)
  (self.tool/'pandanote-normal-suspend.mipsel').write_bytes(self.elf);self.meta['source_sha256'].pop('suspend.in');pin=self.save()
  with self.assertRaises(ValueError):b.suspend_capture(self.tool,pin)
 def test_source_and_startup_tampering_rejected_even_when_manifest_hash_updated(self):
  self.meta['source_sha256']['suspend_helper.c']='f'*64
  with self.assertRaises(ValueError):b.suspend_capture(self.tool,self.save())
  self.meta['source_sha256']['suspend_helper.c']=b.sha((ROOT/'suspend_helper.c').read_bytes());self.meta['startup_sha256']['entry.h']='f'*64
  with self.assertRaises(ValueError):b.suspend_capture(self.tool,self.save())
 def test_native_without_suspend_capability_rejected_before_any_output(self):
  native=self.root/'native';native.mkdir();source=self.root/'source';source.mkdir();sources={}
  for n in ('powerkeys.h','powerkeys.cpp','powerkeys_posix.cpp','powerrequest.h','powerrequest.cpp'):
   raw=('controlled fixture '+n).encode();(source/n).write_bytes(raw);sources[n]=b.sha(raw)
  raw=b.canon(dict(sources=sources,artifacts=[],capabilities=['normal-suspend-v1']));(native/'manifest.json').write_bytes(raw)
  with self.assertRaisesRegex(ValueError,'normal-suspend-v2'):
   b.build(native,b.sha(raw),self.root/'missing-reference',self.root/'missing-radio',self.root/'output',source)
  self.assertFalse((self.root/'output').exists())
if __name__=='__main__':unittest.main(verbosity=2)
