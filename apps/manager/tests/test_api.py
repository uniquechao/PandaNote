"""HTTP acceptance tests: real loopback transport, Store and image pipeline."""
from contextlib import contextmanager
from datetime import date
import hashlib
import http.client
from io import BytesIO
import json
from pathlib import Path
import threading
import time

from PIL import Image
import pytest

from manager.app import create_server
from manager.provider import UnavailableProvider
from manager.service import ManagerService
from manager.store import Store
from manager.sync import SyncCoordinator


class ExampleProvider:
    label = 'example'
    def __init__(self):
        self.calls = []
        self.authorization = 'authorized'
        self.events = []
        self.failure = False
    def status(self):
        self.calls.append('status')
        return dict(schema=1, ok=True, authorization=self.authorization)
    def request_access(self):
        self.calls.append('request-access')
        return self.status()
    def calendars(self):
        self.calls.append('calendars')
        if self.authorization != 'authorized':
            return dict(schema=1, ok=False, error=dict(code='permission_denied', message='示例权限已拒绝'))
        return dict(schema=1, ok=True, calendars=[dict(id='work', title='示例工作'), dict(id='home', title='示例生活')])
    def export(self, query):
        self.calls.append(('export', query))
        if self.failure or self.authorization != 'authorized':
            return dict(schema=1, ok=False, error=dict(code='permission_denied', message='示例权限已拒绝'))
        return dict(schema=1, ok=True, readAt=int(time.time()), calendarIds=query['calendarIds'], missingCalendarIds=[], events=self.events)


def png(color='gray'):
    out = BytesIO()
    Image.new('RGB', (600, 1000), color).save(out, 'PNG')
    return out.getvalue()


class ManualScheduler(SyncCoordinator):
    """Hold autonomous time in manual API tests; manual sync remains real."""
    def start(self):
        pass


@contextmanager
def running(root, provider=None, *, automatic=False):
    server = create_server(root, provider=provider or ExampleProvider(), port=0,
                           coordinator_factory=SyncCoordinator if automatic else ManualScheduler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Client(server), server.service
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


class Client:
    def __init__(self, server):
        self.port = server.server_port
        self.origin = f'http://127.0.0.1:{self.port}'
        self.cookie = ''
        _, headers, _ = self.request('GET', '/', private=False)
        self.cookie = headers['set-cookie'].split(';')[0]
    def request(self, method, path, body=None, *, private=True, headers=None):
        h = {'Origin': self.origin, **({'Cookie': self.cookie} if private else {})}
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            h['Content-Type'] = 'application/json'
        h.update(headers or {})
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        conn.request(method, path, body, h)
        response = conn.getresponse()
        data = response.read()
        result = response.status, {key.lower():value for key,value in response.getheaders()}, data
        conn.close()
        return result
    def json(self, method, path, body=None, **kwargs):
        code, _, data = self.request(method, path, body, **kwargs)
        return code, json.loads(data)


def selection(ids=('work',)):
    return dict(display_timezone='Asia/Singapore', window_start=date.today().isoformat(), day_count=7, selected_calendar_ids=list(ids))


def event():
    now = int(time.time())
    return dict(id='occurrence-1', calendarId='work', summary='示例项目复盘', location='示例会议室', allDay=False, sourceTimezone='Asia/Singapore', startEpoch=now-60, endEpoch=now+3600)


def test_selection_and_full_replacement(tmp_path):
    provider = ExampleProvider()
    provider.events = [event()]
    with running(tmp_path/'data', provider) as (client, service):
        assert client.json('PUT', '/api/calendar-selection', selection())[0] == 200
        assert client.json('POST', '/api/calendar/sync', {})[1]['published']
        first = client.json('GET', '/api/preview')[1]
        assert first['events'][0]['summary'] == '示例项目复盘'
        provider.events = []  # cancelled/deleted occurrence: authoritative empty
        assert client.json('POST', '/api/calendar/sync', {})[0] == 200
        second = client.json('GET', '/api/preview')[1]
        assert second['events'] == []
        assert second['version'] != first['version']
        assert client.json('GET', '/api/preview?version='+first['version'])[1]['events'] == first['events']


def test_upload_crop_and_same_version_resources(tmp_path):
    with running(tmp_path/'data') as (client, service):
        client.json('PUT', '/api/calendar-selection', selection())
        client.json('POST', '/api/calendar/sync', {})
        code, result = client.json('PUT', '/api/background', png('black'), headers={'Content-Type':'image/png', 'X-Crop':json.dumps(dict(x=30,y=50,width=480,height=800))})
        assert code == 200 and result['published']
        preview = client.json('GET', '/api/preview')[1]
        content = client.request('GET', preview['resources']['content.ini'])[2]
        background = client.request('GET', preview['resources']['background.png'])[2]
        manifest = client.request('GET', preview['resources']['SHA256SUMS'])[2]
        assert (service.store.load_version(preview['version'])/'content.ini').read_bytes() == content
        assert hashlib.sha256(content).hexdigest().encode() in manifest
        assert hashlib.sha256(background).hexdigest().encode() in manifest
        assert Image.open(BytesIO(background)).size == (480,800)
        assert Image.open(BytesIO(background)).getpixel((1,1)) == 0
        assert preview['layout']['width'] == 480 and preview['layout']['height'] == 800
        assert preview['source'] == 'example'


def test_unavailable_and_permission_failure_retain_content(tmp_path):
    unavailable = UnavailableProvider()
    with running(tmp_path/'data', unavailable) as (client, service):
        status = client.json('GET','/api/status')[1]
        assert status['authorization'] == 'unavailable' and status['source_state'] == 'never_synced'
        assert client.json('POST','/api/calendar/connect',{})[1]['error']['code'] == 'bridge_unavailable'
        code, result = client.json('PUT','/api/background',png(),headers={'Content-Type':'image/png'})
        assert code == 200 and result['draft'] and not result['published']
        assert client.json('GET','/api/preview')[1]['draft']
    provider = ExampleProvider()
    provider.events = [event()]
    with running(tmp_path/'good',provider) as (client, service):
        client.json('PUT','/api/calendar-selection',selection())
        client.json('POST','/api/calendar/sync',{})
        version = service.store.load_current().version
        provider.authorization = 'denied'
        code, result = client.json('POST','/api/calendar/sync',{})
        assert code == 409 and result['error']['code'] == 'permission_denied'
        assert service.store.load_current().version == version
        assert client.json('GET','/api/status')[1]['source_state'] == 'cached'
        assert 'request-access' not in provider.calls
        client.json('POST','/api/calendar/connect',{})
        assert provider.calls.count('request-access') == 1


def test_offline_background_restart_preserves_calendar_and_desired_selection(tmp_path):
    provider = ExampleProvider()
    provider.events = [event()]
    root=tmp_path/'data'
    with running(root,provider) as (client, service):
        client.json('PUT','/api/calendar-selection',selection())
        client.json('POST','/api/calendar/sync',{})
        old_read = service.store.last_successful_read()
        provider.failure=True
        client.json('PUT','/api/calendar-selection',selection(('home','missing')))
        client.json('POST','/api/calendar/sync',{})
    with running(root,UnavailableProvider()) as (client, service):
        code, result=client.json('PUT','/api/background',png('black'),headers={'Content-Type':'image/png'})
        assert code == 200 and result['published'] and result['source_state']=='cached'
        preview=client.json('GET','/api/preview')[1]
        assert preview['events'][0]['summary']=='示例项目复盘'
        assert preview['published_settings']['selected_calendar_ids']==['work']
        assert service.store.load_settings().selected_calendar_ids==('home','missing')
        assert service.store.last_successful_read()==old_read
        status=client.json('GET','/api/status')[1]
        assert status['device']['last_contact_at'] is None and status['device']['last_displayed_version'] is None


@pytest.mark.parametrize('method,path,body', [('GET','/api/status',None),('GET','/api/calendars',None),('GET','/api/preview',None),('POST','/api/calendar/connect',{}),('POST','/api/calendar/sync',{}),('PUT','/api/calendar-selection',selection()),('PUT','/api/background',b'x')])
def test_private_reads_and_mutations_require_session_and_local_origin(tmp_path,method,path,body):
    provider=ExampleProvider()
    with running(tmp_path/'data',provider) as (client,service):
        before=list(provider.calls)
        assert client.json(method,path,body,private=False)[0]==403
        assert client.json(method,path,body,headers={'Origin':'http://evil.invalid'})[0]==403
        assert client.json(method,path,body,headers={'Host':'localhost:'+str(client.port)})[0]==403
        assert provider.calls==before


def test_resources_private_and_invalid_image_preserves_previous(tmp_path):
    with running(tmp_path/'data') as (client,service):
        client.json('POST','/api/calendar/sync',{})
        preview=client.json('GET','/api/preview')[1]
        url=preview['resources']['background.png']
        assert client.request('GET',url,private=False)[0]==403
        version=service.store.load_current().version
        assert client.json('PUT','/api/background',b'bad',headers={'Content-Type':'image/png'})[0]==400
        assert service.store.load_current().version==version
        assert client.request('GET','/api/resources/../../state.sqlite3')[0]==404


def test_size_bound_before_body_read_and_no_provider_calls(tmp_path):
    with running(tmp_path/'data') as (client,service):
        assert client.json('PUT','/api/background',b'',headers={'Content-Type':'image/png','Content-Length':str(10*1024*1024+1)})[0]==413
        assert client.json('PUT','/api/calendar-selection',{'bad':'x'})[0]==400


def test_private_permissions_and_initial_timezone(tmp_path):
    with running(tmp_path/'data') as (client,service):
        status=client.json('GET','/api/status')[1]
        assert status['settings']['display_timezone']=='Asia/Singapore'
        client.json('PUT','/api/calendar-selection',selection())
        assert (service.store.root.stat().st_mode & 0o777)==0o700
        assert ((service.store.root/'state.sqlite3').stat().st_mode & 0o777)==0o600


def test_old_preview_resources_survive_new_background_and_missing_read_headers(tmp_path):
    with running(tmp_path/'data') as (client,service):
        client.json('POST','/api/calendar/sync',{})
        preview=client.json('GET','/api/preview')[1]
        previous=client.request('GET',preview['resources']['background.png'])[2]
        assert client.json('PUT','/api/background',png('black'),headers={'Content-Type':'image/png'})[0]==200
        assert client.json('GET','/api/preview')[1]['version']!=preview['version']
        assert client.request('GET',preview['resources']['background.png'])[2]==previous
        assert client.json('GET','/api/status',headers={'Origin':''})[0]==403
        assert client.json('GET','/',private=False,headers={'Origin':'http://foreign.invalid'})[0]==403
        assert client.json('GET','/',private=False,headers={'Sec-Fetch-Site':'cross-site'})[0]==403


def test_inflight_export_cannot_overwrite_new_desired_selection(tmp_path):
    started, release=threading.Event(), threading.Event()
    class Slow(ExampleProvider):
        def export(self,query):
            started.set()
            assert release.wait(3)
            return super().export(query)
    provider=Slow()
    with running(tmp_path/'data',provider) as (client,service):
        client.json('PUT','/api/calendar-selection',selection())
        results=[]
        sync=threading.Thread(target=lambda:results.append(service.sync()))
        sync.start()
        assert started.wait(2)
        selection_thread=threading.Thread(target=lambda:results.append(service.selection(selection(('home',)))))
        selection_thread.start()
        release.set()
        sync.join(4);selection_thread.join(4)
        assert len(results)==2
        assert service.store.load_settings().selected_calendar_ids==('home',)
        assert client.json('GET','/api/preview')[1]['published_settings']['selected_calendar_ids']==['work']


def test_missing_calendar_selection_retained_and_invalid_export_rejected(tmp_path):
    class Missing(ExampleProvider):
        invalid=False
        def export(self,query):
            result=super().export(query)
            result['calendarIds']=[]
            result['missingCalendarIds']=[] if self.invalid else query['calendarIds']
            return result
    provider=Missing()
    with running(tmp_path/'data',provider) as (client,service):
        client.json('PUT','/api/calendar-selection',selection(('missing',)))
        assert client.json('POST','/api/calendar/sync',{})[0]==200
        preview=client.json('GET','/api/preview')[1]
        assert preview['missing_calendar_ids']==['missing'] and preview['events']==[]
        assert service.store.load_settings().selected_calendar_ids==('missing',)
        provider.invalid=True
        assert client.json('POST','/api/calendar/sync',{})[1]['error']['code']=='invalid_snapshot'
        assert service.store.load_current().version==preview['version']


@pytest.mark.parametrize('changes', [dict(window_start='2020-01-01'),dict(day_count=9),dict(day_count=1)])
def test_public_configuration_cannot_expand_today_seven_day_window(tmp_path,changes):
    with running(tmp_path/'data') as (client,service):
        assert client.json('PUT','/api/calendar-selection',{**selection(),**changes})[0]==400
        assert not any(isinstance(call,tuple) for call in service.provider.calls)


def test_export_uses_display_zone_today_seven_even_with_old_saved_settings(tmp_path,monkeypatch):
    from datetime import datetime,timezone
    from manager.content import Settings
    import manager.service as service_module
    class FixedDateTime(datetime):
        @classmethod
        def now(cls,zone=None):
            return datetime(2026,10,21,0,30,tzinfo=timezone.utc).astimezone(zone)
    monkeypatch.setattr(service_module,'datetime',FixedDateTime)
    # API synchronization gets its timestamp from the coordinator, not from
    # datetime.now inside the service. Pin both independent clock boundaries.
    fixed_epoch=datetime(2026,10,21,0,30,tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(ManualScheduler,'__init__',lambda self,service:SyncCoordinator.__init__(self,service,wall_clock=lambda:fixed_epoch))
    provider=ExampleProvider()
    with running(tmp_path/'data',provider) as (client,service):
        service.store.save_settings(Settings('America/Los_Angeles',date(2020,1,1),9,('work',)))
        assert client.json('POST','/api/calendar/sync',{})[0]==200
        query=[item[1] for item in provider.calls if isinstance(item,tuple)][-1]
        assert query['windowStartDate']=='2026-10-20' and query['dayCount']==7
        assert datetime.fromtimestamp(query['startEpoch'],timezone.utc).isoformat()=='2026-10-20T07:00:00+00:00'
        assert datetime.fromtimestamp(query['endEpoch'],timezone.utc).isoformat()=='2026-10-27T07:00:00+00:00'


@pytest.mark.parametrize('operation', ['save','publish'])
def test_sqlite_failure_returns_concrete_json_and_retains_old_version(tmp_path,operation):
    import sqlite3
    with running(tmp_path/'data') as (client,service):
        client.json('PUT','/api/calendar-selection',selection())
        client.json('POST','/api/calendar/sync',{})
        previous=service.store.load_current()
        original=(previous.directory/'content.ini').read_bytes()
        column='settings' if operation=='save' else 'version'
        with sqlite3.connect(service.store.root/'state.sqlite3') as db:
            db.execute(f"CREATE TRIGGER full_disk BEFORE UPDATE OF {column} ON state BEGIN SELECT RAISE(ABORT, 'database or disk is full'); END")
        code,headers,data=client.request('PUT','/api/calendar-selection',selection(('home',))) if operation=='save' else client.request('PUT','/api/background',png('black'),headers={'Content-Type':'image/png'})
        assert code==500 and headers['content-type'].startswith('application/json')
        error=json.loads(data)['error']
        assert error['code']=='storage_failure' and 'database or disk is full' in error['message']
        assert service.store.load_current().version==previous.version
        assert (previous.directory/'content.ini').read_bytes()==original
