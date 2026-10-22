"""Trusted own-code fixtures only; exact immutable nonroot isolated lab entry."""
import json,os,platform,resource,subprocess
from pathlib import Path
assert platform.system()=='Linux' and os.geteuid()==65534
os.umask(0o077);root=Path('/tmp/pandanote-connectivity/bluetooth');root.mkdir(parents=True,mode=0o700)
resource.setrlimit(resource.RLIMIT_FSIZE,(2*1024*1024,2*1024*1024));result={};children=[]
try:
 for label in ['runtime','ipc','service','delivery']:
  runtime=root/label;runtime.mkdir(mode=0o700)
  args=[] if label=='service' else [str(runtime)]
  with (root/(label+'.out')).open('wb') as out,(root/(label+'.trace')).open('wb') as trace:
   p=subprocess.Popen(['/usr/bin/qemu-mipsel','-strace','-L','/case/runtime','-E','LD_LIBRARY_PATH=/lib','/case/bin/'+label+'-cases.mipsel',*args],stdout=out,stderr=trace,env={'PATH':'/usr/bin:/bin','HOME':str(root)})
   children.append(p)
   try:rc=p.wait(timeout=10)
   except subprocess.TimeoutExpired:
    p.terminate()
    try:p.wait(timeout=1)
    except subprocess.TimeoutExpired:p.kill();p.wait(timeout=1)
    raise
  result[label]={'exit':rc,'stdout':(root/(label+'.out')).read_text(errors='replace'),'trace':(root/(label+'.trace')).read_text(errors='replace')}
finally:
 for p in children:
  if p.poll() is None:
   p.terminate()
   try:p.wait(timeout=1)
   except subprocess.TimeoutExpired:p.kill();p.wait(timeout=1)
 result['all_children_reaped']=all(p.poll() is not None for p in children)
 print(json.dumps(result,sort_keys=True),flush=True)
