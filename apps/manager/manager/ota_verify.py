"""签名进程使用的独立闭包与 wire 校验；不导入输入快照中的代码。"""
from .ota_store import strict_json,digest,hex_value
from .ota_publish import files_contract

def closure(store,key):
    raw=store.read(key,262144);manifest=strict_json(raw)
    with store.db() as db:row=db.execute('SELECT data FROM ota_baselines WHERE package_sha256=?',(key,)).fetchone()
    if not row:raise ValueError('baseline_unsupported')
    record=strict_json(row[0].encode(),4*1024*1024)
    if record['manifest']!=manifest or manifest.get('schema')!=1 or manifest.get('profile')!='normal-persistent-v1' or manifest.get('device_apply_supported') is not False:raise ValueError('baseline_mismatch')
    public=[{k:f[k] for k in ('path','mode','bytes','sha256','role')} for f in manifest['files']];files_contract(public,manifest['native_sha256'],manifest['boot_id'])
    files={}
    if set(record['files'])!={f['source'] for f in manifest['files']}:raise ValueError('baseline_mismatch')
    for item in manifest['files']:
        if item['source']!='files/'+item['path'][1:]:raise ValueError('baseline_mismatch')
        data=store.read(record['files'][item['source']])
        if digest(data)!=item['sha256'] or len(data)!=item['bytes']:raise ValueError('baseline_mismatch')
        files[item['path']]=(item,data)
    native=manifest['native_sha256'];boot=manifest['boot_id'];release='/user/pandanote/apps/releases/'+native+'/';system='/etc/pandanote-system/'+boot+'/'
    if files['/user/pandanote/apps/current'][1]!=(native+'\n').encode() or system.encode() not in files['/etc/inittab'][1]:raise ValueError('baseline_mismatch')
    for name in (system+'service.sh',system+'policy.sh',system+'child-supervisor.sh',system+'SHA256SUMS',release+'manifest.json',release+'reader-shell.mipsel',release+'release.sha256'):
        if name not in files:raise ValueError('baseline_mismatch')
    native_raw=files[release+'manifest.json'][1]
    if digest(native_raw)!=native:raise ValueError('baseline_mismatch')
    meta=strict_json(native_raw)
    for artifact in meta['artifacts']:
        item,data=files[release+artifact['path']]
        if artifact['sha256']!=item['sha256'] or artifact['bytes']!=len(data):raise ValueError('baseline_mismatch')
    for index,base in ((release+'release.sha256',release),(system+'SHA256SUMS',system)):
        seen=set()
        for line in files[index][1].decode('ascii').splitlines():
            sha,name=line.split('  ',1);path=base+name;hex_value(sha)
            if path in seen or path not in files or digest(files[path][1])!=sha:raise ValueError('baseline_mismatch')
            seen.add(path)
        if seen!={p for p in files if p.startswith(base) and p!=index}:raise ValueError('baseline_mismatch')
    return manifest,files

def candidate_wire(store,key,old_key,superblock):
    candidate,files=closure(store,key);old,old_files=closure(store,old_key);hex_value(superblock)
    expected=dict(schema=1,profile='normal-exact-upgrade-v1',old_package_sha256=old_key,old_native_sha256=old['native_sha256'],old_boot_id=old['boot_id'],old_inittab_sha256=old_files['/etc/inittab'][0]['sha256'],old_current_sha256=old_files['/user/pandanote/apps/current'][0]['sha256'],live_superblock_sha256=superblock,old_files=[{k:f[k] for k in ('path','mode','bytes','sha256')} for f,_ in old_files.values() if f['role'] in ('system','release')])
    if candidate.get('upgrade_from')!=expected or candidate.get('old_inittab_sha256')!=expected['old_inittab_sha256'] or candidate['native_sha256']==old['native_sha256'] or candidate['boot_id']==old['boot_id']:raise ValueError('baseline_mismatch')
    base=expected;wire=bytearray(f"PANDANOTE-UPGRADE-1 {candidate['boot_id']} {candidate['native_sha256']} {base['old_inittab_sha256']} {len(files)}\n".encode())
    wire.extend(f"BASE {old_key} {base['old_native_sha256']} {base['old_boot_id']} {base['old_current_sha256']} {superblock} {len(base['old_files'])}\n".encode())
    for f in base['old_files']:wire.extend(f"CHECK {f['mode']:o} {f['bytes']} {f['sha256']} {f['path']}\n".encode())
    for path,(item,data) in files.items():
        wire.extend(f"{item['role']} {item['mode']:o} {len(data)} {digest(data)} {path}\n".encode());wire.extend(data);wire.extend(b'\n')
    if len(wire)>24*1024*1024:raise ValueError('too_large')
    return bytes(wire),candidate
