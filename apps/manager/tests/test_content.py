"""Real SQLite/filesystem/INI boundary tests with independent expected values."""
import base64
import configparser
from dataclasses import replace
from datetime import date
import hashlib
from io import BytesIO
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from PIL import Image
import pytest
from manager.content import Settings, normalize_events
from manager.store import Store


NOW = 1792458000
SETTINGS = Settings('Asia/Shanghai', date(2026, 10, 20), selected_calendar_ids=('work', 'home'))


def background(shade=230):
    out = BytesIO()
    Image.new('L', (480, 800), shade).save(out, 'PNG')
    return out.getvalue()


def timed(id='meeting', start=1792458000, end=1792461600, calendar='work', **extra):
    return dict(id=id, calendarId=calendar, summary='讨论,规划\\日程\n第二行', location='', allDay=False,
                startEpoch=start, endEpoch=end, sourceTimezone='Asia/Shanghai', **extra)


def ini(content):
    parsed = configparser.ConfigParser(interpolation=None)
    parsed.optionxform = str
    parsed.read(content.directory / 'content.ini', encoding='utf-8')
    return parsed


def decoded(value):
    return base64.b64decode(value).decode('utf-8')


def test_import_and_constructor_have_no_filesystem_side_effects(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]), PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run([sys.executable, '-c', 'import manager; from manager.store import Store; Store("absent")'], cwd=tmp_path, env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []
    store = Store(tmp_path / 'store')
    assert store.load_current() is None
    assert not store.root.exists()


def test_publish_three_members_manifest_and_persistent_settings(tmp_path):
    store = Store(tmp_path / 'store')
    published = store.publish_snapshot([timed()], SETTINGS, background(), generated_at=NOW)
    assert set(p.name for p in published.directory.iterdir()) == {'content.ini', 'background.png', 'SHA256SUMS'}
    assert published.version == published.directory.name
    assert len(published.version) == 32 and int(published.version, 16) >= 0
    parsed = ini(published)
    assert decoded(parsed['event000']['summary']) == '讨论,规划\\日程\n第二行'
    assert parsed['event000']['startDate'] == '2026-10-20'
    assert parsed['event000']['startUtcOffsetSeconds'] == '28800'
    assert parsed['days']['count'] == '7'
    assert parsed['day000']['startEpoch'] == '1792425600'
    expected = ''.join(hashlib.sha256((published.directory / name).read_bytes()).hexdigest() + '  ' + name + '\n' for name in ['content.ini', 'background.png'])
    assert (published.directory / 'SHA256SUMS').read_text() == expected
    assert Store(store.root).load_current() == published
    assert store.load_settings() == SETTINGS


def test_unchanged_content_keeps_version_and_generated_at_but_read_time_is_fresh(tmp_path):
    store = Store(tmp_path / 'store')
    first = store.publish_snapshot([timed()], SETTINGS, background(), generated_at=NOW)
    store.record_successful_read(NOW)
    second = store.publish_snapshot([timed()], SETTINGS, background(), generated_at=NOW + 300)
    store.record_successful_read(NOW + 300)
    assert second == first
    assert store.last_successful_read() == NOW + 300
    assert len(list((store.root / 'versions').iterdir())) == 1
    assert ini(first)['content']['generatedAt'] == str(NOW)


def test_preview_old_background_survives_updates_and_reopen(tmp_path):
    store = Store(tmp_path / 'store')
    old = store.publish_snapshot([timed()], SETTINGS, background(20), generated_at=NOW)
    old_bytes = (old.directory / 'background.png').read_bytes()
    with (old.directory / 'background.png').open('rb') as preview:
        current = store.publish_snapshot([], SETTINGS, background(240), generated_at=NOW + 1)
        assert preview.read() == old_bytes
        assert old.directory.is_dir()
        assert Store(store.root).load_current() == current
        assert ini(current)['events']['count'] == '0'
    assert (old.directory / 'background.png').read_bytes() == old_bytes


@pytest.mark.parametrize('boundary', ['write', 'rename', 'select'])
def test_publication_failure_or_interrupt_retains_old_package(tmp_path, monkeypatch, boundary):
    store = Store(tmp_path / 'store')
    old = store.publish_snapshot([timed()], SETTINGS, background(), generated_at=NOW)
    before = {p.name: p.read_bytes() for p in old.directory.iterdir()}
    if boundary == 'write':
        original = Path.write_bytes
        def interrupt(path, data):
            if path.name == 'background.png':
                raise KeyboardInterrupt('simulated write interruption')
            return original(path, data)
        monkeypatch.setattr(Path, 'write_bytes', interrupt)
    elif boundary == 'rename':
        monkeypatch.setattr(os, 'replace', lambda *args: (_ for _ in ()).throw(OSError('simulated rename failure')))
    else:
        # Real SQLite failure after the complete package directory is generated.
        with sqlite3.connect(store.root / 'state.sqlite3') as db:
            db.execute("CREATE TRIGGER reject_selection BEFORE UPDATE ON state BEGIN SELECT RAISE(ABORT, 'simulated selection failure'); END")
    with pytest.raises((KeyboardInterrupt, OSError, sqlite3.DatabaseError)):
        store.publish_snapshot([], SETTINGS, background(10), generated_at=NOW + 1)
    assert Store(store.root).load_current() == old
    assert {p.name: p.read_bytes() for p in old.directory.iterdir()} == before
    assert store.load_settings() == SETTINGS


def test_merges_unsorted_calendars_and_deduplicates_then_orders_utf16_ties(tmp_path):
    events = [timed('late', NOW + 7200, NOW + 7300, 'home'), timed('\ue000', NOW, NOW + 60), timed('early', NOW - 3600, NOW - 3500, 'home'), timed('\U00010000', NOW, NOW + 60), timed('middle', NOW + 3600, NOW + 3700), timed('late', NOW + 7200, NOW + 7300, 'home')]
    published = Store(tmp_path / 'store').publish_snapshot(events, SETTINGS, background(), generated_at=NOW)
    parsed = ini(published)
    ids = [decoded(parsed[f'event{i:03}']['id']) for i in range(5)]
    assert ids == ['early', '\U00010000', '\ue000', 'middle', 'late']
    # Full schedule preserves serialized order in groups of four, including page 2.
    assert [ids[i:i+4] for i in range(0, len(ids), 4)] == [['early', '\U00010000', '\ue000', 'middle'], ['late']]


def test_window_overlap_includes_long_running_and_excludes_outside_and_unselected(tmp_path):
    events = [timed('long', 1790816400, 1792893600), timed('before', 1792335600, 1792425600), timed('after', 1793030400, 1793034000), timed('private', calendar='other')]
    published = Store(tmp_path / 'store').publish_snapshot(events, SETTINGS, background(), generated_at=NOW)
    parsed = ini(published)
    assert parsed['events']['count'] == '1'
    assert decoded(parsed['event000']['id']) == 'long'
    assert parsed['event000']['startEpoch'] == '1790816400'
    assert parsed['event000']['endEpoch'] == '1792893600'


def test_dst_endpoints_and_local_day_lengths_are_computed_independently(tmp_path):
    settings = Settings('America/Los_Angeles', date(2026, 11, 1), selected_calendar_ids=('work',))
    events = [timed('long-dst', 1790870400, 1795629600)]
    parsed = ini(Store(tmp_path / 'store').publish_snapshot(events, settings, background(), generated_at=NOW))
    event = parsed['event000']
    assert (event['startDate'], event['endDate']) == ('2026-10-01', '2026-11-25')
    assert (event['startUtcOffsetSeconds'], event['endUtcOffsetSeconds']) == ('-25200', '-28800')
    assert (parsed['day000']['startEpoch'], parsed['day000']['endEpoch']) == ('1793516400', '1793606400')


def test_all_day_floating_dates_survive_display_zone_change_and_exclusive_end(tmp_path):
    event = dict(id='all-day', calendarId='work', summary='', location='', allDay=True, startDate='2026-10-20', endDate='2026-10-22', sourceTimezone='Asia/Tokyo')
    settings = replace(SETTINGS, display_timezone='America/Los_Angeles')
    parsed = ini(Store(tmp_path / 'store').publish_snapshot([event], settings, background(), generated_at=NOW))
    assert (parsed['event000']['startDate'], parsed['event000']['endDate']) == ('2026-10-20', '2026-10-22')
    assert parsed['event000']['startEpoch'] == '1792479600'
    assert decoded(parsed['event000']['startDisplay']) == '全天'
    assert parsed['event000']['endDisplay'] == ''


@pytest.mark.parametrize('bad', [timed('nul\0'), timed(summary2='private'), timed('a', NOW, NOW), timed('a', 0, NOW), dict(id='a', calendarId='work', summary='', location='', allDay=True, startDate='2026-10-20', endDate='2026-10-20', sourceTimezone=None)])
def test_invalid_normalized_event_is_rejected(bad):
    with pytest.raises(ValueError):
        normalize_events([bad], SETTINGS)


def test_conflicting_duplicate_id_is_not_silently_overwritten():
    with pytest.raises(ValueError, match='duplicate'):
        normalize_events([timed('same'), timed('same', NOW + 60, NOW + 120)], SETTINGS)


def test_protocol_limits_fail_without_switching_current(tmp_path):
    store = Store(tmp_path / 'store')
    old = store.publish_snapshot([], SETTINGS, background(), generated_at=NOW)
    for events in [[timed(str(i)) for i in range(201)], [dict(timed(), summary='x' * 4097)], [dict(timed(str(i)), summary='中' * 1365) for i in range(30)]]:
        with pytest.raises(ValueError):
            store.publish_snapshot(events, SETTINGS, background(), generated_at=NOW)
        assert store.load_current() == old


@pytest.mark.parametrize('bad', [b'garbage', background()[:60]])
def test_publish_rejects_invalid_background_without_switching(tmp_path, bad):
    store = Store(tmp_path / 'store')
    old = store.publish_snapshot([], SETTINGS, background(), generated_at=NOW)
    with pytest.raises(ValueError):
        store.publish_snapshot([], SETTINGS, bad, generated_at=NOW)
    assert store.load_current() == old


def test_upload_name_cannot_be_used_as_resource_path(tmp_path):
    store = Store(tmp_path / 'store')
    for name in ['../escape.png', '/etc/passwd', 'a/b', 'a\\b']:
        with pytest.raises(ValueError):
            store.load_version(name)
    assert list(tmp_path.iterdir()) == []
    published = store.publish_snapshot([timed('../not-a-path')], SETTINGS, background(), generated_at=NOW)
    assert published.directory.parent == store.root / 'versions'
    assert decoded(ini(published)['content']['background']) == 'background.png'


def test_rejects_symlink_storage_component(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    root = tmp_path / 'store'
    root.mkdir()
    (root / 'versions').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        Store(root).publish_snapshot([], SETTINGS, background(), generated_at=NOW)
    assert list(outside.iterdir()) == []


def test_selection_persists_without_initial_publication(tmp_path):
    store = Store(tmp_path / 'store')
    store.save_settings(SETTINGS)
    assert Store(store.root).load_settings() == SETTINGS
    assert store.load_current() is None
    changed = replace(SETTINGS, selected_calendar_ids=('deleted-calendar-id',))
    store.save_settings(changed)
    assert store.load_settings() == changed


def test_new_local_day_and_changed_events_or_background_create_new_versions(tmp_path):
    store = Store(tmp_path / 'store')
    first = store.publish_snapshot([timed()], SETTINGS, background(), generated_at=NOW)
    second = store.publish_snapshot([dict(timed(), location='办公室')], SETTINGS, background(), generated_at=NOW)
    third = store.publish_snapshot([dict(timed(), location='办公室')], SETTINGS, background(100), generated_at=NOW)
    fourth = store.publish_snapshot([], replace(SETTINGS, window_start=date(2026, 10, 21)), background(100), generated_at=NOW)
    assert len({item.version for item in [first, second, third, fourth]}) == 4
    assert all(item.directory.exists() for item in [first, second, third, fourth])


def test_two_simultaneous_identical_publishers_select_one_complete_version(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    root = tmp_path / 'store'
    # Initialize configuration once; race only the real publication transaction.
    Store(root).save_settings(SETTINGS)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: Store(root).publish_snapshot([timed()], SETTINGS, background(), generated_at=NOW), range(2)))
    assert results[0] == results[1] == Store(root).load_current()
    assert set(p.name for p in results[0].directory.iterdir()) == {'SHA256SUMS', 'content.ini', 'background.png'}
    assert len(list((root / 'versions').iterdir())) == 1


def test_parent_symlink_cannot_redirect_the_injected_store(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        Store(alias / 'store').publish_snapshot([], SETTINGS, background(), generated_at=NOW)
    assert list(outside.iterdir()) == []


def test_hard_process_interruption_preserves_old_and_next_publish_recovers(tmp_path):
    import json
    store = Store(tmp_path / 'store')
    old = store.publish_snapshot([timed()], SETTINGS, background(), generated_at=NOW)
    script = '''import base64,json,os,sys
from pathlib import Path
from manager.content import Settings
from manager.store import Store
original=Path.write_bytes
def stopped(path,data):
    if path.name=='background.png': os._exit(77)
    return original(path,data)
Path.write_bytes=stopped
Store(sys.argv[1]).publish_snapshot([],Settings.from_dict(json.loads(sys.argv[2])),base64.b64decode(sys.argv[3]),generated_at=1792458001)
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    result = subprocess.run([sys.executable, '-c', script, str(store.root), json.dumps(SETTINGS.to_dict()), base64.b64encode(background()).decode()], env=env, capture_output=True)
    assert result.returncode == 77
    assert Store(store.root).load_current() == old
    assert (old.directory / 'background.png').read_bytes() == background()
    recovered = store.publish_snapshot([], SETTINGS, background(200), generated_at=NOW + 2)
    assert store.load_current() == recovered
    assert ini(recovered)['events']['count'] == '0'


def test_rejects_repeated_midnight_that_frozen_reader_cannot_represent(tmp_path):
    settings = Settings('America/Havana', date(2026, 11, 1), selected_calendar_ids=('work',))
    # DST repeats 00:00 at 05:00UTC; reader requires a local-midnight endpoint
    # within its table to equal the table's actual start (04:00UTC).
    with pytest.raises(ValueError, match='midnight'):
        Store(tmp_path / 'store').publish_snapshot([timed('fold', 1793509200, 1793512800)], settings, background(), generated_at=NOW)


def test_accepts_reader_maximum_text_and_event_count(tmp_path):
    store = Store(tmp_path / 'store')
    title = '中' * 1365  #4095 UTF-8 bytes, legal without truncation.
    first = store.publish_snapshot([dict(timed(), summary=title)], SETTINGS, background(), generated_at=NOW)
    assert decoded(ini(first)['event000']['summary']) == title
    maximum = store.publish_snapshot([dict(timed(str(i)), summary='') for i in range(200)], SETTINGS, background(), generated_at=NOW)
    assert ini(maximum)['events']['count'] == '200'
