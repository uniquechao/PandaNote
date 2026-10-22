"""独立 OTA 数据库与不可变对象；读取入口绝不隐式迁移。"""
from contextlib import contextmanager, ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
import uuid

MAX_SEQUENCE = 2**53-1

def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def identifier():
    return uuid.uuid4().hex

def hex_value(value, length=64):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{'+str(length)+'}', value) is None:
        raise ValueError('invalid_input')
    return value

def strict_json(raw, limit=262144):
    if len(raw)>limit:
        raise ValueError('too_large')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('invalid_input')
            result[key]=value
        return result
    try:
        value=json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid_input')))
        def check(item, depth=0):
            if depth>8:raise ValueError('invalid_input')
            if isinstance(item,dict):
                for child in item.values():check(child,depth+1)
            elif isinstance(item,list):
                for child in item:check(child,depth+1)
            elif type(item) is float:raise ValueError('invalid_input')
            elif type(item) is int and abs(item)>MAX_SEQUENCE:raise ValueError('invalid_input')
        check(value)
        return value
    except (UnicodeError, RecursionError, json.JSONDecodeError):raise ValueError('invalid_input') from None

def fsync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

SCHEMA='''
CREATE TABLE ota_schema(version INTEGER NOT NULL CHECK(version=1));
INSERT INTO ota_schema VALUES(1);
CREATE TABLE ota_objects(sha256 TEXT PRIMARY KEY,kind TEXT NOT NULL,bytes INTEGER NOT NULL,verified_at INTEGER NOT NULL);
CREATE TABLE ota_object_seals(sha256 TEXT PRIMARY KEY REFERENCES ota_objects(sha256),device INTEGER,inode INTEGER,bytes INTEGER,mtime INTEGER,ctime INTEGER);
CREATE TABLE ota_devices(device_id TEXT PRIMARY KEY,config TEXT NOT NULL,baseline TEXT,highest_sequence INTEGER NOT NULL DEFAULT 0,last_report INTEGER,observed TEXT,alert TEXT);
CREATE TABLE ota_baselines(package_sha256 TEXT PRIMARY KEY REFERENCES ota_objects(sha256),data TEXT NOT NULL,reviewed INTEGER NOT NULL,source TEXT NOT NULL);
CREATE TABLE ota_inputs(input_sha256 TEXT PRIMARY KEY REFERENCES ota_objects(sha256),data TEXT NOT NULL);
CREATE TABLE ota_sequences(model TEXT,channel TEXT,next_sequence INTEGER NOT NULL,PRIMARY KEY(model,channel));
CREATE TABLE ota_releases(release_id TEXT PRIMARY KEY,model TEXT NOT NULL,channel TEXT NOT NULL,sequence INTEGER NOT NULL,version TEXT NOT NULL,input_sha256 TEXT NOT NULL REFERENCES ota_inputs(input_sha256),state TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,payload TEXT,envelope TEXT,error TEXT,reason TEXT,UNIQUE(model,channel,sequence));
CREATE TABLE ota_campaigns(campaign_id TEXT PRIMARY KEY,release_id TEXT NOT NULL REFERENCES ota_releases(release_id),state TEXT NOT NULL,batch INTEGER NOT NULL DEFAULT 0,policy TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,created_at INTEGER NOT NULL);
CREATE TABLE ota_targets(target_id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES ota_campaigns(campaign_id),release_id TEXT NOT NULL REFERENCES ota_releases(release_id),device_id TEXT NOT NULL REFERENCES ota_devices(device_id),batch INTEGER NOT NULL,state TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,last_report INTEGER,healthy_at INTEGER,phase TEXT,alert TEXT,candidate TEXT,bundle TEXT,UNIQUE(campaign_id,device_id),UNIQUE(release_id,device_id));
CREATE UNIQUE INDEX ota_active_device ON ota_targets(device_id) WHERE active=1;
CREATE TABLE ota_jobs(job_id TEXT PRIMARY KEY,build_key TEXT NOT NULL UNIQUE,target_id TEXT NOT NULL REFERENCES ota_targets(target_id),request TEXT NOT NULL,state TEXT NOT NULL,generation INTEGER NOT NULL DEFAULT 0,lease_until INTEGER NOT NULL DEFAULT 0,started_at INTEGER,tries INTEGER NOT NULL DEFAULT 0,error TEXT);
CREATE TABLE ota_artifacts(build_key TEXT PRIMARY KEY REFERENCES ota_jobs(build_key),candidate TEXT NOT NULL REFERENCES ota_baselines(package_sha256),bundle TEXT NOT NULL REFERENCES ota_objects(sha256));
CREATE TABLE ota_grants(grant_id TEXT PRIMARY KEY,device_id TEXT NOT NULL REFERENCES ota_devices(device_id),nonce TEXT NOT NULL,request_sha256 TEXT NOT NULL,request TEXT NOT NULL,target_id TEXT NOT NULL REFERENCES ota_targets(target_id),job_id TEXT NOT NULL REFERENCES ota_jobs(job_id),state TEXT NOT NULL,envelope TEXT,expires_at INTEGER,created_at INTEGER NOT NULL,UNIQUE(device_id,nonce));
CREATE TABLE ota_attempts(device_id TEXT,attempt_id TEXT,target_id TEXT NOT NULL REFERENCES ota_targets(target_id),sequence INTEGER NOT NULL,bundle TEXT NOT NULL,state TEXT NOT NULL,alert TEXT,PRIMARY KEY(device_id,attempt_id));
CREATE TABLE ota_events(received INTEGER PRIMARY KEY AUTOINCREMENT,device_id TEXT,event_id TEXT,attempt_id TEXT,body_sha256 TEXT NOT NULL,raw TEXT NOT NULL,created_at INTEGER NOT NULL,UNIQUE(device_id,event_id));
CREATE TABLE ota_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,actor TEXT NOT NULL,action TEXT NOT NULL,object_id TEXT NOT NULL,before_revision INTEGER,after_revision INTEGER,result TEXT NOT NULL,created_at INTEGER NOT NULL,request_id TEXT NOT NULL);
CREATE TABLE ota_idempotency(actor TEXT,operation TEXT,key TEXT,body_sha256 TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(actor,operation,key));
CREATE TABLE ota_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
'''

class OtaStore:
    def __init__(self,root,clock=time.time):
        self.root=Path(root).absolute();self.clock=clock
    def guard(self):
        for path in [*self.root.parents,self.root,self.root/'state.sqlite3',self.root/'objects',self.root/'staging']:
            if path.is_symlink():raise ValueError('storage_failure')
        if self.root.exists() and stat.S_IMODE(self.root.stat().st_mode)!=0o700:raise ValueError('storage_failure')
        for name in ('objects','staging'):
            directory=self.root/name
            if directory.exists() and (not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode)!=0o700):raise ValueError('storage_failure')
        database=self.root/'state.sqlite3'
        if database.exists():
            info=database.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600:raise ValueError('storage_failure')
    def initialize(self):
        self.guard();self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        for name in ('objects','staging'):(self.root/name).mkdir(mode=0o700,exist_ok=True)
        if (self.root/'state.sqlite3').exists():
            with self.db():pass
            return
        fd=os.open(self.root/'state.sqlite3',os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600);os.close(fd)
        db=sqlite3.connect(self.root/'state.sqlite3')
        try:
            db.execute('PRAGMA synchronous=FULL');db.executescript('BEGIN IMMEDIATE;'+SCHEMA+'COMMIT;')
        finally:db.close()
        fsync_dir(self.root)
    @contextmanager
    def db(self,write=False):
        self.guard()
        db=sqlite3.connect((self.root/'state.sqlite3').as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=5)
        db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA synchronous=FULL');db.execute('PRAGMA busy_timeout=5000')
            if [tuple(r) for r in db.execute('SELECT version FROM ota_schema')]!=[(1,)]:raise ValueError('storage_failure')
            if write:db.execute('BEGIN IMMEDIATE')
            yield db
            if write:db.commit()
        except BaseException:
            db.rollback();raise
        finally:db.close()
    def put(self,raw,kind):
        if not isinstance(raw,bytes) or len(raw)>256*1024*1024:raise ValueError('too_large')
        key=digest(raw);self.guard();target=self.root/'objects'/key
        if target.exists():
            if self.read(key,limit=max(len(raw),1),indexed=False)!=raw:raise ValueError('storage_failure')
        else:
            temporary=self.root/'staging'/identifier()
            fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:
                with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
                # 不覆盖已有摘要；并发导入只接受相同原始字节。
                try:os.link(temporary,target)
                except FileExistsError:pass
            finally:temporary.unlink(missing_ok=True)
            fsync_dir(self.root/'objects');fsync_dir(self.root/'staging')
            if self.read(key,limit=max(len(raw),1),indexed=False)!=raw:raise ValueError('storage_failure')
        info=target.stat()
        with self.db(True) as db:
            db.execute('INSERT OR IGNORE INTO ota_objects VALUES(?,?,?,?)',(key,kind,len(raw),int(self.clock())))
            db.execute('INSERT OR REPLACE INTO ota_object_seals VALUES(?,?,?,?,?,?)',(key,info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns))
        return key
    def read(self,key,limit=24*1024*1024,indexed=True):
        hex_value(key);self.guard()
        from .reader import _directory
        with ExitStack() as stack:
            parent=_directory(self.root/'objects',stack)
            fd=os.open(key,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
            with os.fdopen(fd,'rb') as handle:
                info=os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600 or info.st_size>limit:raise ValueError('storage_failure')
                raw=handle.read(limit+1);after=os.fstat(handle.fileno())
                if (info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) or len(raw)!=info.st_size or digest(raw)!=key:raise ValueError('storage_failure')
        if indexed:
            with self.db() as db:row=db.execute('SELECT bytes FROM ota_objects WHERE sha256=?',(key,)).fetchone()
            if row is None or row['bytes']!=len(raw):raise ValueError('storage_failure')
        return raw
    def chunk(self,key,index):
        hex_value(key)
        if type(index) is not int or index<0:raise ValueError('invalid_input')
        self.guard()
        with self.db() as db:row=db.execute('SELECT o.bytes,s.device,s.inode,s.mtime,s.ctime FROM ota_objects o JOIN ota_object_seals s USING(sha256) WHERE sha256=?',(key,)).fetchone()
        if row is None or index*262144>=row['bytes']:raise ValueError('not_found')
        from .reader import _directory
        with ExitStack() as stack:
            parent=_directory(self.root/'objects',stack)
            fd=os.open(key,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
            with os.fdopen(fd,'rb') as handle:
                before=os.fstat(handle.fileno())
                if (before.st_dev,before.st_ino,before.st_mtime_ns,before.st_ctime_ns)!=(row['device'],row['inode'],row['mtime'],row['ctime']) or not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size!=row['bytes'] or stat.S_IMODE(before.st_mode)!=0o600:raise ValueError('storage_failure')
                handle.seek(index*262144);raw=handle.read(min(262144,before.st_size-index*262144))
                after=os.fstat(handle.fileno())
                if len(raw)!=min(262144,before.st_size-index*262144) or (before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('storage_failure')
                return raw
    def audit(self,db,actor,action,object_id,before=None,after=None,result='ok',request_id=None):
        db.execute('INSERT INTO ota_audit(actor,action,object_id,before_revision,after_revision,result,created_at,request_id) VALUES(?,?,?,?,?,?,?,?)',(actor,action,object_id,before,after,result,int(self.clock()),request_id or identifier()))
    def verify(self):
        with self.db() as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or list(db.execute('PRAGMA foreign_key_check')):raise ValueError('storage_failure')
            objects=list(db.execute('SELECT sha256,bytes FROM ota_objects'))
            for row in db.execute('SELECT model,channel,MAX(sequence) AS high FROM ota_releases GROUP BY model,channel'):
                seq=db.execute('SELECT next_sequence FROM ota_sequences WHERE model=? AND channel=?',(row['model'],row['channel'])).fetchone()
                if not seq or seq[0]<=row['high']:raise ValueError('storage_failure')
        for row in objects:self.read(row['sha256'],max(1,row['bytes']))
        return [row['sha256'] for row in objects]
    def backup(self,destination):
        destination=Path(destination);destination.mkdir(mode=0o700,exist_ok=False)
        snapshot=OtaStore(destination,self.clock);(destination/'objects').mkdir(mode=0o700);(destination/'staging').mkdir(mode=0o700)
        fd=os.open(destination/'state.sqlite3',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        with self.db() as source:
            output=sqlite3.connect(destination/'state.sqlite3')
            try:source.backup(output)
            finally:output.close()
        with snapshot.db() as db:objects=list(db.execute('SELECT sha256,bytes FROM ota_objects'))
        for row in objects:
            raw=self.read(row['sha256'],max(1,row['bytes']));path=destination/'objects'/row['sha256']
            fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
        snapshot.verify()
        with snapshot.db(True) as db:
            for row in objects:
                info=(destination/'objects'/row['sha256']).stat()
                db.execute('INSERT OR REPLACE INTO ota_object_seals VALUES(?,?,?,?,?,?)',(row['sha256'],info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns))
        fsync_dir(destination/'objects');fsync_dir(destination)
        return snapshot
