"""共享 OTA reader 与管理路由，复用既有外层认证。"""
from collections import defaultdict,deque
import threading
import sqlite3
import time
from fastapi import Request
from fastapi.responses import JSONResponse,Response
from starlette.concurrency import run_in_threadpool
from .ota import OtaError,fail,load_service
from .ota_store import strict_json,encode

MESSAGES={'ota_disabled':'OTA 尚未启用，请先完成受控接入。','revision_conflict':'记录已更新，请刷新后重试。','idempotency_conflict':'重复请求内容不一致，请刷新后重试。','invalid_state':'当前状态不允许此操作。','signing_unavailable':'签名服务暂不可用，请稍后重试。','build_unavailable':'候选构建暂不可用。','ota_not_enrolled':'设备尚未完成 OTA 受控接入。','baseline_unsupported':'缺少已审核的完整旧包。','baseline_mismatch':'设备基线不一致，需要核对。','incompatible_release':'发布与设备或受控输入不兼容。','attempt_conflict':'设备存在未核对完成的升级事务或告警。','observation_pending':'当前批次尚未满足健康确认与观察时长。','storage_failure':'OTA 存储校验失败，已停止派发。','not_found':'记录不存在。','invalid_input':'输入无效，请检查后重试。'}

def failure(code,status,reader=False):return JSONResponse(dict(schema=1,ok=False,error=dict(code=code,message=code if reader else MESSAGES.get(code,'OTA 操作失败，请刷新后重试。'))),status_code=status)
async def body(request,limit):
    lengths=request.headers.getlist('content-length')
    if request.headers.getlist('transfer-encoding') or len(lengths)!=1 or not lengths[0].isascii() or not lengths[0].isdecimal():fail('length_required',411)
    if len(lengths[0])>10 or int(lengths[0])>limit:fail('too_large',413)
    if request.headers.getlist('content-type')!=['application/json']:fail('invalid_input',400)
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>limit:fail('too_large',413)
    if len(raw)!=int(lengths[0]):fail('invalid_input',400)
    value=strict_json(bytes(raw),limit)
    if not isinstance(value,dict):fail('invalid_input',400)
    return value

class Limiter:
    def __init__(self,clock=time.monotonic):self.clock=clock;self.buckets={};self.active=defaultdict(int);self.lock=threading.Lock()
    def enter(self,device,action):
        now=self.clock();window,limit=(60,2) if action=='check' else (60,60) if action=='report' else (1,4)
        with self.lock:
            # 每次按最长窗口清理，避免未接入身份造成无限增长。
            self.buckets={k:v for k,v in self.buckets.items() if v and now-v[-1]<60}
            key=(device,action);bucket=self.buckets.setdefault(key,deque())
            while bucket and now-bucket[0]>=window:bucket.popleft()
            if len(bucket)>=limit or action=='chunk' and self.active[device]>=2:fail('rate_limited',429)
            bucket.append(now)
            if action=='chunk':self.active[device]+=1
    def leave(self,device,action):
        if action=='chunk':
            with self.lock:self.active[device]-=1

def install_ota_reader_api(app,root,identity,prefix='',service=None):
    service=service or load_service(root);limiter=Limiter()
    def endpoint(action):
        async def route(request:Request):
            entered=False;device=None
            try:
                if request.headers.getlist('cookie') or request.headers.getlist('origin') or request.scope['query_string']:fail('forbidden',403)
                if len(request.headers.getlist('authorization'))!=1 or len(request.headers.getlist('host'))!=1:fail('unauthorized',401)
                if service is None:fail('ota_not_enrolled')
                device,credential=identity(request,service)
                if not device:fail('ota_not_enrolled')
                await run_in_threadpool(service.device,device,credential)
                limiter.enter(device,action);entered=True
                value=await body(request,1024 if action=='chunk' else 4096)
                result=await run_in_threadpool(getattr(service,action),device,value,credential)
                if action=='chunk':return Response(result,media_type='application/octet-stream')
                raw=encode(result)
                return Response(raw,media_type='application/json',status_code=202 if 'retry_seconds' in result else 200)
            except OtaError as error:
                response=failure(error.code,error.status,True)
                if error.status==429:response.headers['Retry-After']='60' if action!='chunk' else '1'
                return response
            except ValueError as error:
                code=str(error)
                if code=='storage_failure' and service:
                    try:await run_in_threadpool(service.quarantine)
                    except (OSError,ValueError,sqlite3.Error):pass
                return failure(code if code in {'invalid_input','too_large','not_found'} else 'storage_failure',400 if code=='invalid_input' else 413 if code=='too_large' else 404 if code=='not_found' else 503,True)
            except (OSError,RuntimeError,sqlite3.Error):
                if service:
                    try:await run_in_threadpool(service.quarantine)
                    except (OSError,ValueError,sqlite3.Error):pass
                return failure('storage_failure',503,True)
            finally:
                if entered:limiter.leave(device,action)
        return route
    for action in ('check','chunk','report'):app.add_api_route(prefix+'/reader/v1/ota/'+action,endpoint(action),methods=['POST'])

def install_ota_admin_api(app,root,prefix='',fleet=None,service=None):
    service=service or load_service(root)
    if service:
        profile=app.state.cloud_profile
        service.authorized_devices=profile.device_credentials if profile else {service.config.get('local_device_id'):None}
    def available():
        if service is None:fail('ota_disabled',503)
        return service
    def actor():return app.state.cloud_profile.admin_username if app.state.cloud_profile else 'local-admin'
    async def call(function,*args):
        try:return await run_in_threadpool(function,*args)
        except OtaError as error:return failure(error.code,error.status)
        except ValueError as error:return failure('storage_failure',503) if str(error)=='storage_failure' else failure('invalid_input',400)
        except (TypeError,KeyError):return failure('invalid_input',400)
        except (OSError,sqlite3.Error):return failure('storage_failure',503)
    from fastapi.exceptions import RequestValidationError
    from fastapi.exception_handlers import request_validation_exception_handler
    @app.exception_handler(RequestValidationError)
    async def input_error(request,error):
        if '/ota' in request.url.path:return failure('invalid_input',400)
        return await request_validation_exception_handler(request,error)
    @app.exception_handler(OtaError)
    async def ota_error(request,error):return failure(error.code,error.status)
    base=prefix+'/api'
    if fleet is None:
        @app.get(base+'/devices')
        def local_devices():
            device_id=service.config.get('local_device_id') if service else None
            devices=[]
            if device_id:
                service.device(device_id)
                devices=[dict(id=device_id,name='PandaNote · '+device_id,status=app.state.service.status())]
            return dict(schema=1,ok=True,devices=devices)
    @app.get(base+'/ota/status')
    def status():return dict(schema=1,ok=True,enabled=service is not None)
    @app.get(base+'/ota/{kind}')
    async def listing(kind:str,cursor:str='',limit:int=20):return await call(available().list,kind,cursor,limit)
    @app.get(base+'/ota/releases/{release_id}')
    async def release(release_id:str):return await call(available().release,release_id)
    @app.get(base+'/ota/campaigns/{campaign_id}')
    async def campaign(campaign_id:str):return await call(available().campaign,campaign_id)
    async def write(request,operation,*args):
        keys=request.headers.getlist('idempotency-key')
        if len(keys)!=1:fail('invalid_input',400)
        value=await body(request,65536)
        return await call(operation,actor(),keys[0],*args,value)
    @app.post(base+'/ota/releases')
    async def create_release(request:Request):return await write(request,available().create_release)
    @app.post(base+'/ota/releases/{release_id}/{action}')
    async def release_action(release_id:str,action:str,request:Request):return await write(request,available().release_action,release_id,action)
    @app.post(base+'/ota/campaigns')
    async def create_campaign(request:Request):return await write(request,available().create_campaign)
    @app.post(base+'/ota/campaigns/{campaign_id}/{action}')
    async def campaign_action(campaign_id:str,action:str,request:Request):return await write(request,available().campaign_action,campaign_id,action)
    def scoped(device_id):
        if fleet:
            try:fleet.root_for(device_id)
            except ValueError:fail('not_found',404)
        elif service and service.config.get('local_device_id')!=device_id:fail('not_found',404)
    @app.get(base+'/devices/{device_id}/ota')
    async def device(device_id:str):
        scoped(device_id);return await call(available().device_view,device_id)
    @app.get(base+'/devices/{device_id}/ota/attempts')
    async def attempts(device_id:str,cursor:int=0,limit:int=20,attempt_cursor:str=''):
        scoped(device_id);return await call(available().attempts,device_id,cursor,limit,attempt_cursor)

    return service
