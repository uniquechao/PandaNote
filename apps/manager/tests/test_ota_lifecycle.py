"""真实管理端签名与设备 worker 相接的合成生命周期；不执行安装或硬件操作。"""
import json
import os
from pathlib import Path
import subprocess
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes,serialization
from manager.ota_store import encode,identifier
from manager.ota_signer import b64
from ota_fixtures import Fixture

PROJECT=Path(__file__).resolve().parents[3]
BINARY=PROJECT/'apps/reader-shell/build/ota-tests/ota-worker-host'

class RealSigner:
    def __init__(self):self.key=ec.generate_private_key(ec.SECP256R1())
    def sign(self,kind,object_id,revision,raw):
        domain=b'PANDANOTE-OTA-RELEASE-1\n' if kind=='release' else b'PANDANOTE-OTA-DEPLOYMENT-1\n'
        return dict(schema=1,key_id='fixture',payload_b64=b64(raw),signature_b64=b64(self.key.sign(domain+raw,ec.ECDSA(hashes.SHA256()))))

@pytest.mark.parametrize('downloading',[False,True])
def test_real_worker_renewal_reports_and_second_baseline(tmp_path,downloading):
    if not BINARY.is_file():pytest.skip('需先运行 tests/run_ota_host.py 生成真实 worker 夹具')
    f=Fixture(tmp_path);signer=RealSigner();f.service.signer=signer
    previous_dir=f.old_dir;previous=f.old;baseline=f.old_sha
    for sequence in (1,2):
        release,candidate,directory,manifest=f.release('v'+str(sequence),old_dir=previous_dir);f.campaign(release)
        request=f.check(package_sha=baseline,manifest=previous);request['highest_sequence']=sequence-1
        f.service.check('one',request);bundle=f.ready(request,candidate,directory);offer=f.service.check('one',request)
        start=f.now;f.now+=3601;renewed_request={**request,'request_nonce':identifier()*2,'highest_sequence':sequence};renewed=f.service.check('one',renewed_request)
        transaction=str(sequence)*32
        root=tmp_path/('clone-'+str(sequence));attempt=root/('user/pandanote/state/ota/attempts/'+transaction)
        for path in (attempt/'events',root/'run/pandanote-normal/ota',root/'user/pandanote/apps',root/'user/pandanote/config'):path.mkdir(parents=True,exist_ok=True)
        for path in (root,*[p for p in root.rglob('*') if p.is_dir()]):path.chmod(0o700)
        pem=signer.key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        config=dict(schema=1,device_id='one',model='966U2',channel='stable',keys={'fixture':pem},helper_sha256='d'*64,helper_path='/user/pandanote/apps/releases/'+'c'*64+'/ota/pandanote-ota-upgrade.mipsel')
        rows={'user/pandanote/config/ota.json':encode(config),'config':encode(config),'request':encode(request),'response':encode(offer),'wire':f.store.read(bundle,24*1024*1024),'plan':encode(dict(attempt_id=transaction,now=start,renewed_at=f.now,request=renewed_request,offer=renewed,downloading=int(downloading))),
              'user/pandanote/state/ota/accepted.json':encode(dict(sequence=sequence-1,release_sha256='0'*64)),
              'user/pandanote/apps/current':(previous['native_sha256']+'\n').encode(),'run/pandanote-normal/early.ready':(previous['boot_id']+'\n').encode()}
        for name,raw in rows.items():path=root/name;path.write_bytes(raw);path.chmod(0o600)
        env={**os.environ,'LD_LIBRARY_PATH':str(PROJECT/'build/ota-host/qt-root/usr/lib/x86_64-linux-gnu')}
        result=subprocess.run([str(BINARY),str(root),str(root/'config'),str(root/'request'),str(root/'response'),str(root/'plan')],capture_output=True,env=env)
        assert result.returncode==0,result.stderr.decode()
        events=[json.loads(p.read_bytes()) for p in (attempt/'events').glob('*.json')]
        # 每轮由真实 worker 生成事件；同一轮续期必须始终只有一个事务 ID。
        assert {e['attempt_id'] for e in events}=={transaction}
        for event in sorted(events,key=lambda e:e['state']=='HEALTHY'):
            assert f.service.report('one',event)['ok']
        state=json.loads((root/'user/pandanote/state/ota/state.json').read_bytes());assert state['state']=='HEALTHY'
        assert f.service.device_view('one')['confirmed']['package_sha256']==candidate
        previous_dir=directory;previous=manifest;baseline=candidate
