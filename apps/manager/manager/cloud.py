"""Cloud role adapter. Explicit private profile; sockets bind loopback only."""
import argparse
import configparser
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse,Response
from .cloud_auth import CloudProfile
from .reader import LIMITS,package,bounded_json
from .store import Store
from .fleet import DeviceScopes
from .content import epoch

def error(code,status):return JSONResponse(dict(schema=1,ok=False,error=dict(code=code,message=code)),status_code=status)
def create_cloud_reader_app(root,profile,*,clock=time.time):
    if isinstance(profile,dict):profile=CloudProfile(**profile)
    if not isinstance(profile,CloudProfile):raise ValueError('explicit cloud profile required')
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None);app.state.profile=profile;scopes=DeviceScopes(root,profile);prefix=profile.prefix
    @app.middleware('http')
    async def boundary(request,call_next):
        # No admin session, publisher, network source or credential provisioning.
        if not request.url.path.startswith(prefix+'/'):response=error('not_found',404)
        elif not profile.trusted_request(request):response=error('forbidden',403)
        elif profile.device(request) is None:response=error('unauthorized',401)
        elif 'origin' in request.headers:response=error('forbidden',403)
        elif request.scope['query_string']:response=error('invalid_input',400)
        else:
            try:response=await call_next(request)
            except (OSError,sqlite3.Error,ValueError):response=error('storage_failure',500)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'})
        if response.status_code==401:response.headers['WWW-Authenticate']='Bearer'
        return response
    def device_store(request):return Store(scopes.root_for(profile.device(request)))
    @app.get(prefix+'/reader/v1/manifest')
    def manifest(request:Request):
        store=device_store(request)
        try:
            selected=store.load_current()
            if selected is None:return error('not_published',404)
            captured,generated=package(store,selected.version)
            if generated!=selected.generated_at:raise ValueError('invalid package')
        except (ValueError,KeyError,configparser.Error,OSError):return error('invalid_package',409)
        now=epoch(int(clock()));value=dict(schema=1,version=selected.version,serverEpoch=now,generatedAt=generated,pollSeconds=300,files=[dict(name=n,bytes=len(b),sha256=hashlib.sha256(b).hexdigest(),path=f'/reader/v1/resources/{selected.version}/{n}') for n,b in captured.items()])
        raw=json.dumps(value,separators=(',',':')).encode()
        if len(raw)>65536:return error('invalid_package',409)
        store.record_reader(now);return Response(raw,media_type='application/json')
    @app.get(prefix+'/reader/v1/resources/{version}/{name}')
    def resource(version:str,name:str,request:Request):
        store=device_store(request)
        if name not in LIMITS:return error('not_found',404)
        try:store.load_version(version)
        except ValueError:return error('not_found',404)
        try:captured,_=package(store,version)
        except (ValueError,KeyError,configparser.Error,OSError):return error('invalid_package',409)
        return Response(captured[name],media_type='image/png' if name=='background.png' else 'application/octet-stream')
    @app.post(prefix+'/reader/v1/ack')
    async def ack(request:Request):
        store=device_store(request)
        value,failed=await bounded_json(request,1024)
        if failed is not None:return failed
        if set(value)!={'schema','version','displayed'} or type(value['schema']) is not int or value['schema']!=1 or value['displayed'] is not True:return error('invalid_input',400)
        try:store.load_version(value['version'])
        except ValueError:return error('not_found',404)
        try:package(store,value['version'])
        except (ValueError,KeyError,configparser.Error,OSError):return error('invalid_package',409)
        store.record_reader(epoch(int(clock())),displayed_version=value['version']);return dict(schema=1,ok=True)
    return app

def main():
    parser=argparse.ArgumentParser(description='PandaNote private-profile cloud role (loopback only)')
    parser.add_argument('--profile',type=Path,required=True);parser.add_argument('--data-root',type=Path,required=True);parser.add_argument('--role',choices=['admin','reader'],required=True);parser.add_argument('--port',type=int,required=True)
    args=parser.parse_args()
    try:
        profile=CloudProfile.from_file(args.profile)
        if not 1024<=args.port<=65535:raise ValueError('invalid port')
        if args.role=='reader':app=create_cloud_reader_app(args.data_root,profile)
        else:
            from .app import create_app
            from .caldav_provider import CalDAVProvider
            app=create_app(args.data_root,CalDAVProvider(args.data_root),port=args.port,cloud_profile=profile)
    except (ValueError,OSError,TypeError):parser.exit(2,'Cloud role could not validate its private configuration.\n')
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=args.port,proxy_headers=False,access_log=False,log_level='warning')
if __name__=='__main__':main()
