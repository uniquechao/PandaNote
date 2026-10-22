"""Reader contract/security tests against the ASGI application and real Store."""
from datetime import date
import hashlib
import json
import os

import pytest

from manager import app as app_module
from manager.content import Settings
from manager.service import blank_background
from manager.store import Store
from asgi_client import request

TOKEN = 'fixture-reader-token-with-at-least-32-chars'
AUTH = {'authorization': 'Bearer ' + TOKEN}


def reader(root, clock=lambda: 1792516000):
    factory = getattr(app_module, 'create_reader_app', None)
    assert callable(factory), 'separate authenticated reader application is missing'
    return factory(root, TOKEN, clock=clock)


def publish(store, shade=None):
    from PIL import Image
    from io import BytesIO
    out = BytesIO()
    Image.new('L', (480, 800), shade or 242).save(out, 'PNG')
    return store.publish_snapshot([], Settings('Asia/Singapore', date(2026, 10, 21)), out.getvalue(), generated_at=1792515600)


def test_authentication_precedes_store_access_and_admin_routes_are_absent(tmp_path):
    root = tmp_path/'untouched'
    app = reader(root)
    for headers in ({}, {'authorization': 'Bearer wrong'}, {'cookie': 'pandanote_session=fake'}):
        assert request(app, 'GET', '/reader/v1/manifest', headers=headers)[0] == 401
    assert not root.exists()
    for path in ('/', '/api/status', '/api/calendar/sync', '/api/device/wifi-queue', '/openapi.json'):
        assert request(app, 'GET', path, headers=AUTH)[0] == 404
    assert not root.exists()
    assert request(app, 'GET', '/reader/v1/manifest?token='+TOKEN, headers=AUTH)[0] == 400
    assert request(app, 'GET', '/reader/v1/manifest', headers={**AUTH, 'origin': 'http://foreign.invalid'})[0] == 403
    assert request(app, 'GET', '/reader/v1/manifest', headers={**AUTH, 'host': 'foreign.invalid'})[0] == 403


def test_exact_manifest_fresh_time_and_download_never_marks_display(tmp_path):
    store = Store(tmp_path/'data')
    current = publish(store)
    times = iter([1792516000, 1792516300])
    app = reader(store.root, lambda: next(times))
    code, headers, data = request(app, 'GET', '/reader/v1/manifest', headers=AUTH)
    manifest = json.loads(data)
    assert code == 200 and len(data) <= 65536 and headers['cache-control'] == 'no-store'
    assert set(manifest) == {'schema','version','serverEpoch','generatedAt','pollSeconds','files'}
    assert manifest['schema'] == 1 and manifest['version'] == current.version
    assert manifest['serverEpoch'] == 1792516000 and manifest['generatedAt'] == 1792515600
    assert manifest['pollSeconds'] == 300
    assert [item['name'] for item in manifest['files']] == ['content.ini','background.png','SHA256SUMS']
    for item in manifest['files']:
        assert set(item) == {'name','bytes','sha256','path'}
        assert item['path'] == f'/reader/v1/resources/{current.version}/{item["name"]}'
        status, _, exact = request(app, 'GET', item['path'], headers=AUTH)
        assert status == 200 and exact == (current.directory/item['name']).read_bytes()
        assert len(exact) == item['bytes'] and hashlib.sha256(exact).hexdigest() == item['sha256']
    contact = store.load_value('reader_status')
    assert contact['last_contact_at'] == 1792516000
    assert contact['last_displayed_at'] is None and contact['last_displayed_version'] is None
    newer = json.loads(request(app, 'GET', '/reader/v1/manifest', headers=AUTH)[2])
    assert newer['version'] == current.version and newer['serverEpoch'] == 1792516300
    assert store.load_value('reader_status')['last_displayed_version'] is None


def test_ack_is_strict_bounded_and_persisted_separately(tmp_path):
    store = Store(tmp_path/'data')
    first = publish(store)
    app = reader(store.root)
    invalid = [dict(schema=1, version=first.version, displayed=False), dict(schema=True, version=first.version, displayed=True),
               dict(schema=1, version=first.version, displayed=1), dict(schema=1, version='f'*32, displayed=True),
               dict(schema=1, version=first.version, displayed=True, password='fixture-secret')]
    for payload in invalid:
        assert request(app, 'POST', '/reader/v1/ack', payload, headers=AUTH)[0] in (400,404)
    assert store.load_value('reader_status') is None
    assert request(app, 'POST', '/reader/v1/ack', b'x'*1025, headers={**AUTH,'content-type':'application/json'})[0] == 413
    assert request(app, 'POST', '/reader/v1/ack', b'{}', headers=AUTH)[0] == 400
    assert request(app, 'POST', '/reader/v1/ack', {}, headers={**AUTH,'transfer-encoding':'chunked'})[0] == 411
    assert request(app, 'POST', '/reader/v1/ack', dict(schema=1,version=first.version,displayed=True), headers=AUTH)[0] == 200
    publish(store, 1)
    status = Store(store.root).load_value('reader_status')
    assert status == dict(last_contact_at=1792516000,last_displayed_at=1792516000,last_displayed_version=first.version)
    # A later manifest updates only contact even when a newer publication exists.
    request(reader(store.root, lambda: 1792517000), 'GET','/reader/v1/manifest',headers=AUTH)
    status = store.load_value('reader_status')
    assert status['last_contact_at'] == 1792517000 and status['last_displayed_version'] == first.version


def test_immutable_old_resources_and_bad_packages_fail_closed(tmp_path):
    store = Store(tmp_path/'data')
    first = publish(store)
    app = reader(store.root)
    manifest = json.loads(request(app,'GET','/reader/v1/manifest',headers=AUTH)[2])
    publish(store, 2)
    for item in manifest['files']:
        assert hashlib.sha256(request(app,'GET',item['path'],headers=AUTH)[2]).hexdigest() == item['sha256']
    current = store.load_current()
    current.directory.chmod(0o755)
    target = current.directory/'content.ini'
    target.chmod(0o644)
    target.write_bytes(b'inconsistent fixture')
    assert request(app,'GET','/reader/v1/manifest',headers=AUTH)[0] == 409
    assert request(app,'GET',f'/reader/v1/resources/{current.version}/content.ini',headers=AUTH)[0] == 409
    target.unlink(); target.symlink_to(first.directory/'content.ini')
    assert request(app,'GET','/reader/v1/manifest',headers=AUTH)[0] == 409
    target.unlink(); target.write_bytes(b'x'*131073)
    assert request(app,'GET','/reader/v1/manifest',headers=AUTH)[0] == 409
    assert request(app,'GET',f'/reader/v1/resources/{first.version}/state.sqlite3',headers=AUTH)[0] == 404
    assert request(reader(tmp_path/'empty'),'GET','/reader/v1/manifest',headers=AUTH)[0] == 404


def test_manifest_captures_version_once_during_publication(tmp_path, monkeypatch):
    store = Store(tmp_path/'data')
    first = publish(store)
    original = Store.load_current
    def concurrently_publish(instance):
        captured = original(instance)
        publish(store, 3)
        return captured
    monkeypatch.setattr(Store,'load_current',concurrently_publish)
    payload = json.loads(request(reader(store.root),'GET','/reader/v1/manifest',headers=AUTH)[2])
    assert payload['version'] == first.version
    assert all('/'+first.version+'/' in item['path'] for item in payload['files'])


def test_private_credential_file_is_required_before_listener_creation(tmp_path):
    from importlib.util import find_spec
    assert find_spec('manager.reader_listener') is not None, 'reader listener/credential boundary is missing'
    from manager.reader_listener import load_credential
    private = tmp_path/'private'
    private.mkdir(mode=0o700)
    credential = private/'reader-token'
    credential.write_text(TOKEN)
    credential.chmod(0o600)
    assert load_credential(tmp_path) == TOKEN
    credential.chmod(0o644)
    with pytest.raises(ValueError):
        load_credential(tmp_path)
    credential.unlink()
    outside = tmp_path/'outside-token'
    outside.write_text(TOKEN)
    outside.chmod(0o600)
    credential.symlink_to(outside)
    with pytest.raises((ValueError,OSError)):
        load_credential(tmp_path)
    credential.unlink()
    credential.write_text('short')
    credential.chmod(0o600)
    with pytest.raises(ValueError):
        load_credential(tmp_path)


def test_manager_status_reads_persisted_contact_and_display_without_claiming_connected(tmp_path):
    from manager.app import create_app
    from manager.provider import UnavailableProvider
    store = Store(tmp_path/'data')
    current = publish(store)
    app = reader(store.root)
    request(app,'GET','/reader/v1/manifest',headers=AUTH)
    request(app,'POST','/reader/v1/ack',dict(schema=1,version=current.version,displayed=True),headers=AUTH)
    admin = create_app(store.root,UnavailableProvider())
    _, headers, _ = request(admin,'GET','/',authority='127.0.0.1:8767')
    headers = {'origin':'http://127.0.0.1:8767','cookie':headers['set-cookie'].split(';')[0]}
    code, _, body = request(admin,'GET','/api/status',headers=headers,authority='127.0.0.1:8767')
    status = json.loads(body)['device']
    assert code == 200 and status['last_contact_at'] == 1792516000
    assert status['last_displayed_at'] == 1792516000 and status['last_displayed_version'] == current.version
    assert status['state'] == 'contact_recorded'


def test_tls_policy_rejects_lan_http_wildcards_and_missing_private_certificate(tmp_path):
    import manager.reader_listener as listener
    assert callable(getattr(listener,'reader_config',None)), 'offline TLS configuration is missing'
    for host in ('0.0.0.0','224.0.0.1','255.255.255.255','example.invalid','::1'):
        with pytest.raises(ValueError):
            listener.reader_config(tmp_path,host=host,tls=True)
    with pytest.raises(ValueError,match='TLS'):
        listener.reader_config(tmp_path,host='192.168.50.2')
    private = tmp_path/'private'
    private.mkdir(mode=0o700)
    token = private/'reader-token'
    token.write_text(TOKEN);token.chmod(0o600)
    with pytest.raises((ValueError,OSError)):
        listener.reader_config(tmp_path,host='192.168.50.2',tls=True)


def test_tls12_ecdsa_ip_verification_handshake_without_network(tmp_path):
    import shutil
    import ssl
    import subprocess
    import manager.reader_listener as listener
    assert callable(getattr(listener,'reader_config',None)), 'offline TLS configuration is missing'
    openssl = shutil.which('openssl')
    if not openssl:
        pytest.skip('OpenSSL CLI unavailable for generating an ephemeral test certificate')
    private = tmp_path/'private'
    private.mkdir(mode=0o700)
    token = private/'reader-token'
    token.write_text(TOKEN);token.chmod(0o600)
    key, cert = private/'reader-server.key', private/'reader-server.crt'
    subprocess.run([openssl,'req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes',
                    '-keyout',str(key),'-out',str(cert),'-subj','/CN=fixture-reader','-days','1',
                    '-addext','subjectAltName=IP:192.168.50.2'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    key.chmod(0o600);cert.chmod(0o600)
    config = listener.reader_config(tmp_path,host='192.168.50.2',tls=True)
    assert config.host == '192.168.50.2' and config.port == 8768 and config.access_log is False
    assert config.loaded and config.ssl.minimum_version >= ssl.TLSVersion.TLSv1_2
    client_context = ssl.create_default_context(cafile=str(cert))
    client_context.maximum_version = ssl.TLSVersion.TLSv1_2
    client_context.set_ciphers('ECDHE-ECDSA-AES128-GCM-SHA256')
    def handshake(address):
        incoming, outgoing, received, sending = (ssl.MemoryBIO() for _ in range(4))
        client = client_context.wrap_bio(received,sending,server_side=False,server_hostname=address)
        server = config.ssl.wrap_bio(incoming,outgoing,server_side=True)
        done = set()
        for _ in range(100):
            for name, peer in [('client',client),('server',server)]:
                try:
                    peer.do_handshake();done.add(name)
                except ssl.SSLWantReadError:
                    pass
            if sending.pending:
                incoming.write(sending.read())
            if outgoing.pending:
                received.write(outgoing.read())
            if len(done) == 2:
                return client
        raise AssertionError('offline TLS handshake did not complete')
    client = handshake('192.168.50.2')
    assert client.version() == 'TLSv1.2' and client.cipher()[0] == 'ECDHE-ECDSA-AES128-GCM-SHA256'
    exact_der = ssl.PEM_cert_to_DER_cert(cert.read_text())
    assert hashlib.sha256(client.getpeercert(binary_form=True)).digest() == hashlib.sha256(exact_der).digest()
    with pytest.raises(ssl.SSLCertVerificationError):
        handshake('192.168.50.3')
    key.chmod(0o644)
    with pytest.raises(ValueError):
        listener.reader_config(tmp_path,host='192.168.50.2',tls=True)
