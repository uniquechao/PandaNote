import json,os,platform,resource,subprocess
from pathlib import Path
assert platform.system()=='Linux' and os.geteuid()==65534
os.umask(0o077);root=Path('/tmp/pandanote-c4-tests');root.mkdir(mode=0o700)
resource.setrlimit(resource.RLIMIT_FSIZE,(2*1024*1024,2*1024*1024))
with (root/'out').open('wb') as out,(root/'err').open('wb') as err:
 p=subprocess.Popen(['/case/cases'],stdout=out,stderr=err,env={'PATH':'/usr/bin:/bin'})
 try:rc=p.wait(timeout=18)
 except subprocess.TimeoutExpired:
  p.terminate()
  try:p.wait(timeout=1)
  except subprocess.TimeoutExpired:p.kill();p.wait(timeout=1)
  raise
result={'exit':rc,'reaped':p.poll() is not None,'stdout':(root/'out').read_text(),'stderr':(root/'err').read_text(),'native_architecture':platform.machine()}
print(json.dumps(result,sort_keys=True),flush=True)
if rc or not result['reaped'] or 'PASS C4 socket interleaving' not in result['stdout']:raise SystemExit(1)
