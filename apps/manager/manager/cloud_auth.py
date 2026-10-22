"""Explicit cloud trust profile; passwords/tokens never enter application logs."""
from dataclasses import dataclass,field
import base64
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import time
from urllib.parse import urlsplit

COOKIE='__Secure-pandanote_admin'
def hash_password(password):
    if not isinstance(password,str) or not 12<=len(password)<=256:
        raise ValueError('admin password must contain 12-256 characters')
    salt=secrets.token_bytes(16)
    return 'pbkdf2_sha256$600000$'+salt.hex()+'$'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000).hex()

def password_parts(encoded):
    if not isinstance(encoded,str) or re.fullmatch(r'pbkdf2_sha256\$(600000|[6-9][0-9]{5}|1[01][0-9]{5}|1200000)\$[0-9a-f]{32}\$[0-9a-f]{64}',encoded) is None:
        raise ValueError('invalid private admin hash')
    _,rounds,salt,digest=encoded.split('$')
    return int(rounds),bytes.fromhex(salt),bytes.fromhex(digest)

@dataclass(repr=False)
class CloudProfile:
    origin:str
    admin_password_hash:str=field(repr=False)
    device_credentials:dict=field(repr=False)
    prefix:str='/pandanote'
    admin_username:str='admin'
    session_seconds:int=28800
    def __post_init__(self):
        if not isinstance(self.origin,str):raise ValueError('invalid HTTPS origin')
        parsed=urlsplit(self.origin)
        hostname=parsed.hostname or ''
        if not hostname or len(hostname)>253 or '.' not in hostname or any(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',part) is None for part in hostname.split('.')) or self.origin!='https://'+hostname or self.prefix!='/pandanote':
            raise ValueError('explicit canonical PandaNote HTTPS origin/prefix required')
        if not isinstance(self.admin_username,str) or re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',self.admin_username) is None:
            raise ValueError('invalid admin account')
        password_parts(self.admin_password_hash)
        if type(self.session_seconds) is not int or not 300<=self.session_seconds<=28800:
            raise ValueError('invalid session lifetime')
        if not isinstance(self.device_credentials,dict) or not 1<=len(self.device_credentials)<=32:
            raise ValueError('explicit device credential hashes required')
        if any(not isinstance(k,str) or re.fullmatch(r'[A-Za-z0-9_-]{1,64}',k) is None or not isinstance(v,str) or re.fullmatch(r'[0-9a-f]{64}',v) is None for k,v in self.device_credentials.items()):
            raise ValueError('invalid device credential hashes')
        if len(set(self.device_credentials.values()))!=len(self.device_credentials):raise ValueError('duplicate device credential')
        self.device_credentials=dict(self.device_credentials)
    @classmethod
    def from_file(cls,path):
        # Pin every component, then read the same verified descriptor once.
        from .reader import _directory
        from contextlib import ExitStack
        path=Path(path).absolute()
        with ExitStack() as stack:
            parent=_directory(path.parent,stack);info=os.fstat(parent)
            if info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700:raise ValueError('unsafe private profile directory')
            fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent);stack.callback(os.close,fd);info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600 or not 1<=info.st_size<=16384:raise ValueError('unsafe private profile')
            raw=os.read(fd,16385)
            if len(raw)!=info.st_size:raise ValueError('private profile changed')
        def unique(pairs):
            out={}
            for k,v in pairs:
                if k in out:raise ValueError('duplicate profile field')
                out[k]=v
            return out
        value=json.loads(raw,object_pairs_hook=unique)
        if not isinstance(value,dict):raise ValueError('invalid private profile')
        if value.pop('schema',1)!=1:raise ValueError('invalid private profile schema')
        try:return cls(**value)
        except TypeError:raise ValueError('invalid private profile fields') from None
    def trusted_request(self,request):
        try:local=ipaddress.ip_address(request.client.host).is_loopback
        except (ValueError,AttributeError):local=False
        return local and request.headers.getlist('host')==[urlsplit(self.origin).netloc]
    def login_peer(self,request):
        # Only called after exact Host + loopback socket validation. The owned
        # reverse proxy MUST overwrite this dedicated header with remote_addr;
        # general Forwarded/X-Forwarded-For headers never influence a bucket.
        values=request.headers.getlist('x-pandanote-client-ip')
        if self.trusted_request(request) and len(values)==1 and len(values[0])<=64:
            try:return str(ipaddress.ip_address(values[0]))
            except ValueError:pass
        return request.client.host
    def same_origin(self,request,required=False):
        origins=request.headers.getlist('origin');refs=request.headers.getlist('referer')
        if len(origins)>1 or len(refs)>1:return False
        if origins and origins[0]!=self.origin:return False
        if refs:
            try:ref=urlsplit(refs[0])
            except ValueError:return False
            if ref.scheme+'://'+ref.netloc!=self.origin:return False
        if request.headers.get('sec-fetch-site') in {'cross-site','same-site'}:return False
        return not required or bool(origins or refs)
    def device(self,request):
        values=request.headers.getlist('authorization')
        if len(values)!=1 or re.fullmatch(r'Bearer [A-Za-z0-9_-]{43}',values[0]) is None:return None
        token=values[0][7:]
        try:
            raw=base64.urlsafe_b64decode(token+'=')
            if len(raw)!=32 or base64.urlsafe_b64encode(raw).decode().rstrip('=')!=token:return None
        except ValueError:return None
        digest=hashlib.sha256(token.encode('ascii')).hexdigest();found=None
        for name,expected in self.device_credentials.items():
            if hmac.compare_digest(digest,expected):found=name
        return found

class CloudAuth:
    def __init__(self,profile,clock=time.monotonic):
        self.profile=profile;self.clock=clock;self.sessions={};self.attempts={};self.global_attempts=[];self.lock=threading.RLock()
    @staticmethod
    def key(token):return hashlib.sha256(token.encode()).hexdigest()
    def session(self,token):
        if not isinstance(token,str) or re.fullmatch(r'[A-Za-z0-9_-]{43}',token) is None:return None
        with self.lock:
            now=self.clock();self.sessions={k:v for k,v in self.sessions.items() if v['expires']>now}
            return self.sessions.get(self.key(token))
    def allow_login(self,peer):
        with self.lock:
            now=self.clock();self.attempts={k:[v for v in values if now-v<300] for k,values in self.attempts.items() if any(now-v<300 for v in values)}
            self.global_attempts=[v for v in self.global_attempts if now-v<60]
            values=self.attempts.get(peer,[])
            if len(values)>=6 or len(self.global_attempts)>=60 or (peer not in self.attempts and len(self.attempts)>=256):return False
            self.attempts[peer]=values+[now];self.global_attempts.append(now);return True
    def login(self,username,password,old_token=''):
        if not isinstance(username,str) or not isinstance(password,str) or len(username)>64 or not 1<=len(password)<=256:return None
        rounds,salt,want=password_parts(self.profile.admin_password_hash)
        try:
            password_bytes=password.encode();username_bytes=username.encode()
        except UnicodeError:return None
        got=hashlib.pbkdf2_hmac('sha256',password_bytes,salt,rounds)
        if not (hmac.compare_digest(got,want)&hmac.compare_digest(username_bytes,self.profile.admin_username.encode())):return None
        with self.lock:
            token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32);now=self.clock()
            self.sessions={k:v for k,v in self.sessions.items() if v['expires']>now}
            if old_token:self.sessions.pop(self.key(old_token),None)
            if len(self.sessions)>=64:self.sessions.pop(next(iter(self.sessions)))
            self.sessions[self.key(token)]=dict(csrf=csrf,expires=now+self.profile.session_seconds)
            return token,csrf
    def logout(self,token):
        with self.lock:self.sessions.pop(self.key(token),None)
