import importlib.util
import pathlib
import unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('lab_proof', ROOT/'lab/proof.py')
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)

class LabProofTests(unittest.TestCase):
 def good(self):
  return {'production_exit':3,'production_stdout':'C2 precondition failed\n',
          'probe_exit':0,'probe':{'spawn':0,'child_exit':0,'cleanup':True,'reaped':True},
          'child_stdout':'5.87\n','production_trace':'1 geteuid() = 65534\n',
          'probe_trace':'1 execveat(4,"",0,0,4096) = 0\n',
          'forbidden_state':False,'oversize':False,'all_children_reaped':True}
 def test_real_child_version_required(self):
  self.assertEqual(proof.errors(self.good()),[])
  p=self.good();p['child_stdout']='';self.assertIn('actual pinned child version missing',proof.errors(p))
 def test_exec_failure_cannot_pass(self):
  p=self.good();p['probe']['spawn']=-1;p['probe']['child_exit']=126;p['probe_exit']=4
  self.assertIn('production core nested execution failed',proof.errors(p))
 def test_root_refusal_required(self):
  p=self.good();p['production_exit']=0
  self.assertIn('production UID precondition not demonstrated',proof.errors(p))
 def test_cleanup_and_trace_required(self):
  for key,value in [('all_children_reaped',False),('oversize',True),('forbidden_state',True),('probe_trace','')]:
   p=self.good();p[key]=value;self.assertTrue(proof.errors(p),key)
 def test_failed_child_reap_required(self):
  p=self.good();p['probe']['reaped']=False
  self.assertIn('owned nested child not reaped',proof.errors(p))
 def test_actual_retained_nested_exec_failure_stays_failure(self):
  import json
  data=json.loads((ROOT/'evidence/runtime-completion/offline-prerequisite-nofile64.result.json').read_text())
  self.assertFalse(data['nested_exec_proven'])
  self.assertIn('production core nested execution failed',proof.errors(data['result']))
  self.assertIn('errno=8 (Exec format error)',data['result']['child_stdout'])
  self.assertEqual(data['result']['probe'],{'spawn':-1,'child_exit':126,'cleanup':True,'reaped':True})
if __name__=='__main__':unittest.main()
