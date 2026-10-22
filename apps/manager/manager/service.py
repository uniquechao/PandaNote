"""Manager operations; one lock protects desired config and publication.

The synchronization coordinator uses this same export/publish path.
"""
import base64
import configparser
from datetime import datetime
from io import BytesIO
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

from PIL import Image

from .content import Settings, days, epoch, utf16_key
from .images import Crop, normalize_background
from .provider import CalendarBridgeProvider
from .store import Store


class ManagerError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def local_zone():
    path = Path('/etc/localtime')
    target = str(path.resolve())
    marker = '/zoneinfo/'
    if marker in target:
        zone = target.split(marker, 1)[1]
        ZoneInfo(zone)
        return zone
    raise ValueError('cannot detect Mac IANA timezone from /etc/localtime')


def blank_background():
    out = BytesIO()
    Image.new('L', (480, 800), 242).save(out, 'PNG')
    return out.getvalue()


class ManagerService:
    def __init__(self, root, provider=None, *, default_timezone=None):
        self.store = Store(root)
        self.provider = provider if provider is not None else CalendarBridgeProvider()
        self.lock = threading.RLock()
        self.last_error = None
        self.fresh_read = False
        zone = local_zone() if default_timezone is None else default_timezone
        ZoneInfo(zone)
        self.default_settings = Settings(zone, datetime.now(ZoneInfo(zone)).date())

    def settings(self, now=None):
        saved = self.store.load_settings() or self.default_settings
        today = (datetime.now(ZoneInfo(saved.display_timezone)) if now is None else datetime.fromtimestamp(now, ZoneInfo(saved.display_timezone))).date()
        return Settings(saved.display_timezone, today, 7, saved.selected_calendar_ids)

    def _call(self, action, *args):
        try:
            result = getattr(self.provider, action)(*args)
        except Exception as error:
            raise ManagerError('bridge_failure', '日历桥接读取失败。') from error
        if not isinstance(result, dict) or result.get('schema') != 1 or type(result.get('ok')) is not bool:
            raise ManagerError('bridge_invalid', '日历桥接返回了无效结果。')
        if not result['ok']:
            detail = result.get('error', {})
            raise ManagerError(str(detail.get('code', 'bridge_failure')), str(detail.get('message', '日历读取失败。')))
        return result

    def source_state(self):
        current = self.store.load_current()
        if current is None:
            return 'never_synced'
        if not self.fresh_read:
            return 'cached'
        read = self.store.last_successful_read()
        return 'stale' if read is None or time.time() - read > 900 else 'fresh'

    def status(self):
        with self.lock:
            status_error = None
            try:
                authorization = self._call('status')['authorization']
            except ManagerError as error:
                authorization = 'unavailable'
                status_error = dict(code=error.code, message=error.message)
            current = self.store.load_current()
            reader = self.store.load_value('reader_status') or dict(last_contact_at=None,last_displayed_at=None,last_displayed_version=None)
            return dict(schema=1, ok=True, server_time=int(time.time()), authorization=authorization,
                        provider=getattr(self.provider, 'label', 'real'), source_state=self.source_state(),
                        settings=self.settings().to_dict(), version=current.version if current else None,
                        generated_at=current.generated_at if current else None,
                        last_successful_read=self.store.last_successful_read(), error=self.last_error or status_error,
                        device=dict(state='contact_recorded' if reader['last_contact_at'] else 'not_connected', **reader))

    def calendars(self):
        with self.lock:
            return self._call('calendars')

    def connect(self):
        with self.lock:
            # This is the only path that invokes provider.request_access.
            return self._call('request_access')

    def selection(self, value):
        if set(value) != {'display_timezone', 'window_start', 'day_count', 'selected_calendar_ids'}:
            raise ValueError('日历配置字段不完整。')
        if not isinstance(value['selected_calendar_ids'], list) or len(value['selected_calendar_ids']) > 200:
            raise ValueError('最多选择 200 个日历。')
        settings = Settings.from_dict(value)
        today = datetime.now(ZoneInfo(settings.display_timezone)).date()
        if settings.window_start != today or settings.day_count != 7:
            raise ValueError('仅允许显示时区本地今天起未来七天。')
        with self.lock:
            self.store.save_settings(settings)
            return dict(schema=1, ok=True, saved=True, published=False, settings=settings.to_dict())

    def _background(self):
        current = self.store.load_current()
        if current:
            return current.background.read_bytes()
        draft = self.store.load_value('background_draft')
        return base64.b64decode(draft) if draft else blank_background()

    def sync(self, now=None, *, should_publish=None):
        with self.lock:
            settings = self.settings(now)
            table = days(settings)
            query = dict(schema=1, calendarIds=list(settings.selected_calendar_ids), displayTimezone=settings.display_timezone,
                         windowStartDate=settings.window_start.isoformat(), dayCount=settings.day_count,
                         startEpoch=table[0]['startEpoch'], endEpoch=table[-1]['endEpoch'])
            try:
                result = self._call('export', query)
                epoch(result['readAt'])
                if not isinstance(result['events'], list) or not isinstance(result['calendarIds'], list) or not isinstance(result['missingCalendarIds'], list):
                    raise ValueError('invalid bridge export')
                selected = set(settings.selected_calendar_ids)
                present, missing = set(result['calendarIds']), set(result['missingCalendarIds'])
                if present & missing or present | missing != selected:
                    raise ValueError('bridge calendar inventory does not match selection')
                if any(not isinstance(event, dict) or event.get('calendarId') not in present for event in result['events']):
                    raise ValueError('bridge event calendar does not match export inventory')
                source = dict(events=result['events'], settings=settings.to_dict(), readAt=result['readAt'],
                              source=getattr(self.provider, 'label', 'real'), missingCalendarIds=result['missingCalendarIds'])
                if should_publish is not None and not should_publish():
                    raise ManagerError('sync_stopped', '日历同步已停止。')
                current = self.store.publish_snapshot(result['events'], settings, self._background(), source_snapshot=source)
            except ManagerError as error:
                self.last_error = dict(code=error.code, message=error.message)
                self.fresh_read = False
                raise
            except (KeyError, TypeError, ValueError) as error:
                self.last_error = dict(code='invalid_snapshot', message=str(error))
                self.fresh_read = False
                raise ManagerError('invalid_snapshot', str(error)) from error
            self.fresh_read = True
            self.last_error = None
            return dict(schema=1, ok=True, published=True, version=current.version, source_state=self.source_state())

    def background(self, source, crop):
        normalized = normalize_background(source, crop)
        with self.lock:
            current = self.store.load_current()
            cached = self.store.load_source(current.version) if current else None
            if cached:
                # Use the last good export's settings while desired selection is
                # independently retained. Never label an offline edit a new read.
                current = self.store.publish_snapshot(cached['events'], Settings.from_dict(cached['settings']), normalized,
                                                      source_snapshot=cached, update_settings=False)
                return dict(schema=1, ok=True, published=True, draft=False, version=current.version, source_state=self.source_state())
            if current:
                raise ManagerError('source_unavailable', '当前包没有可保留的来源快照。')
            self.store.save_value('background_draft', base64.b64encode(normalized).decode('ascii'))
            return dict(schema=1, ok=True, published=False, draft=True, source_state='never_synced')

    def preview(self, version=None):
        with self.lock:
            current = self.store.load_current()
            if version is None and current is None:
                return dict(schema=1, ok=True, draft=True, version=None, source='unavailable', source_state='never_synced',
                            events=[], settings=self.settings().to_dict(), layout=layout(), resources=dict(background='/api/draft-background'))
            directory = self.store.load_version(version) if version is not None else current.directory
            version = directory.name
            ini = configparser.ConfigParser(interpolation=None)
            ini.optionxform = str
            ini.read_string((directory/'content.ini').read_text('utf-8'))
            events = []
            text_fields = {'id','summary','location','startDisplay','endDisplay'}
            for index in range(int(ini['events']['count'])):
                row = dict(ini[f'event{index:03}'])
                events.append({key: base64.b64decode(value).decode('utf-8') if key in text_fields else
                               int(value) if key in {'startEpoch','endEpoch','allDay','startUtcOffsetSeconds','endUtcOffsetSeconds'} else value for key,value in row.items()})
            source = self.store.load_source(version)
            return dict(schema=1, ok=True, draft=False, version=version, source=source['source'] if source else 'unknown',
                        source_state=self.source_state(), source_read_at=source['readAt'] if source else None,
                        generated_at=int(ini['content']['generatedAt']), published_settings=source['settings'] if source else None,
                        missing_calendar_ids=source.get('missingCalendarIds',[]) if source else [], events=events,
                        display_timezone=base64.b64decode(ini['content']['displayTimezone']).decode(),
                        server_time=int(time.time()), days=[dict(ini[f'day{i:03}']) for i in range(int(ini['days']['count']))],
                        home={**home(events, ini), 'sync_failed': self.last_error is not None}, layout=layout(), resources={name:f'/api/resources/{version}/{name}' for name in ('content.ini','background.png','SHA256SUMS')})


def layout():
    # Frozen reader shell.cpp Home / navigation.cpp coordinates; browser text
    # shaping differs from Qt4. These are content/layout parity, not pixel parity.
    return dict(width=480, height=800, white_top=[0,0,480,458], white_bottom=[0,680,480,120],
                date=[28,32,424,44], weekday=[28,82,424,32], events=[28,146,424],
                row_heights=dict(fewer_than_three=140,three=98), button=[160,704,160,64])


def home(events, ini):
    table = [dict(ini[f'day{i:03}']) for i in range(int(ini['days']['count']))]
    live = int(time.time())
    def day_at(value):
        return next((row['date'] for row in table if int(row['startEpoch']) <= value < int(row['endEpoch'])), None)
    trusted = day_at(live) is not None
    now = live if trusted else int(ini['content']['generatedAt'])
    today = day_at(now)
    selected = []
    def order(event):
        active = event['startEpoch'] <= now < event['endEpoch']
        return (not active, event['startEpoch'], utf16_key(event['id']))
    if today:
        for event in events:
            end_midnight = (event['endEpoch'] + event['endUtcOffsetSeconds']) % 86400 == 0
            overlap = event['startDate'] <= today and (event['endDate'] > today or event['endDate'] == today and not end_midnight)
            if event['endEpoch'] > now and overlap:
                selected.append(event)
        selected = sorted(selected,key=order)[:3]
        if not selected:
            selected = sorted([event for event in events if event['startEpoch'] > now],key=order)[:1]
    return dict(date=today, trusted_time=trusted, events=selected, now=now)
