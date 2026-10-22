"""Controlled scheduler clocks with real ManagerService and immutable Store."""
from datetime import datetime, timezone
import json
import os
import sqlite3
from pathlib import Path
import sys
import threading
import time

import pytest

from manager.content import Settings
from manager.service import ManagerError, ManagerService
from manager.sync import SyncCoordinator
from test_api import ExampleProvider


class Clock:
    def __init__(self, wall=1792511940):  # 2026-10-20 15:59 UTC / 23:59 Singapore
        self.wall = wall
        self.mono = 10.0
    def advance(self, seconds, *, asleep=False):
        self.wall += seconds
        if not asleep:
            self.mono += seconds


class Source(ExampleProvider):
    def __init__(self, clock):
        super().__init__()
        self.clock = clock
        self.missing = False
        self.invalid = False
    def export(self, query):
        value = super().export(query)
        if value['ok']:
            value['readAt'] = int(self.clock.wall)
            if self.missing:
                value.update(calendarIds=[], missingCalendarIds=query['calendarIds'], events=[])
            if self.invalid:
                value['events'] = [dict(id='invalid')]
        return value


def setup(tmp_path, *, source=None, clock=None):
    clock = clock or Clock()
    source = source or Source(clock)
    service = ManagerService(tmp_path/'data', source)
    service.store.save_settings(Settings('Asia/Singapore', datetime.fromtimestamp(clock.wall, timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('Asia/Singapore')).date(), 7, ('work',)))
    source.events = [dict(id='ongoing', calendarId='work', summary='Synthetic ongoing', location='', allDay=False,
                          sourceTimezone='Asia/Singapore', startEpoch=clock.wall-3600, endEpoch=clock.wall+5*86400)]
    coordinator = SyncCoordinator(service, wall_clock=lambda:clock.wall, monotonic=lambda:clock.mono)
    return clock, source, service, coordinator


def exports(source):
    return [call[1] for call in source.calls if isinstance(call, tuple)]


def test_periodic_manual_and_unchanged_content_keep_version(tmp_path):
    clock, source, service, sync = setup(tmp_path, clock=Clock(1792500000))
    sync.poll()
    first = service.store.load_current()
    clock.advance(299)
    sync.poll()
    assert len(exports(source)) == 1
    clock.advance(1)
    sync.poll()
    assert len(exports(source)) == 2
    assert service.store.load_current() == first
    assert service.store.last_successful_read() == clock.wall
    source.events[0]['summary'] = 'Synthetic new title'
    result = sync.sync_once(clock.wall)
    assert result['version'] != first.version
    assert service.preview(first.version)['events'][0]['summary'] == 'Synthetic ongoing'
    assert 'request-access' not in source.calls
    sync.stop()


def test_repeated_changes_debounce_and_bounded_burst(tmp_path):
    clock, source, service, sync = setup(tmp_path)
    sync.poll()
    for _ in range(5):
        sync.notify_change()
        clock.advance(.1)
        sync.poll()
    assert len(exports(source)) == 1
    clock.advance(.3)
    sync.poll()
    assert len(exports(source)) == 2
    # A never-quiet source must still publish within the bounded two-second cap.
    for _ in range(25):
        sync.notify_change()
        clock.advance(.1)
        sync.poll()
    assert len(exports(source)) == 3
    sync.stop()


@pytest.mark.parametrize('failure', ['denied', 'unavailable', 'invalid', 'readback'])
def test_failed_read_retains_previous_then_retries_without_permission_prompt(tmp_path, failure):
    clock, source, service, sync = setup(tmp_path)
    sync.poll()
    first = service.store.load_current()
    original = first.directory.joinpath('content.ini').read_bytes()
    read = service.store.last_successful_read()
    if failure == 'denied':
        source.authorization = 'denied'
    elif failure == 'unavailable':
        source.failure = True
    elif failure == 'invalid':
        source.invalid = True
    else:
        original_export = source.export
        def broken(query):
            raise OSError('synthetic source read failure')
        source.export = broken
    source.events = []
    clock.advance(300)
    sync.poll()
    assert service.store.load_current() == first
    assert first.directory.joinpath('content.ini').read_bytes() == original
    assert service.store.last_successful_read() == read
    assert service.last_error is not None and service.source_state() == 'cached'
    source.authorization = 'authorized'
    source.failure = source.invalid = False
    if failure == 'readback':
        source.export = original_export
    clock.advance(300)
    sync.poll()
    assert service.preview()['events'] == []
    assert service.store.load_current().version != first.version
    assert service.last_error is None
    assert 'request-access' not in source.calls
    sync.stop()


def test_missing_calendar_removes_events_and_reselection_recovers(tmp_path):
    clock, source, service, sync = setup(tmp_path)
    sync.poll()
    source.missing = True
    clock.advance(300)
    sync.poll()
    assert service.preview()['events'] == []
    assert service.preview()['missing_calendar_ids'] == ['work']
    assert service.store.load_settings().selected_calendar_ids == ('work',)
    service.store.save_settings(Settings('Asia/Singapore', service.settings().window_start, 7, ('home',)))
    source.missing = False
    source.events[0]['calendarId'] = 'home'
    sync.notify_change()
    clock.advance(.3)
    sync.poll()
    assert service.preview()['events'][0]['summary'] == 'Synthetic ongoing'
    assert exports(source)[-1]['calendarIds'] == ['home']
    sync.stop()


def test_day_roll_and_resume_with_stopped_monotonic_clock(tmp_path):
    clock, source, service, sync = setup(tmp_path)
    sync.poll()
    assert exports(source)[-1]['windowStartDate'] == '2026-10-20'
    clock.advance(61)
    sync.poll()
    assert exports(source)[-1]['windowStartDate'] == '2026-10-21'
    assert service.preview()['days'][0]['date'] == '2026-10-21'
    before = len(exports(source))
    # Wake within the same local day, even if system monotonic excluded sleep.
    clock.advance(40, asleep=True)
    sync.poll()
    assert len(exports(source)) == before + 1
    clock.advance(86400, asleep=True)
    sync.poll()
    assert exports(source)[-1]['windowStartDate'] == '2026-10-22'
    sync.stop()


def test_manual_timer_overlap_serialized_and_changes_during_read_not_lost(tmp_path):
    clock = Clock()
    started, release = threading.Event(), threading.Event()
    class Slow(Source):
        def export(self, query):
            started.set()
            assert release.wait(3)
            return super().export(query)
    clock, source, service, sync = setup(tmp_path, source=Slow(clock), clock=clock)
    result = []
    first = threading.Thread(target=lambda:result.append(sync.sync_once(clock.wall)))
    first.start()
    assert started.wait(1)
    sync.notify_change()
    source.events[0]['summary'] = 'Changed during read'
    release.set()
    first.join(3)
    assert len(result) == 1
    clock.advance(.3)
    sync.poll()
    assert len(exports(source)) == 2
    assert service.preview()['events'][0]['summary'] == 'Changed during read'
    sync.stop()


def test_shutdown_cancels_inflight_publication_and_rejects_later_manual(tmp_path):
    clock = Clock()
    started, release = threading.Event(), threading.Event()
    class Slow(Source):
        def export(self, query):
            started.set()
            assert release.wait(3)
            return super().export(query)
    clock, source, service, sync = setup(tmp_path, source=Slow(clock), clock=clock)
    failures = []
    def manual():
        try:
            sync.sync_once(clock.wall)
        except ManagerError as error:
            failures.append(error.code)
    work = threading.Thread(target=manual)
    work.start()
    assert started.wait(1)
    stopping = threading.Thread(target=sync.stop)
    stopping.start()
    time.sleep(.02)
    release.set()
    work.join(3)
    stopping.join(3)
    assert failures == ['sync_stopped']
    assert service.store.load_current() is None
    with pytest.raises(ManagerError, match='停止'):
        sync.sync_once(clock.wall)


def fixture_command(tmp_path, mode):
    script = tmp_path/'bridge.py'
    script.write_text('''import json, os, sys, time
from pathlib import Path
root=Path(__file__).parent
(root/'child-pid').write_text(str(os.getpid()))
mode=sys.argv[1]
assert sys.argv[2:] == ['watch','60']
if mode=='changed':
 print('{"schema":1,"changed":true}',flush=True)
elif mode=='malformed':
 print('{"schema":1,"changed":true,"events":["DO NOT RETAIN"]}',flush=True)
elif mode=='oversized':
 print('x'*70000,flush=True)
elif mode=='duplicate':
 print('{"schema":1,"changed":false,"changed":true}',flush=True)
elif mode=='denied':
 sys.exit(1)
time.sleep(60)
''')
    return [sys.executable, str(script), mode]


@pytest.mark.parametrize('mode', ['changed', 'malformed', 'oversized', 'duplicate'])
def test_owned_real_watch_child_signals_validate_and_stop_reaps(tmp_path, mode, request):
    clock, source, service, sync = setup(tmp_path)
    source.command = fixture_command(tmp_path, mode)
    request.addfinalizer(sync.stop)
    sync.poll()
    deadline = time.monotonic()+3
    while not (tmp_path/'child-pid').exists() and time.monotonic()<deadline:
        sync.poll()
        time.sleep(.01)
    pid = int((tmp_path/'child-pid').read_text())
    for _ in range(10):
        sync.poll()
        time.sleep(.01)
    clock.advance(.3)
    sync.poll()
    assert len(exports(source)) == (2 if mode == 'changed' else 1)
    sync.stop()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    count = len(exports(source))
    clock.advance(1000)
    sync.poll()
    assert len(exports(source)) == count


def test_failed_midnight_read_retries_on_period_not_every_owner_tick(tmp_path):
    clock, source, service, sync = setup(tmp_path)
    sync.poll()
    source.authorization = 'denied'
    clock.advance(61)
    sync.poll()
    count = len(exports(source))
    clock.advance(.25)
    sync.poll()
    assert len(exports(source)) == count
    clock.advance(300)
    sync.poll()
    assert len(exports(source)) == count+1
    sync.stop()


def test_watch_failed_exit_has_bounded_recovery_backoff(tmp_path, request):
    clock, source, service, sync = setup(tmp_path)
    source.command = fixture_command(tmp_path, 'denied')
    request.addfinalizer(sync.stop)
    sync.poll()
    sync.poll()
    deadline = time.monotonic()+2
    while not (tmp_path/'child-pid').exists() and time.monotonic()<deadline:
        time.sleep(.01)
    first_pid = int((tmp_path/'child-pid').read_text())
    time.sleep(.05)
    sync.poll()
    assert sync.watch_state == 'retrying'
    clock.advance(.25)
    sync.poll()
    time.sleep(.05)
    assert int((tmp_path/'child-pid').read_text()) == first_pid
    assert len(exports(source)) == 1
    sync.stop()


@pytest.mark.parametrize('failed_read', [1, 2], ids=['service-settings', 'configured-state'])
@pytest.mark.parametrize('recovery', ['notification', 'periodic'])
def test_actual_worker_survives_configuration_read_failure_with_bounded_retry(
        tmp_path, monkeypatch, request, failed_read, recovery):
    # Both configuration reads must share the scheduled storage-error boundary.
    # Let a real owner thread run against a real Store; only its transient read
    # fault and clocks are controlled, so a dead owner cannot pass this test.
    from test_integration import eventually

    clock, source, service, sync = setup(tmp_path, clock=Clock(1792500000))
    request.addfinalizer(sync.stop)
    sync.sync_once()
    first = service.store.load_current()
    original_content = first.directory.joinpath('content.ini').read_bytes()
    last_read = service.store.last_successful_read()
    source.events[0]['summary'] = 'Recovered synthetic title'
    sync.notify_change()
    clock.advance(.3)
    original_load = service.store.load_settings
    read_calls = []
    fault_seen = threading.Event()
    thread_errors = []

    def transient_read():
        read_calls.append(clock.mono)
        if len(read_calls) == failed_read:
            fault_seen.set()
            raise sqlite3.OperationalError('synthetic transient database is locked')
        return original_load()

    monkeypatch.setattr(service.store, 'load_settings', transient_read)
    monkeypatch.setattr(threading, 'excepthook', lambda args: thread_errors.append(args.exc_value))
    sync.start()
    assert fault_seen.wait(2)
    assert eventually(lambda: service.last_error or not sync._thread.is_alive())
    assert sync._thread.is_alive(), 'a transient configuration read must not kill the sole owner'
    assert thread_errors == []
    assert service.last_error['code'] == 'storage_failure'
    assert service.source_state() == 'cached'
    assert service.store.load_current() == first
    assert first.directory.joinpath('content.ini').read_bytes() == original_content
    assert service.store.last_successful_read() == last_read
    # Cover multiple real owner ticks while storage would already be healthy.
    time.sleep(.6)
    assert len(read_calls) == failed_read
    assert len(exports(source)) == 1
    if recovery == 'notification':
        sync.notify_change()
        clock.advance(.3)
    else:
        clock.advance(299)
        time.sleep(.35)
        assert len(read_calls) == failed_read
        assert len(exports(source)) == 1
        clock.advance(1)
    assert eventually(lambda: service.store.load_current().version != first.version)
    assert service.preview()['events'][0]['summary'] == 'Recovered synthetic title'
    assert service.last_error is None
    assert service.fresh_read is True
    assert service.store.last_successful_read() == int(clock.wall)
    assert len(exports(source)) == 2
    assert 'request-access' not in source.calls
    sync.stop()
    assert not sync._thread.is_alive()
    assert thread_errors == []
