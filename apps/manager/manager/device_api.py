"""Scoped admin routes reuse the same validated publisher and provider."""
import json,re
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import FileResponse,Response,JSONResponse
from starlette.concurrency import run_in_threadpool
from .images import Crop,MAX_UPLOAD
from .service import ManagerError

class LocalOtaDeviceScope:
    """已明确绑定的本地设备继续复用原内容根及同步生命周期。"""
    def __init__(self,ota,service,coordinator):
        self.ota=ota;self.service=service;self.coordinator=coordinator
    def bundle(self,device_id):
        from .ota import OtaError
        from types import SimpleNamespace
        if device_id!=self.ota.config.get('local_device_id'):raise ValueError('unknown device')
        try:self.ota.device(device_id)
        except OtaError:raise ValueError('unknown device') from None
        return SimpleNamespace(service=self.service,coordinator=self.coordinator)


def install_device_api(app,prefix,fleet,json_body,body,*,include_inventory=True):
    router=APIRouter(prefix=prefix+'/api/devices')
    def device(device_id:str):
        try:return fleet.bundle(device_id)
        except ValueError:raise HTTPException(404,'设备不存在') from None
    if include_inventory:
        @router.get('')
        async def devices():return dict(schema=1,ok=True,devices=await run_in_threadpool(fleet.devices))
    @router.get('/{device_id}/status')
    def status(bundle=Depends(device)):
        value=bundle.service.status()
        if value.get('error'):value['error']={'code':'calendar_failure','message':'此设备日历来源暂不可用，已有内容已保留。'}
        return value
    @router.get('/{device_id}/calendars')
    def calendars(bundle=Depends(device)):return bundle.service.calendars()
    @router.put('/{device_id}/calendar-selection')
    async def selection(request:Request,bundle=Depends(device)):
        value=await json_body(request)
        try:result=await run_in_threadpool(bundle.service.selection,value)
        except (TypeError,KeyError):raise ValueError('日历配置格式无效。') from None
        bundle.coordinator.notify_change();return result
    async def empty(request):
        if await json_body(request):raise ValueError('请求格式无效。')
    @router.post('/{device_id}/calendar/connect')
    async def connect(request:Request,bundle=Depends(device)):
        await empty(request);return await run_in_threadpool(bundle.service.connect)
    @router.post('/{device_id}/calendar/sync')
    async def sync(request:Request,bundle=Depends(device)):
        await empty(request);return await run_in_threadpool(bundle.coordinator.sync_once)
    @router.put('/{device_id}/background')
    async def background(request:Request,bundle=Depends(device)):
        encoded=request.headers.get('x-crop','{}')
        if len(encoded)>1024:raise ValueError('裁切参数过长。')
        crop=json.loads(encoded)
        if not isinstance(crop,dict) or set(crop)-{'x','y','width','height'}:raise ValueError('裁切参数无效。')
        source=await body(request,MAX_UPLOAD)
        return await run_in_threadpool(bundle.service.background,source,Crop(**crop,mime_type=request.headers.get('content-type','')))
    @router.get('/{device_id}/preview')
    def preview(device_id:str,version:str|None=None,bundle=Depends(device)):
        value=bundle.service.preview(version)
        base=prefix+'/api/devices/'+device_id
        value['resources']={name:base+url.removeprefix('/api') for name,url in value['resources'].items()}
        return value
    @router.get('/{device_id}/draft-background')
    def draft_background(bundle=Depends(device)):
        with bundle.service.lock:return Response(bundle.service._background(),media_type='image/png')
    @router.get('/{device_id}/resources/{version}/{name}')
    def resource(version:str,name:str,bundle=Depends(device)):
        if name not in {'content.ini','background.png','SHA256SUMS'}:raise HTTPException(404,'资源不存在')
        try:directory=bundle.service.store.load_version(version)
        except ValueError:raise HTTPException(404,'版本不存在') from None
        return FileResponse(directory/name,media_type='image/png' if name.endswith('.png') else 'text/plain',filename=name)
    def operation(bundle,action,*args):
        try:
            with bundle.service.lock:result=getattr(bundle.service.provider,action)(*args)
            if not isinstance(result,dict) or result.get('ok') is not True:raise ValueError('source failed')
            fields=('id','label','url','username','enabled','has_password','configured')
            clean=lambda item:{key:item[key] for key in fields if key in item}
            if action=='list_sources':return dict(schema=1,ok=True,sources=[clean(item) for item in result['sources']])
            if action=='save_source':return dict(schema=1,ok=True,source=clean(result['source']))
            return dict(schema=1,ok=True)
        except Exception:raise ManagerError('caldav_configuration','此设备日历来源配置失败。') from None
    async def source_data(request):
        value=await json_body(request)
        if set(value)-{'label','url','username','password','enabled'} or not {'label','url','username'}<=set(value):raise ValueError('日历来源格式无效。')
        return value
    @router.get('/{device_id}/caldav/sources')
    async def sources(bundle=Depends(device)):return await run_in_threadpool(operation,bundle,'list_sources')
    @router.post('/{device_id}/caldav/sources/test')
    async def test_source(request:Request,bundle=Depends(device)):
        value=await json_body(request)
        if set(value)-{'id','label','url','username','password','enabled'} or not {'label','url','username'}<=set(value):raise ValueError('日历来源格式无效。')
        result=await run_in_threadpool(bundle.service.provider.test_source,value)
        if result.get('ok') is not True:return JSONResponse(dict(schema=1,ok=False,error=dict(code='connection_failed',message='连接失败，请检查地址、账号和应用专用密码。')),status_code=409)
        return dict(schema=1,ok=True,connected=True,calendar_count=result['calendar_count'])
    @router.post('/{device_id}/caldav/sources')
    async def add_source(request:Request,bundle=Depends(device)):
        result=await run_in_threadpool(operation,bundle,'save_source',await source_data(request));bundle.coordinator.notify_change();return result
    @router.put('/{device_id}/caldav/sources/{source_id}')
    async def update_source(source_id:str,request:Request,bundle=Depends(device)):
        if re.fullmatch('[A-Za-z0-9_-]{1,64}',source_id) is None:raise ValueError('来源编号无效。')
        value=await source_data(request);value['id']=source_id
        result=await run_in_threadpool(operation,bundle,'save_source',value);bundle.coordinator.notify_change();return result
    @router.delete('/{device_id}/caldav/sources/{source_id}')
    async def delete_source(source_id:str,request:Request,bundle=Depends(device)):
        if re.fullmatch('[A-Za-z0-9_-]{1,64}',source_id) is None:raise ValueError('来源编号无效。')
        await empty(request)
        result=await run_in_threadpool(operation,bundle,'delete_source',source_id);bundle.coordinator.notify_change();return result
    app.include_router(router)
