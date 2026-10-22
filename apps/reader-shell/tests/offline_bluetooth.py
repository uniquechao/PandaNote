"""Disposable-only navigation + actual stock Qt frames; input is SIMULATED."""
import base64,os,re,resource,subprocess,time
from pathlib import Path
if os.environ.get('PANDANOTE_OFFLINE_GUARD_TEST')!='1': raise SystemExit('missing offline gate marker')
# Our own local Unix fixture is not BlueZ/radio/hardware.
import socket,threading,struct
fixture_root=Path('/tmp/bt-fixture');fixture_root.mkdir(mode=0o700)
fixture_errors=[];fixture_stop=threading.Event();fixture_sockets=[]
def answer(flags=0,accepted=True,nonce=None,kind=0,control=0,event=0,size=0,remaining=None):
 b=bytearray(48);b[:4]=b'OBT1';b[4]=0 if accepted else 1;b[5]=flags;b[6]=5 if flags&6 else 0;b[7]=control
 struct.pack_into('<I',b,8,42 if flags else 0);b[12:28]=nonce if nonce is not None else (b'a'*16 if flags else bytes(16));struct.pack_into('<I',b,28,remaining if remaining is not None else (25000 if flags&1 else 100000 if flags&4 else 0));b[32:38]=bytes.fromhex('aabbccddeeff') if flags else bytes(6);b[38]=kind;struct.pack_into('<I',b,40,size);struct.pack_into('<H',b,44,event);return b
class Fixture:
 def __init__(self,name):self.name=name;self.expiry_delivered=False;self.phase=0;self.acked=False;self.window=0;self.event=258;self.effect_index=0;self.failed_ack=False;self.nonce=b'a'*16
 def respond(self,r):
  if len(r)!=24 or r[:4]!=b'OBT1' or r[7]:raise RuntimeError('bad fixture request')
  op=r[4]
  with open(fixture_root/(self.name+'.ops'),'ab') as f:f.write((str(op)+':'+str(r[5]|r[6]<<8)+'\n').encode())
  if self.name=='late':time.sleep(.65);return answer()
  if self.name=='eof':return answer()
  if self.name=='oversize':return answer()+b'x'
  if self.name=='short':return answer()[:20]
  if self.name=='zero':return answer(6,remaining=0)
  if self.name=='flags':b=answer();b[5]=128;return b
  if self.name=='wrong':return answer(6,nonce=b'b'*16)
  if self.name=='rejected':return answer(1,False,nonce=b'b'*16)
  if op==1:self.window+=1;self.phase=1;self.event=258;self.effect_index=0;self.failed_ack=False;self.nonce=bytes([self.window])*16 if self.name in ('ui','draft','timeout') else b'a'*16;return answer()
  if op==4:self.phase=0;return answer()
  if op==3:
   if r[8:24]!=self.nonce:return answer(1,False,nonce=self.nonce)
   if not r[6]:self.phase=0;return answer(0,False)
   if not r[5] or r[5]&~5:return answer(1,False,nonce=self.nonce)
   self.phase=2;return answer(6,nonce=self.nonce)
  if op==2:
   if self.name=='expired-deferred' and self.phase==2 and self.expiry_delivered:time.sleep(.03);return answer(6,nonce=self.nonce,remaining=1)
   return answer(1,nonce=self.nonce,remaining=30 if self.name=='timeout' else 25000) if self.phase==1 else answer(6,nonce=self.nonce) if self.phase==2 else answer()
  if op==5:
   if self.phase!=2:return answer()
   event=r[5]|r[6]<<8
   if event:
    if event==self.event and r[8:24]==self.nonce:
     if self.name in ('ui','draft') and event==19 and not self.failed_ack:self.failed_ack=True;return answer(6,False,nonce=self.nonce)
     self.acked=True
     if self.name in ('ui','draft'):self.effect_index+=1;self.event=[7,19,83,0][min(self.effect_index,3)]
    return answer(6,nonce=self.nonce)
   if self.name.startswith('expired-'):
    if self.name=='expired-deferred':self.expiry_delivered=True;return answer(6,nonce=self.nonce,kind=1,control=1,event=self.event)
    time.sleep(.03)
    return answer(6,nonce=self.nonce,kind=5 if self.name=='expired-file' else 1,control=0 if self.name=='expired-file' else 2 if self.name=='expired-refresh' else 1,event=self.event,size=123 if self.name=='expired-file' else 0,remaining=0 if self.name=='expired-zero' else 1)
   if self.name in ('ui','draft'):
    return answer(6,nonce=self.nonce,kind=1,control=self.effect_index+1,event=self.event) if self.effect_index<2 else answer(6,nonce=self.nonce,kind=5,event=self.event,size=123) if self.effect_index==2 else answer(6,nonce=self.nonce)
   return answer(6,nonce=self.nonce,kind=1,control=1,event=self.event) if not self.acked else answer(6,nonce=self.nonce)
  raise RuntimeError('unknown fixture operation')
def serve(sock,state):
 while not fixture_stop.is_set():
  try:conn,_=sock.accept()
  except socket.timeout:continue
  except OSError:break
  try:
   conn.settimeout(.8);request=b''
   while len(request)<24:
    part=conn.recv(24-len(request))
    if not part:break
    request+=part
   if len(request)<24:continue # Legitimate client cancellation; real C3 quietly closes it.
   result=state.respond(request)
   # Actual stream fixture exercises fragmented replies, then EOF.
   conn.sendall(result[:9]);time.sleep(.001);conn.sendall(result[9:]);
   if state.name=='eof':time.sleep(.65)
  except (BrokenPipeError,ConnectionResetError):pass
  except Exception as e:fixture_errors.append(str(e))
  finally:conn.close()
(fixture_root/'late-ready').mkdir(mode=0o700)
for name in ['delayed','core','oversize','short','late','wrong','rejected','flags','mode','eof','ui','draft','timeout','zero','expired-home','expired-refresh','expired-file','expired-zero','expired-deferred']:
 sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);path=str(fixture_root/('late-ready/core.sock' if name=='delayed' else name+'.sock'));sock.bind(path);os.chmod(path,0o666 if name=='mode' else 0o600);sock.listen(4);sock.settimeout(.1);fixture_sockets.append(sock);threading.Thread(target=serve,args=(sock,Fixture(name)),daemon=True).start()
os.symlink('core.sock',fixture_root/'link.sock');(fixture_root/'public').mkdir(mode=0o755)
base=['/usr/bin/qemu-mipsel','-cpu','P5600','-L','/sample-qt/sysroot','-strace',
 '-E','QWS_NO_SHARE_FONTS=1','-E','HOME=/tmp','-E','TMPDIR=/tmp','-E','LD_LIBRARY_PATH=/opt/image/opt/Qtopia/lib:/lib:/usr/lib']
# Synthetic FIFO is the enabled guest LinuxInput source, never host hardware.
input_fifo='/tmp/pandanote-qws-input'
os.mkfifo(input_fifo,0o600)
input_keepalive=os.open(input_fifo,os.O_RDWR|os.O_NONBLOCK)
Path('/tmp/pandanote-qws-pointercal').write_text('65536 0 0 0 65536 0 65536\n')
commands=[base+['/content-test/content.mipsel'],base+[
 '-E','PANDANOTE_BT_GUI_FIXTURE=1','-E','LD_PRELOAD=/test-harness/libpandanote-fakefb.so','-E','QT_QWS_FONTDIR=/content-test/assets',
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
        status=1
fixture_stop.set()
for sock in fixture_sockets:sock.close()
if fixture_errors:raise SystemExit("FAIL own Unix fixture: "+str(fixture_errors))
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
