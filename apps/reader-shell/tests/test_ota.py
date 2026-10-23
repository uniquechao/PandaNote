"""OTA 原生解析、真实签名、精确 wire 与持久化边界的定向主机夹具。"""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]
OUT = ROOT / 'build/ota-tests'

def raw(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()

def sha(value):
    return hashlib.sha256(value).hexdigest()

class OtaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        cls.binary = OUT / 'ota-host'
        cls.source = Path(os.environ.get('PANDANOTE_MBEDTLS_SOURCE', str(PROJECT / 'build/ota-host/mbedtls-3.6.7')))
        cls.crypto = cls.source.is_dir()
        sources = ['ota/json.cpp', 'ota/storage.cpp', 'ota/authorization.cpp', 'tests/ota_host.cpp']
        subprocess.run(['cc', '-c', str(ROOT/'third_party/sha256/sha256.c'), '-o', str(OUT/'sha.o')], check=True)
        cmd = ['g++', '-std=c++98', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation', '-ffunction-sections', '-fdata-sections']
        if cls.crypto:
            library = Path(os.environ.get('PANDANOTE_MBEDTLS_HOST_LIB',str(PROJECT / 'build/ota-host/libmbed.a')))
            if not library.is_file():
                raise RuntimeError('需先用固定 MbedTLS 源码编译主机验证库')
            sources += ['ota/crypto.cpp']
            cmd += ['-I'+str(cls.source/'include'), '-I'+str(ROOT/'third_party/mbedtls'), '-DMBEDTLS_CONFIG_FILE="pandanote_config.h"']
        else:
            cmd += ['-DOTA_TEST_NO_CRYPTO']
        cmd += [str(ROOT/s) for s in sources] + [str(OUT/'sha.o')]
        if cls.crypto:
            cmd += [str(library)]
        cmd += ['-Wl,--wrap=open,--wrap=fsync,--gc-sections', '-o', str(cls.binary)]
        subprocess.run(cmd, check=True)

    def invoke(self, *args, body=None, env=None):
        return subprocess.run([str(self.binary), *map(str, args)], input=body, capture_output=True, env=env)

    def test_strict_json_and_unicode(self):
        for value in [b'{"a":1,"a":2}', b'{"a":true,"a":3}', b'{"n":1.0}', b'{"n":1e2}', b'{"n":9007199254740992}', b'{"n":01}', b'{"x":"\xff"}', b'{"x":"\\ud800"}', b'[[[[[[[[[[0]]]]]]]]]]', b'{} trailing', b'{"a":[0,]}']:
            with self.subTest(value=value):
                self.assertNotEqual(self.invoke('json', body=value).returncode, 0)
        value = {'版本':'新版本 😀', 'sequence':9007199254740991, 'files':[{'a':1}]*128}
        result = self.invoke('json', body=raw(value))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), value)
        value['files'].append({})
        self.assertNotEqual(self.invoke('json', body=raw(value)).returncode, 0)

    def test_confirmation_requires_same_visible_prompt_and_short_gesture(self):
        self.assertEqual(self.invoke('gesture','tap').stdout,b'1')
        for case in ('new_attempt','new_generation','late_prompt','drag','boundary'):
            with self.subTest(case=case):self.assertEqual(self.invoke('gesture',case).stdout,b'0')

    def test_live_process_identity_ignores_changing_runtime_statistics(self):
        result=self.invoke('process')
        self.assertEqual(result.returncode,0,result.stderr)

    def test_base64_is_canonical(self):
        for value in ('AA==', 'YWJj', ''):
            self.assertEqual(self.invoke('base64', value).returncode, 0)
        for value in ('AB==', 'AA=', '=AAA', 'AA==\n', '????', 'YQ==AAAA'):
            self.assertNotEqual(self.invoke('base64', value).returncode, 0)

    def test_daily_check_and_clock_regression(self):
        now = 1792700000
        for last, expected in [(0,1), (now-86399,0), (now-86400,1), (now+1,1)]:
            self.assertEqual(self.invoke('due', now, last).stdout, str(expected).encode())
        self.assertEqual(self.invoke('due', 0, 0).stdout, b'0')

    def test_durable_private_files_refuse_links_and_unsafe_ancestors(self):
        with tempfile.TemporaryDirectory(dir=OUT) as temp:
            p = Path(temp); (p/'state').mkdir(mode=0o700)
            (p/'state/value').write_bytes(b'old'); (p/'state/value').chmod(0o600)
            (p/'state/link').symlink_to('value')
            os.link(p/'state/value', p/'state/hard')
            # The multiply linked original is also rejected; use a separate value.
            (p/'state/value').unlink(); (p/'state/value').write_bytes(b'old'); (p/'state/value').chmod(0o600)
            (p/'state/other').write_bytes(b'other'); (p/'state/other').chmod(0o600)
            (p/'state/hard').unlink(); os.link(p/'state/other',p/'state/hard')
            (p/'state/parent').symlink_to('.')
            result = self.invoke('storage', p)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((p/'state/other').read_bytes(), b'other')
            self.assertFalse((p/'escape').exists())

    def test_fsync_failure_never_claims_success(self):
        for boundary in (1,2):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory(dir=OUT) as temp:
                p=Path(temp);(p/'state').mkdir(mode=0o700)
                result=self.invoke('storage',p,env={**os.environ,'OTA_FAIL_FSYNC':str(boundary)})
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout,b'failure')

    def test_checkpoint_resume_truncates_uncommitted_tail(self):
        with tempfile.TemporaryDirectory(dir=OUT) as temp:
            p=Path(temp);(p/'state').mkdir(mode=0o700)
            result=self.invoke('chunks',p)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_crash_recovery_never_reapplies_or_restarts_health_budget(self):
        for state,new_boot,target,expected in [
            ('APPLYING',0,0,'RECOVERY_REQUIRED'),('APPLYING',1,1,'RECOVERY_REQUIRED'),
            ('COMMITTED_PENDING_REBOOT',0,1,'RECOVERY_REQUIRED'),
            ('COMMITTED_PENDING_REBOOT',1,0,'RECOVERY_REQUIRED'),
            ('COMMITTED_PENDING_REBOOT',1,1,'BOOT_VERIFYING'),
            ('BOOT_VERIFYING',0,1,'BOOT_VERIFYING'),('BOOT_VERIFYING',1,1,'RECOVERY_REQUIRED'),
            ('HEALTHY',1,1,'HEALTHY'),('ROLLED_BACK',1,0,'ROLLED_BACK'),('unknown',0,1,'RECOVERY_REQUIRED')]:
            with self.subTest(state=state,new_boot=new_boot,target=target):
                self.assertEqual(self.invoke('resume',state,new_boot,target).stdout.decode(),expected)

    def fixture(self,native_content=b'fixture-native-manifest',boot='b'*24):
        if not self.crypto:
            self.skipTest('未提供固定 MbedTLS 3.6.7 主机验证库')
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        key=ec.generate_private_key(ec.SECP256R1())
        config=dict(schema=1,device_id='fixture-device',model='966U2',channel='stable',helper_sha256='6'*64,helper_path='/user/pandanote/apps/releases/'+'c'*64+'/ota/pandanote-ota-upgrade.mipsel',keys={'test':key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()})
        native=sha(native_content);oldnative='c'*64;oldboot='d'*24
        rows=[];data={}
        for path,mode,role,content in [('/etc/inittab',0o644,'entry',b'new entry'),('/user/pandanote/apps/current',0o600,'pointer',(native+'\n').encode()), *[('/user/pandanote/apps/releases/'+native+'/'+name,0o700 if name.endswith('mipsel') else 0o600,'release',native_content if name=='manifest.json' else name.encode()) for name in ('reader-shell.mipsel','manifest.json','release.sha256','ota/ota-worker.mipsel','ota/pandanote-ota-upgrade.mipsel','ota/helper-manifest.json')], *[('/etc/pandanote-system/'+boot+'/'+name,0o600,'system',name.encode()) for name in ('service.sh','SHA256SUMS')]]:
            data[path]=content;rows.append(dict(path=path,mode=mode,role=role,bytes=len(content),sha256=sha(content)))
        oldfiles=[dict(path='/etc/pandanote-system/'+oldboot+'/'+str(i),mode=0o600,bytes=1,sha256=sha(b'x')) for i in range(4)]
        request=dict(schema=1,request_nonce='1'*64,model='966U2',channel='stable',ota_abi=1,old_package_sha256='2'*64,old_native_sha256=oldnative,old_boot_id=oldboot,old_inittab_sha256='3'*64,old_current_sha256='4'*64,live_superblock_sha256='5'*64,highest_sequence=0)
        old=dict(schema=1,profile='normal-exact-upgrade-v1',**{k:v for k,v in request.items() if k.startswith('old_') or k=='live_superblock_sha256'},old_files=oldfiles)
        candidate=dict(schema=1,profile='normal-persistent-v1',native_sha256=native,boot_id=boot,old_inittab_sha256=request['old_inittab_sha256'],upgrade_from=old,files=[dict(f,source='files'+f['path']) for f in rows])
        release=dict(schema=1,model='966U2',channel='stable',sequence=1,version='1.2.3',native_sha256=native,boot_id=boot,ota_abi=1,workspace_schema=1,files=rows)
        wire=(f'PANDANOTE-UPGRADE-1 {boot} {native} {request["old_inittab_sha256"]} {len(rows)}\nBASE {request["old_package_sha256"]} {oldnative} {oldboot} {request["old_current_sha256"]} {request["live_superblock_sha256"]} {len(oldfiles)}\n').encode()
        for f in oldfiles:wire+=f'CHECK {f["mode"]:o} {f["bytes"]} {f["sha256"]} {f["path"]}\n'.encode()
        for f in rows:wire+=f'{f["role"]} {f["mode"]:o} {f["bytes"]} {f["sha256"]} {f["path"]}\n'.encode()+data[f['path']]+b'\n'
        deployment=dict(schema=1,device_id=config['device_id'],request_nonce=request['request_nonce'],release_sha256=sha(raw(release)),sequence=1,**{k:v for k,v in request.items() if k.startswith('old_') or k=='live_superblock_sha256'},candidate_sha256=sha(raw(candidate)),bundle_sha256=sha(wire),bundle_bytes=len(wire),helper_sha256='6'*64,issued_at=1792700000,expires_at=1792703600)
        return key,config,request,release,deployment,candidate,wire

    def signed(self,key,domain,payload):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        encoded=raw(payload)
        return dict(schema=1,key_id='test',payload_b64=base64.b64encode(encoded).decode(),signature_b64=base64.b64encode(key.sign(domain+encoded,ec.ECDSA(hashes.SHA256()))).decode())

    def check(self,fixture,change=None,bundle=False,now=1792700001,tamper=None):
        key,c,q,r,d,candidate,wire=fixture
        c=copy.deepcopy(c);q=copy.deepcopy(q);r=copy.deepcopy(r);d=copy.deepcopy(d);candidate=copy.deepcopy(candidate)
        if change:change(c,q,r,d,candidate)
        response=dict(schema=1,status='update',release=self.signed(key,b'PANDANOTE-OTA-RELEASE-1\n',r),deployment=self.signed(key,b'PANDANOTE-OTA-DEPLOYMENT-1\n',d),candidate_b64=base64.b64encode(raw(candidate)).decode())
        if tamper:tamper(response)
        with tempfile.TemporaryDirectory(dir=OUT) as temp:
            p=Path(temp)
            for name,value in [('config',c),('request',q),('response',response)]: (p/name).write_bytes(raw(value))
            (p/'bundle').write_bytes(wire);(p/'bundle').chmod(0o600)
            return self.invoke('bundle' if bundle else 'authorize',p/'config',p/'request',p/'response',now,p)

    def test_real_signatures_and_exact_wire(self):
        f=self.fixture()
        self.assertEqual(self.check(f).returncode,0)
        self.assertEqual(self.check(f,bundle=True).returncode,0)
        f=(*f[:-1],f[-1][:-1]+b'x')
        self.assertNotEqual(self.check(f,bundle=True).returncode,0)

    def test_tampered_signature_payload_and_unknown_key_are_rejected(self):
        f=self.fixture()
        for tamper in [lambda v:v['release'].update(signature_b64=base64.b64encode(b'bad-signature').decode()),
                       lambda v:v['release'].update(payload_b64=base64.b64encode(raw(dict(f[3],version='tampered'))).decode()),
                       lambda v:v['deployment'].update(key_id='untrusted')]:
            self.assertNotEqual(self.check(f,tamper=tamper).returncode,0)

    def test_device_nonce_baseline_expiry_and_replay_are_rejected(self):
        f=self.fixture()
        changes=[lambda c,q,r,d,m:c.update(device_id='other'),lambda c,q,r,d,m:q.update(request_nonce='9'*64),lambda c,q,r,d,m:q.update(old_current_sha256='9'*64),lambda c,q,r,d,m:c.update(helper_sha256='9'*64),lambda c,q,r,d,m:q.update(highest_sequence=2),lambda c,q,r,d,m:q.update(highest_sequence=1),lambda c,q,r,d,m:r.update(ota_abi=2),lambda c,q,r,d,m:d.update(expires_at=d['issued_at']+86401),lambda c,q,r,d,m:d.update(sequence=2),lambda c,q,r,d,m:r['files'][0].update(path='/user/pandanote/config/ota.json')]
        for i,change in enumerate(changes):
            with self.subTest(case=i):self.assertNotEqual(self.check(f,change).returncode,0)
        self.assertNotEqual(self.check(f,now=1792703600).returncode,0)
        self.assertNotEqual(self.check(f,now=1792699999).returncode,0)
        self.assertEqual(self.check(f,lambda c,q,r,d,m:(q.update(highest_sequence=1),c.update(accepted_release_sha256=sha(raw(r))))).returncode,0)

    def test_worker_requires_fresh_consent_and_honors_deferral(self):
        binary=Path(os.environ.get('PANDANOTE_OTA_WORKER_HOST',str(PROJECT/'build/ota-host/ota-worker-test')))
        if not binary.is_file():self.skipTest('未提供 QtCore 主机 worker 夹具')
        import time
        key,c,q,r,d,m,wire=self.fixture()
        d['issued_at']=int(time.time())-1;d['expires_at']=d['issued_at']+3600
        response=dict(schema=1,status='update',release=self.signed(key,b'PANDANOTE-OTA-RELEASE-1\n',r),deployment=self.signed(key,b'PANDANOTE-OTA-DEPLOYMENT-1\n',d),candidate_b64=base64.b64encode(raw(m)).decode())
        with tempfile.TemporaryDirectory(dir=OUT) as temp:
            root=Path(temp);attempt=root/('user/pandanote/state/ota/attempts/'+'1'*32)
            for directory in [attempt/'events',root/'run/pandanote-normal/ota',root/'user/pandanote/apps']:
                directory.mkdir(parents=True,exist_ok=True)
            for directory in [root,*[v for v in root.rglob('*') if v.is_dir()]]:directory.chmod(0o700)
            files={root/'config':raw(c),root/'request':raw(q),root/'response':raw(response),root/'wire':wire,
                   root/'user/pandanote/state/ota/accepted.json':raw(dict(sequence=0,release_sha256='0'*64)),
                   root/'user/pandanote/apps/current':(q['old_native_sha256']+'\n').encode(),
                   root/'run/pandanote-normal/early.ready':(q['old_boot_id']+'\n').encode(),attempt/'request.json':raw(q)}
            for path,data in files.items():path.write_bytes(data);path.chmod(0o600)
            lib=PROJECT/'build/ota-host/qt-root/usr/lib/x86_64-linux-gnu'
            result=subprocess.run([str(binary),str(root),str(root/'config'),str(root/'request'),str(root/'response')],capture_output=True,env={**os.environ,'LD_LIBRARY_PATH':str(lib)})
            self.assertEqual(result.returncode,0,result.stderr.decode())
            state=json.loads((root/'user/pandanote/state/ota/state.json').read_bytes())
            self.assertEqual((state['state'],state['confirmed'],state['last_check']),('IDLE',0,0))
            self.assertEqual(state['attempt_id'],'1'*32)
            self.assertLessEqual(len(list((attempt/'events').glob('*.json'))),7)

    def test_supervisor_restarts_only_exited_safe_workers_with_a_budget(self):
        with tempfile.TemporaryDirectory(dir=OUT) as temp:
            root=Path(temp);worker=root/'worker'
            worker.write_text('#!/bin/sh\n[ -f "$0.allow" ]\n');worker.chmod(0o700)
            script=r'''
. "$1"
DEV_RUN=$2;NORMAL_OTA_WORKER=$2/worker;NORMAL_OTA_RESTARTS=0
normal_private_file(){ [ -f "$1" ]; }
normal_stop(){ echo stop >> "$DEV_RUN/log";rm -f "$DEV_RUN/ota.exit"; }
normal_ota_init(){ echo spawn >> "$DEV_RUN/log"; }
normal_ota_supervise
[ ! -e "$DEV_RUN/log" ] || exit 10
touch "$DEV_RUN/ota.exit"
normal_ota_supervise
[ ! -e "$DEV_RUN/log" ] || exit 11
touch "$NORMAL_OTA_WORKER.allow"
for iteration in 1 2 3 4;do touch "$DEV_RUN/ota.exit";normal_ota_supervise;done
[ "$NORMAL_OTA_RESTARTS" = 3 ] || exit 12
[ "$(wc -l < "$DEV_RUN/log")" = 6 ] || exit 13
'''
            result=subprocess.run(['sh','-c',script,'fixture',str(ROOT/'deploy/normal_boot/ota.in'),str(root)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode())

    def test_real_ui_ready_handoff_and_heartbeat_failure(self):
        binary=Path(os.environ.get('PANDANOTE_OTA_UI_HOST',str(OUT/'ota-ui-host')))
        if not binary.is_file():self.skipTest('需先生成真实 ReaderShell 主机夹具')
        with tempfile.TemporaryDirectory(dir=OUT) as temp:
            root=Path(temp)
            for name in ('user/pandanote/state/ota','run/pandanote-normal/ota'): (root/name).mkdir(parents=True)
            for path in (root,*[p for p in root.rglob('*') if p.is_dir()]):path.chmod(0o700)
            boot=root/'run/pandanote-normal/ota/boot.generation';boot.write_text('3'*32);boot.chmod(0o600)
            runtime=OUT/'runtime';runtime.mkdir(mode=0o700,exist_ok=True)
            library=PROJECT/'build/ota-host/qt-root/usr/lib/x86_64-linux-gnu'
            env={**os.environ,'QT_QPA_PLATFORM':'offscreen','QT_PLUGIN_PATH':os.environ.get('QT_PLUGIN_PATH',str(library/'qt5/plugins')),'LD_LIBRARY_PATH':os.environ.get('LD_LIBRARY_PATH',str(library)),'XDG_RUNTIME_DIR':str(runtime),'XDG_CACHE_HOME':str(OUT/'cache'),'XDG_CONFIG_HOME':str(OUT/'config')}
            result=subprocess.run([str(binary),str(root)],capture_output=True,env=env)
            self.assertEqual(result.returncode,0,result.stderr.decode())

    def test_next_release_keeps_the_bootstrap_helper_pin(self):
        first=self.fixture();second=list(self.fixture(b'fixture-native-manifest-v2','e'*24))
        second[0]=first[0];second[1]['keys']=copy.deepcopy(first[1]['keys'])
        key,c,q,r,d,m,wire=second
        q.update(old_package_sha256=sha(raw(first[5])),old_native_sha256=first[3]['native_sha256'],old_boot_id=first[3]['boot_id'],highest_sequence=1,request_nonce='8'*64,live_superblock_sha256='7'*64)
        for f in first[3]['files']:
            if f['role']=='entry':q['old_inittab_sha256']=f['sha256']
            if f['role']=='pointer':q['old_current_sha256']=f['sha256']
        c['accepted_release_sha256']=sha(raw(first[3]));r['sequence']=2;d['sequence']=2;d['request_nonce']=q['request_nonce']
        for k,v in q.items():
            if k.startswith('old_') or k=='live_superblock_sha256':d[k]=v;m['upgrade_from'][k]=v
        m['old_inittab_sha256']=q['old_inittab_sha256']
        m['upgrade_from']['old_files']=[{k:v for k,v in f.items() if k!='role'} for f in first[3]['files'] if f['role'] in ('release','system')]
        d['release_sha256']=sha(raw(r));d['candidate_sha256']=sha(raw(m))
        # 连续发布的元数据仍绑定首次接入的 helper，不依赖新版 helper 字节相同。
        self.assertEqual(c['helper_sha256'],first[1]['helper_sha256'])
        self.assertEqual(self.check(second).returncode,0)

    def test_candidate_and_release_must_match(self):
        f=self.fixture()
        def change(c,q,r,d,m):
            m['files'][0]['sha256']='9'*64;d['candidate_sha256']=sha(raw(m))
        self.assertNotEqual(self.check(f,change).returncode,0)
        self.assertNotEqual(self.check(f,lambda c,q,r,d,m:d.update(release_sha256='9'*64)).returncode,0)

if __name__=='__main__':unittest.main()
