"""Independent, bearer-only reader surface; never starts a content publisher.

The controller owns credential provisioning, transport and listener activation.
This module has no calendar bridge, browser session, queue or admin routes.
"""
import base64
import configparser
from contextlib import ExitStack
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .content import epoch
from .store import Store

LIMITS = {'content.ini': 131072, 'background.png': 2097152, 'SHA256SUMS': 512}


def failure(code, status):
    # Never reflect request bodies, credentials, filesystem paths or exceptions.
    return JSONResponse({'schema': 1, 'ok': False, 'error': {'code': code, 'message': code}}, status_code=status)


def _directory(path, stack):
    """Pin every directory component; reject symlinks even during replacement."""
    path = Path(path).absolute()
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    stack.callback(os.close, fd)
    for part in path.parts[1:]:
        fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        stack.callback(os.close, fd)
    return fd


def package(store, version):
    """Hash and serve these same captured bytes, never a later FileResponse read."""
    Store._version(version)
    store._guard()
    captured = {}
    with ExitStack() as stack:
        fd = _directory(store.root/'versions'/version, stack)
        if set(os.listdir(fd)) != set(LIMITS):
            raise ValueError('invalid_package')
        for name, limit in LIMITS.items():
            item = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(item, 'rb') as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= limit:
                    raise ValueError('invalid_package')
                data = handle.read(limit + 1)
                if len(data) != info.st_size or len(data) > limit:
                    raise ValueError('invalid_package')
                captured[name] = data
    expected = ''.join(hashlib.sha256(captured[name]).hexdigest()+'  '+name+'\n'
                       for name in ('content.ini','background.png')).encode('ascii')
    if captured['SHA256SUMS'] != expected:
        raise ValueError('invalid_package')
    ini = configparser.ConfigParser(interpolation=None)
    ini.optionxform = str
    ini.read_string(captured['content.ini'].decode('utf-8'))
    if ini['content']['schema'] != '1' or ini['content']['version'] != base64.b64encode(version.encode()).decode():
        raise ValueError('invalid_package')
    generated = epoch(int(ini['content']['generatedAt']))
    return captured, generated


async def bounded_json(request, limit):
    if request.headers.get('transfer-encoding'):
        return None, failure('length_required', 411)
    length = request.headers.get('content-length', '')
    if not length.isascii() or not length.isdecimal():
        return None, failure('length_required', 411)
    if len(length) > 12 or int(length) > limit:
        return None, failure('too_large', 413)
    if request.headers.get('content-type','').split(';')[0].strip() != 'application/json':
        return None, failure('invalid_input', 400)
    captured = bytearray()
    async for chunk in request.stream():
        if len(captured) + len(chunk) > limit:
            return None, failure('too_large', 413)
        captured.extend(chunk)
    if len(captured) != int(length):
        return None, failure('invalid_input', 400)
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate_field')
            result[key] = value
        return result
    try:
        value = json.loads(captured, object_pairs_hook=unique_pairs)
        if not isinstance(value, dict):
            raise ValueError('invalid_input')
        return value, None
    except (ValueError, UnicodeError, RecursionError):
        return None, failure('invalid_input', 400)


def create_reader_app(root, credential, *, host='127.0.0.1', port=8768, clock=time.time):
    if not isinstance(credential, str) or re.fullmatch(r'[A-Za-z0-9_-]{32,128}', credential) is None:
        raise ValueError('reader credential must be 32-128 URL-safe characters')
    expected = ('Bearer '+credential).encode('ascii')
    store = Store(root)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    authority = f'{host}:{port}'

    @app.middleware('http')
    async def reader_boundary(request, call_next):
        # Authentication precedes all disk access; browser cookies never count.
        values = request.headers.getlist('authorization')
        supplied = values[0].encode('utf-8') if len(values) == 1 else b''
        if not hmac.compare_digest(supplied, expected):
            response = failure('unauthorized', 401)
            response.headers['WWW-Authenticate'] = 'Bearer'
        elif request.headers.getlist('host') != [authority] or 'origin' in request.headers:
            response = failure('forbidden', 403)
        elif request.scope['query_string']:
            response = failure('invalid_input', 400)
        else:
            try:
                response = await call_next(request)
            except (OSError, sqlite3.Error):
                response = failure('storage_failure', 500)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    from .ota_api import install_ota_reader_api
    install_ota_reader_api(app,root,lambda request,service:(service.config.get('local_device_id'),credential))

    @app.get('/reader/v1/manifest')
    def manifest():
        try:
            selected = store.load_current()  # Capture selected version exactly once.
            if selected is None:
                return failure('not_published', 404)
            captured, generated = package(store, selected.version)
            if generated != selected.generated_at:
                raise ValueError('invalid_package')
        except (ValueError, KeyError, configparser.Error, OSError):
            return failure('invalid_package', 409)
        now = epoch(int(clock()))
        value = dict(schema=1, version=selected.version, serverEpoch=now, generatedAt=generated, pollSeconds=300,
                     files=[dict(name=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                                 path=f'/reader/v1/resources/{selected.version}/{name}') for name, data in captured.items()])
        encoded = json.dumps(value, separators=(',', ':')).encode('utf-8')
        if len(encoded) > 65536:
            return failure('invalid_package', 409)
        store.record_reader(now)
        return Response(encoded, media_type='application/json')

    @app.get('/reader/v1/resources/{version}/{name}')
    def resource(version: str, name: str):
        if name not in LIMITS:
            return failure('not_found', 404)
        try:
            store.load_version(version)
        except ValueError:
            return failure('not_found', 404)
        try:
            captured, _ = package(store, version)
        except (ValueError, KeyError, configparser.Error, OSError):
            return failure('invalid_package', 409)
        return Response(captured[name], media_type='image/png' if name == 'background.png' else 'application/octet-stream')

    @app.post('/reader/v1/ack')
    async def ack(request: Request):
        value, error = await bounded_json(request, 1024)
        if error is not None:
            return error
        if set(value) != {'schema','version','displayed'} or type(value['schema']) is not int or value['schema'] != 1 or value['displayed'] is not True:
            return failure('invalid_input', 400)
        try:
            store.load_version(value['version'])
        except ValueError:
            return failure('not_found', 404)
        try:
            package(store, value['version'])
        except (ValueError, KeyError, configparser.Error, OSError):
            return failure('invalid_package', 409)
        store.record_reader(epoch(int(clock())), displayed_version=value['version'])
        return dict(schema=1, ok=True)

    return app
