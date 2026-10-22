import os
from pathlib import Path
import shutil
import subprocess
import time
import pytest
from manager.ota_store import encode,identifier,strict_json
from manager.ota_signer import SigningAuthority,DOMAINS,b64,unb64,payload_contract,envelope_payload
from ota_fixtures import Fixture

@pytest.fixture
def f(tmp_path):return Fixture(tmp_path)

def authority(f):
    if not shutil.which('openssl'):pytest.skip('需要 OpenSSL')
    directory=f.path/'keys';directory.mkdir(mode=0o700);key=directory/'fixture.key'
    subprocess.run(['openssl','genpkey','-algorithm','EC','-pkeyopt','ec_paramgen_curve:P-256','-out',str(key)],check=True,capture_output=True);key.chmod(0o600)
    return SigningAuthority(f.store,key,'fixture',directory/'ledger.sqlite3',[os.geteuid()+1])

def test_actual_p256_signature_domains_raw_payload_and_der(f):
    a=authority(f);release,_,_,_=f.release()
    # 使用尚未批准的另一个受审发布请求真实签名。
    with f.store.db(True) as db:
        db.execute("UPDATE ota_releases SET state='VALIDATED' WHERE release_id=?",(release,));row=db.execute('SELECT * FROM ota_releases WHERE release_id=?',(release,)).fetchone()
    raw=row['payload'].encode();request=dict(kind='release',object_id=release,revision=row['revision'],payload_b64=b64(raw));envelope=a.sign(request)
    assert a.sign(request)==envelope
    data=DOMAINS['release']+raw;public=f.path/'public.pem';signature=f.path/'signature.der'
    public.write_bytes(subprocess.run(['openssl','pkey','-in',str(a.key),'-pubout'],capture_output=True,check=True).stdout);signature.write_bytes(unb64(envelope['signature_b64']))
    command=['openssl','dgst','-sha256','-verify',str(public),'-signature',str(signature)]
    assert subprocess.run(command,input=data,capture_output=True).returncode==0
    assert subprocess.run(command,input=DOMAINS['deployment']+raw,capture_output=True).returncode!=0
    assert subprocess.run(command,input=DOMAINS['release']+raw+b' ',capture_output=True).returncode!=0
    assert envelope_payload(envelope,'release')[0]==raw
    with pytest.raises(ValueError):envelope_payload({**envelope,'signature_b64':'AA==='},'release')
    with f.store.db(True) as db:db.execute("UPDATE ota_releases SET state='REVOKED' WHERE release_id=?",(release,))
    with pytest.raises(ValueError):a.sign(request)

def test_deployment_independently_checks_closure_and_wire_without_snapshot_execution(f,monkeypatch):
    a=authority(f);f.now=int(time.time())
    class Direct:
        def sign(self,kind,key,revision,raw):return a.sign(dict(kind=kind,object_id=key,revision=revision,payload_b64=b64(raw)))
    f.service.signer=Direct()
    release,candidate,directory,manifest=f.release();f.campaign(release);check=f.check();f.service.check('one',check);bundle=f.ready(check,candidate,directory)
    # 签名流程不调用快照加载器。
    monkeypatch.setattr('manager.ota_publish.tool_module',lambda *args:(_ for _ in ()).throw(AssertionError('不应执行快照')))
    result=f.service.offer(iter_grants(f)[0])
    assert result['status']=='update';deployment=strict_json(unb64(result['deployment']['payload_b64']));assert deployment['bundle_sha256']==bundle

def iter_grants(f):
    with f.store.db() as db:return [r[0] for r in db.execute('SELECT grant_id FROM ota_grants')]

def test_signer_rejects_same_identity_and_bad_file_contract(f):
    a=authority(f)
    with pytest.raises(ValueError):SigningAuthority(f.store,a.key,'fixture',a.ledger,[os.geteuid()])
    with pytest.raises(ValueError):payload_contract('release',encode({'schema':True}))

def test_socket_client_transport_and_owner_checks(f):
    import socketserver,threading
    from manager.ota_signer import SignerClient,receive,send
    a=authority(f);release,_,_,_=f.release()
    with f.store.db(True) as db:
        db.execute("UPDATE ota_releases SET state='VALIDATED' WHERE release_id=?",(release,));row=dict(db.execute('SELECT * FROM ota_releases WHERE release_id=?',(release,)).fetchone())
    # 路径留在项目内并避开 Unix socket 的 108 字节长度限制。
    directory=Path('build')/('ota-socket-'+identifier());directory.mkdir(mode=0o700);path=directory/'signer.sock'
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):send(self.request,{'envelope':a.sign(receive(self.request))})
    try:
        with socketserver.UnixStreamServer(str(path),Handler) as server:
            path.chmod(0o660);thread=threading.Thread(target=lambda:server.serve_forever(poll_interval=0.01),daemon=True);thread.start()
            try:
                result=SignerClient(path,os.geteuid()).sign('release',release,row['revision'],row['payload'].encode())
                assert envelope_payload(result,'release')[0]==row['payload'].encode()
                with pytest.raises(ValueError):SignerClient(path,os.geteuid()+1).sign('release',release,row['revision'],row['payload'].encode())
            finally:server.shutdown();thread.join(timeout=2)
    finally:
        path.unlink(missing_ok=True);directory.rmdir()
