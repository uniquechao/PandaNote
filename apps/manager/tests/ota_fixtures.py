"""合成完整 NORMAL 闭包；不依赖真实设备，不执行目标二进制。"""
import shutil
from pathlib import Path
from manager.ota_store import OtaStore,encode,digest,identifier
from manager.ota_publish import import_package,import_tree,tool_module,enroll
from manager.ota import OtaService
from manager.ota_signer import b64

SOURCE=Path(__file__).resolve().parents[2]/'reader-shell'
TOKEN='fixture-ota-token-with-at-least-32-chars'
class FakeSigner:
    hook=None
    def sign(self,kind,object_id,revision,raw):
        if self.hook:self.hook(kind)
        return dict(schema=1,key_id='fixture',payload_b64=b64(raw),signature_b64=b64(b'fixture-signature'))

def package(directory,version,old=None,snapshot=None,sb='c'*64):
    native_raw=encode(dict(artifacts=[dict(path='reader-shell.mipsel',bytes=len(version),sha256=digest(version.encode()))]))
    native=digest(native_raw);boot=digest(version.encode())[:24];release='/user/pandanote/apps/releases/'+native+'/';system='/etc/pandanote-system/'+boot+'/'
    data={release+'manifest.json':native_raw,release+'reader-shell.mipsel':version.encode(),system+'service.sh':b'service',system+'policy.sh':b'policy',system+'child-supervisor.sh':b'supervisor'}
    for base,index in ((release,'release.sha256'),(system,'SHA256SUMS')):
        data[base+index]=''.join(digest(raw)+'  '+p.removeprefix(base)+'\n' for p,raw in sorted(data.items()) if p.startswith(base)).encode()
    data['/user/pandanote/apps/current']=(native+'\n').encode();data['/etc/inittab']=(system+'service.sh\n').encode()
    directory.mkdir();files=[]
    for path,raw in data.items():
        role='pointer' if path.endswith('/current') else 'entry' if path=='/etc/inittab' else 'release' if path.startswith(release) else 'system'
        mode=0o700 if path.endswith('reader-shell.mipsel') else 0o644 if role=='entry' else 0o600
        name='files/'+path[1:];target=directory/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw);target.chmod(mode)
        files.append(dict(path=path,source=name,mode=mode,bytes=len(raw),sha256=digest(raw),role=role))
    manifest=dict(schema=1,profile='normal-persistent-v1',device_apply_supported=False,native_sha256=native,boot_id=boot,files=files,sources={})
    if old:
        old_sha=digest((old/'manifest.json').read_bytes());bound=tool_module(snapshot,'upgrade_profile').bind(old,old_sha,sb);manifest.update(upgrade_from=bound,old_inittab_sha256=bound['old_inittab_sha256'])
    (directory/'manifest.json').write_bytes(encode(manifest));return manifest

class Fixture:
    def __init__(self,tmp_path):
        self.path=tmp_path;self.now=1800000000;self.store=OtaStore(tmp_path/'ota',lambda:self.now);self.store.initialize();self.signer=FakeSigner();self.service=OtaService(self.store,self.signer,{'local_device_id':'one'},lambda:self.now)
        self.snapshot=tmp_path/'snapshot';destination=self.snapshot/'apps/reader-shell/deploy/normal_boot';destination.mkdir(parents=True)
        for path in (SOURCE/'deploy/normal_boot').glob('*.py'):shutil.copyfile(path,destination/path.name)
        self.old_dir=tmp_path/'old';self.old=package(self.old_dir,'old')
        self.old_sha=import_package(self.store,self.old_dir,reviewed=True,snapshot=self.snapshot)
        for device in ('one','two'):
            enroll(self.store,dict(device_id=device,credential_sha256=digest((TOKEN if device=='one' else 'second-token').encode()),model='966U2',channels=['stable'],ota_abi=1,helper_sha256='d'*64,bootstrap_version='1',baseline=self.old_sha,unique_credential_verified=True))
    def release(self,version='new',old_dir=None):
        directory=self.path/('package-'+identifier());manifest=package(directory,version,old_dir or self.old_dir,self.snapshot)
        target=import_package(self.store,directory,snapshot=self.snapshot)
        data=dict(meta=dict(model='966U2',channel='stable',version=version,toolchain_sha256='f'*64,native_sha256=manifest['native_sha256'],suspend_helper_sha256='e'*64),trees={'snapshot':import_tree(self.store,self.snapshot)},target=target)
        raw=encode(data);key=self.store.put(raw,'release_input')
        with self.store.db(True) as db:db.execute('INSERT INTO ota_inputs VALUES(?,?)',(key,raw.decode()))
        result=self.service.create_release('admin',identifier(),dict(input_sha256=key,model='966U2',channel='stable',version=version));release_id=result['release_id']
        self.service.release_action('admin',identifier(),release_id,'validate',{'revision':1});self.service.release_action('admin',identifier(),release_id,'approve',{'revision':2})
        return release_id,target,directory,manifest
    def campaign(self,release_id,devices=None):
        devices=devices or ['one'];result=self.service.create_campaign('admin',identifier(),dict(release_id=release_id,device_ids=devices,batches=[[d] for d in devices]));key=result['campaign_id'];self.service.campaign_action('admin',identifier(),key,'start',{'revision':1});return key
    def check(self,nonce=None,package_sha=None,manifest=None):
        old=manifest or self.old;files={f['path']:f for f in old['files']}
        return dict(schema=1,request_nonce=nonce or identifier()*2,model='966U2',channel='stable',ota_abi=1,old_package_sha256=package_sha or self.old_sha,old_native_sha256=old['native_sha256'],old_boot_id=old['boot_id'],old_inittab_sha256=files['/etc/inittab']['sha256'],old_current_sha256=files['/user/pandanote/apps/current']['sha256'],live_superblock_sha256='c'*64,highest_sequence=0)
    def ready(self,request,candidate,directory):
        from manager.ota_worker import Worker
        worker=Worker(self.store);job=worker.claim();wire,_=tool_module(self.snapshot,'normal_upgrade').capture_bundle(directory,candidate);bundle=self.store.put(wire,'wire');worker.commit(job,candidate,bundle);return bundle
    def event(self,bundle,manifest,state='HEALTHY',attempt=None,**extra):
        return dict(schema=1,event_id=identifier(),attempt_id=attempt or identifier(),sequence=1,bundle_sha256=bundle,active_native_sha256=manifest['native_sha256'],boot_id=manifest['boot_id'],state=state,error_code='none',**extra)
