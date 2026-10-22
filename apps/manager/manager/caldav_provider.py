"""Read-only, bounded multi-source CalDAV boundary.

RFC 4791 server expansion is preferred. Servers ignoring it use an isolated,
resource-limited recurring-ical-events worker; no custom RRULE interpreter.
No credential or source URL crosses that worker boundary.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import date, datetime, timedelta, timezone
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import selectors
import signal
import subprocess
import sys
import ssl
import stat
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote
import uuid
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from defusedxml.ElementTree import fromstring as safe_xml
from icalendar import Calendar, Timezone

from .content import Settings, days, epoch, text

D, C = 'DAV:', 'urn:ietf:params:xml:ns:caldav'
MAX_BODY, MAX_SOURCES, MAX_CALENDARS, MAX_EVENTS = 2*1024*1024, 8, 200, 200
MAX_REQUESTS, OPERATION_TIMEOUT, SOCKET_TIMEOUT = 64, 30.0, 8.0
_RESOLVERS = ThreadPoolExecutor(max_workers=2, thread_name_prefix='caldav-dns')
_RESOLVER_SLOTS = threading.BoundedSemaphore(2)
_EXPAND_SCRIPT=Path(__file__).with_name('caldav_expand.py')
_EXPAND_LOCK=threading.Lock()
_EXPAND_PENDING=[]
MAX_EXPAND_INPUT=16*1024*1024
MAX_EXPAND_OUTPUT=2*1024*1024
EXPAND_TIMEOUT=5.0


class _Failure(Exception):
    """Only fixed public codes/messages cross the provider boundary."""
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def _fail(code='caldav_invalid', message='CalDAV 返回的数据无效；上次成功内容已保留。'):
    raise _Failure(code, message)


def _public_error(error):
    if isinstance(error, _Failure):
        return dict(schema=1, ok=False, error=dict(code=error.code, message=error.message))
    return dict(schema=1, ok=False, error=dict(code='caldav_failed', message='CalDAV 读取失败；上次成功内容已保留。'))


def _url(value):
    if not isinstance(value, str) or not value or len(value)>4096 or re.search(r'[\x00-\x20\x7f\\<>"`{}|^]', value):
        _fail('caldav_url', '请输入安全的 HTTPS CalDAV 地址。')
    try:
        parts = urlsplit(value)
        if '?' in value or '#' in value or parts.scheme != 'https' or parts.username is not None or parts.password is not None or parts.query or parts.fragment or not parts.hostname:
            raise ValueError()
        host = parts.hostname.encode('idna').decode('ascii').lower()
        if not re.fullmatch(r'[a-z0-9.-]+|[0-9a-f:]+',host) or host.endswith('.') or host in {'localhost','localhost.localdomain'} or host.endswith(('.localhost','.local')):
            raise ValueError()
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError()
        except ValueError:
            # An actual IP literal must be public; a DNS name is checked again
            # at connection time and pinned to the verified public address.
            if ':' in host or re.fullmatch(r'[0-9.]+',host):
                raise
        port = parts.port or 443
        if not 1<=port<=65535:
            raise ValueError()
        path = parts.path or '/'
        decoded = unquote(path, errors='strict')
        if not path.startswith('/') or '//' in decoded or any(s in {'.','..'} for s in decoded.split('/')) or re.search(r'[\x00-\x1f\x7f\\?#%<>"`{}|^]',decoded):
            raise ValueError()
        if re.search(r'%(?![0-9A-Fa-f]{2})',path) or re.search(r'%(?:2f|5c)',path,re.I):
            raise ValueError()
        authority = ('['+host+']') if ':' in host else host
        if port!=443:
            authority += ':'+str(port)
        return urlunsplit(('https',authority,path,'',''))
    except (ValueError, UnicodeError):
        _fail('caldav_url', '请输入安全的 HTTPS CalDAV 地址。')


def _same_origin(base, href):
    result = _url(urljoin(base,href))
    a,b=urlsplit(base),urlsplit(result)
    if (a.hostname,a.port or 443)!=(b.hostname,b.port or 443):
        _fail('caldav_origin','CalDAV 返回了其他主机的地址，已停止读取。')
    return result


def _resolve(host, port, timeout):
    if not _RESOLVER_SLOTS.acquire(blocking=False):
        _fail('caldav_busy','CalDAV 域名解析忙，请稍后重试。')
    future = _RESOLVERS.submit(socket.getaddrinfo,host,port,0,socket.SOCK_STREAM)
    future.add_done_callback(lambda _: _RESOLVER_SLOTS.release())
    try:
        addresses=future.result(timeout=max(0.001,timeout))
    except FutureTimeout:
        _fail('caldav_timeout','CalDAV 读取超时；上次成功内容已保留。')
    # Reject a mixed public/private answer, not merely the first address.
    if not addresses or len(addresses)>32 or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        _fail('caldav_address','CalDAV 服务必须使用公网 HTTPS 地址。')
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        started=time.monotonic()
        addresses=_resolve(self.host,self.port,self.timeout)
        for family,kind,proto,_,address in addresses:
            remaining=self.timeout-(time.monotonic()-started)
            if remaining<=0:
                break
            raw=socket.socket(family,kind,proto)
            raw.settimeout(remaining)
            try:
                raw.connect(address)
                raw.settimeout(max(0.001,self.timeout-(time.monotonic()-started)))
                self.sock=self._context.wrap_socket(raw,server_hostname=self.host)
                return
            except OSError:
                raw.close()
        _fail('caldav_network','无法安全连接 CalDAV 服务；请检查地址和证书。')


_HTTPSConnection = _PinnedHTTPSConnection


def _xml_request(root, props):
    node=ET.Element('{'+D+'}'+root)
    prop=ET.SubElement(node,'{'+D+'}prop')
    for namespace,name in props:
        ET.SubElement(prop,'{'+namespace+'}'+name)
    return ET.tostring(node,encoding='utf-8',xml_declaration=True)


def _properties(document):
    try:
        root=safe_xml(document,forbid_dtd=True,forbid_entities=True,forbid_external=True)
    except Exception:
        _fail()
    if root.tag!='{'+D+'}multistatus' or sum(1 for _ in root.iter())>12000:
        _fail()
    rows=[]
    for response in root.findall('{'+D+'}response'):
        hrefs=response.findall('{'+D+'}href')
        if len(hrefs)!=1 or len(hrefs[0]):
            _fail()
        href=hrefs[0].text
        if not href:
            _fail()
        props={}
        for block in response.findall('{'+D+'}propstat'):
            status=block.findtext('{'+D+'}status','')
            if re.fullmatch(r'HTTP/\d\.\d 2\d\d(?: .*)?',status):
                prop=block.find('{'+D+'}prop')
                if prop is None:
                    _fail()
                for item in prop:
                    if item.tag in props:
                        _fail()
                    props[item.tag]=item
        # An inaccessible object in a REPORT must never become an empty read.
        if not props:
            _fail('caldav_incomplete','CalDAV 返回了不可读取的日历数据；现有内容已保留。')
        rows.append((href,props))
        if len(rows)>1000:
            _fail('caldav_oversized','CalDAV 返回的数据超过限制。')
    return rows


def _calendar_properties(root,begin,finish):
    prop=ET.SubElement(root,'{'+D+'}prop')
    ET.SubElement(prop,'{'+D+'}getetag')
    data=ET.SubElement(prop,'{'+C+'}calendar-data')
    ET.SubElement(data,'{'+C+'}expand',start=begin.strftime('%Y%m%dT%H%M%SZ'),end=finish.strftime('%Y%m%dT%H%M%SZ'))


def _member_url(source,collection,href):
    target=_same_origin(source['url'],urljoin(collection,href))
    if not urlsplit(target).path.startswith(urlsplit(collection).path.rstrip('/')+'/'):
        _fail('caldav_scope','CalDAV 返回了所选日历范围外的数据。')
    return target


def _etag(props):
    value=props.get('{'+D+'}getetag')
    if value is None or len(value) or not value.text:
        _fail('caldav_incomplete','CalDAV 未返回完整的对象标识；现有内容已保留。')
    result=text(value.text,empty=False,limit=4096)
    if any(ord(c)<32 or ord(c)==127 for c in result):
        _fail('caldav_incomplete','CalDAV 返回的对象标识无效；现有内容已保留。')
    return result


def _identity(*parts):
    return hashlib.sha256(json.dumps(parts,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


class CalDAVProvider:
    label='caldav'

    def __init__(self, root):
        self.root=Path(root).absolute()
        self.lock=threading.RLock()
        self.authorization='unavailable'
        # Construction does not read credentials or make a network request.

    def _directory(self):
        if any(path.is_symlink() for path in [self.root,*self.root.parents]):
            _fail('caldav_storage','CalDAV 私有配置路径不能使用符号链接。')
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
        root=os.open(self.root,flags)
        try:
            info=os.fstat(root)
            if info.st_uid!=os.getuid():
                _fail('caldav_storage','CalDAV 私有配置目录不可用。')
            try:
                os.mkdir('caldav-private',0o700,dir_fd=root)
            except FileExistsError:
                pass
            directory=os.open('caldav-private',flags,dir_fd=root)
        finally:
            os.close(root)
        info=os.fstat(directory)
        if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:
            os.close(directory)
            _fail('caldav_storage','CalDAV 私有配置目录权限必须为 0700。')
        return directory

    def _load(self,directory):
        try:
            fd=os.open('sources.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=directory)
        except FileNotFoundError:
            return []
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1 or info.st_size>65536:
                _fail('caldav_storage','CalDAV 私有配置文件权限或格式无效。')
            raw=os.read(fd,65537)
            if len(raw)>65536:
                _fail()
            def pairs(values):
                result={}
                for k,v in values:
                    if k in result:
                        _fail()
                    result[k]=v
                return result
            data=json.loads(raw,object_pairs_hook=pairs)
            if not isinstance(data,dict) or set(data)!={'schema','sources'} or data['schema']!=1 or not isinstance(data['sources'],list) or len(data['sources'])>MAX_SOURCES:
                _fail()
            sources=[self._validate(row,existing=True) for row in data['sources']]
            if len({s['id'] for s in sources})!=len(sources):
                _fail()
            return sources
        finally:
            os.close(fd)

    @staticmethod
    def _validate(row,existing=False):
        if not isinstance(row,dict) or set(row)-{'id','label','url','username','password','enabled'}:
            _fail('caldav_config','CalDAV 配置字段无效。')
        identifier=row.get('id') or str(uuid.uuid4())
        if str(uuid.UUID(identifier))!=identifier:
            _fail('caldav_config','CalDAV 来源标识无效。')
        label=text(row.get('label',''),empty=False,limit=256)
        username=text(row.get('username',''),empty=False,limit=1024)
        password=text(row.get('password',''),limit=4096)
        if ':' in username or any(ord(c)<32 or ord(c)==127 for c in username+password):
            _fail('caldav_config','CalDAV 用户名或应用密码格式无效。')
        enabled=row.get('enabled',True)
        if type(enabled) is not bool:
            _fail('caldav_config','CalDAV 启用状态无效。')
        return dict(id=identifier,label=label,url=_url(row.get('url')),username=username,password=password,enabled=enabled)

    @staticmethod
    def _public(row):
        return {**{k:row[k] for k in ('id','label','url','username','enabled')},'has_password':bool(row['password']),'configured':bool(row['url'] and row['username'] and row['password'])}

    def list_sources(self):
        try:
            with self.lock:
                directory=self._directory()
                try:
                    sources=self._load(directory)
                finally:
                    os.close(directory)
                return dict(schema=1,ok=True,sources=[self._public(row) for row in sources])
        except Exception as error:
            return _public_error(error)

    get_sources=list_sources

    def save_source(self,data):
        try:
            with self.lock:
                directory=self._directory()
                try:
                    sources=self._load(directory)
                    if not isinstance(data,dict):
                        _fail()
                    data=dict(data)
                    old=next((s for s in sources if s['id']==data.get('id')),None)
                    if data.get('id') and old is None:
                        _fail('caldav_not_found','CalDAV 来源不存在。')
                    if old:
                        # Empty edit preserves a stored application password.
                        if not data.get('password'):
                            data['password']=old['password']
                        data={**old,**data}
                    elif len(sources)>=MAX_SOURCES:
                        _fail('caldav_limit','最多配置 8 个 CalDAV 来源。')
                    row=self._validate(data)
                    sources=[s for s in sources if s['id']!=row['id']]+[row]
                    self._write(directory,sources)
                finally:
                    os.close(directory)
                self.authorization='not_determined'
                return dict(schema=1,ok=True,source=self._public(row))
        except Exception as error:
            return _public_error(error)

    def _write(self,directory,sources):
        name='sources-'+uuid.uuid4().hex+'.tmp'
        fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=directory)
        try:
            os.fchmod(fd,0o600)
            data=json.dumps(dict(schema=1,sources=sources),ensure_ascii=False,allow_nan=False).encode()
            if len(data)>65536:
                _fail('caldav_limit','CalDAV 配置超过大小限制。')
            with os.fdopen(fd,'wb',closefd=False) as output:
                output.write(data);output.flush();os.fsync(fd)
            os.replace(name,'sources.json',src_dir_fd=directory,dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            os.close(fd)
            try:
                os.unlink(name,dir_fd=directory)
            except FileNotFoundError:
                pass

    def set_source(self,identifier,data):
        return self.save_source({**data,**({'id':identifier} if identifier else {})})

    def delete_source(self,identifier):
        try:
            with self.lock:
                directory=self._directory()
                try:
                    sources=self._load(directory)
                    remaining=[s for s in sources if s['id']!=identifier]
                    if len(remaining)==len(sources):
                        _fail('caldav_not_found','CalDAV 来源不存在。')
                    self._write(directory,remaining)
                finally:
                    os.close(directory)
                self.authorization='not_determined' if remaining else 'unavailable'
                return dict(schema=1,ok=True,deleted=True)
        except Exception as error:
            return _public_error(error)

    remove_source=delete_source

    def _configured(self):
        directory=self._directory()
        try:
            sources=self._load(directory)
        finally:
            os.close(directory)
        return [s for s in sources if s['enabled'] and s['password']]

    def status(self):
        try:
            with self.lock:
                sources=self._configured()
                authorization=self.authorization if sources else 'unavailable'
                if sources and authorization=='unavailable':
                    authorization='not_determined'
                return dict(schema=1,ok=True,authorization=authorization)
        except Exception as error:
            return _public_error(error)

    def _operation(self,callback):
        try:
            with self.lock:
                sources=self._configured()
                if not sources:
                    self.authorization='unavailable'
                    _fail('caldav_not_configured','请先配置并启用 CalDAV 来源。')
                budget={'deadline':time.monotonic()+OPERATION_TIMEOUT,'requests':0,'bytes':0}
                result=callback(sources,budget)
                if time.monotonic()>=budget['deadline']:
                    _fail('caldav_timeout','CalDAV 读取超时；上次成功内容已保留。')
                self.authorization='authorized'
                return result
        except Exception as error:
            self.authorization='denied' if isinstance(error,_Failure) and error.code=='caldav_auth' else 'unavailable'
            return _public_error(error)

    def _request(self,source,url,method,body,depth,budget):
        if method not in {'PROPFIND','REPORT'}:
            _fail()
        url=_same_origin(source['url'],url)
        remaining=budget['deadline']-time.monotonic()
        budget['requests']+=1
        if remaining<=0:
            _fail('caldav_timeout','CalDAV 读取超时；上次成功内容已保留。')
        if budget['requests']>MAX_REQUESTS:
            _fail('caldav_limit','CalDAV 请求数量超过限制，请减少选中的日历。')
        parts=urlsplit(url)
        credentials=base64.b64encode((source['username']+':'+source['password']).encode()).decode('ascii')
        connection=_HTTPSConnection(parts.hostname,parts.port or 443,timeout=min(remaining,SOCKET_TIMEOUT),context=ssl.create_default_context())
        # Socket timeouts restart on each recv. An absolute watchdog also bounds
        # slow HTTP status lines/headers and a continuously dribbling body.
        expired=threading.Event()
        transport=[None]
        def interrupt():
            expired.set()
            sock=transport[0] or connection.sock
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        watchdog=threading.Timer(min(remaining,SOCKET_TIMEOUT),interrupt)
        watchdog.daemon=True
        watchdog.start()
        try:
            headers={'Authorization':'Basic '+credentials,'Content-Type':'application/xml; charset=utf-8','Accept':'application/xml','Accept-Encoding':'identity','User-Agent':'PandaNote-CalDAV/1'}
            if depth is not None:
                headers['Depth']=str(depth)
            connection.request(method,parts.path or '/',body=body,headers=headers)
            transport[0]=connection.sock
            if expired.is_set():
                _fail('caldav_timeout','CalDAV 读取超时；上次成功内容已保留。')
            response=connection.getresponse()
            if expired.is_set():
                _fail('caldav_timeout','CalDAV 读取超时；上次成功内容已保留。')
            if response.status in {401,403}:
                _fail('caldav_auth','CalDAV 认证失败；请检查账号和应用专用密码。')
            if 300<=response.status<400:
                _fail('caldav_redirect','CalDAV 地址发生跳转；请直接填写最终 HTTPS 地址。')
            if response.status!=207:
                _fail('caldav_http','CalDAV 服务读取失败；上次成功内容已保留。')
            if response.getheader('Content-Encoding','identity').lower() not in {'identity',''}:
                _fail()
            length=response.getheader('Content-Length')
            if length is not None and (not length.isdecimal() or int(length)>MAX_BODY):
                _fail('caldav_oversized','CalDAV 返回的数据超过限制。')
            data=bytearray()
            while True:
                remaining=budget['deadline']-time.monotonic()
                if remaining<=0 or expired.is_set():
                    _fail('caldav_timeout','CalDAV 读取超时；上次成功内容已保留。')
                if connection.sock is not None:
                    connection.sock.settimeout(min(remaining,SOCKET_TIMEOUT))
                piece=response.read(min(65536,MAX_BODY+1-len(data)))
                if not piece:
                    break
                data.extend(piece)
                budget['bytes']+=len(piece)
                if len(data)>MAX_BODY or budget['bytes']>8*MAX_BODY:
                    _fail('caldav_oversized','CalDAV 返回的数据超过限制。')
            if expired.is_set():
                _fail('caldav_timeout','CalDAV 读取超时；上次成功内容已保留。')
            return _properties(bytes(data))
        except (TimeoutError,socket.timeout):
            _fail('caldav_timeout','CalDAV 读取超时；上次成功内容已保留。')
        except Exception:
            if expired.is_set():
                _fail('caldav_timeout','CalDAV 读取超时；上次成功内容已保留。')
            raise
        finally:
            watchdog.cancel()
            connection.close()

    def _discover(self,source,budget):
        props=[(D,'resourcetype'),(D,'displayname'),(D,'current-user-principal'),(C,'calendar-home-set'),(C,'supported-calendar-component-set')]
        body=_xml_request('propfind',props)
        url=source['url']
        rows=self._request(source,url,'PROPFIND',body,1,budget)
        def calendars(rows,base):
            output=[]
            for href,values in rows:
                target=_same_origin(source['url'],urljoin(base,href))
                kind=values.get('{'+D+'}resourcetype')
                if kind is None or kind.find('{'+C+'}calendar') is None:
                    continue
                components=values.get('{'+C+'}supported-calendar-component-set')
                if components is not None and not any(c.attrib.get('name')=='VEVENT' for c in components):
                    continue
                title=values.get('{'+D+'}displayname')
                title=text(title.text or '' if title is not None else '',limit=4096) or '日历'
                output.append(dict(id=source['id']+':'+_identity(target),title=title,source_id=source['id'],source_label=source['label'],url=target))
            if len(output)>MAX_CALENDARS or len({x['id'] for x in output})!=len(output):
                _fail()
            return output
        found=calendars(rows,url)
        if found:
            return found
        home=None
        home_base=url
        for _,values in rows:
            item=values.get('{'+C+'}calendar-home-set')
            if item is not None:
                home=item.findtext('{'+D+'}href')
                break
        if not home:
            principal=None
            for _,values in rows:
                item=values.get('{'+D+'}current-user-principal')
                if item is not None:
                    principal=item.findtext('{'+D+'}href')
                    break
            if principal:
                principal=_same_origin(source['url'],urljoin(url,principal))
                principal_rows=self._request(source,principal,'PROPFIND',body,0,budget)
                home_base=principal
                for _,values in principal_rows:
                    item=values.get('{'+C+'}calendar-home-set')
                    if item is not None:
                        home=item.findtext('{'+D+'}href')
                        break
        if home:
            home=_same_origin(source['url'],urljoin(home_base,home))
            return calendars(self._request(source,home,'PROPFIND',body,1,budget),home)
        # A successful collection listing may legitimately contain no calendars.
        return []

    def test_source(self,data):
        """Probe exactly one draft source without saving or changing authorization."""
        try:
            with self.lock:
                data=dict(data)
                if data.get('id'):
                    directory=self._directory()
                    try:old=next((row for row in self._load(directory) if row['id']==data['id']),None)
                    finally:os.close(directory)
                    if old is None:_fail('caldav_not_found','日历来源不存在。')
                    if not data.get('password'):
                        if _url(data.get('url'))!=old['url'] or data.get('username')!=old['username']:
                            _fail('caldav_password','地址或账号变更后请重新输入应用专用密码。')
                        data['password']=old['password']
                source=self._validate(data)
                if not source['password']:_fail('caldav_password','请输入应用专用密码。')
                budget={'deadline':time.monotonic()+OPERATION_TIMEOUT,'requests':0,'bytes':0}
                calendars=self._discover(source,budget)
                if time.monotonic()>=budget['deadline']:_fail('caldav_timeout','连接测试超时。')
                return dict(schema=1,ok=True,connected=True,calendar_count=len(calendars))
        except Exception as error:return _public_error(error)

    def request_access(self):
        def run(sources,budget):
            for source in sources:
                self._discover(source,budget)
            return dict(schema=1,ok=True,authorization='authorized')
        return self._operation(run)

    def calendars(self):
        def run(sources,budget):
            rows=[]
            for source in sources:
                rows.extend(self._discover(source,budget))
            if len(rows)>MAX_CALENDARS:
                _fail('caldav_limit','CalDAV 日历数量超过限制。')
            return dict(schema=1,ok=True,calendars=[{k:v for k,v in row.items() if k!='url'} for row in rows])
        return self._operation(run)

    def export(self,query):
        def run(sources,budget):
            if not isinstance(query,dict) or set(query)!={'schema','calendarIds','displayTimezone','windowStartDate','dayCount','startEpoch','endEpoch'} or query['schema']!=1:
                _fail()
            settings=Settings.from_dict(dict(display_timezone=query['displayTimezone'],window_start=query['windowStartDate'],day_count=query['dayCount'],selected_calendar_ids=query['calendarIds']))
            table=days(settings)
            if query['startEpoch']!=table[0]['startEpoch'] or query['endEpoch']!=table[-1]['endEpoch'] or len(settings.selected_calendar_ids)>MAX_CALENDARS:
                _fail()
            ids=list(settings.selected_calendar_ids)
            by_source={s['id']:s for s in sources}
            # A removed/disabled/unconfigured source is not an empty successful read.
            selected_sources={identifier.split(':',1)[0] for identifier in ids}
            if selected_sources-set(by_source):
                _fail('caldav_source_missing','选中的 CalDAV 来源已停用或删除，请重新选择日历。')
            present,missing,events=[],[],[]
            if not ids:
                # Even an intentionally empty export must reflect a real server
                # read, rather than fabricate freshness from local settings.
                for source in sources:
                    self._discover(source,budget)
            for source in sources:
                if source['id'] not in selected_sources:
                    continue
                calendars=self._discover(source,budget)
                inventory={row['id']:row for row in calendars}
                for identifier in ids:
                    if identifier.split(':',1)[0]!=source['id']:
                        continue
                    if identifier not in inventory:
                        missing.append(identifier)
                        continue
                    row=inventory[identifier]
                    events.extend(self._events(source,row,settings,budget))
                    present.append(identifier)
                    if len(events)>MAX_EVENTS:
                        _fail('caldav_limit','日历窗口超过 200 条事件，请减少选中的日历。')
            if len({e['id'] for e in events})!=len(events):
                _fail()
            return dict(schema=1,ok=True,readAt=int(time.time()),calendarIds=present,missingCalendarIds=missing,events=events)
        return self._operation(run)

    def _complete_calendar_data(self,source,calendar,rows,begin,finish,budget,query_body):
        # A 200 getetag identifies missing calendar-data without treating a
        # property-level 404 as a deleted event or an empty successful read.
        def members(values):
            result={}
            for href,props in values:
                target=_member_url(source,calendar['url'],href)
                if target in result:
                    _fail('caldav_incomplete','CalDAV 重复返回了同一对象；现有内容已保留。')
                result[target]=props
            return result
        def retrieve(targets):
            root=ET.Element('{'+C+'}calendar-multiget')
            _calendar_properties(root,begin,finish)
            for target in targets:
                # Already canonicalized same-origin collection members. Some
                # compliant servers only accept the absolute-path href form.
                ET.SubElement(root,'{'+D+'}href').text=urlsplit(target).path
            body=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            # RFC 4791 section 7.9: no Depth header on calendar-multiget.
            result=members(self._request(source,calendar['url'],'REPORT',body,None,budget))
            if set(result)!=set(targets):
                _fail('caldav_incomplete','CalDAV 返回的对象集合不完整；现有内容已保留。')
            for props in result.values():
                _etag(props)
                data=props.get('{'+C+'}calendar-data')
                if data is None or not data.text or len(data.text.encode())>MAX_BODY:
                    _fail('caldav_incomplete','CalDAV 未返回完整事件正文；现有内容已保留。')
            return result
        listed=members(rows)
        needed={target:_etag(props) for target,props in listed.items() if '{'+C+'}calendar-data' not in props}
        completed=dict(listed);mismatched={};verification={}
        targets=list(needed)
        # Every pass shares the original request/byte/deadline operation budget.
        for at in range(0,len(targets),32):
            fetched=retrieve(targets[at:at+32])
            for target,props in fetched.items():
                if _etag(props)!=needed[target]:
                    mismatched[target]=props
                completed[target]=props
        if mismatched:
            # Some servers expose different, stable ETag namespaces in query
            # and multiget. Never ignore the mismatch: independently prove a
            # stable complete query inventory and the complete reader model.
            inventory={target:_etag(props) for target,props in listed.items()}
            repeated=members(self._request(source,calendar['url'],'REPORT',query_body,1,budget))
            if {target:_etag(props) for target,props in repeated.items()}!=inventory:
                _fail('caldav_changed','CalDAV 事件清单在读取时发生变化；请稍后重新同步。')
            targets=list(mismatched)
            for at in range(0,len(targets),32):
                fetched=retrieve(targets[at:at+32])
                for target,props in fetched.items():
                    first=mismatched[target]
                    if _etag(props)!=_etag(first):
                        _fail('caldav_changed','CalDAV 事件在重复读取时发生变化；请稍后重新同步。')
                    verification[target]=props['{'+C+'}calendar-data'].text
        return list(completed.items()),verification

    def _events(self,source,calendar,settings,budget):
        table=days(settings)
        # A padded query includes floating/all-day boundaries in every IANA zone;
        # we post-filter exact display-local dates below.
        begin=datetime.fromtimestamp(table[0]['startEpoch']-86400,timezone.utc)
        finish=datetime.fromtimestamp(table[-1]['endEpoch']+86400,timezone.utc)
        root=ET.Element('{'+C+'}calendar-query')
        _calendar_properties(root,begin,finish)
        filters=ET.SubElement(root,'{'+C+'}filter')
        top=ET.SubElement(filters,'{'+C+'}comp-filter',name='VCALENDAR')
        component=ET.SubElement(top,'{'+C+'}comp-filter',name='VEVENT')
        ET.SubElement(component,'{'+C+'}time-range',start=begin.strftime('%Y%m%dT%H%M%SZ'),end=finish.strftime('%Y%m%dT%H%M%SZ'))
        zone=ZoneInfo(settings.display_timezone)
        zone_calendar=Calendar();zone_calendar.add('version','2.0');zone_calendar.add('prodid','-//PandaNote//CalDAV timezone//EN')
        zone_calendar.add_component(Timezone.from_tzinfo(zone,first_date=settings.window_start-timedelta(days=370),last_date=settings.window_start+timedelta(days=370)))
        ET.SubElement(root,'{'+C+'}timezone').text=zone_calendar.to_ical().decode()
        body=ET.tostring(root,encoding='utf-8',xml_declaration=True)
        rows=self._request(source,calendar['url'],'REPORT',body,1,budget)
        rows,verification=self._complete_calendar_data(source,calendar,rows,begin,finish,budget,body)
        documents=[];replacements=[]
        for target,props in rows:
            data=props.get('{'+C+'}calendar-data')
            if data is None or not data.text or len(data.text.encode())>MAX_BODY:
                _fail('caldav_incomplete','CalDAV 未返回完整事件正文；现有内容已保留。')
            if target in verification:
                replacements.append(dict(index=len(documents),document=verification[target]))
            documents.append(data.text)
        return self._expand_documents(documents,source,calendar,settings,budget,replacements)

    def _expand_documents(self,documents,source,calendar,settings,budget,replacements=None):
        payload=dict(documents=documents,displayTimezone=settings.display_timezone,windowStartDate=settings.window_start.isoformat(),dayCount=settings.day_count)
        if replacements:
            payload['verificationReplacements']=replacements
        raw=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
        if len(raw)>MAX_EXPAND_INPUT:
            _fail('caldav_oversized','CalDAV 事件正文超过解析限制。')
        remaining=budget['deadline']-time.monotonic()
        if remaining<=0:
            _fail('caldav_timeout','CalDAV 读取超时；上次成功内容已保留。')
        if not _EXPAND_LOCK.acquire(blocking=False):
            _fail('caldav_busy','CalDAV 解析忙，请稍后重试。')
        process=None
        try:
            _EXPAND_PENDING[:]=[child for child in _EXPAND_PENDING if child.poll() is None]
            if _EXPAND_PENDING:
                _fail('caldav_busy','CalDAV 解析尚未结束，请稍后重试。')
            deadline=min(budget['deadline'],time.monotonic()+EXPAND_TIMEOUT)
            process=subprocess.Popen([sys.executable,'-I',str(_EXPAND_SCRIPT)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,close_fds=True,start_new_session=True,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8'})
            output=bytearray();written=0
            with selectors.DefaultSelector() as selector:
                os.set_blocking(process.stdin.fileno(),False)
                os.set_blocking(process.stdout.fileno(),False)
                selector.register(process.stdin,selectors.EVENT_WRITE)
                selector.register(process.stdout,selectors.EVENT_READ)
                while selector.get_map():
                    left=deadline-time.monotonic()
                    if left<=0:
                        _fail('caldav_expand_timeout','CalDAV 事件展开超时；上次成功内容已保留。')
                    for key,mask in selector.select(left):
                        if mask&selectors.EVENT_WRITE:
                            count=os.write(key.fd,raw[written:written+65536])
                            written+=count
                            if written==len(raw):
                                selector.unregister(process.stdin);process.stdin.close()
                        else:
                            chunk=os.read(key.fd,min(65536,MAX_EXPAND_OUTPUT+1-len(output)))
                            if not chunk:
                                selector.unregister(process.stdout)
                            else:
                                output.extend(chunk)
                                if len(output)>MAX_EXPAND_OUTPUT:
                                    _fail('caldav_oversized','CalDAV 解析结果超过大小限制。')
                left=deadline-time.monotonic()
                if left<=0:
                    _fail('caldav_expand_timeout','CalDAV 事件展开超时；上次成功内容已保留。')
                try:
                    status=process.wait(timeout=left)
                except subprocess.TimeoutExpired:
                    _fail('caldav_expand_timeout','CalDAV 事件展开超时；上次成功内容已保留。')
            if status:
                _fail('caldav_limit','CalDAV 事件展开超过资源限制；上次成功内容已保留。')
            value=json.loads(output)
            if not isinstance(value,dict) or value.get('schema')!=1 or type(value.get('ok')) is not bool:
                _fail()
            if not value['ok']:
                codes={'caldav_changed','caldav_invalid','caldav_incomplete','caldav_timezone','caldav_duration','caldav_recurrence','caldav_limit','caldav_oversized'}
                code=value.get('code')
                _fail(code if code in codes else 'caldav_invalid','CalDAV 事件无法完整解析或展开；上次成功内容已保留。')
            if set(value)!={'schema','ok','events'} or not isinstance(value['events'],list) or len(value['events'])>MAX_EVENTS:
                _fail()
            events=[]
            for item in value['events']:
                common={'uid','recurrenceIdentity','summary','location','allDay','sourceTimezone'}
                if not isinstance(item,dict) or type(item.get('allDay')) is not bool or set(item)!=common|({'startDate','endDate'} if item['allDay'] else {'startEpoch','endEpoch'}):
                    _fail()
                uid=text(item.pop('uid'),empty=False)
                recurrence=item.pop('recurrenceIdentity')
                if recurrence is not None:
                    text(recurrence,empty=False,limit=256)
                item.update(id=_identity(source['id'],calendar['id'],uid,recurrence),calendarId=calendar['id'])
                events.append(item)
            return events
        finally:
            if process is not None:
                for stream in (process.stdin,process.stdout):
                    if stream is not None:
                        stream.close()
                if process.poll() is None:
                    try:
                        os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=.25)
                    except subprocess.TimeoutExpired:
                        # Keep ownership and deny a new worker until reaped.
                        _EXPAND_PENDING.append(process)
            _EXPAND_LOCK.release()
