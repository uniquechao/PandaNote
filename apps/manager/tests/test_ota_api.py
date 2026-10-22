import asyncio
import json
from fastapi import FastAPI
import pytest
from asgi_client import request,exchange
from manager.ota_api import install_ota_reader_api,install_ota_admin_api,Limiter
from manager.ota import OtaError
from manager.reader import create_reader_app
from manager.ota_store import encode,identifier
from ota_fixtures import Fixture,TOKEN

@pytest.fixture
def f(tmp_path):return Fixture(tmp_path)

def api(f,device='one'):
    app=FastAPI();install_ota_reader_api(app,f.path,lambda req,service:(device,TOKEN if device=='one' else 'second-token'),service=f.service)
    return app

def test_reader_check_chunk_report_and_device_isolation(f):
    release,candidate,directory,manifest=f.release();f.campaign(release);app=api(f);headers={'authorization':'Bearer '+TOKEN}
    check=f.check();code,h,raw=request(app,'POST','/reader/v1/ota/check',check,headers=headers);assert code==202 and int(h['content-length'])==len(raw)
    bundle=f.ready(check,candidate,directory)
    code,h,raw=request(app,'POST','/reader/v1/ota/check',check,headers=headers);assert code==200 and json.loads(raw)['status']=='update'
    chunk={'schema':1,'bundle_sha256':bundle,'index':0}
    assert request(app,'POST','/reader/v1/ota/chunk',chunk,headers=headers)[0]==200
    assert request(api(f,'two'),'POST','/reader/v1/ota/chunk',chunk,headers=headers)[0]==404
    event=f.event(bundle,manifest);assert request(app,'POST','/reader/v1/ota/report',event,headers=headers)[0]==200
    assert request(app,'POST','/reader/v1/ota/report',event,headers=headers)[0]==200
    assert not (f.path/'state.sqlite3').exists()

@pytest.mark.parametrize('headers',[{'cookie':'browser=session'},{'origin':'http://foreign.invalid'},{'content-length':'999999'},{'transfer-encoding':'chunked'}])
def test_reader_rejects_browser_and_bad_length_before_jobs(f,headers):
    code,_,raw=request(api(f),'POST','/reader/v1/ota/check',f.check(),headers={'authorization':'Bearer '+TOKEN,**headers})
    assert code in {403,411,413}
    with f.store.db() as db:assert not db.execute('SELECT 1 FROM ota_jobs').fetchone()
    assert TOKEN.encode() not in raw

def test_reader_duplicate_headers_json_and_rate_limit(f):
    from starlette.requests import Request
    from manager.ota_api import body
    scope=dict(type='http',method='POST',path='/',headers=[(b'content-length',b'2'),(b'content-length',b'2'),(b'content-type',b'application/json')])
    with pytest.raises(OtaError) as e:asyncio.run(body(Request(scope),4096))
    assert e.value.code=='length_required'
    app=api(f);headers={'authorization':'Bearer '+TOKEN,'content-type':'application/json'}
    assert request(app,'POST','/reader/v1/ota/check',b'{"schema":1,"schema":1}',headers=headers)[0]==400
    assert request(app,'POST','/reader/v1/ota/check?device=two',f.check(),headers=headers)[0]==403
    now=[1];limiter=Limiter(lambda:now[0]);limiter.enter('one','chunk');limiter.enter('one','chunk')
    with pytest.raises(OtaError):limiter.enter('one','chunk')
    limiter.leave('one','chunk');limiter.enter('one','chunk');now[0]+=60;limiter.enter('one','check');limiter.enter('one','check')
    with pytest.raises(OtaError):limiter.enter('one','check')

def test_real_local_reader_ota_disabled_content_unchanged(f):
    app=create_reader_app(f.path,TOKEN)
    assert request(app,'POST','/reader/v1/ota/check',f.check(),headers={'authorization':'Bearer '+TOKEN})[0]==409
    assert request(app,'GET','/api/ota/releases',headers={'authorization':'Bearer '+TOKEN})[0]==404

def test_admin_boundary_and_disabled_state(f):
    from test_api import ExampleProvider,ManualScheduler
    from manager.app import create_app
    app=create_app(f.path,ExampleProvider(),coordinator_factory=ManualScheduler)
    assert request(app,'GET','/api/ota/status',authority='127.0.0.1:8767')[0]==403
    _,headers,_=request(app,'GET','/',authority='127.0.0.1:8767')
    auth={'cookie':headers['set-cookie'].split(';')[0],'origin':'http://127.0.0.1:8767'}
    code,_,raw=request(app,'GET','/api/ota/status',authority='127.0.0.1:8767',headers=auth);assert code==200 and not json.loads(raw)['enabled']
    assert request(app,'GET','/api/ota/releases',authority='127.0.0.1:8767',headers=auth)[0]==503
    assert request(app,'POST','/reader/v1/ota/check',f.check(),authority='127.0.0.1:8767',headers=auth)[0]==404

def test_store_seal_rejects_same_size_replacement(f):
    raw=b'fixed';key=f.store.put(raw,'wire');path=f.store.root/'objects'/key
    assert f.store.chunk(key,0)==raw
    path.write_bytes(b'wrong')
    with pytest.raises(ValueError):f.store.chunk(key,0)

def test_local_shared_token_mapping_does_not_gain_ota(f):
    app=FastAPI();install_ota_reader_api(app,f.path,lambda request,service:('two',TOKEN),service=f.service)
    code,_,raw=request(app,'POST','/reader/v1/ota/check',f.check(),headers={'authorization':'Bearer '+TOKEN})
    assert code==409 and json.loads(raw)['error']['code']=='ota_not_enrolled'

def test_malformed_error_enum_never_raises_internal_error(f):
    release,candidate,directory,manifest=f.release();f.campaign(release);check=f.check();f.service.check('one',check);bundle=f.ready(check,candidate,directory);f.service.check('one',check)
    event=f.event(bundle,manifest);event['error_code']=[]
    code,_,raw=request(api(f),'POST','/reader/v1/ota/report',event,headers={'authorization':'Bearer '+TOKEN})
    assert code==400 and json.loads(raw)['error']['code']=='invalid_input'

def test_current_admin_credential_scope_prevents_old_device_campaign(f):
    release,_,_,_=f.release();f.service.authorized_devices={'two':None}
    with pytest.raises(OtaError) as error:f.campaign(release)
    assert error.value.code=='ota_not_enrolled'

def test_corrupt_chunk_quarantines_future_dispatch(f):
    release,candidate,directory,_=f.release();campaign=f.campaign(release);check=f.check();f.service.check('one',check);bundle=f.ready(check,candidate,directory);f.service.check('one',check)
    path=f.store.root/'objects'/bundle;raw=path.read_bytes();path.write_bytes(b'x'+raw[1:])
    code,_,_=request(api(f),'POST','/reader/v1/ota/chunk',{'schema':1,'bundle_sha256':bundle,'index':0},headers={'authorization':'Bearer '+TOKEN})
    assert code==503
    with f.store.db() as db:assert db.execute("SELECT 1 FROM ota_settings WHERE key='quarantined'").fetchone()
    assert f.service.campaign(campaign)['campaign']['state']=='PAUSED'

def test_local_enrolled_device_reuses_existing_content_routes(f,monkeypatch):
    from manager.app import create_app
    from test_api import ExampleProvider,ManualScheduler
    monkeypatch.setattr('manager.ota_api.load_service',lambda *args,**kwargs:f.service)
    app=create_app(f.path,ExampleProvider(),coordinator_factory=ManualScheduler)
    _,headers,_=request(app,'GET','/',authority='127.0.0.1:8767')
    auth={'cookie':headers['set-cookie'].split(';')[0],'origin':'http://127.0.0.1:8767'}
    def call(path):return request(app,'GET',path,headers=auth,authority='127.0.0.1:8767')
    assert call('/api/devices/one/status')[0]==200
    assert call('/api/devices/one/calendars')[0]==200
    code,_,raw=call('/api/devices/one/preview');assert code==200
    preview=json.loads(raw);assert preview['resources']['background']=='/api/devices/one/draft-background'
    assert call('/api/devices/one/draft-background')[0]==200
    assert call('/api/devices/two/status')[0]==404
    assert app.state.fleet is None
