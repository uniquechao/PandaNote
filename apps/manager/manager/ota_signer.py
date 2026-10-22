"""独立身份的 Unix socket 签名服务；私钥从不传入 HTTP/构建进程。"""
import argparse
import base64
import os
import re
from pathlib import Path
import socket
import socketserver
import sqlite3
import stat
import struct
import subprocess
import time
from .ota_store import OtaStore, digest, encode, hex_value, strict_json
from .ota_publish import files_contract

DOMAINS={'release':b'PANDANOTE-OTA-RELEASE-1\n','deployment':b'PANDANOTE-OTA-DEPLOYMENT-1\n'}
RELEASE_FIELDS={'schema','model','channel','sequence','version','native_sha256','boot_id','ota_abi','workspace_schema','files'}
DEPLOYMENT_FIELDS={'schema','device_id','request_nonce','release_sha256','sequence','old_package_sha256','old_native_sha256','old_boot_id','old_inittab_sha256','old_current_sha256','live_superblock_sha256','candidate_sha256','bundle_sha256','bundle_bytes','helper_sha256','issued_at','expires_at'}

def payload_contract(kind,raw):
    value=strict_json(raw,262144 if kind=='release' else 16384)
    if not isinstance(value,dict) or set(value)!=(RELEASE_FIELDS if kind=='release' else DEPLOYMENT_FIELDS):raise ValueError('invalid_input')
    if type(value['schema']) is not int or value['schema']!=1 or type(value['sequence']) is not int or not 1<=value['sequence']<=2**53-1:raise ValueError('invalid_input')
    if kind=='release':
        if any(not isinstance(value[k],str) or not re.fullmatch('[A-Za-z0-9._-]{1,64}',value[k]) for k in ('model','channel','version')):raise ValueError('invalid_input')
        if type(value['ota_abi']) is not int or value['ota_abi']!=1 or type(value['workspace_schema']) is not int or value['workspace_schema']!=1:raise ValueError('incompatible_release')
        files_contract(value['files'],value['native_sha256'],value['boot_id'])
    else:
        if not isinstance(value['device_id'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',value['device_id']):raise ValueError('invalid_input')
        for key in ('request_nonce','release_sha256','old_package_sha256','old_native_sha256','old_inittab_sha256','old_current_sha256','live_superblock_sha256','candidate_sha256','bundle_sha256','helper_sha256'):hex_value(value[key])
        for key in ('old_boot_id',):hex_value(value[key],24)
        if any(type(value[k]) is not int for k in ('issued_at','expires_at','bundle_bytes')) or not 0<value['bundle_bytes']<=24*1024*1024 or not 0<value['expires_at']-value['issued_at']<=86400:raise ValueError('invalid_input')
    return value

def b64(raw):return base64.b64encode(raw).decode('ascii')
def unb64(value):
    if not isinstance(value,str):raise ValueError('invalid_input')
    try:raw=base64.b64decode(value,validate=True)
    except (ValueError,TypeError):raise ValueError('invalid_input') from None
    if b64(raw)!=value:raise ValueError('invalid_input')
    return raw

def envelope_payload(envelope,kind):
    if not isinstance(envelope,dict) or set(envelope)!={'schema','key_id','payload_b64','signature_b64'} or type(envelope['schema']) is not int or envelope['schema']!=1:raise ValueError('invalid_input')
    raw=unb64(envelope['payload_b64']);sig=unb64(envelope['signature_b64'])
    if not 1<=len(sig)<=128 or len(encode(envelope))>(352*1024 if kind=='release' else 24*1024):raise ValueError('invalid_input')
    return raw,payload_contract(kind,raw)

def receive(sock):
    def exact(size):
        out=bytearray()
        while len(out)<size:
            part=sock.recv(size-len(out))
            if not part:raise ValueError('signing_unavailable')
            out.extend(part)
        return bytes(out)
    size=struct.unpack('!I',exact(4))[0]
    if size>768*1024:raise ValueError('too_large')
    return strict_json(exact(size),768*1024)

def send(sock,value):
    raw=encode(value);sock.sendall(struct.pack('!I',len(raw))+raw)

class SignerClient:
    def __init__(self,path,uid):self.path=Path(path);self.uid=uid
    def sign(self,kind,object_id,revision,raw):
        payload_contract(kind,raw)
        info=self.path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=self.uid or stat.S_IMODE(info.st_mode)&0o007:raise ValueError('signing_unavailable')
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
            sock.settimeout(20);sock.connect(str(self.path))
            _,uid,_=struct.unpack('3i',sock.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
            if uid!=self.uid:raise ValueError('signing_unavailable')
            send(sock,dict(kind=kind,object_id=object_id,revision=revision,payload_b64=b64(raw)))
            result=receive(sock)
        if set(result)!={'envelope'}:raise ValueError('signing_unavailable')
        signed,_=envelope_payload(result['envelope'],kind)
        if signed!=raw:raise ValueError('signing_unavailable')
        return result['envelope']

class SigningAuthority:
    def __init__(self,store,key,key_id,ledger,allowed_uids):
        self.store=store;self.key=Path(key).absolute();self.key_id=key_id;self.allowed_uids=set(allowed_uids)
        if not isinstance(key_id,str) or not re.fullmatch('[A-Za-z0-9._-]{1,64}',key_id):raise ValueError('invalid_input')
        if os.geteuid() in self.allowed_uids:raise ValueError('签名服务必须使用独立身份')
        from .ota_publish import regular
        regular(self.key,16384);info=self.key.stat()
        if info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600 or stat.S_IMODE(self.key.parent.stat().st_mode)!=0o700:raise ValueError('私钥权限无效')
        probe=subprocess.run(['openssl','pkey','-in',str(self.key),'-text_pub','-noout'],capture_output=True,timeout=10,check=True)
        if b'prime256v1' not in probe.stdout:raise ValueError('仅支持 P-256 私钥')
        self.ledger=Path(ledger).absolute()
        if self.ledger.parent!=self.key.parent or self.ledger.is_symlink():raise ValueError('签名审计必须位于私钥目录')
        if not self.ledger.exists():
            fd=os.open(self.ledger,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        db=sqlite3.connect(self.ledger)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS signatures(model TEXT,channel TEXT,sequence INTEGER,release_sha256 TEXT,kind TEXT,payload_sha256 TEXT,envelope TEXT,created_at INTEGER,UNIQUE(kind,payload_sha256))');db.commit()
        finally:db.close()
    def sign(self,request):
        if set(request)!={'kind','object_id','revision','payload_b64'} or request['kind'] not in DOMAINS:raise ValueError('invalid_input')
        kind=request['kind'];raw=unb64(request['payload_b64']);value=payload_contract(kind,raw)
        release,release_value=self.authorize(kind,request['object_id'],request['revision'],raw,value)
        db=sqlite3.connect(self.ledger)
        try:
            db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT envelope FROM signatures WHERE kind=? AND payload_sha256=?',(kind,digest(raw))).fetchone()
            if old:return strict_json(old[0].encode(),352*1024)
            previous=db.execute('SELECT release_sha256 FROM signatures WHERE model=? AND channel=? AND sequence=?',(release['model'],release['channel'],release['sequence'])).fetchall()
            release_sha=digest(release['payload'].encode())
            if kind=='deployment' and not db.execute("SELECT 1 FROM signatures WHERE kind='release' AND payload_sha256=?",(release_sha,)).fetchone():raise ValueError('forbidden')
            if any(item[0]!=release_sha for item in previous):raise ValueError('incompatible_release')
            highest=db.execute('SELECT MAX(sequence) FROM signatures WHERE model=? AND channel=?',(release['model'],release['channel'])).fetchone()[0] or 0
            if kind=='release' and value['sequence']<highest:raise ValueError('incompatible_release')
            signature=subprocess.run(['openssl','dgst','-sha256','-sign',str(self.key)],input=DOMAINS[kind]+raw,capture_output=True,timeout=10,check=True).stdout
            envelope=dict(schema=1,key_id=self.key_id,payload_b64=b64(raw),signature_b64=b64(signature));envelope_payload(envelope,kind)
            # 签名后再次读取策略，过期结果不会登记给调用方。
            self.authorize(kind,request['object_id'],request['revision'],raw,value)
            db.execute('INSERT INTO signatures VALUES(?,?,?,?,?,?,?,?)',(release['model'],release['channel'],release['sequence'],release_sha,kind,digest(raw),encode(envelope).decode(),int(time.time())));db.commit()
            return envelope
        finally:db.close()
    def authorize(self,kind,object_id,revision,raw,value):
        hex_value(object_id,32)
        with self.store.db() as db:
            if kind=='release':release=db.execute('SELECT * FROM ota_releases WHERE release_id=?',(object_id,)).fetchone()
            else:
                grant=db.execute('SELECT * FROM ota_grants WHERE grant_id=?',(object_id,)).fetchone()
                if not grant or grant['state']!='PENDING':raise ValueError('forbidden')
                target=db.execute('SELECT * FROM ota_targets WHERE target_id=?',(grant['target_id'],)).fetchone()
                campaign=db.execute('SELECT * FROM ota_campaigns WHERE campaign_id=?',(target['campaign_id'],)).fetchone()
                if campaign['state']!='RUNNING' or campaign['revision']!=revision or target['batch']!=campaign['batch']:raise ValueError('forbidden')
                release=db.execute('SELECT * FROM ota_releases WHERE release_id=?',(target['release_id'],)).fetchone()
            if not release or release['state']!=('VALIDATED' if kind=='release' else 'APPROVED') or (kind=='release' and release['revision']!=revision):raise ValueError('release_revoked')
            approved=strict_json(release['payload'].encode())
            input_row=db.execute('SELECT data FROM ota_inputs WHERE input_sha256=?',(release['input_sha256'],)).fetchone()
            input_data=strict_json(self.store.read(release['input_sha256'],4*1024*1024),4*1024*1024)
            if input_data!=strict_json(input_row[0].encode(),4*1024*1024):raise ValueError('baseline_mismatch')
            target_package=db.execute('SELECT data FROM ota_baselines WHERE package_sha256=?',(input_data['target'],)).fetchone()
            manifest=strict_json(self.store.read(input_data['target'],262144))
            if manifest!=strict_json(target_package[0].encode())['manifest']:raise ValueError('baseline_mismatch')
            if any(approved[k]!=input_data['meta'][k] for k in ('model','channel','version','native_sha256')) or any(approved[k]!=release[k] for k in ('model','channel','version','sequence')):raise ValueError('incompatible_release')
            expected_files=[{k:f[k] for k in ('path','mode','bytes','sha256','role')} for f in manifest['files']]
            if approved['files']!=expected_files or approved['native_sha256']!=manifest['native_sha256'] or approved['boot_id']!=manifest['boot_id']:raise ValueError('incompatible_release')
            if kind=='release':
                if raw!=release['payload'].encode():raise ValueError('forbidden')
            else:
                job=db.execute('SELECT * FROM ota_jobs WHERE job_id=?',(grant['job_id'],)).fetchone()
                artifact=db.execute('SELECT * FROM ota_artifacts WHERE build_key=?',(job['build_key'],)).fetchone()
                device=db.execute('SELECT * FROM ota_devices WHERE device_id=?',(grant['device_id'],)).fetchone();config=strict_json(device['config'].encode())
                candidate=strict_json(self.store.read(artifact['candidate'],262144));old=candidate['upgrade_from'];check=strict_json(grant['request'].encode())
                if [{k:f[k] for k in ('path','mode','bytes','sha256','role')} for f in candidate['files']]!=approved['files']:raise ValueError('baseline_mismatch')
                for key in ('old_package_sha256','old_native_sha256','old_boot_id','old_inittab_sha256','old_current_sha256','live_superblock_sha256'):
                    if value[key]!=check[key] or old[key]!=check[key]:raise ValueError('baseline_mismatch')
                expected=dict(schema=1,device_id=grant['device_id'],request_nonce=grant['nonce'],release_sha256=digest(release['payload'].encode()),sequence=release['sequence'],candidate_sha256=artifact['candidate'],bundle_sha256=artifact['bundle'],bundle_bytes=len(self.store.read(artifact['bundle'])),helper_sha256=config['helper_sha256'],issued_at=value['issued_at'],expires_at=value['expires_at'],**{k:check[k] for k in ('old_package_sha256','old_native_sha256','old_boot_id','old_inittab_sha256','old_current_sha256','live_superblock_sha256')})
                now=int(time.time())
                if expected!=value or abs(now-value['issued_at'])>30 or value['expires_at']-value['issued_at']!=3600 or device['alert']:raise ValueError('forbidden')
                # 独立协议实现复核闭包，不运行构建输入中的任何代码。
                from .ota_verify import candidate_wire
                wire,_=candidate_wire(self.store,artifact['candidate'],old['old_package_sha256'],old['live_superblock_sha256'])
                if digest(wire)!=artifact['bundle']:raise ValueError('baseline_mismatch')
        from .ota_verify import closure
        closure(self.store,input_data['target'])
        # 全部发布文件对象必须可读取且与签名清单一致。
        package_data=strict_json(target_package[0].encode())
        for item in manifest['files']:
            data=self.store.read(package_data['files'][item['source']])
            if len(data)!=item['bytes'] or digest(data)!=item['sha256']:raise ValueError('baseline_mismatch')
        return dict(release),approved

def serve(authority,path,group):
    path=Path(path).absolute()
    if path.exists() or path.is_symlink() or stat.S_IMODE(path.parent.stat().st_mode)&0o007:raise ValueError('签名 socket 目录权限无效')
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(20)
            try:
                _,uid,_=struct.unpack('3i',self.request.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                if uid not in authority.allowed_uids:raise ValueError('forbidden')
                send(self.request,{'envelope':authority.sign(receive(self.request))})
            except (ValueError,OSError,sqlite3.Error,subprocess.SubprocessError):send(self.request,{'error':'signing_unavailable'})
    with socketserver.UnixStreamServer(str(path),Handler) as server:
        os.chown(path,-1,group);os.chmod(path,0o660)
        try:server.serve_forever()
        finally:path.unlink(missing_ok=True)

def main():
    parser=argparse.ArgumentParser(description='独立身份 OTA 签名服务')
    for flag in ('root','key','ledger','socket'):parser.add_argument('--'+flag,type=Path,required=True)
    parser.add_argument('--key-id',required=True);parser.add_argument('--client-uid',type=int,action='append',required=True);parser.add_argument('--socket-gid',type=int,required=True)
    args=parser.parse_args();serve(SigningAuthority(OtaStore(args.root),args.key,args.key_id,args.ledger,args.client_uid),args.socket,args.socket_gid)
if __name__=='__main__':main()
