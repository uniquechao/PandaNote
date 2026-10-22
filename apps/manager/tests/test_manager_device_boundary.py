"""Mac manager never accepts device Wi-Fi credentials, even from its own UI."""
from manager.app import create_app
from manager.provider import UnavailableProvider
from asgi_client import request
import pytest


@pytest.mark.parametrize('method', ['GET','PUT','DELETE'])
def test_authenticated_manager_has_no_wifi_credential_queue(method, tmp_path):
    root = tmp_path/'uncreated-manager-data'
    app = create_app(root,UnavailableProvider())
    _, headers, _ = request(app,'GET','/',authority='127.0.0.1:8767')
    browser = {'origin':'http://127.0.0.1:8767','cookie':headers['set-cookie'].split(';')[0]}
    credential = dict(schema=1,ssid='fixture-device-only-network',password='fixture-device-only-password')
    status, _, response = request(app,method,'/api/device/wifi-queue',credential,
                                  headers=browser,authority='127.0.0.1:8767')
    assert status == 404
    assert credential['password'].encode() not in response
    assert not root.exists()  # No queue, database or private file created.
