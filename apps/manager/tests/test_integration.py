"""Real HTTP/service/publication acceptance, using synthetic source data only."""
import time

from manager.content import Settings
from manager.store import Store
from test_api import ExampleProvider, event, running, selection


def eventually(predicate, seconds=2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    return predicate()


def test_saved_selection_syncs_automatically_on_manager_start(tmp_path):
    root = tmp_path/'data'
    Store(root).save_settings(Settings.from_dict(selection()))
    provider = ExampleProvider()
    provider.events = [event()]
    with running(root, provider, automatic=True) as (client, service):
        current = eventually(service.store.load_current)
        assert current is not None, 'saved selected calendars must be read at startup without permission prompting'
        preview = client.json('GET', '/api/preview')[1]
        assert preview['events'][0]['summary'] == '示例项目复盘'
        assert preview['version'] == current.version
        assert 'request-access' not in provider.calls


def test_saving_selection_schedules_authoritative_update(tmp_path):
    provider = ExampleProvider()
    provider.events = [event()]
    with running(tmp_path/'data', provider, automatic=True) as (client, service):
        assert client.json('PUT', '/api/calendar-selection', selection())[0] == 200
        current = eventually(service.store.load_current)
        assert current is not None, 'configuration changes must schedule synchronization'
        provider.events = []
        assert client.json('POST', '/api/calendar/sync', {})[0] == 200
        assert client.json('GET', '/api/preview')[1]['events'] == []
        assert client.json('GET', '/api/preview?version='+current.version)[1]['events'][0]['summary'] == '示例项目复盘'


def test_unconfigured_startup_is_inert_but_saved_empty_selection_is_authoritative(tmp_path):
    provider = ExampleProvider()
    with running(tmp_path/'unconfigured', provider, automatic=True) as (client, service):
        time.sleep(.35)
        assert service.store.load_current() is None
        assert not any(isinstance(call, tuple) for call in provider.calls)
        assert not (service.store.root/'state.sqlite3').exists()
    root = tmp_path/'configured-empty'
    Store(root).save_settings(Settings.from_dict(selection(())))
    with running(root, provider, automatic=True) as (client, service):
        assert eventually(service.store.load_current) is not None
        assert client.json('GET', '/api/preview')[1]['events'] == []
        assert 'request-access' not in provider.calls


def test_actual_worker_and_manual_calls_serialize_then_publish_latest_selection(tmp_path):
    import threading
    from manager.app import create_server
    from test_api import Client
    started, release = threading.Event(), threading.Event()
    class SlowSource(ExampleProvider):
        active = maximum = 0
        def export(self, query):
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            try:
                if not started.is_set():
                    started.set()
                    assert release.wait(3)
                value = super().export(query)
                value['events'] = []
                return value
            finally:
                self.active -= 1
    root = tmp_path/'data'
    Store(root).save_settings(Settings.from_dict(selection()))
    source = SlowSource()
    server = create_server(root, source, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    client = Client(server)
    jobs, results = [], []
    try:
        assert started.wait(2)
        # Desired config waits for the in-flight service read, then the change
        # notification must cause a fresh export using that saved latest value.
        jobs.append(threading.Thread(target=lambda:results.append(client.json('PUT', '/api/calendar-selection', selection(('home',))))))
        for _ in range(2):
            jobs.append(threading.Thread(target=lambda:results.append(client.json('POST', '/api/calendar/sync', {}))))
        for job in jobs:
            job.start()
        server.app.state.coordinator.notify_change()
        server.app.state.coordinator.notify_change()
        release.set()
        for job in jobs:
            job.join(4)
        assert len(results) == 3 and all(row[0] == 200 for row in results)
        def latest():
            value = server.service.store.load_current()
            return value and server.service.store.load_source(value.version)['settings']['selected_calendar_ids'] == ['home']
        assert eventually(latest)
        assert server.service.store.load_settings().selected_calendar_ids == ('home',)
        assert source.maximum == 1
        assert 'request-access' not in source.calls
    finally:
        release.set()
        for job in jobs:
            job.join(4)
        server.shutdown()
        worker.join(5)
        server.server_close()
    assert not worker.is_alive()
    assert not server.app.state.coordinator._thread.is_alive()


def test_interrupted_new_package_preserves_current_and_old_resource_download(tmp_path, monkeypatch):
    import manager.store as store_module
    provider = ExampleProvider()
    provider.events = [event()]
    with running(tmp_path/'data', provider) as (client, service):
        client.json('PUT', '/api/calendar-selection', selection())
        client.json('POST', '/api/calendar/sync', {})
        first = service.store.load_current()
        url = '/api/resources/'+first.version+'/content.ini'
        before = client.request('GET', url)[2]
        original = store_module._fsync_directory
        def interrupt(path):
            if path.name.startswith('.staging-'):
                raise OSError('synthetic interrupted new-package readback')
            original(path)
        monkeypatch.setattr(store_module, '_fsync_directory', interrupt)
        provider.events = []
        assert client.json('POST', '/api/calendar/sync', {})[0] == 500
        assert service.store.load_current() == first
        assert client.request('GET', url)[2] == before
        monkeypatch.setattr(store_module, '_fsync_directory', original)
        assert client.json('POST', '/api/calendar/sync', {})[0] == 200
        assert service.preview()['events'] == []
        assert service.store.load_current().version != first.version
        assert client.request('GET', url)[2] == before
