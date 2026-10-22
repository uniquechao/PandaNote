"""Only in inspected immutable nonroot/no-network/no-device disposable lab."""
import json,os,platform,resource,subprocess
from pathlib import Path
assert platform.system()=='Linux' and os.geteuid()==65534
ROOT=Path('/tmp/pandanote-connectivity/bluetooth')
os.umask(0o077)
ROOT.mkdir(mode=0o700,parents=True)
# Bound QEMU traces too; inherited by both target entries and nested children.
resource.setrlimit(resource.RLIMIT_FSIZE,(2*1024*1024,2*1024*1024))
result={'all_children_reaped':True,'oversize':False}
env={'PATH':'/usr/bin:/bin','HOME':str(ROOT)}
children=[]
try:
 for label,name,args in [('production','pandanote-bt-lifecycle.mipsel',['--private-daemon-lifecycle-capabilities']),('probe','exec-probe.mipsel',[])]:
  with (ROOT/(label+'.out')).open('wb') as out,(ROOT/(label+'.trace')).open('wb') as trace:
   p=subprocess.Popen(['/usr/bin/qemu-mipsel','-strace','-L','/case/runtime','-E','LD_LIBRARY_PATH=/lib','/case/bin/'+name,*args],stdout=out,stderr=trace,env=env)
   children.append(p)
   try:result[label+'_exit']=p.wait(timeout=12)
   except subprocess.TimeoutExpired:
    p.terminate()
    try:p.wait(timeout=1)
    except subprocess.TimeoutExpired:p.kill();p.wait(timeout=1)
    raise
  result[label+'_stdout']=(ROOT/(label+'.out')).read_text(errors='replace')
  result[label+'_trace']=(ROOT/(label+'.trace')).read_text(errors='replace')
 result['probe']=json.loads(result['probe_stdout'])
 result['child_stdout']=(ROOT/'probe-child.out').read_text(errors='replace') if (ROOT/'probe-child.out').exists() else ''
finally:
 for p in children:
  if p.poll() is None:
   p.terminate()
   try:p.wait(timeout=1)
   except subprocess.TimeoutExpired:p.kill();p.wait(timeout=1)
 result['all_children_reaped']=all(p.poll() is not None for p in children)
 result['oversize']=any(p.stat().st_size>=2*1024*1024 for p in ROOT.glob('*') if p.is_file())
 result['forbidden_state']=Path('/var/lib/bluetooth').exists() or Path('/var/run/sdp').exists()
 print(json.dumps(result,sort_keys=True),flush=True)
