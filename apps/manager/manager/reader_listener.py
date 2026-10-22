"""Controller-operated loopback reader listener; importing this never binds.

Run only after controller review. The bearer is loaded from the project's
private file, never a command-line argument, URL, environment variable or log.
Transport beyond loopback requires a separately audited TLS/tunnel boundary.
"""
import argparse
from contextlib import ExitStack, contextmanager
import ipaddress
import os
from pathlib import Path
import re
import socket
import stat
import ssl

import uvicorn

from .reader import _directory, create_reader_app


@contextmanager
def _private_descriptor(root, name):
    with ExitStack() as stack:
        directory = _directory(Path(root)/'private',stack)
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('unsafe reader private directory')
        item = os.open(name,os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,dir_fd=directory)
        stack.callback(os.close,item)
        info = os.fstat(item)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('unsafe reader private file')
        yield item


def load_credential(root):
    with _private_descriptor(root,'reader-token') as item:
        encoded = os.read(item,130)
    try:
        token = encoded.decode('ascii')
    except UnicodeError:
        raise ValueError('invalid reader credential') from None
    if re.fullmatch(r'[A-Za-z0-9_-]{32,128}',token) is None:
        raise ValueError('invalid reader credential')
    return token


def reader_config(root, *, host='127.0.0.1', port=8768, tls=False):
    """Validate and load configuration offline, before creating any socket.

    Host must name an owned numeric IPv4 interface. The controller verifies
    ownership; no interfaces, routes, radios or certificates are provisioned here.
    TLS files are fixed private-root paths. OpenSSL reads pinned descriptors so
    swapping a pathname after validation cannot redirect a key/certificate read.
    """
    address = ipaddress.ip_address(host)
    if not isinstance(address,ipaddress.IPv4Address) or str(address) != host or address.is_unspecified or address.is_multicast or address.is_reserved:
        raise ValueError('explicit owned numeric IPv4 address required')
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('invalid reader port')
    if not address.is_loopback and not tls:
        raise ValueError('TLS required for non-loopback reader listener')
    credential = load_credential(root)
    app = create_reader_app(root,credential,host=host,port=port)
    options = dict(host=host,port=port,log_level='critical',access_log=False,log_config=None)
    if tls:
        with _private_descriptor(root,'reader-server.crt') as cert, _private_descriptor(root,'reader-server.key') as key:
            config = uvicorn.Config(app,**options,ssl_certfile=f'/dev/fd/{cert}',ssl_keyfile=f'/dev/fd/{key}',
                                    ssl_version=ssl.PROTOCOL_TLS_SERVER,ssl_ciphers='ECDHE-ECDSA-AES128-GCM-SHA256')
            config.load()
        config.ssl.minimum_version = ssl.TLSVersion.TLSv1_2
    else:
        config = uvicorn.Config(app,**options)
        config.load()
    return config


class ReaderServer:
    """Separate socket/app with no admin session, coordinator or publisher."""
    def __init__(self, root, *, host='127.0.0.1', port=8768, tls=False):
        config = reader_config(root,host=host,port=port,tls=tls)
        self.socket = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        try:
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            self.socket.bind((host,port))
            self.server_port = self.socket.getsockname()[1]
            if port == 0:
                config = reader_config(root,host=host,port=self.server_port,tls=tls)
            self.app = config.app
            self.server = uvicorn.Server(config)
            self.socket.listen(128)
        except BaseException:
            self.socket.close()
            raise
    def serve_forever(self):
        self.server.run(sockets=[self.socket])
    def shutdown(self):
        self.server.should_exit = True
    def server_close(self):
        self.socket.close()


def main():
    parser = argparse.ArgumentParser(description='PandaNote 966U2 loopback reader listener (controller activation only)')
    parser.add_argument('--port',type=int,default=8768)
    parser.add_argument('--host',default='127.0.0.1',help='explicit numeric owned IPv4 interface; non-loopback requires --tls')
    parser.add_argument('--tls',action='store_true',help='use private/reader-server.crt and private/reader-server.key')
    parser.add_argument('--data-root',type=Path,required=True)
    args = parser.parse_args()
    try:
        server = ReaderServer(args.data_root,host=args.host,port=args.port,tls=args.tls)
    except (ValueError,OSError):
        parser.exit(2,'Reader listener could not validate transport/private files or bind its owned socket.\n')
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
