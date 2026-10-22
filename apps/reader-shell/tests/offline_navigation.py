"""Disposable-only navigation + actual stock Qt frames; input is SIMULATED."""
import base64,os,re,resource,subprocess,time
from pathlib import Path
if os.environ.get('PANDANOTE_OFFLINE_GUARD_TEST')!='1': raise SystemExit('missing offline gate marker')
base=['/usr/bin/qemu-mipsel','-cpu','P5600','-L','/sample-qt/sysroot','-strace',
 '-E','QWS_NO_SHARE_FONTS=1','-E','HOME=/tmp','-E','TMPDIR=/tmp','-E','LD_LIBRARY_PATH=/opt/image/opt/Qtopia/lib:/lib:/usr/lib']
# Synthetic FIFO is the enabled guest LinuxInput source, never host hardware.
input_fifo='/tmp/pandanote-qws-input'
os.mkfifo(input_fifo,0o600)
input_keepalive=os.open(input_fifo,os.O_RDWR|os.O_NONBLOCK)
Path('/tmp/pandanote-qws-pointercal').write_text('65536 0 0 0 65536 0 65536\n')
commands=[base+['/content-test/content.mipsel'],base+[
 '-E','LD_PRELOAD=/test-harness/libpandanote-fakefb.so','-E','QT_QWS_FONTDIR=/content-test/assets',
 '-E','QWS_DISPLAY=LinuxFb:nographicsmodeswitch:0','-E','QWS_KEYBOARD=none','-E','QWS_MOUSE_PROTO=LinuxInput:/dev/../tmp/pandanote-qws-input',
 '-E','POINTERCAL_FILE=/tmp/pandanote-qws-pointercal',
 '/content-test/shell.mipsel']]
traces=[];status=0;start=time.monotonic()
for i,command in enumerate(commands):
    with open('/tmp/trace-%d.txt'%i,'wb') as output:
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=output)
        try: stdout,_=process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill();process.communicate();raise SystemExit('FAIL navigation execution timeout')
    trace=Path('/tmp/trace-%d.txt'%i).read_text(errors='replace');traces.append(trace)
    print(stdout.decode(errors='replace'),end='')
    # QWS uses AF_LOCAL sockets inside the isolated tmpfs; internet families forbidden.
    if re.search(r'\b(mount|umount2|execve|reboot)\(|socket\((?:PF_|AF_)?INET',trace):
        print(trace[-12000:]);raise SystemExit('FAIL unexpected guest syscall')
    if process.returncode:
        for line in trace.splitlines():
            if 'FAIL ' in line: print(line)
        status=1;break
os.close(input_keepalive)
qsf_files=list(Path('/tmp').rglob('*.qsf'))
qpf_records=sum(trace.count('QFontEngineQPF getFontFileName') for trace in traces)
print('FONT_CACHE QWS_NO_SHARE_FONTS=1 qsf_files=%d qpf_records=%d'%(len(qsf_files),qpf_records))
if qsf_files or qpf_records: raise SystemExit('FAIL unexpected shared font cache')
for path in sorted(Path('/tmp').glob('*.png')):
    print('PANDANOTE_FRAME_BASE64='+path.stem+':'+base64.b64encode(path.read_bytes()).decode())
print('MONITOR duration_seconds=%.3f max_host_qemu_rss_kib=%d network=none hardware_access=false input=SIMULATED'%(time.monotonic()-start,resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss))
print('PANDANOTE_TRACE_BASE64='+base64.b64encode('\n'.join(traces).encode()).decode())
raise SystemExit(status)
