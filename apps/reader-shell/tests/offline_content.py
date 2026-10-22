"""Bounded monitoring inside disposable offline image, never on compiler host."""
import base64,os,re,subprocess,time
from pathlib import Path
if os.environ.get('PANDANOTE_OFFLINE_GUARD_TEST')!='1': raise SystemExit('missing offline gate marker')
command=['/usr/bin/qemu-mipsel','-cpu','P5600','-L','/sample-qt/sysroot','-strace',
 '-E','HOME=/tmp','-E','TMPDIR=/tmp','-E','LD_LIBRARY_PATH=/opt/image/opt/Qtopia/lib:/lib:/usr/lib',
 '/content-test/content.mipsel','/content-test/fixtures']
start=time.monotonic()
with open('/tmp/content-syscalls.txt','wb') as trace:
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=trace)
    try: stdout,_=process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill();process.communicate();raise SystemExit('FAIL content execution timeout')
trace=Path('/tmp/content-syscalls.txt').read_text(errors='replace')
print(stdout.decode('utf-8',errors='replace'),end='')
print('MONITOR duration_seconds=%.3f exit=%d network=none reader_execution=false'%(time.monotonic()-start,process.returncode))
if re.search(r'\b(socket|connect|mount|umount2|execve|reboot)\(',trace):
    print(trace[-12000:]);raise SystemExit('FAIL unexpected guest syscall')
print('PANDANOTE_TRACE_BASE64='+base64.b64encode(trace.encode()).decode())
if process.returncode:
    for line in trace.splitlines():
        if 'FAIL ' in line: print(line)
    raise SystemExit(process.returncode if process.returncode>0 else 1)
