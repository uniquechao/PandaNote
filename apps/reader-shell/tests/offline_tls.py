"""Real TLS handshakes through memory BIO, no guest/network/hardware socket."""
import base64,json,os,re,select,ssl,subprocess,time
from pathlib import Path
if os.environ.get('PANDANOTE_OFFLINE_GUARD_TEST')!='1':raise SystemExit('missing offline gate marker')
root=Path('/content-test/fixtures');domain=json.loads((root/'domain/profile.json').read_text());profile=json.loads((root/'profile.json').read_text());alltrace='';checks=0
cases=[
 ('valid-pin-ip-time','server.crt','127.0.0.1',profile['certificateSha256'],profile['bootstrapEpoch'],'ok'),
 ('wrong-pin','server.crt','127.0.0.1','0'*64,profile['bootstrapEpoch'],'fail'),
 ('wrong-ip','server.crt','127.0.0.2',profile['certificateSha256'],profile['bootstrapEpoch'],'fail'),
 ('untrusted-certificate','other.crt','127.0.0.1',profile['certificateSha256'],profile['bootstrapEpoch'],'fail'),
 ('expired-certificate','server.crt','127.0.0.1',profile['certificateSha256'],1893456000,'fail'),
 ('not-yet-valid','server.crt','127.0.0.1',profile['certificateSha256'],1577836800,'fail')]
for name,leaf,expected in [('domain-chain','leaf','ok'),('renewed-leaf-same-anchor','renew','ok'),('domain-wrong-san','wrong-san','fail'),('domain-cn-only','cn-only','fail')]:
 cases.append((name,'domain/root.crt',domain['host'],domain['certificateSha256'],domain['bootstrapEpoch'],expected))
cases += [('domain-wrong-anchor','domain/root.crt',domain['host'],'0'*64,domain['bootstrapEpoch'],'fail'),('domain-expired','domain/root.crt',domain['host'],domain['certificateSha256'],1893456000,'fail'),('domain-future','domain/root.crt',domain['host'],domain['certificateSha256'],1577836800,'fail'),('domain-untrusted','other.crt',domain['host'],domain['certificateSha256'],domain['bootstrapEpoch'],'fail'),('domain-missing-chain','domain/root.crt',domain['host'],domain['certificateSha256'],domain['bootstrapEpoch'],'fail')]
for case,cert,host,pin,epoch,expected in cases:
 context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2;context.maximum_version=ssl.TLSVersion.TLSv1_2;context.set_ciphers('ECDHE-ECDSA-AES128-GCM-SHA256');leaf={'domain-chain':'leaf','renewed-leaf-same-anchor':'renew','domain-wrong-san':'wrong-san','domain-cn-only':'cn-only'}.get(case,'leaf' if case.startswith('domain-') else None);context.load_cert_chain(root/('domain/'+leaf+('.crt' if case=='domain-missing-chain' else '-chain.crt') if leaf else 'server.crt'),root/('domain/'+leaf+'.key' if leaf else 'test-only-server.key'));incoming=ssl.MemoryBIO();outgoing=ssl.MemoryBIO();sni=[];context.set_servername_callback(lambda sock,name,ctx:sni.append(name));server=context.wrap_bio(incoming,outgoing,server_side=True)
 command=['/usr/bin/qemu-mipsel','-cpu','P5600','-L','/sample-qt/sysroot','-strace','-E','HOME=/tmp','-E','TMPDIR=/tmp','-E','LD_LIBRARY_PATH=/opt/image/opt/Qtopia/lib:/lib:/usr/lib','/content-test/content.mipsel',str(root/cert),host,pin,str(epoch)]
 with open('/tmp/tls-'+case+'.trace','wb') as trace:
  p=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=trace);deadline=time.monotonic()+12;actual=None
  try:
   while time.monotonic()<deadline:
    if not select.select([p.stdout],[],[],max(0,deadline-time.monotonic()))[0]:break
    line=p.stdout.readline().decode().strip()
    if line.startswith('TLS_RESULT='):actual=line.split('=',1)[1].split(':',1)[0];break
    if line.startswith('TLS_OUT='):
     raw=bytes.fromhex(line.split('=',1)[1]);incoming.write(raw)
     try:server.do_handshake()
     except ssl.SSLWantReadError:pass
     except ssl.SSLError:pass # Expected fatal alerts in negative cases.
     response=outgoing.read();p.stdin.write(b'TLS_IN='+response.hex().encode()+b'\n');p.stdin.flush()
    elif not line:break
   p.stdin.close();p.wait(timeout=2)
  finally:
   if p.poll() is None:p.kill();p.wait()
 text=Path('/tmp/tls-'+case+'.trace').read_text(errors='replace');alltrace+=text
 if re.search(r'\b(socket|connect|mount|umount2|execve|reboot)\(',text):raise SystemExit('FAIL forbidden syscall '+case)
 if p.returncode or actual!=expected:print(text[-4000:]);raise SystemExit('FAIL '+case+' actual='+str(actual)+' exit='+str(p.returncode))
 if expected=='ok' and leaf and sni!=[host]:raise SystemExit('FAIL SNI '+str(sni))
 checks+=1;print('PASS TLS '+case+' expected='+expected+' memoryBIO=true reader_execution=false')
print('PASS TLS %d cases network=none'%checks)
print('PANDANOTE_TRACE_BASE64='+base64.b64encode(alltrace.encode()).decode())
