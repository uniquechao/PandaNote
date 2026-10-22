"""Offline protocol fixtures. No real CalDAV endpoint or credentials are used."""
import base64
import importlib
import json
import os
import stat
import time
from pathlib import Path
from xml.sax.saxutils import escape

import pytest


def provider_class():
    try:
        return importlib.import_module('manager.caldav_provider').CalDAVProvider
    except ModuleNotFoundError:
        pytest.fail('CalDAVProvider is not implemented')


D = 'DAV:'
C = 'urn:ietf:params:xml:ns:caldav'


def multi(rows):
    body = ''.join('<d:response><d:href>'+escape(href)+'</d:href><d:propstat><d:prop>'+props+'</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>' for href, props in rows)
    return ('<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'+body+'</d:multistatus>').encode()


def collection(title='工作'):
    return multi([('/cal/', '<d:resourcetype><d:collection/></d:resourcetype>'), ('/cal/work/', '<d:resourcetype><d:collection/><c:calendar/></d:resourcetype><d:displayname>'+title+'</d:displayname>')])


def ics(*events):
    return 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//PandaNote fixture//EN\r\n' + ''.join('BEGIN:VEVENT\r\n'+event.replace('\n','\r\n')+'\r\nEND:VEVENT\r\n' for event in events) + 'END:VCALENDAR\r\n'


def report(value):
    return multi([('/cal/work/event.ics', '<c:calendar-data>'+escape(value)+'</c:calendar-data>')])


class Reply:
    def __init__(self, status, data, headers=None):
        self.status, self.data, self.headers = status, data, headers or {}
    def getheader(self, key, default=None):
        return self.headers.get(key, default)
    def read(self, amount=-1):
        part, self.data = self.data[:amount], self.data[amount:]
        return part


@pytest.fixture
def wire(monkeypatch):
    calls, replies = [], []
    class Connection:
        def __init__(self, host, port=None, timeout=None, context=None):
            self.host, self.port, self.timeout = host, port, timeout
            self.sock = None
        def request(self, method, path, body=None, headers=None):
            calls.append((self.host, method, path, body, headers))
        def getresponse(self):
            value = replies.pop(0)
            if isinstance(value, Exception):
                raise value
            return Reply(*value)
        def close(self):
            pass
    module = importlib.import_module(provider_class().__module__)
    monkeypatch.setattr(module, '_HTTPSConnection', Connection)
    return calls, replies


def configured(tmp_path, **kwargs):
    p = provider_class()(tmp_path/'private')
    result = p.save_source(dict(label='工作', url='https://calendar.example/cal/', username='fixture-user', password='S3CRET-fixture', enabled=True, **kwargs))
    assert result['ok'], result
    return p, result['source']


def query(ids):
    return dict(schema=1, calendarIds=ids, displayTimezone='Asia/Shanghai', windowStartDate='2026-10-22', dayCount=7, startEpoch=1792598400, endEpoch=1793203200)


def test_unconfigured_is_inert_and_never_fabricates_a_read(tmp_path):
    p = provider_class()(tmp_path/'private')
    assert p.status() == dict(schema=1, ok=True, authorization='unavailable')
    assert p.list_sources() == dict(schema=1, ok=True, sources=[])
    assert not p.request_access()['ok']
    assert not p.export(query([]))['ok']


def test_private_sources_crud_keeps_password_secret_and_empty_edit_retains(tmp_path):
    p, source = configured(tmp_path)
    assert source['has_password'] and source['configured'] and source['enabled']
    assert 'password' not in source and 'S3CRET' not in json.dumps(source)
    saved = p.save_source(dict(id=source['id'], label='新名称', url=source['url'], username=source['username'], password='', enabled=False))
    assert saved['ok'] and saved['source']['has_password'] and not saved['source']['enabled']
    assert provider_class()(tmp_path/'private').list_sources()['sources'][0]['id'] == source['id']
    private = tmp_path/'private'/'caldav-private'
    assert stat.S_IMODE(private.stat().st_mode) == 0o700
    assert stat.S_IMODE((private/'sources.json').stat().st_mode) == 0o600
    assert 'S3CRET-fixture' in (private/'sources.json').read_text()
    assert p.delete_source(source['id'])['ok']
    assert p.list_sources()['sources'] == []


@pytest.mark.parametrize('url', ['http://calendar.example/cal/', 'https://user:pass@calendar.example/', 'https://calendar.example/?secret=x', 'https://calendar.example/#fragment', 'https://calendar.example/\\evil', 'https://calendar.example/%0d%0aevil', 'https://calendar.example/ white', 'https://calendar.example/%2f%2fevil', 'https://127.0.0.1/cal/'])
def test_unsafe_url_rejected_before_network_or_persistence(tmp_path, url):
    p = provider_class()(tmp_path/'private')
    result = p.save_source(dict(url=url, username='u', password='SECRET', label='x'))
    assert not result['ok']
    assert 'SECRET' not in json.dumps(result)
    assert p.list_sources()['sources'] == []


def test_symlink_and_world_readable_credential_file_are_rejected(tmp_path):
    p, _ = configured(tmp_path)
    private = tmp_path/'private'/'caldav-private'
    (private/'sources.json').chmod(0o644)
    assert not p.list_sources()['ok']
    (private/'sources.json').unlink()
    target = tmp_path/'outside'; target.write_text('do not change')
    (private/'sources.json').symlink_to(target)
    assert not p.save_source(dict(url='https://calendar.example/', username='x', password='secret', label='x'))['ok']
    assert target.read_text() == 'do not change'


def test_read_only_discovery_and_authentication_failure_never_leak(tmp_path, wire):
    p, _ = configured(tmp_path)
    calls, replies = wire
    replies.append((207, collection()))
    assert p.request_access()['authorization'] == 'authorized'
    assert calls[0][1:3] == ('PROPFIND','/cal/')
    assert calls[0][4]['Authorization'] == 'Basic '+base64.b64encode(b'fixture-user:S3CRET-fixture').decode()
    replies.append((401,b'S3CRET-fixture fixture-user unauthorized'))
    result = p.calendars()
    assert not result['ok'] and result['error']['code'] == 'caldav_auth'
    assert 'S3CRET' not in json.dumps(result) and 'fixture-user' not in json.dumps(result)
    assert p.status()['authorization'] == 'denied'


def test_redirect_never_retries_or_transmits_password_to_other_origin(tmp_path, wire):
    p, _ = configured(tmp_path); calls,replies=wire
    replies.append((302,b'',{'Location':'https://other.example/cal/'}))
    assert p.calendars()['error']['code'] == 'caldav_redirect'
    assert len(calls) == 1 and calls[0][0] == 'calendar.example'


def test_principal_discovery_and_cross_origin_href_rejected(tmp_path, wire):
    p,_=configured(tmp_path);calls,replies=wire
    replies.extend([(207,multi([('/cal/','<d:current-user-principal><d:href>/principal/me/</d:href></d:current-user-principal>')])),(207,multi([('/principal/me/','<c:calendar-home-set><d:href>/cal/</d:href></c:calendar-home-set>')])),(207,collection())])
    result=p.calendars();assert result['ok'] and len(result['calendars'])==1
    assert [row[2] for row in calls] == ['/cal/','/principal/me/','/cal/']
    replies.append((207,multi([('/cal/','<c:calendar-home-set><d:href>https://evil.example/cal/</d:href></c:calendar-home-set>')])))
    assert not p.calendars()['ok'] and len(calls)==4


def test_aggregation_namespaces_calendars_and_uids_and_reports_selected_sources_only(tmp_path, wire):
    p,a=configured(tmp_path); b=p.save_source(dict(label='私人',url='https://second.example/cal/',username='u2',password='p2'))['source']
    calls,replies=wire;replies.extend([(207,collection()),(207,collection())])
    rows=p.calendars()['calendars'];assert len({r['id'] for r in rows})==2
    assert {r['source_id'] for r in rows}=={a['id'],b['id']}
    event=ics('UID:same\nDTSTART:20261022T010000Z\nDTEND:20261022T020000Z\nSUMMARY:meeting')
    replies.extend([(207,collection()),(207,report(event)),(207,collection()),(207,report(event))])
    result=p.export(query([r['id'] for r in rows]));assert result['ok']
    assert len({e['id'] for e in result['events']})==2
    assert all(call[1] in {'PROPFIND','REPORT'} for call in calls)
    reports=[call for call in calls if call[1]=='REPORT'];assert len(reports)==2
    from xml.etree import ElementTree as ET
    expanded=ET.fromstring(reports[0][3]).find('.//{'+C+'}expand')
    assert expanded is not None and expanded.attrib['start']=='20261020T160000Z'


def test_timezone_all_day_expanded_recurrence_cancel_and_read_time(tmp_path, wire):
    p,_=configured(tmp_path);calls,replies=wire;replies.append((207,collection()))
    cid=p.calendars()['calendars'][0]['id']
    value=ics('UID:tz\nDTSTART;TZID=America/New_York:20261022T090000\nDTEND;TZID=America/New_York:20261022T100000\nSUMMARY:纽约', 'UID:day\nDTSTART;VALUE=DATE:20261022\nDTEND;VALUE=DATE:20261024\nSUMMARY:两天', 'UID:daily\nRECURRENCE-ID:20261022T020000Z\nDTSTART:20261022T020000Z\nDTEND:20261022T030000Z\nSUMMARY:repeat', 'UID:daily\nRECURRENCE-ID:20261023T020000Z\nDTSTART:20261023T040000Z\nDTEND:20261023T050000Z\nSUMMARY:moved', 'UID:daily\nRECURRENCE-ID:20261024T020000Z\nSTATUS:CANCELLED')
    replies.extend([(207,collection()),(207,report(value))])
    before=int(time.time());result=p.export(query([cid]));after=int(time.time())
    assert result['ok'],result
    assert before <= result['readAt'] <= after and len(result['events'])==4
    timed=next(e for e in result['events'] if e['summary']=='纽约')
    assert timed['startEpoch']==1792674000 and timed['sourceTimezone']=='America/New_York'
    day=next(e for e in result['events'] if e['allDay']);assert (day['startDate'],day['endDate'])==('2026-10-22','2026-10-24')
    ids=[e['id'] for e in result['events']];assert len(set(ids))==4


def test_invalid_rules_or_xml_entities_or_oversized_response_fail_closed(tmp_path, wire):
    p,_=configured(tmp_path);calls,replies=wire;replies.append((207,collection()))
    cid=p.calendars()['calendars'][0]['id']
    replies.extend([(207,collection()),(207,report(ics('UID:x\nDTSTART:20261022T010000Z\nDTEND:20261022T020000Z\nRRULE:FREQ=INVALID')))])
    failed=p.export(query([cid]));assert not failed['ok'] and failed['error']['code']=='caldav_invalid'
    replies.append((207,b'<!DOCTYPE x [<!ENTITY x "secret">]><d:multistatus xmlns:d="DAV:">&x;</d:multistatus>'))
    assert not p.calendars()['ok']
    replies.append((207,b'x'*(2*1024*1024+1)))
    assert p.calendars()['error']['code']=='caldav_oversized'


def test_source_failure_does_not_publish_empty_or_fresh_cached_read(tmp_path, wire):
    p,_=configured(tmp_path);calls,replies=wire;replies.append((207,collection()))
    cid=p.calendars()['calendars'][0]['id']
    replies.extend([(207,collection()),(207,report(ics('UID:x\nDTSTART:20261022T010000Z\nDTEND:20261022T020000Z')))])
    good=p.export(query([cid]));assert good['ok']
    replies.append((503,b'error SECRET'))
    failed=p.export(query([cid]));assert not failed['ok'] and 'readAt' not in failed and 'events' not in failed
    assert 'SECRET' not in json.dumps(failed)


def test_empty_selection_requires_a_real_read_before_read_at(tmp_path, wire):
    p,_=configured(tmp_path);calls,replies=wire
    replies.append((207,collection()))
    result=p.export(query([]))
    assert result['ok'] and result['events']==[] and result['calendarIds']==[]
    assert len(calls)==1 and calls[0][1]=='PROPFIND'


def test_failed_second_source_aborts_complete_snapshot(tmp_path, wire):
    p,_=configured(tmp_path)
    p.save_source(dict(label='私人',url='https://second.example/cal/',username='u2',password='p2'))
    calls,replies=wire;replies.extend([(207,collection()),(207,collection())])
    ids=[r['id'] for r in p.calendars()['calendars']]
    replies.extend([(207,collection()),(207,report(ics('UID:x\nDTSTART:20261022T010000Z\nDTEND:20261022T020000Z'))),(401,b'p2')])
    failed=p.export(query(ids));assert not failed['ok']
    assert 'events' not in failed and 'readAt' not in failed


def test_transport_timeout_does_not_echo_exception_secrets(tmp_path, wire):
    p,_=configured(tmp_path);calls,replies=wire
    replies.append(TimeoutError('S3CRET-fixture https://fixture-user:secret@calendar.example'))
    failed=p.calendars()
    assert failed['error']['code']=='caldav_timeout'
    assert 'S3CRET' not in json.dumps(failed) and 'fixture-user' not in json.dumps(failed)


def test_mixed_public_private_dns_is_rejected(monkeypatch):
    module=importlib.import_module(provider_class().__module__)
    monkeypatch.setattr(module.socket,'getaddrinfo',lambda *a:[(2,1,6,'',('93.184.216.34',443)),(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(Exception,match='公网 HTTPS'):
        module._resolve('calendar.example',443,1)


def test_http_headers_slow_drip_has_absolute_deadline(tmp_path, monkeypatch):
    """An actual TLS socket prevents per-recv timeout resets hiding slowloris."""
    import socket
    import ssl
    import threading
    module=importlib.import_module(provider_class().__module__)
    server=socket.socket();server.bind(('127.0.0.1',0));server.listen(1)
    port=server.getsockname()[1]
    # Generate isolated, short-lived TLS material; no private keys are published.
    import shutil
    import subprocess
    openssl=shutil.which('openssl')
    if not openssl:
        pytest.skip('OpenSSL CLI unavailable for ephemeral TLS test material')
    fixtures=tmp_path/'ephemeral-tls'
    fixtures.mkdir(mode=0o700)
    key=fixtures/'test-only-server.key'
    cert=fixtures/'server.crt'
    subprocess.run([openssl,'req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256',
                    '-nodes','-keyout',str(key),'-out',str(cert),'-subj','/CN=fixture-reader',
                    '-days','1','-addext','subjectAltName=IP:127.0.0.1'],
                   check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    key.chmod(0o600)
    cert.chmod(0o600)
    server_ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(fixtures/'server.crt',fixtures/'test-only-server.key')
    client_ctx=ssl.create_default_context(cafile=str(fixtures/'server.crt'))
    stop=threading.Event()
    def serve():
        try:
            raw,_=server.accept()
            with server_ctx.wrap_socket(raw,server_side=True) as conn:
                conn.recv(65536)
                for ch in b'HTTP/1.1 207 Multi-Status\r\n':
                    if stop.wait(.03):
                        break
                    conn.send(bytes([ch]))
        except OSError:
            pass
    thread=threading.Thread(target=serve,daemon=True);thread.start()
    monkeypatch.setattr(module,'SOCKET_TIMEOUT',.12)
    monkeypatch.setattr(module,'_resolve',lambda *a:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',port))])
    monkeypatch.setattr(module.ssl,'create_default_context',lambda:client_ctx)
    original=module._PinnedHTTPSConnection
    class LocalFixture(original):
        def __init__(self,*a,**kw):
            super().__init__('127.0.0.1',port,timeout=kw['timeout'],context=kw['context'])
    monkeypatch.setattr(module,'_HTTPSConnection',LocalFixture)
    p,_=configured(tmp_path)
    started=time.monotonic()
    try:
        result=p.calendars()
        elapsed=time.monotonic()-started
        assert result['error']['code']=='caldav_timeout',result
        assert elapsed<.45
    finally:
        stop.set();server.close();thread.join(1)


def test_ancestor_symlink_cannot_redirect_secret_storage(tmp_path):
    outside=tmp_path/'outside';outside.mkdir()
    alias=tmp_path/'alias';alias.symlink_to(outside,target_is_directory=True)
    p=provider_class()(alias/'store')
    failed=p.save_source(dict(label='x',url='https://calendar.example/cal/',username='u',password='secret'))
    assert not failed['ok']
    assert not (outside/'store').exists()


def test_real_manager_retains_published_package_after_caldav_failure(tmp_path,wire):
    from manager.content import Settings
    from manager.service import ManagerService,ManagerError
    p,_=configured(tmp_path);calls,replies=wire;replies.append((207,collection()))
    cid=p.calendars()['calendars'][0]['id']
    service=ManagerService(tmp_path/'store',p)
    service.store.save_settings(Settings('Asia/Shanghai',__import__('datetime').date(2026,10,22),7,(cid,)))
    replies.extend([(207,collection()),(207,report(ics('UID:real-boundary\nDTSTART:20261022T010000Z\nDTEND:20261022T020000Z\nSUMMARY:retained')))])
    first=service.sync(now=1792598400)['version']
    read=service.store.last_successful_read()
    files={name:(service.store.load_current().directory/name).read_bytes() for name in ('content.ini','background.png','SHA256SUMS')}
    replies.append((401,b'S3CRET-fixture'))
    with pytest.raises(ManagerError,match='CalDAV 认证失败'):
        service.sync(now=1792598400)
    assert service.store.load_current().version==first
    assert service.store.last_successful_read()==read
    assert {name:(service.store.load_current().directory/name).read_bytes() for name in files}==files
    assert not service.fresh_read


def test_relative_calendar_home_uses_principal_response_uri(tmp_path,wire):
    p,_=configured(tmp_path);calls,replies=wire
    replies.extend([(207,multi([('/cal/','<d:current-user-principal><d:href>/principals/me/</d:href></d:current-user-principal>')])),(207,multi([('/principals/me/','<c:calendar-home-set><d:href>calendars/</d:href></c:calendar-home-set>')])),(207,multi([('/principals/me/calendars/work/','<d:resourcetype><c:calendar/></d:resourcetype><d:displayname>work</d:displayname>')]))])
    result=p.calendars()
    assert result['ok'] and len(result['calendars'])==1
    assert [row[2] for row in calls]==['/cal/','/principals/me/','/principals/me/calendars/']


def deferred_query(rows):
    """Real interoperability shape: getetag 200, calendar-data 404 per href."""
    items=[]
    for href,etag in rows:
        items.append('<d:response><d:href>'+escape(href)+'</d:href><d:propstat><d:prop><d:getetag>'+escape(etag)+'</d:getetag></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat><d:propstat><d:prop><c:calendar-data/></d:prop><d:status>HTTP/1.1 404 Not Found</d:status></d:propstat></d:response>')
    return ('<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'+''.join(items)+'</d:multistatus>').encode()


def fetched(rows):
    return multi([(href,('<d:getetag>'+escape(etag)+'</d:getetag>' if etag is not None else '')+('<c:calendar-data>'+escape(data)+'</c:calendar-data>' if data is not None else '')) for href,etag,data in rows])


def event_ics(uid='one'):
    return ics('UID:'+uid+'\nDTSTART:20261022T010000Z\nDTEND:20261022T020000Z\nSUMMARY:real fixture')


def fallback_setup(tmp_path,wire):
    p,_=configured(tmp_path);calls,replies=wire;replies.append((207,collection()))
    cid=p.calendars()['calendars'][0]['id']
    replies.append((207,collection()))
    return p,cid,calls,replies


def test_query_404_data_with_200_etag_uses_strict_multiget_expand(tmp_path,wire):
    from xml.etree import ElementTree as ET
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    rows=[('/cal/work/one.ics','"one-v1"'),('/cal/work/two.ics','"two-v1"')]
    replies.extend([(207,deferred_query(rows)),(207,fetched([(rows[1][0],rows[1][1],event_ics('two')),(rows[0][0],rows[0][1],event_ics('one'))]))])
    result=p.export(query([cid]));assert result['ok'],result
    assert len(result['events'])==2 and len({e['id'] for e in result['events']})==2
    reports=[c for c in calls if c[1]=='REPORT'];assert len(reports)==2
    initial,second=map(lambda c:ET.fromstring(c[3]),reports)
    assert initial.find('{'+D+'}prop/{'+D+'}getetag') is not None
    assert second.tag=='{'+C+'}calendar-multiget'
    assert second.find('.//{'+C+'}expand').attrib==initial.find('.//{'+C+'}expand').attrib
    assert {node.text for node in second.findall('{'+D+'}href')}=={row[0] for row in rows}
    assert not any(key.lower()=='depth' for key in reports[1][4])
    assert all(c[1] in {'PROPFIND','REPORT'} for c in calls)


@pytest.mark.parametrize('fault',['missing_href','duplicate_href','extra_href','cross_origin','outside_collection','changed_etag','missing_etag','missing_data','empty_data','invalid_rule'])
def test_multiget_any_incomplete_or_changed_member_aborts_whole_export(tmp_path,wire,fault):
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    expected=[('/cal/work/one.ics','"a"'),('/cal/work/two.ics','"b"')]
    rows=[(href,etag,event_ics(str(i))) for i,(href,etag) in enumerate(expected)]
    if fault=='missing_href':rows.pop()
    elif fault=='duplicate_href':rows.append(rows[0])
    elif fault=='extra_href':rows.append(('/cal/work/extra.ics','"c"',event_ics('extra')))
    elif fault=='cross_origin':rows[0]=('https://evil.example/cal/work/one.ics',rows[0][1],rows[0][2])
    elif fault=='outside_collection':rows[0]=('/cal/other/one.ics',rows[0][1],rows[0][2])
    elif fault=='changed_etag':rows[0]=(rows[0][0],'"changed"',rows[0][2])
    elif fault=='missing_etag':rows[0]=(rows[0][0],None,rows[0][2])
    elif fault=='missing_data':rows[0]=(rows[0][0],rows[0][1],None)
    elif fault=='empty_data':rows[0]=(rows[0][0],rows[0][1],'')
    elif fault=='invalid_rule':rows[0]=(rows[0][0],rows[0][1],ics('UID:raw\nDTSTART:20261022T010000Z\nDTEND:20261022T020000Z\nRRULE:FREQ=INVALID'))
    replies.extend([(207,deferred_query(expected)),(207,fetched(rows))])
    if fault=='changed_etag':
        replies.append((207,deferred_query([(expected[0][0],'\"new\"'),expected[1]])))
    result=p.export(query([cid]))
    assert not result['ok'] and 'events' not in result and 'readAt' not in result
    assert len([c for c in calls if c[1]=='REPORT'])==(3 if fault=='changed_etag' else 2)


@pytest.mark.parametrize('fault',['missing_etag','duplicate_etag','duplicate_href','outside_collection','cross_origin'])
def test_query_without_trustworthy_member_identity_never_attempts_multiget(tmp_path,wire,fault):
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    row=('/cal/work/one.ics','"one"')
    body=deferred_query([row])
    if fault=='missing_etag':body=body.replace(b'<d:getetag>"one"</d:getetag>',b'')
    elif fault=='duplicate_etag':body=body.replace(b'</d:getetag>',b'</d:getetag><d:getetag>"two"</d:getetag>')
    elif fault=='duplicate_href':body=deferred_query([row,row])
    elif fault=='outside_collection':body=deferred_query([('/cal/other/one.ics','"one"')])
    elif fault=='cross_origin':body=deferred_query([('https://evil.example/cal/work/one.ics','"one"')])
    replies.append((207,body))
    result=p.export(query([cid]));assert not result['ok'] and 'events' not in result
    assert len([c for c in calls if c[1]=='REPORT'])==1


def test_multiget_batches_are_bounded_to_32_and_inline_data_stays_inline(tmp_path,wire):
    from xml.etree import ElementTree as ET
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    rows=[('/cal/work/'+str(i)+'.ics','"v'+str(i)+'"') for i in range(33)]
    # One valid inline object is not included in either retrieval batch.
    inline=multi([('/cal/work/inline.ics','<c:calendar-data>'+escape(event_ics('inline'))+'</c:calendar-data>')])
    listed=deferred_query(rows).replace(b'</d:multistatus>',inline.split(b'>',1)[1].rsplit(b'</d:multistatus>',1)[0]+b'</d:multistatus>')
    replies.extend([(207,listed),(207,fetched([(href,etag,event_ics(str(i))) for i,(href,etag) in enumerate(rows[:32])])),(207,fetched([(rows[32][0],rows[32][1],event_ics('last'))]))])
    result=p.export(query([cid]));assert result['ok'] and len(result['events'])==34,result
    reports=[ET.fromstring(c[3]) for c in calls if c[1]=='REPORT']
    assert [len(r.findall('{'+D+'}href')) for r in reports]==[0,32,1]
    assert all('inline.ics' not in (h.text or '') for r in reports[1:] for h in r.findall('{'+D+'}href'))


def test_multiget_uses_original_operation_request_budget(tmp_path,wire,monkeypatch):
    module=importlib.import_module(provider_class().__module__)
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    rows=[('/cal/work/'+str(i)+'.ics','"v'+str(i)+'"') for i in range(33)]
    replies.extend([(207,deferred_query(rows)),(207,fetched([(href,etag,event_ics(str(i))) for i,(href,etag) in enumerate(rows[:32])]))])
    monkeypatch.setattr(module,'MAX_REQUESTS',3) # discovery + query + first batch
    result=p.export(query([cid]))
    assert not result['ok'] and result['error']['code']=='caldav_limit'
    assert len([c for c in calls if c[1]=='REPORT'])==2


def test_multiget_etag_change_preserves_real_manager_package_and_read_time(tmp_path,wire):
    from datetime import date
    from manager.content import Settings
    from manager.service import ManagerService,ManagerError
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    service=ManagerService(tmp_path/'store',p)
    service.store.save_settings(Settings('Asia/Shanghai',date(2026,10,22),7,(cid,)))
    member='/cal/work/one.ics'
    replies.extend([(207,deferred_query([(member,'"v1"')])),(207,fetched([(member,'"v1"',event_ics())]))])
    first=service.sync(now=1792598400)['version'];read=service.store.last_successful_read()
    files={name:(service.store.load_current().directory/name).read_bytes() for name in ('content.ini','background.png','SHA256SUMS')}
    replies.extend([(207,collection()),(207,deferred_query([(member,'"v1"')])),(207,fetched([(member,'"v2"',event_ics())])),(207,deferred_query([(member,'"v2"')]))])
    with pytest.raises(ManagerError) as failed:
        service.sync(now=1792598400)
    assert failed.value.code=='caldav_changed'
    assert service.store.load_current().version==first and service.store.last_successful_read()==read
    assert {name:(service.store.load_current().directory/name).read_bytes() for name in files}==files
    assert not service.fresh_read


@pytest.mark.parametrize('body',[ics(),ics('UID:todo\nDTSTART:20261022T010000Z\nDTEND:20261022T020000Z').replace('VEVENT','VTODO')])
def test_listed_calendar_object_without_any_vevent_is_not_a_fresh_empty_read(tmp_path,wire,body):
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    replies.append((207,report(body)))
    failed=p.export(query([cid]));assert not failed['ok'] and 'readAt' not in failed


def test_operation_deadline_is_rechecked_after_callback(tmp_path,monkeypatch):
    p,_=configured(tmp_path);module=importlib.import_module(provider_class().__module__);clock=[100.]
    monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
    def late(sources,budget):
        clock[0]=131.
        return dict(schema=1,ok=True,readAt=1792600000,events=[])
    failed=p._operation(late)
    assert not failed['ok'] and failed['error']['code']=='caldav_timeout' and 'readAt' not in failed


@pytest.mark.parametrize('extra',['<d:href>https://evil.example/cal/work/one.ics</d:href>','<d:href><d:href>/cal/work/one.ics</d:href></d:href>'])
def test_response_with_multiple_or_nested_href_is_rejected(tmp_path,wire,extra):
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    body=report(event_ics()).replace(b'</d:href>',b'</d:href>'+extra.encode(),1)
    replies.append((207,body))
    failed=p.export(query([cid]));assert not failed['ok'] and 'events' not in failed


def test_client_library_expands_rule_exdate_rdate_moved_and_cancelled_override(tmp_path,wire):
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    body=ics('UID:daily\nDTSTART:20261020T010000Z\nDTEND:20261020T020000Z\nRRULE:FREQ=DAILY;COUNT=7\nEXDATE:20261022T010000Z\nRDATE:20261028T010000Z\nSUMMARY:base', 'UID:daily\nRECURRENCE-ID:20261023T010000Z\nDTSTART:20261023T050000Z\nDTEND:20261023T060000Z\nSUMMARY:moved', 'UID:daily\nRECURRENCE-ID:20261024T010000Z\nSTATUS:CANCELLED')
    replies.append((207,report(body)))
    result=p.export(query([cid]));assert result['ok'],result
    assert sorted(e['startEpoch'] for e in result['events'])==[1792731600,1792890000,1792976400,1793149200]
    assert [e['summary'] for e in result['events']].count('moved')==1
    assert len({e['id'] for e in result['events']})==4


def test_client_library_preserves_dst_all_day_and_ongoing_overlap(tmp_path,wire):
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    body=ics('UID:dst\nDTSTART;TZID=Europe/London:20261023T090000\nDTEND;TZID=Europe/London:20261023T100000\nRRULE:FREQ=DAILY;COUNT=5\nSUMMARY:dst', 'UID:day\nDTSTART;VALUE=DATE:20261020\nDTEND;VALUE=DATE:20261021\nRRULE:FREQ=DAILY;COUNT=10\nSUMMARY:day', 'UID:ongoing\nDTSTART:20261021T150000Z\nDTEND:20261021T170000Z\nSUMMARY:ongoing')
    replies.append((207,report(body)))
    result=p.export(query([cid]));assert result['ok'],result
    dst=sorted(e['startEpoch'] for e in result['events'] if e['summary']=='dst')
    assert dst==[1792742400,1792828800,1792918800,1793005200,1793091600]
    assert sorted(e['startDate'] for e in result['events'] if e['allDay'])==['2026-10-'+str(d) for d in range(22,29)]
    assert len([e for e in result['events'] if e['summary']=='ongoing'])==1


def test_dense_recurrence_fails_with_bounded_worker_and_no_read_at(tmp_path,wire):
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    body=ics('UID:dense\nDTSTART:20261022T000000Z\nDTEND:20261022T000001Z\nRRULE:FREQ=SECONDLY;COUNT=1000000')
    replies.append((207,report(body)));started=time.monotonic()
    failed=p.export(query([cid]))
    assert not failed['ok'] and 'readAt' not in failed and 'events' not in failed
    assert time.monotonic()-started<6.5


def test_raw_reversed_duration_is_not_silently_repaired_by_recurrence_library(tmp_path,wire):
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    body=ics('UID:bad-span\nDTSTART:20261022T020000Z\nDTEND:20261022T010000Z\nRRULE:FREQ=DAILY;COUNT=2')
    replies.append((207,report(body)))
    result=p.export(query([cid]));assert not result['ok'] and 'readAt' not in result


@pytest.mark.parametrize('rule',['','RRULE:FREQ=DAILY;COUNT=1\n'])
def test_source_floating_timezone_is_identical_with_and_without_rule(tmp_path,wire,rule):
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    body=ics('UID:floating\nDTSTART:20261022T090000\nDTEND:20261022T100000\n'+rule+'SUMMARY:source-zone').replace('VERSION:2.0','VERSION:2.0\r\nX-WR-TIMEZONE:America/New_York')
    replies.append((207,report(body)))
    result=p.export(query([cid]));assert result['ok'],result
    assert len(result['events'])==1
    assert result['events'][0]['startEpoch']==1792674000


def test_overrides_moving_into_and_out_of_window_use_actual_start(tmp_path,wire):
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    body=ics('UID:moving\nDTSTART:20261021T010000Z\nDTEND:20261021T020000Z\nRRULE:FREQ=DAILY;COUNT=3\nSUMMARY:base','UID:moving\nRECURRENCE-ID:20261021T010000Z\nDTSTART:20261022T060000Z\nDTEND:20261022T070000Z\nSUMMARY:moved-in','UID:moving\nRECURRENCE-ID:20261023T010000Z\nDTSTART:20261030T010000Z\nDTEND:20261030T020000Z\nSUMMARY:moved-out')
    replies.append((207,report(body)))
    result=p.export(query([cid]));assert result['ok'],result
    assert sorted(e['summary'] for e in result['events'])==['base','moved-in']


@pytest.mark.parametrize('fault',[None,'inventory_changed','inventory_missing','inventory_extra','inventory_duplicate','inventory_no_etag','inventory_duplicate_etag','data_changed','etag_changed','missing','duplicate','extra','no_data','budget'])
def test_report_specific_etags_require_stable_full_inventory_and_repeated_body(tmp_path,wire,monkeypatch,fault):
    from xml.etree import ElementTree as ET
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    member='/cal/work/one%20meeting.ics';other='/cal/work/two.ics'
    inventory=[(member,'query-tag'),(other,'same-tag')]
    first=[(member,'multiget-tag',event_ics()),(other,'same-tag',event_ics('two'))]
    second_inventory=list(inventory)
    if fault=='inventory_changed':second_inventory[0]=(member,'changed')
    elif fault=='inventory_missing':second_inventory.pop()
    elif fault=='inventory_extra':second_inventory.append(('/cal/work/extra.ics','extra'))
    elif fault=='inventory_duplicate':second_inventory.append(second_inventory[0])
    body=deferred_query(second_inventory)
    if fault=='inventory_no_etag':body=body.replace(b'<d:getetag>query-tag</d:getetag>',b'')
    elif fault=='inventory_duplicate_etag':body=body.replace(b'</d:getetag>',b'</d:getetag><d:getetag>other</d:getetag>',1)
    second=[first[0]]
    if fault=='data_changed':second=[(member,'multiget-tag',event_ics('changed'))]
    elif fault=='etag_changed':second=[(member,'changed',event_ics())]
    elif fault=='missing':second=[]
    elif fault=='duplicate':second.append(second[0])
    elif fault=='extra':second.append((other,'same-tag',event_ics('two')))
    elif fault=='no_data':second=[(member,'multiget-tag',None)]
    replies.extend([(207,deferred_query(inventory)),(207,fetched(first)),(207,body),(207,fetched(second))])
    if fault=='budget':monkeypatch.setattr(importlib.import_module(provider_class().__module__),'MAX_REQUESTS',4)
    result=p.export(query([cid]))
    if fault is not None:
        assert not result['ok'] and 'readAt' not in result and 'events' not in result
        assert len([c for c in calls if c[1]=='REPORT'])==(3 if fault.startswith('inventory_') or fault=='budget' else 4)
        if fault in {'inventory_changed','data_changed','etag_changed'}:assert result['error']['code']=='caldav_changed'
        return
    assert result['ok'] and len(result['events'])==2,result
    reports=[c for c in calls if c[1]=='REPORT'];assert len(reports)==4
    assert reports[0][3]==reports[2][3] and reports[0][4]['Depth']==reports[2][4]['Depth']=='1'
    retry=ET.fromstring(reports[3][3]);assert [n.text for n in retry.findall('{'+D+'}href')]==[member]
    assert not any(k.lower()=='depth' for k in reports[3][4])


@pytest.mark.parametrize('difference',['metadata','summary','location','time','cancelled','rule','timezone'])
def test_report_specific_etags_require_same_complete_reader_model(tmp_path,wire,difference):
    p,cid,calls,replies=fallback_setup(tmp_path,wire)
    member='/cal/work/model.ics';inventory=[(member,'query-tag')]
    event='UID:model\nDTSTART:20261022T010000Z\nDTEND:20261022T020000Z\nSUMMARY:original\nLOCATION:room\nDTSTAMP:20261022T000000Z\nATTENDEE:mailto:a@example.test\nATTENDEE:mailto:b@example.test'
    other=event.replace('DTSTAMP:20261022T000000Z','DTSTAMP:20261022T000001Z').replace('ATTENDEE:mailto:a@example.test\nATTENDEE:mailto:b@example.test','ATTENDEE:mailto:b@example.test\nATTENDEE:mailto:a@example.test')
    if difference=='summary':other=other.replace('SUMMARY:original','SUMMARY:changed')
    elif difference=='location':other=other.replace('LOCATION:room','LOCATION:changed')
    elif difference=='time':other=other.replace('20261022T020000Z','20261022T030000Z')
    elif difference=='cancelled':other+='\nSTATUS:CANCELLED'
    elif difference=='rule':other+='\nRRULE:FREQ=DAILY;COUNT=2'
    elif difference=='timezone':other=other.replace('DTSTART:20261022T010000Z','DTSTART;TZID=Asia/Shanghai:20261022T090000').replace('DTEND:20261022T020000Z','DTEND;TZID=Asia/Shanghai:20261022T100000')
    replies.extend([(207,deferred_query(inventory)),(207,fetched([(member,'multiget-tag',ics(event))])),(207,deferred_query(inventory)),(207,fetched([(member,'multiget-tag',ics(other))]))])
    result=p.export(query([cid]))
    if difference=='metadata':assert result['ok'] and len(result['events'])==1,result
    else:assert not result['ok'] and result['error']['code']=='caldav_changed' and 'readAt' not in result
    assert len([c for c in calls if c[1]=='REPORT'])==4


def test_unsaved_connection_probe_does_not_save_source_or_return_secrets(tmp_path, wire):
    calls,replies=wire
    p=provider_class()(tmp_path/'probe')
    replies.append((207,collection()))
    result=p.test_source(dict(label='Test',url='https://calendar.example/cal/',username='fixture',password='probe-secret',enabled=True))
    assert result['ok'] and result['calendar_count']==1
    assert p.list_sources()['sources']==[]
    assert 'probe-secret' not in json.dumps(result)


def test_edit_probe_reuses_only_its_own_saved_password(tmp_path, wire):
    calls,replies=wire;p,source=configured(tmp_path)
    replies.append((207,collection()))
    result=p.test_source(dict(id=source['id'],label=source['label'],url=source['url'],username=source['username'],enabled=True))
    assert result['ok'] and result['calendar_count']==1
    assert len(p.list_sources()['sources'])==1
    assert not p.test_source(dict(id='unknown',label='Test',url=source['url'],username='fixture',enabled=True))['ok']
