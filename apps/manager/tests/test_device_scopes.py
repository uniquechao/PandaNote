import hashlib,json
from manager.app import create_app
from manager.cloud import create_cloud_reader_app
from manager.store import Store
from test_api import ExampleProvider,ManualScheduler,selection
from test_cloud import profile,call,login,PREFIX,ORIGIN
from test_reader_api import publish
from asgi_client import request

TOKEN_A='Q'*43
TOKEN_B='A'*43

def config():
 p=profile();p['device_credentials']={'device_a':hashlib.sha256(TOKEN_A.encode()).hexdigest(),'device_b':hashlib.sha256(TOKEN_B.encode()).hexdigest()};return p

def test_independent_sources_settings_and_public_preview_urls(tmp_path):
 app=create_app(tmp_path/'data',cloud_profile=config(),coordinator_factory=ManualScheduler);auth=login(app)
 assert call(app,'GET',PREFIX+'/api/devices')[0]==401
 code,_,raw=call(app,'GET',PREFIX+'/api/devices',headers=auth);assert code==200
 assert [d['id'] for d in json.loads(raw)['devices']]==['device_a','device_b']
 base=PREFIX+'/api/devices/'
 a=dict(label='Alice',url='https://calendar.example.com/dav/',username='alice',password='private-alice',enabled=True)
 assert call(app,'POST',base+'device_a/caldav/sources',a,headers=auth)[0]==200
 for device,expected in [('device_a',1),('device_b',0)]:
  code,_,raw=call(app,'GET',base+device+'/caldav/sources',headers=auth);assert code==200
  assert len(json.loads(raw)['sources'])==expected and b'private-alice' not in raw
 value=selection();value['selected_calendar_ids']=['alice-calendar']
 assert call(app,'PUT',base+'device_a/calendar-selection',value,headers=auth)[0]==200
 code,_,raw=call(app,'GET',base+'device_b/status',headers=auth);assert code==200 and json.loads(raw)['settings']['selected_calendar_ids']==[]
 code,_,raw=call(app,'GET',base+'device_a/preview',headers=auth);assert code==200
 assert json.loads(raw)['resources']['background']==base+'device_a/draft-background'
 assert call(app,'GET',base+'unknown/status',headers=auth)[0]==404
 assert call(app,'POST',base+'device_a/caldav/sources',a,headers={'cookie':auth['cookie']})[0]==403

def test_device_bearer_cannot_read_or_ack_another_devices_content(tmp_path):
 root=tmp_path/'data';app=create_app(root,cloud_profile=config(),coordinator_factory=ManualScheduler)
 # Explicit scoped stores are also the roots used by publishers.
 a=publish(Store(root/'devices/device_a'));b=publish(Store(root/'devices/device_b'))
 reader=create_cloud_reader_app(root,config(),clock=lambda:1792516000)
 def get(token,method,path,body=None):return request(reader,method,PREFIX+path,body,authority='pandanote.example.invalid',headers={'authorization':'Bearer '+token})
 code,_,raw=get(TOKEN_A,'GET','/reader/v1/manifest');assert code==200 and json.loads(raw)['version']==a.version
 assert get(TOKEN_B,'GET','/reader/v1/resources/'+a.version+'/content.ini')[0]==404
 assert get(TOKEN_B,'POST','/reader/v1/ack',dict(schema=1,version=a.version,displayed=True))[0]==404
 assert get(TOKEN_B,'POST','/reader/v1/ack',dict(schema=1,version=b.version,displayed=True))[0]==200
 assert Store(root/'devices/device_b').load_value('reader_status')['last_displayed_version']==b.version
 assert Store(root/'devices/device_a').load_value('reader_status')['last_displayed_version'] is None

def test_existing_single_device_keeps_legacy_content_when_another_is_added(tmp_path):
 root=tmp_path/'data';current=publish(Store(root));one=profile();one['device_credentials']={'device_a':hashlib.sha256(TOKEN_A.encode()).hexdigest()}
 app=create_app(root,cloud_profile=one,coordinator_factory=ManualScheduler)
 app.state.fleet.bind_legacy()
 reader=create_cloud_reader_app(root,config(),clock=lambda:1792516000)
 def get(token):return request(reader,'GET',PREFIX+'/reader/v1/manifest',authority='pandanote.example.invalid',headers={'authorization':'Bearer '+token})
 assert json.loads(get(TOKEN_A)[2])['version']==current.version
 assert get(TOKEN_B)[0]==404
 assert Store(root).load_current().version==current.version

def test_connection_probe_is_device_scoped_csrf_protected_and_never_saves(tmp_path,monkeypatch):
 app=create_app(tmp_path/'data',cloud_profile=config(),coordinator_factory=ManualScheduler);auth=login(app)
 provider=app.state.fleet.bundle('device_a').service.provider
 seen=[]
 def discover(source,budget):
  seen.append(source['username']);return []
 monkeypatch.setattr(provider,'_discover',discover)
 path=PREFIX+'/api/devices/device_a/caldav/sources/test'
 draft=dict(label='Probe',url='https://calendar.example.com/',username='fixture-probe',password='probe-only-secret',enabled=True)
 assert call(app,'POST',path,draft,headers={'cookie':auth['cookie']})[0]==403 and not seen
 code,_,raw=call(app,'POST',path,draft,headers=auth)
 assert code==200 and json.loads(raw)['calendar_count']==0 and b'probe-only-secret' not in raw
 assert seen==['fixture-probe'] and provider.list_sources()['sources']==[]
 assert app.state.fleet.bundle('device_b').service.provider.list_sources()['sources']==[]
