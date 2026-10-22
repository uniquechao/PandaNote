"""Real stock MIPS getaddrinfo to a deterministic loopback DNS in network=none."""
import base64,os,pathlib,re,subprocess,socket,threading,struct
if os.environ.get('PANDANOTE_OFFLINE_GUARD_TEST')!='1':raise SystemExit('missing offline guard')
root=pathlib.Path('/tmp/dhcp-dns-private');root.mkdir(mode=0o700)
server=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);server.bind(('127.0.0.1',1053));server.settimeout(8);queries=[];errors=[]
def answer():
 try:
  packet,peer=server.recvfrom(512);at=12;labels=[]
  while packet[at]:
   size=packet[at];at+=1;labels.append(packet[at:at+size].decode('ascii'));at+=size
  at+=1;question=packet[12:at+4]
  if '.'.join(labels)!='dhcp-proof.example' or packet[at:at+4]!=b'\x00\x01\x00\x01':raise RuntimeError('unexpected query')
  queries.append('.'.join(labels))
  server.sendto(packet[:2]+b'\x81\x80'+b'\x00\x01\x00\x01\x00\x00\x00\x00'+question+b'\xc0\x0c\x00\x01\x00\x01'+struct.pack('!IH',60,4)+socket.inet_aton('203.0.113.41'),peer)
 except Exception as e:errors.append(str(e))
 finally:server.close()
thread=threading.Thread(target=answer);thread.start()
command=['/usr/bin/qemu-mipsel','-cpu','P5600','-L','/sample-qt/sysroot','-strace','-E','LD_LIBRARY_PATH=/opt/image/opt/Qtopia/lib:/lib:/usr/lib','/content-test/content.mipsel',str(root),'--query']
result=subprocess.run(command,capture_output=True,timeout=10);thread.join(timeout=9)
print(result.stdout.decode(),end='');trace=result.stderr.decode(errors='replace');print('PANDANOTE_TRACE_BASE64='+base64.b64encode(trace.encode()).decode())
if re.search(r'\b(mount|umount2|execve|reboot)\(',trace):raise SystemExit('unexpected guest syscall')
if result.returncode or errors or queries!=['dhcp-proof.example']:
 print(trace[-10000:]);raise SystemExit('DNS query failed: '+repr((result.returncode,errors,queries)))
print('PASS actual stock MIPS getaddrinfo DHCP DNS custom-loopback1053 network=none; /etc DNS192.0.2.250 unused')
