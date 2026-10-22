"""Actual standalone service against own-code synthetic BlueZ on private bus."""
import json,os,platform,resource,subprocess,time
from pathlib import Path
assert platform.system()=='Linux' and os.geteuid()==65534
os.umask(0o077);root=Path('/tmp/pandanote-connectivity/bluetooth');root.mkdir(parents=True,mode=0o700)
(root/'run').mkdir(mode=0o700);(root/'etc').mkdir(mode=0o700);(root/'inbox').mkdir(mode=0o700)
(root/'etc/private-bus.conf').write_text(Path('/case/private-bus.conf').read_text().replace('<policy user="root">','<policy user="65534">'))
resource.setrlimit(resource.RLIMIT_FSIZE,(2*1024*1024,2*1024*1024));result={};children=[];handles=[]
def start(name,args):
 out=(root/(name+'.out')).open('wb');trace=(root/(name+'.trace')).open('wb');handles.extend([out,trace])
 p=subprocess.Popen(['/usr/bin/qemu-mipsel','-strace','-L','/case/runtime','-E','LD_LIBRARY_PATH=/lib','/case/bin/'+args[0],*args[1:]],stdout=out,stderr=trace,env={'PATH':'/usr/bin:/bin','HOME':str(root)})
 children.append(p);return p
try:
 bus=start('private-bus',['dbus-daemon','--nofork','--nopidfile','--nosyslog','--config-file='+str(root/'etc/private-bus.conf')])
 deadline=time.monotonic()+3
 while not (root/'run/bus').exists():
  assert bus.poll() is None,'private bus exited'
  assert time.monotonic()<deadline,'bus readiness timeout'
  time.sleep(.01)
 (root/'run/bus').chmod(0o600)
 p=start('bus',['bus-cases.mipsel',str(root/'inbox')]);rc=p.wait(timeout=20)
 result['bus']={'exit':rc}
 assert bus.poll() is None,'bus died before owned cleanup'
finally:
 for p in reversed(children):
  if p.poll() is None:
   p.terminate()
   try:p.wait(timeout=1)
   except subprocess.TimeoutExpired:p.kill();p.wait(timeout=1)
 for f in handles:f.close()
 result['all_children_reaped']=all(p.poll() is not None for p in children)
 for name in ['private-bus','bus']:
  record=result.setdefault(name,{})
  record['stdout']=(root/(name+'.out')).read_text(errors='replace') if (root/(name+'.out')).exists() else ''
  record['trace']=(root/(name+'.trace')).read_text(errors='replace') if (root/(name+'.trace')).exists() else ''
 print(json.dumps(result,sort_keys=True),flush=True)
