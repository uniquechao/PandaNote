"""Fail-closed prerequisite proof. Diagnostics never count as nested-exec success."""
def errors(p):
 if not isinstance(p,dict):return ['missing proof object']
 result=[]
 if p.get('production_exit')!=3 or p.get('production_stdout')!='C2 precondition failed\n':
  result.append('production UID precondition not demonstrated')
 probe=p.get('probe')
 if not isinstance(probe,dict):return result+['missing actual core probe result']
 if p.get('probe_exit')!=0 or probe.get('spawn')!=0 or probe.get('child_exit')!=0:
  result.append('production core nested execution failed')
 if '5.87' not in str(p.get('child_stdout','')).splitlines():result.append('actual pinned child version missing')
 if probe.get('cleanup') is not True or probe.get('reaped') is not True:
  result.append('owned nested child not reaped')
 if p.get('all_children_reaped') is not True:result.append('outer children not reaped')
 if p.get('oversize') is not False:result.append('missing or exceeded output bound')
 if p.get('forbidden_state') is not False:result.append('unexpected global Bluetooth state')
 for name in ['production_trace','probe_trace']:
  if not isinstance(p.get(name),str) or not p[name]:result.append('missing actual syscall trace: '+name)
 return result
