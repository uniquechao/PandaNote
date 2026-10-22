"""In-process HTTP boundary tests: no socket, server or provider startup."""
import asyncio
import json
from urllib.parse import urlsplit, unquote


async def exchange(app, method, path, data=None, headers=None, authority='127.0.0.1:8768'):
    if isinstance(data, dict):
        data = json.dumps(data).encode()
        headers = {'content-type': 'application/json', **(headers or {})}
    data = data or b''
    supplied = {'host': authority, 'content-length': str(len(data)), **(headers or {})}
    parts = urlsplit(path)
    scope = dict(type='http', asgi={'version': '3.0'}, http_version='1.1', method=method,
                 scheme='http', path=unquote(parts.path), raw_path=parts.path.encode(),
                 query_string=parts.query.encode(), root_path='', server=('127.0.0.1', 8768),
                 client=('127.0.0.1', 1), headers=[(k.lower().encode(), v.encode()) for k, v in supplied.items()])
    first = True
    complete = asyncio.Event()
    messages = []
    async def receive():
        nonlocal first
        if first:
            first = False
            return {'type': 'http.request', 'body': data, 'more_body': False}
        await complete.wait()
        return {'type': 'http.disconnect'}
    async def send(message):
        messages.append(message)
        if message['type'] == 'http.response.body' and not message.get('more_body', False):
            complete.set()
    await app(scope, receive, send)
    start = next(message for message in messages if message['type'] == 'http.response.start')
    body = b''.join(message.get('body', b'') for message in messages if message['type'] == 'http.response.body')
    return start['status'], dict((k.decode(), v.decode()) for k, v in start['headers']), body


def request(app, method, path, data=None, **kwargs):
    return asyncio.run(exchange(app, method, path, data, **kwargs))
