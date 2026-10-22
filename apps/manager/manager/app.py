"""Loopback FastAPI boundary with an owned in-process sync lifecycle."""
import argparse
from contextlib import asynccontextmanager

from starlette.concurrency import run_in_threadpool
import json
from pathlib import Path
import secrets
import socket
import sqlite3
import re
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
import uvicorn

from .images import Crop, MAX_UPLOAD
from .service import ManagerError, ManagerService
from .sync import SyncCoordinator
from .reader import create_reader_app, bounded_json
from .cloud_auth import CloudProfile, CloudAuth, COOKIE

STATIC = Path(__file__).with_name('static')


def failure(code, message, status=400):
    return JSONResponse(dict(schema=1, ok=False, error=dict(code=code, message=message)), status_code=status)


def create_app(root, provider=None, *, port=8767, service=None, coordinator_factory=SyncCoordinator, cloud_profile=None):
    if isinstance(cloud_profile, dict):cloud_profile=CloudProfile(**cloud_profile)
    if cloud_profile is not None and not isinstance(cloud_profile,CloudProfile):raise ValueError('explicit cloud profile required')
    if cloud_profile is not None and provider is None and service is None:
        from .caldav_provider import CalDAVProvider
        provider=CalDAVProvider(root)
    prefix=cloud_profile.prefix if cloud_profile else ''
    cloud_auth=CloudAuth(cloud_profile) if cloud_profile else None
    service = service or ManagerService(root, provider, default_timezone='Asia/Singapore' if cloud_profile else None)
    coordinator = coordinator_factory(service)
    from .fleet import DeviceFleet
    fleet=DeviceFleet(root,cloud_profile,service,coordinator,coordinator_factory) if cloud_profile else None

    @asynccontextmanager
    async def lifespan(app):
        if fleet:fleet.start()
        if not fleet or any(fleet.root_for(key)==fleet.root for key in cloud_profile.device_credentials):coordinator.start()
        try:
            yield
        finally:
            await run_in_threadpool(coordinator.stop)
            if fleet:await run_in_threadpool(fleet.stop)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.cloud_auth = cloud_auth
    app.state.cloud_profile = cloud_profile
    app.state.service = service
    app.state.coordinator = coordinator
    app.state.fleet = fleet
    session = secrets.token_urlsafe(32)
    style_nonce = secrets.token_urlsafe(24)
    host = f'127.0.0.1:{port}'
    origin = 'http://' + host

    def harden(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = f"default-src 'self'; script-src 'self'; style-src 'self' 'nonce-{style_nonce}'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response
    @app.middleware('http')
    async def browser_boundary(request, call_next):
        if cloud_profile:
            if not request.url.path.startswith(prefix+'/'):return harden(failure('not_found','页面不存在。',404))
            if not cloud_profile.trusted_request(request) or not cloud_profile.same_origin(request):return harden(failure('forbidden','管理来源验证失败。',403))
            path=request.url.path
            if path.startswith(prefix+'/api/') and path!=prefix+'/api/auth/login':
                active=cloud_auth.session(request.cookies.get(COOKIE,''))
                if active is None or request.headers.get('authorization'):return harden(failure('unauthorized','请登录管理账号。',401))
                if not cloud_profile.same_origin(request,required=True):return harden(failure('forbidden','需要同源管理请求。',403))
                if request.method not in {'GET','HEAD'}:
                    supplied=request.headers.getlist('x-csrf-token')
                    if len(supplied)!=1 or not secrets.compare_digest(supplied[0].encode('utf-8'),active['csrf'].encode('ascii')):return harden(failure('forbidden','请求验证失败，请重新登录。',403))
        else:
            if request.headers.get('host') != host:
                return failure('forbidden', '仅允许本机管理来源。', 403)
            supplied_origin = request.headers.get('origin')
            referer = request.headers.get('referer')
            referred_origin = None
            if referer:
                parsed = urlsplit(referer)
                referred_origin = f'{parsed.scheme}://{parsed.netloc}'
            if (supplied_origin is not None and supplied_origin != origin) or (referer and referred_origin != origin):
                return failure('forbidden', '管理来源验证失败。', 403)
            if request.headers.get('sec-fetch-site') in {'cross-site', 'same-site'}:
                return failure('forbidden', '管理页面只接受同源请求。', 403)
            if request.url.path.startswith('/api/'):
                if request.cookies.get('pandanote_session') != session or not (supplied_origin == origin or referred_origin == origin):
                    return failure('forbidden', '需要从本机管理页建立会话。', 403)
        try:
            response = await call_next(request)
        except (OSError, sqlite3.Error) as error:
            return harden(failure('storage_failure', '存储服务暂不可用。' if cloud_profile else '本地存储失败：' + str(error), 500))
        except Exception:
            if cloud_profile:return harden(failure('service_failure','服务暂不可用，已有内容已保留。',500))
            raise
        return harden(response)

    async def body(request, limit):
        if request.headers.get('transfer-encoding'):
            raise ManagerError('length_required', '需要明确的请求长度。')
        length = request.headers.get('content-length')
        if length is None or not length.isascii() or not length.isdecimal():
            raise ManagerError('length_required', '需要明确的请求长度。')
        if int(length) > limit:
            raise ManagerError('too_large', '上传内容超过大小限制。')
        chunks = bytearray()
        async for chunk in request.stream():
            if len(chunks) + len(chunk) > limit:
                raise ManagerError('too_large', '上传内容超过大小限制。')
            chunks.extend(chunk)
        if len(chunks) != int(length):
            raise ValueError('请求内容长度不一致。')
        return bytes(chunks)

    async def json_body(request):
        if request.headers.get('content-type','').split(';')[0] != 'application/json':
            raise ValueError('需要 application/json。')
        result = json.loads(await body(request, 64 * 1024))
        if not isinstance(result, dict):
            raise ValueError('需要 JSON 对象。')
        return result

    @app.exception_handler(ManagerError)
    async def manager_error(request, error):
        return failure(error.code if not cloud_profile or re.fullmatch('[a-z_]{1,64}',error.code) else 'calendar_failure', '日历服务暂不可用，已有内容已保留。' if cloud_profile else error.message, 413 if error.code == 'too_large' else 411 if error.code == 'length_required' else 409)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return failure('invalid_input', '输入无效，请检查配置。' if cloud_profile else str(error))

    @app.get(prefix+'/')
    def index():
        html = (STATIC/'index.html').read_text('utf-8').replace('<!--CSP_NONCE-->', '<meta name="csp-nonce" content="' + style_nonce + '"><meta name="app-prefix" content="'+prefix+'"><meta name="cloud-profile" content="'+('true' if cloud_profile else 'false')+'">')
        if cloud_profile:html=html.replace('<title>PandaNote 966U2 · 本机管理</title>','<title>PandaNote · 云管理</title>')
        if prefix:html=html.replace('src="/assets/', 'src="'+prefix+'/assets/').replace('href="/assets/', 'href="'+prefix+'/assets/')
        response = Response(html, media_type='text/html')
        if cloud_profile is None:response.set_cookie('pandanote_session', session, httponly=True, samesite='strict', path='/')
        return response

    @app.get(prefix+'/assets/{name}')
    def asset(name: str):
        if re.fullmatch(r'[A-Za-z0-9_-]{1,100}\.(js|css|webp|svg)', name) is None or not (STATIC/'assets'/name).is_file():
            return failure('not_found', '资源不存在。', 404)
        return FileResponse(STATIC/'assets'/name)

    @app.get(prefix+'/api/status')
    def status():
        value=app.state.service.status()
        if cloud_profile and value.get('error'):value['error']=dict(code='calendar_failure',message='日历服务暂不可用，已有内容已保留。')
        return value

    @app.get(prefix+'/api/calendars')
    def calendars():
        return app.state.service.calendars()

    @app.put(prefix+'/api/calendar-selection')
    async def selection(request: Request):
        value = await json_body(request)
        try:
            result = await run_in_threadpool(app.state.service.selection, value)
            coordinator.notify_change()
            return result
        except (TypeError, KeyError) as error:
            raise ValueError('日历配置格式无效。') from error

    @app.post(prefix+'/api/calendar/connect')
    async def connect(request: Request):
        await json_body(request)
        # Provider permission UI runs outside the event loop.
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(app.state.service.connect)

    @app.post(prefix+'/api/calendar/sync')
    async def sync(request: Request):
        await json_body(request)
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(coordinator.sync_once)

    @app.put(prefix+'/api/background')
    async def background(request: Request):
        encoded_crop = request.headers.get('x-crop', '{}')
        if len(encoded_crop) > 1024:
            raise ValueError('裁切参数过长。')
        crop = json.loads(encoded_crop)
        if not isinstance(crop, dict) or set(crop) - {'x','y','width','height'}:
            raise ValueError('裁切参数无效。')
        source = await body(request, MAX_UPLOAD)
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(app.state.service.background, source, Crop(**crop, mime_type=request.headers.get('content-type','')))

    @app.get(prefix+'/api/preview')
    def preview(version: str | None = None):
        value=app.state.service.preview(version)
        if prefix:value['resources']={name:prefix+url for name,url in value['resources'].items()}
        return value

    @app.get(prefix+'/api/draft-background')
    def draft_background():
        with app.state.service.lock:
            return Response(app.state.service._background(), media_type='image/png')

    @app.get(prefix+'/api/resources/{version}/{name}')
    def resource(version: str, name: str):
        if name not in {'content.ini','background.png','SHA256SUMS'}:
            return failure('not_found','资源不存在。',404)
        try:
            directory = app.state.service.store.load_version(version)
        except ValueError:
            return failure('not_found','版本不存在。',404)
        return FileResponse(directory/name, media_type='image/png' if name.endswith('.png') else 'text/plain', filename=name)

    if cloud_profile:
        @app.post(prefix+'/api/auth/login')
        async def cloud_login(request:Request):
            if not cloud_profile.same_origin(request,required=True):return failure('forbidden','需要同源管理请求。',403)
            if not cloud_auth.allow_login(cloud_profile.login_peer(request)):return failure('rate_limited','登录尝试过多，请稍后再试。',429)
            value,invalid=await bounded_json(request,4096)
            if invalid is not None:return invalid
            if set(value)!={'username','password'}:return failure('invalid_input','登录信息无效。')
            result=await run_in_threadpool(cloud_auth.login,value['username'],value['password'],request.cookies.get(COOKIE,''))
            if result is None:return failure('unauthorized','账号或密码不正确。',401)
            token,csrf=result;response=JSONResponse(dict(schema=1,ok=True,csrf_token=csrf,username=cloud_profile.admin_username))
            response.set_cookie(COOKIE,token,secure=True,httponly=True,samesite='strict',path=prefix+'/',max_age=cloud_profile.session_seconds)
            return response
        @app.get(prefix+'/api/auth/session')
        def cloud_session(request:Request):
            active=cloud_auth.session(request.cookies.get(COOKIE,''))
            if active is None:return failure('unauthorized','请登录管理账号。',401)
            return dict(schema=1,ok=True,csrf_token=active['csrf'],username=cloud_profile.admin_username)
        @app.post(prefix+'/api/auth/logout')
        async def cloud_logout(request:Request):
            value,invalid=await bounded_json(request,32)
            if invalid is not None:return invalid
            if value:return failure('invalid_input','请求无效。')
            cloud_auth.logout(request.cookies.get(COOKIE,''));response=JSONResponse(dict(schema=1,ok=True))
            response.delete_cookie(COOKIE,path=prefix+'/',secure=True,httponly=True,samesite='strict')
            return response
        def provider_operation(action,*args):
            try:
                with service.lock:result=getattr(service.provider,action)(*args)
                if not isinstance(result,dict) or result.get('ok') is not True:raise ValueError('provider failure')
                # Only these non-secret fields may cross the HTTP boundary.
                fields=('id','label','url','username','enabled','has_password','configured')
                clean=lambda item:{key:item[key] for key in fields if key in item}
                if action=='list_sources':return dict(schema=1,ok=True,sources=[clean(item) for item in result['sources']])
                if action=='save_source':return dict(schema=1,ok=True,source=clean(result['source']))
                return dict(schema=1,ok=True)
            except Exception:raise ManagerError('caldav_configuration','日历来源配置失败。') from None
        @app.get(prefix+'/api/caldav/sources')
        async def cloud_sources():return await run_in_threadpool(provider_operation,'list_sources')
        async def source_data(request):
            value=await json_body(request)
            if set(value)-{'label','url','username','password','enabled'} or not {'label','url','username'}<=set(value):raise ValueError('invalid source fields')
            if any(not isinstance(value[k],str) for k in ('label','url','username')) or ('password'in value and not isinstance(value['password'],str)) or ('enabled'in value and type(value['enabled']) is not bool):raise ValueError('invalid source values')
            return value
        @app.post(prefix+'/api/caldav/sources/test')
        async def test_calendar_source(request:Request):
            value=await json_body(request)
            if set(value)-{'id','label','url','username','password','enabled'} or not {'label','url','username'}<=set(value):raise ValueError('日历来源格式无效。')
            result=await run_in_threadpool(service.provider.test_source,value)
            if result.get('ok') is not True:return failure('connection_failed','连接失败，请检查地址、账号和应用专用密码。',409)
            return dict(schema=1,ok=True,connected=True,calendar_count=result['calendar_count'])
        @app.post(prefix+'/api/caldav/sources')
        async def source_add(request:Request):
            value=await source_data(request);result=await run_in_threadpool(provider_operation,'save_source',value);coordinator.notify_change();return result
        @app.put(prefix+'/api/caldav/sources/{source_id}')
        async def source_update(source_id:str,request:Request):
            if re.fullmatch('[A-Za-z0-9_-]{1,64}',source_id) is None:raise ValueError('invalid source id')
            value=await source_data(request);value['id']=source_id;result=await run_in_threadpool(provider_operation,'save_source',value);coordinator.notify_change();return result
        @app.delete(prefix+'/api/caldav/sources/{source_id}')
        async def source_delete(source_id:str,request:Request):
            if re.fullmatch('[A-Za-z0-9_-]{1,64}',source_id) is None:raise ValueError('invalid source id')
            value=await json_body(request)
            if value:raise ValueError('invalid deletion')
            result=await run_in_threadpool(provider_operation,'delete_source',source_id);coordinator.notify_change();return result

    from .ota_api import install_ota_admin_api
    ota_service=install_ota_admin_api(app,root,prefix,fleet)

    device_scope=fleet
    if fleet is None and ota_service and ota_service.config.get('local_device_id'):
        from .device_api import LocalOtaDeviceScope
        device_scope=LocalOtaDeviceScope(ota_service,service,coordinator)
    if device_scope:
        from .device_api import install_device_api
        install_device_api(app,prefix,device_scope,json_body,body,include_inventory=fleet is not None)
    return app


class LocalServer:
    """Small uvicorn lifecycle adapter used by CLI and real-HTTP tests."""
    def __init__(self, root, provider, port, coordinator_factory=SyncCoordinator):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(('127.0.0.1', port))
        self.server_port = self.socket.getsockname()[1]
        self.app = create_app(root, provider, port=self.server_port, coordinator_factory=coordinator_factory)
        self.service = self.app.state.service
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level='warning', access_log=False))
        self.socket.listen(128)
    def serve_forever(self):
        self.server.run(sockets=[self.socket])
    def shutdown(self):
        self.server.should_exit = True
    def server_close(self):
        self.socket.close()


def create_server(root, provider=None, *, port=8767, coordinator_factory=SyncCoordinator):
    return LocalServer(root, provider, port, coordinator_factory)


def main():
    parser = argparse.ArgumentParser(description='PandaNote 966U2 loopback manager')
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--data-root', type=Path, default=Path(__file__).resolve().parents[1]/'data')
    args = parser.parse_args()
    server = create_server(args.data_root, port=args.port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
