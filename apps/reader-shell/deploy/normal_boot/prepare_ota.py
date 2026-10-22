#!/usr/bin/env python3
"""离线准备首次 OTA 接入材料；仅生成文件，不连接或写入设备。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import upgrade_profile


def prepare(package, package_sha256, device_id, model, channel, key_id, public_key, output):
    for value in (device_id,model,channel,key_id):
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,96}',value) or value in ('.','..'):
            raise ValueError('接入标识无效')
    raw=(package/'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=package_sha256:
        raise ValueError('完整引导包摘要不匹配')
    manifest,_=upgrade_profile.capture_old(package,package_sha256)
    native=manifest['native_sha256']
    root=package/'files/user/pandanote/apps/releases'/native
    native_manifest=json.loads((root/'manifest.json').read_bytes())
    if 'device-ota-v1' not in native_manifest.get('capabilities',[]):
        raise ValueError('引导包不包含设备 OTA 能力')
    for name in ('ota/ota-worker.mipsel','ota/pandanote-ota-upgrade.mipsel','ota/helper-manifest.json'):
        if not (root/name).is_file():raise ValueError('引导包 OTA 闭包不完整')
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    pem=public_key.read_bytes()
    key=serialization.load_pem_public_key(pem)
    if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256R1):
        raise ValueError('必须提供已审核的 P-256 发布公钥')
    if output.exists():raise ValueError('输出目录必须不存在，禁止覆盖已有设备状态')
    helper_sha=hashlib.sha256((root/'ota/pandanote-ota-upgrade.mipsel').read_bytes()).hexdigest()
    config=dict(schema=1,device_id=device_id,model=model,channel=channel,keys={key_id:pem.decode('ascii')},helper_path='/user/pandanote/apps/releases/'+native+'/ota/pandanote-ota-upgrade.mipsel',helper_sha256=helper_sha)
    state=dict(schema=1,state='IDLE',attempt_id='',generation=secrets.token_hex(16),confirmed=0,last_check=0,error_code='none',downloaded=0,deferred=0)
    output.mkdir(mode=0o700,parents=True)
    for name in ('user','user/pandanote','user/pandanote/config','user/pandanote/state','user/pandanote/state/ota','user/pandanote/state/ota/attempts'):
        (output/name).mkdir(mode=0o700,exist_ok=True)
    files={'user/pandanote/config/ota.json':json.dumps(config,ensure_ascii=False).encode(),
           'user/pandanote/state/ota/baseline.json':raw,
           'user/pandanote/state/ota/accepted.json':json.dumps(dict(sequence=0,release_sha256='0'*64)).encode(),
           'user/pandanote/state/ota/state.json':json.dumps(state).encode()}
    for name,data in files.items():
        (output/name).write_bytes(data);(output/name).chmod(0o600)
    return dict(device_id=device_id,baseline=package_sha256,helper_sha256=hashlib.sha256((root/'ota/pandanote-ota-upgrade.mipsel').read_bytes()).hexdigest(),output=str(output),device_write_performed=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True);parser.add_argument('--package-sha256',required=True)
    parser.add_argument('--device-id',required=True);parser.add_argument('--model',required=True);parser.add_argument('--channel',required=True)
    parser.add_argument('--key-id',required=True);parser.add_argument('--public-key',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.package,args.package_sha256,args.device_id,args.model,args.channel,args.key_id,args.public_key,args.output),ensure_ascii=False))

if __name__=='__main__':main()
