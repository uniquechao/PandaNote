"""Public cloud authentication and prefix isolation; only in-process ASGI."""
import hashlib,json
from http.cookies import SimpleCookie
import pytest
from manager.app import create_app
from test_api import ExampleProvider,ManualScheduler
from test_reader_api import publish
from manager.store import Store
from asgi_client import request

ORIGIN='https://pandanote.example.invalid';PREFIX='/pandanote';PASSWORD='fixture-admin-password';DEVICE='Q'*43
SALT='0123456789abcdef0123456789abcdef'
HASH='pbkdf2_sha256$600000$'+SALT+'$'+hashlib.pbkdf2_hmac('sha256',PASSWORD.encode(),bytes.fromhex(SALT),600000).hex()
def profile():return dict(origin=ORIGIN,prefix=PREFIX,admin_username='admin',admin_password_hash=HASH,device_credentials={'fixture-reader':hashlib.sha256(DEVICE.encode()).hexdigest()})
def manager(root,provider=None):return create_app(root,provider or ExampleProvider(),cloud_profile=profile(),coordinator_factory=ManualScheduler)
def call(app,method,path,data=None,headers=None):return request(app,method,path,data,authority='pandanote.example.invalid',headers={'origin':ORIGIN,**(headers or {})})
def login(app):
 code,headers,raw=call(app,'POST',PREFIX+'/api/auth/login',dict(username='admin',password=PASSWORD));assert code==200,raw
 return {'cookie':headers['set-cookie'].split(';')[0],'x-csrf-token':json.loads(raw)['csrf_token']}

def test_cloud_never_auto_grants_an_admin_session(tmp_path):
 app=manager(tmp_path/'data');code,headers,html=call(app,'GET',PREFIX+'/')
 assert code==200 and 'set-cookie' not in headers
 assert b'app-prefix' in html and b'/pandanote' in html
 assert call(app,'GET',PREFIX+'/api/status')[0]==401
 assert call(app,'GET','/api/status')[0]==404
 assert call(app,'GET','/')[0]==404

def test_login_cookie_csrf_logout_and_session_expiry(tmp_path):
 app=manager(tmp_path/'data');now=[1000];app.state.cloud_auth.clock=lambda:now[0]
 code,h,raw=call(app,'POST',PREFIX+'/api/auth/login',dict(username='admin',password=PASSWORD));assert code==200
 cookie=SimpleCookie();cookie.load(h['set-cookie']);item=next(iter(cookie.values()));assert item['secure'] and item['httponly'] and item['samesite']=='strict' and item['path']==PREFIX+'/'
 auth={'cookie':h['set-cookie'].split(';')[0],'x-csrf-token':json.loads(raw)['csrf_token']}
 assert call(app,'GET',PREFIX+'/api/status',headers=auth)[0]==200
 assert call(app,'POST',PREFIX+'/api/calendar/connect',{},headers={'cookie':auth['cookie']})[0]==403
 assert call(app,'POST',PREFIX+'/api/calendar/connect',{},headers={**auth,'x-csrf-token':'wrong'})[0]==403
 assert call(app,'POST',PREFIX+'/api/calendar/connect',{},headers=auth)[0]==200
 assert call(app,'GET',PREFIX+'/api/status',headers={**auth,'origin':'https://evil.invalid'})[0]==403
 assert call(app,'GET',PREFIX+'/api/status',headers={**auth,'host':'evil.invalid','x-forwarded-host':'pandanote.example.invalid'})[0]==403
 assert call(app,'POST',PREFIX+'/api/auth/logout',{},headers=auth)[0]==200
 assert call(app,'GET',PREFIX+'/api/status',headers=auth)[0]==401
 auth=login(app);now[0]+=28801;assert call(app,'GET',PREFIX+'/api/status',headers=auth)[0]==401

def test_login_is_origin_bound_rate_limited_and_secret_free(tmp_path):
 app=manager(tmp_path/'data');body=dict(username='admin',password='fixture-secret-not-for-output')
 assert call(app,'POST',PREFIX+'/api/auth/login',body,headers={'origin':'null'})[0]==403
 for _ in range(6):
  code,_,raw=call(app,'POST',PREFIX+'/api/auth/login',body);assert code==401 and b'fixture-secret' not in raw
 assert call(app,'POST',PREFIX+'/api/auth/login',dict(username='admin',password=PASSWORD))[0]==429
 assert len(app.state.cloud_auth.sessions)==0

@pytest.mark.parametrize('bad', ['http://pandanote.example.invalid','https://pandanote.example.invalid/','https://pandanote.example.invalid/other','https://u:p@pandanote.example.invalid'])
def test_cloud_rejects_ambiguous_or_wrong_origins(tmp_path,bad):
 config=profile();config['origin']=bad
 with pytest.raises(ValueError):create_app(tmp_path/'data',ExampleProvider(),cloud_profile=config)

def test_admin_preview_and_resource_urls_keep_prefix(tmp_path):
 app=manager(tmp_path/'data');auth=login(app);code,_,raw=call(app,'GET',PREFIX+'/api/preview',headers=auth)
 assert code==200 and json.loads(raw)['resources']['background']==PREFIX+'/api/draft-background'
 assert call(app,'GET',PREFIX+'/api/draft-background',headers=auth)[0]==200

def test_reader_device_scope_and_admin_credentials_are_separate(tmp_path):
 from manager.cloud import create_cloud_reader_app
 from manager.cloud_auth import CloudProfile
 root=tmp_path/'data';current=publish(Store(root));admin=manager(root);auth=login(admin)
 reader=create_cloud_reader_app(root,CloudProfile(**profile()),clock=lambda:1792516000)
 def device(method,path,data=None,headers=None):return request(reader,method,path,data,authority='pandanote.example.invalid',headers={'authorization':'Bearer '+DEVICE,**(headers or {})})
 assert request(reader,'GET',PREFIX+'/reader/v1/manifest',authority='pandanote.example.invalid',headers=auth)[0]==401
 assert call(admin,'GET',PREFIX+'/api/status',headers={'authorization':'Bearer '+DEVICE})[0]==401
 assert device('GET','/reader/v1/manifest')[0]==404
 code,_,raw=device('GET',PREFIX+'/reader/v1/manifest');m=json.loads(raw);assert code==200
 for f in m['files']:
  assert f['path'].startswith('/reader/v1/resources/') # logical paths stay stable for native validator
  assert device('GET',PREFIX+f['path'])[2]==(current.directory/f['name']).read_bytes()
 assert device('POST',PREFIX+'/reader/v1/ack',dict(schema=1,version=current.version,displayed=True))[0]==200
 assert device('GET',PREFIX+'/api/status')[0]==404
 assert device('POST',PREFIX+'/api/calendar/sync',{})[0]==404
 assert device('GET',PREFIX+'/reader/v1/manifest',headers={'origin':ORIGIN})[0]==403
 assert device('GET',PREFIX+'/reader/v1/manifest?token=ignored')[0]==400
 assert DEVICE not in repr(reader.state.profile.device_credentials)

def test_caldav_source_CRUD_requires_csrf_and_returns_only_public_fields(tmp_path):
 from manager.caldav_provider import CalDAVProvider
 provider=CalDAVProvider(tmp_path/'provider');app=manager(tmp_path/'data',provider);auth=login(app)
 config=dict(label='工作',url='https://calendar.example.com/dav/',username='fixture-user',password='private-fixture-password',enabled=True)
 assert call(app,'POST',PREFIX+'/api/caldav/sources',config,headers={'cookie':auth['cookie']})[0]==403
 code,_,raw=call(app,'POST',PREFIX+'/api/caldav/sources',config,headers=auth);assert code==200,raw
 assert b'private-fixture-password' not in raw and b'"password"' not in raw
 identifier=json.loads(raw)['source']['id']
 code,_,raw=call(app,'PUT',PREFIX+'/api/caldav/sources/'+identifier,{**config,'label':'个人','password':''},headers=auth)
 assert code==200 and json.loads(raw)['source']['has_password'] is True
 code,_,raw=call(app,'GET',PREFIX+'/api/caldav/sources',headers=auth)
 assert code==200 and len(json.loads(raw)['sources'])==1 and b'private-fixture-password' not in raw
 assert call(app,'DELETE',PREFIX+'/api/caldav/sources/'+identifier,{},headers=auth)[0]==200
 assert json.loads(call(app,'GET',PREFIX+'/api/caldav/sources',headers=auth)[2])['sources']==[]

def test_cloud_private_profile_checks_descriptor_permissions_and_symlinks(tmp_path):
 from manager.cloud_auth import CloudProfile
 private=tmp_path/'private';private.mkdir(mode=0o700);path=private/'profile.json';path.write_text(json.dumps(profile()));path.chmod(0o600)
 assert CloudProfile.from_file(path).origin==ORIGIN
 path.chmod(0o644)
 with pytest.raises(ValueError):CloudProfile.from_file(path)
 path.chmod(0o600);link=private/'link';link.symlink_to(path)
 with pytest.raises((OSError,ValueError)):CloudProfile.from_file(link)
 private.chmod(0o755)
 with pytest.raises(ValueError):CloudProfile.from_file(path)

def test_cloud_errors_do_not_reflect_provider_or_filesystem_secrets(tmp_path):
 class Broken(ExampleProvider):
  def save_source(self,value):raise ValueError('private-password https://user:private-password@server /private/internal')
 app=manager(tmp_path/'data',Broken());auth=login(app)
 code,_,raw=call(app,'POST',PREFIX+'/api/caldav/sources',dict(label='work',url='https://calendar.example.com',username='u',password='private-password'),headers=auth)
 assert code==409 and b'private-password' not in raw and b'/private/internal' not in raw

def test_cloud_default_timezone_does_not_depend_on_server_localtime(tmp_path,monkeypatch):
 import manager.service as service_module
 def unavailable():raise ValueError('cloud must not consult OS localtime')
 monkeypatch.setattr(service_module,'local_zone',unavailable)
 app=manager(tmp_path/'new-data');assert app.state.service.settings().display_timezone=='Asia/Singapore'
 from manager.content import Settings
 from datetime import date
 app.state.service.store.save_settings(Settings('America/Los_Angeles',date(2020,1,1)))
 assert manager(tmp_path/'new-data').state.service.settings().display_timezone=='America/Los_Angeles'

def test_trusted_proxy_dedicated_client_ip_has_independent_login_buckets(tmp_path):
 app=manager(tmp_path/'data');bad=dict(username='admin',password='fixture-wrong')
 for _ in range(6):assert call(app,'POST',PREFIX+'/api/auth/login',bad,headers={'x-pandanote-client-ip':'198.51.100.10'})[0]==401
 assert call(app,'POST',PREFIX+'/api/auth/login',dict(username='admin',password=PASSWORD),headers={'x-pandanote-client-ip':'198.51.100.20'})[0]==200
 assert call(app,'POST',PREFIX+'/api/auth/login',dict(username='admin',password=PASSWORD),headers={'x-pandanote-client-ip':'198.51.100.10'})[0]==429

def test_generic_forwarded_or_malformed_client_headers_cannot_choose_buckets(tmp_path):
 app=manager(tmp_path/'data');bad=dict(username='admin',password='fixture-wrong')
 for i in range(6):assert call(app,'POST',PREFIX+'/api/auth/login',bad,headers={'x-forwarded-for':'198.51.100.'+str(i),'x-pandanote-client-ip':'invalid,multiple'})[0]==401
 assert call(app,'POST',PREFIX+'/api/auth/login',dict(username='admin',password=PASSWORD),headers={'x-forwarded-for':'203.0.113.55'})[0]==429


def test_public_marketing_assets_are_bounded_and_do_not_grant_private_api_access(tmp_path, monkeypatch):
    from manager import app as module
    static=tmp_path/'static';(static/'assets').mkdir(parents=True)
    (static/'assets'/'hero-fixture.webp').write_bytes(b'RIFF-fixture')
    (static/'assets'/'panda-fixture.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    (static/'assets'/'secret.json').write_text('{"private":true}')
    monkeypatch.setattr(module,'STATIC',static)
    app=manager(tmp_path/'data')
    for name,mime in [('hero-fixture.webp','image/webp'),('panda-fixture.svg','image/svg+xml')]:
        code,headers,raw=call(app,'GET',PREFIX+'/assets/'+name)
        assert code==200
        assert headers['content-type'].startswith(mime)
        assert headers['x-content-type-options']=='nosniff'
    assert call(app,'GET',PREFIX+'/assets/secret.json')[0]==404
    assert call(app,'GET',PREFIX+'/api/status')[0]==401
