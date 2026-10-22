"""受控离线维护入口；Web 不接受路径、归档或远程 URL。"""
import argparse
import importlib.util
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
from .ota_store import OtaStore, digest, encode, hex_value, strict_json, identifier

MAX_BUNDLE=24*1024*1024

def regular(path,limit=MAX_BUNDLE):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in [*path.parents,path]):raise ValueError('invalid_input')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as source:
        info=os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 0<=info.st_size<=limit:raise ValueError('invalid_input')
        raw=source.read(limit+1)
        after=os.fstat(source.fileno())
        if len(raw)!=info.st_size or (info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('invalid_input')
        return raw

def safe_name(value):
    if not isinstance(value,str) or not re.fullmatch('[A-Za-z0-9._/-]+',value) or value.startswith('/') or str(PurePosixPath(value))!=value or '..' in PurePosixPath(value).parts:raise ValueError('invalid_input')
    return value

def files_contract(files,native,boot):
    hex_value(native);hex_value(boot,24)
    if not isinstance(files,list) or not 4<=len(files)<=128:raise ValueError('invalid_input')
    seen=set();total=0;result=[]
    for item in files:
        if not isinstance(item,dict) or set(item)!={'path','mode','bytes','sha256','role'}:raise ValueError('invalid_input')
        path=item['path'];role=item['role'];mode=item['mode'];size=item['bytes'];hex_value(item['sha256'])
        if not isinstance(path,str) or not path.startswith('/') or safe_name(path[1:])!=path[1:] or path in seen:raise ValueError('invalid_input')
        allowed=(role=='release' and path.startswith('/user/pandanote/apps/releases/'+native+'/') and mode in (0o600,0o700)) or (role=='system' and path.startswith('/etc/pandanote-system/'+boot+'/') and mode==0o600) or (role=='pointer' and path=='/user/pandanote/apps/current' and mode==0o600) or (role=='entry' and path=='/etc/inittab' and mode==0o644)
        if not allowed or type(mode) is not int or type(size) is not int or not 0<=size<=MAX_BUNDLE:raise ValueError('invalid_input')
        if any(path.startswith(prior+'/') or prior.startswith(path+'/') for prior in seen):raise ValueError('invalid_input')
        seen.add(path);total+=size;result.append(item)
    if total>MAX_BUNDLE or '/etc/inittab' not in seen or '/user/pandanote/apps/current' not in seen:raise ValueError('invalid_input')
    return result

def tool_module(snapshot,name):
    path=Path(snapshot)/'apps/reader-shell/deploy/normal_boot'/(name+'.py')
    spec=importlib.util.spec_from_file_location('ota_'+name+'_'+identifier(),path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def import_package(store,directory,*,reviewed=False,source='offline',snapshot=None):
    directory=Path(directory);raw=regular(directory/'manifest.json',262144);manifest=strict_json(raw)
    native=manifest.get('native_sha256');boot=manifest.get('boot_id')
    supplied=manifest.get('files',[])
    public=[{k:item[k] for k in ('path','mode','bytes','sha256','role')} for item in supplied]
    files_contract(public,native,boot);refs={};expected={'manifest.json'}
    for item in supplied:
        name=safe_name(item['source']);expected.add(name);data=regular(directory/name)
        if digest(data)!=item['sha256'] or len(data)!=item['bytes'] or stat.S_IMODE((directory/name).stat().st_mode)!=item['mode']:raise ValueError('baseline_mismatch')
        refs[name]=store.put(data,'package_file')
    actual=set()
    for path in directory.rglob('*'):
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):raise ValueError('invalid_input')
        if path.is_file():actual.add(path.relative_to(directory).as_posix())
    if actual!=expected:raise ValueError('invalid_input')
    # 可信旧包必须经过现有 NORMAL 完整索引校验。
    if snapshot is not None:tool_module(snapshot,'upgrade_profile').capture_old(directory,digest(raw))
    elif reviewed:raise ValueError('baseline_unsupported')
    key=store.put(raw,'package_manifest');data=dict(manifest=manifest,files=refs)
    with store.db(True) as db:
        existing=db.execute('SELECT data FROM ota_baselines WHERE package_sha256=?',(key,)).fetchone()
        if existing and strict_json(existing['data'].encode())!=data:raise ValueError('baseline_mismatch')
        db.execute('INSERT OR IGNORE INTO ota_baselines VALUES(?,?,?,?)',(key,encode(data).decode(),int(reviewed),source))
    return key

def materialize_package(store,key,destination):
    hex_value(key)
    with store.db() as db:row=db.execute('SELECT data FROM ota_baselines WHERE package_sha256=?',(key,)).fetchone()
    if not row:raise ValueError('baseline_unsupported')
    data=strict_json(row['data'].encode());destination=Path(destination);destination.mkdir(mode=0o700,exist_ok=False)
    raw=store.read(key,262144);(destination/'manifest.json').write_bytes(raw)
    modes={item['source']:item['mode'] for item in data['manifest']['files']}
    for name,sha in data['files'].items():
        safe_name(name);path=destination/name;path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.write_bytes(store.read(sha));path.chmod(modes[name])
    return data['manifest']

def import_tree(store,directory):
    directory=Path(directory);refs={};total=0
    for path in sorted(directory.rglob('*')):
        if any(part in {'.git','node_modules','__pycache__'} for part in path.relative_to(directory).parts):continue
        if path.is_symlink():raise ValueError('invalid_input')
        if path.is_dir():continue
        name=safe_name(path.relative_to(directory).as_posix());raw=regular(path,256*1024*1024);total+=len(raw)
        if total>256*1024*1024 or len(refs)>=8192:raise ValueError('too_large')
        refs[name]=dict(sha256=store.put(raw,'snapshot_file'),mode=stat.S_IMODE(path.stat().st_mode)&0o777)
    return refs

def materialize_tree(store,refs,destination):
    destination=Path(destination);destination.mkdir(mode=0o700,exist_ok=False)
    for name,item in refs.items():
        safe_name(name);path=destination/name;path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        path.write_bytes(store.read(item['sha256'],256*1024*1024));path.chmod(0o700 if item['mode']&0o111 else 0o600)

def import_input(store,directory):
    """固定结构：input.json、snapshot/、native/、reference/、radio/、suspend/、target/。"""
    directory=Path(directory);meta=strict_json(regular(directory/'input.json',16384))
    required={'schema','model','channel','native_sha256','suspend_helper_sha256','toolchain_sha256','radio_binary','version'}
    if set(meta)!=required or type(meta['schema']) is not int or meta['schema']!=1:raise ValueError('invalid_input')
    for key in ('native_sha256','suspend_helper_sha256','toolchain_sha256'):hex_value(meta[key])
    for key in ('model','channel','version'):
        if not isinstance(meta[key],str) or not re.fullmatch('[A-Za-z0-9._-]{1,64}',meta[key]):raise ValueError('invalid_input')
    safe_name(meta['radio_binary'])
    trees={name:import_tree(store,directory/name) for name in ('snapshot','native','reference','radio','suspend')}
    for name in ('build.py','upgrade_profile.py','normal_upgrade.py','transaction.py'):
        if 'apps/reader-shell/deploy/normal_boot/'+name not in trees['snapshot']:raise ValueError('invalid_input')
    target=import_package(store,directory/'target',snapshot=directory/'snapshot')
    with store.db() as db:target_data=strict_json(db.execute('SELECT data FROM ota_baselines WHERE package_sha256=?',(target,)).fetchone()[0].encode())
    if target_data['manifest']['native_sha256']!=meta['native_sha256']:raise ValueError('incompatible_release')
    data=dict(meta=meta,trees=trees,target=target);raw=encode(data);key=store.put(raw,'release_input')
    with store.db(True) as db:
        db.execute('INSERT OR IGNORE INTO ota_inputs VALUES(?,?)',(key,raw.decode()));store.audit(db,'maintenance','import',key)
    return key

def enroll(store,value):
    required={'device_id','credential_sha256','model','channels','ota_abi','helper_sha256','bootstrap_version','baseline','unique_credential_verified'}
    if set(value)!=required or value['unique_credential_verified'] is not True:raise ValueError('invalid_input')
    if not isinstance(value['device_id'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',value['device_id']):raise ValueError('invalid_input')
    for key in ('credential_sha256','helper_sha256','baseline'):hex_value(value[key])
    if type(value['ota_abi']) is not int or value['ota_abi']!=1 or not isinstance(value['channels'],list) or not value['channels'] or any(not isinstance(c,str) or not re.fullmatch('[A-Za-z0-9._-]{1,64}',c) for c in value['channels']):raise ValueError('invalid_input')
    if not isinstance(value['model'],str) or not re.fullmatch('[A-Za-z0-9._-]{1,64}',value['model']) or not isinstance(value['bootstrap_version'],str) or not 1<=len(value['bootstrap_version'])<=64:raise ValueError('invalid_input')
    with store.db(True) as db:
        baseline=db.execute('SELECT reviewed FROM ota_baselines WHERE package_sha256=?',(value['baseline'],)).fetchone()
        if not baseline or not baseline[0]:raise ValueError('baseline_unsupported')
        if db.execute('SELECT 1 FROM ota_devices WHERE device_id=?',(value['device_id'],)).fetchone():raise ValueError('attempt_conflict')
        for row in db.execute('SELECT config FROM ota_devices'):
            if strict_json(row[0].encode())['credential_sha256']==value['credential_sha256']:raise ValueError('ota_not_enrolled')
        db.execute('INSERT INTO ota_devices(device_id,config,baseline) VALUES(?,?,?)',(value['device_id'],encode(value).decode(),value['baseline']));store.audit(db,'maintenance','enroll',value['device_id'])

def reconcile(store,value):
    """仅离线维护接入；操作员已经完成实际恢复及完整基线核对。"""
    required={'device_id','target_id','baseline','recovery_verified','reason'}
    if set(value)!=required or value['recovery_verified'] is not True or not isinstance(value['reason'],str) or not 1<=len(value['reason'])<=512:raise ValueError('invalid_input')
    hex_value(value['target_id'],32);hex_value(value['baseline'])
    from .ota_verify import closure
    closure(store,value['baseline'])
    with store.db(True) as db:
        baseline=db.execute('SELECT reviewed FROM ota_baselines WHERE package_sha256=?',(value['baseline'],)).fetchone()
        target=db.execute('SELECT * FROM ota_targets WHERE target_id=? AND device_id=?',(value['target_id'],value['device_id'])).fetchone()
        if not baseline or not baseline[0] or not target or not target['active']:raise ValueError('attempt_conflict')
        db.execute('UPDATE ota_devices SET baseline=?,alert=NULL WHERE device_id=?',(value['baseline'],value['device_id']))
        db.execute("UPDATE ota_targets SET active=0,state='FAILED',alert=NULL WHERE target_id=?",(value['target_id'],))
        store.audit(db,'maintenance','recovery.reconcile',value['target_id'],result=value['reason'])


def main():
    parser=argparse.ArgumentParser(description='OTA 受控维护工具')
    parser.add_argument('--root',required=True,type=Path)
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('init');sub.add_parser('verify')
    p=sub.add_parser('import');p.add_argument('directory',type=Path)
    p=sub.add_parser('baseline');p.add_argument('directory',type=Path);p.add_argument('--snapshot',type=Path,required=True)
    p=sub.add_parser('enroll');p.add_argument('config',type=Path)
    p=sub.add_parser('reconcile');p.add_argument('config',type=Path)
    p=sub.add_parser('backup');p.add_argument('destination',type=Path)
    p=sub.add_parser('restore');p.add_argument('backup',type=Path);p.add_argument('--signing-ledger',type=Path,required=True)
    args=parser.parse_args();store=OtaStore(args.root)
    if args.action=='init':store.initialize()
    elif args.action=='verify':store.verify()
    elif args.action=='import':print(import_input(store,args.directory))
    elif args.action=='baseline':print(import_package(store,args.directory,reviewed=True,snapshot=args.snapshot))
    elif args.action=='enroll':enroll(store,strict_json(regular(args.config,16384)))
    elif args.action=='reconcile':reconcile(store,strict_json(regular(args.config,16384)))
    elif args.action=='backup':store.backup(args.destination)
    elif args.action=='restore':
        # 目标必须不存在，维护者停用 OTA 后显式切换配置，不在线覆盖数据库。
        restored=OtaStore(args.backup).backup(args.root)
        import sqlite3
        ledger=sqlite3.connect(args.signing_ledger.absolute().as_uri()+'?mode=ro',uri=True)
        try:
            with restored.db(True) as db:
                for model,channel,high in ledger.execute('SELECT model,channel,MAX(sequence) FROM signatures GROUP BY model,channel'):
                    db.execute('INSERT INTO ota_sequences VALUES(?,?,?) ON CONFLICT(model,channel) DO UPDATE SET next_sequence=MAX(next_sequence,excluded.next_sequence)',(model,channel,high+1))
        finally:ledger.close()
        restored.verify()

if __name__=='__main__':main()
