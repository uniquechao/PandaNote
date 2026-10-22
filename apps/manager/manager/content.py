"""Bridge normalization and deterministic schema-1 reader serialization."""
import base64
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MIN_EPOCH = 946684800
MAX_EPOCH = 4133980800


def text(value: str, *, empty: bool = True, limit: int = 4096) -> str:
    if not isinstance(value, str) or '\0' in value or (not empty and not value):
        raise ValueError('invalid text field')
    try:
        encoded = value.encode('utf-8')
    except UnicodeError as error:
        raise ValueError('invalid Unicode text') from error
    if len(encoded) > limit:
        raise ValueError('text exceeds reader field limit')
    return value


def epoch(value: int) -> int:
    if type(value) is not int or not MIN_EPOCH <= value < MAX_EPOCH:
        raise ValueError('epoch outside reader range')
    return value


def local_date(value: str) -> date:
    if not isinstance(value, str):
        raise ValueError('expected yyyy-MM-dd')
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError('expected yyyy-MM-dd') from error
    if parsed.isoformat() != value:
        raise ValueError('expected yyyy-MM-dd')
    return parsed


@dataclass(frozen=True)
class Settings:
    display_timezone: str
    window_start: date
    day_count: int = 7
    selected_calendar_ids: tuple[str, ...] = ()

    def __post_init__(self):
        text(self.display_timezone, empty=False, limit=128)
        try:
            ZoneInfo(self.display_timezone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError('unknown display IANA timezone') from error
        if type(self.window_start) is not date or type(self.day_count) is not int or not 1 <= self.day_count <= 9:
            raise ValueError('window requires a date and 1..9 days')
        if not isinstance(self.selected_calendar_ids, tuple) or len(set(self.selected_calendar_ids)) != len(self.selected_calendar_ids):
            raise ValueError('selected calendar IDs must be a unique tuple')
        for value in self.selected_calendar_ids:
            text(value, empty=False)
        days(self)

    def to_dict(self) -> dict:
        return dict(display_timezone=self.display_timezone, window_start=self.window_start.isoformat(), day_count=self.day_count, selected_calendar_ids=list(self.selected_calendar_ids))

    @classmethod
    def from_dict(cls, value: dict) -> 'Settings':
        return cls(value['display_timezone'], local_date(value['window_start']), value['day_count'], tuple(value['selected_calendar_ids']))


def midnight(value: date, zone: ZoneInfo) -> int:
    instant = datetime.combine(value, time(), zone)
    result = epoch(int(instant.timestamp()))
    # Reject exceptional historical skipped midnights rather than fabricate a
    # reader all-day boundary which disagrees with its local Gregorian check.
    if datetime.fromtimestamp(result, zone).replace(tzinfo=None) != datetime.combine(value, time()):
        raise ValueError('display zone has no local midnight on requested date')
    return result


def days(settings: Settings) -> list[dict]:
    zone = ZoneInfo(settings.display_timezone)
    output = []
    for index in range(settings.day_count):
        value = settings.window_start + timedelta(days=index)
        start, end = midnight(value, zone), midnight(value + timedelta(days=1), zone)
        if not 20 * 3600 <= end - start <= 28 * 3600:
            raise ValueError('local day outside reader range')
        output.append(dict(date=value.isoformat(), startEpoch=start, endEpoch=end))
    return output


def endpoint(value: int, zone: ZoneInfo, all_day: bool, end: bool = False) -> dict:
    local = datetime.fromtimestamp(epoch(value), zone)
    offset = int(local.utcoffset().total_seconds())
    if not -50400 <= offset <= 50400:
        raise ValueError('UTC offset outside reader range')
    return dict(Epoch=value, Date=local.date().isoformat(), UtcOffsetSeconds=offset,
                Display=('' if end else '全天') if all_day else local.strftime('%m-%d %H:%M'))


def utf16_key(value: str) -> bytes:
    """Big-endian units compare exactly as case-sensitive QString UTF-16."""
    return value.encode('utf-16-be')


def normalize_events(events: list[dict], settings: Settings) -> list[dict]:
    zone = ZoneInfo(settings.display_timezone)
    table = days(settings)
    window_start, window_end = table[0]['startEpoch'], table[-1]['endEpoch']
    output = {}
    common = {'id', 'calendarId', 'summary', 'location', 'allDay', 'sourceTimezone'}
    for event in events:
        if not isinstance(event, dict) or type(event.get('allDay')) is not bool:
            raise ValueError('invalid normalized event')
        all_day = event['allDay']
        if set(event) != common | ({'startDate', 'endDate'} if all_day else {'startEpoch', 'endEpoch'}):
            raise ValueError('unexpected or missing event fields')
        id = text(event['id'], empty=False)
        calendar = text(event['calendarId'], empty=False)
        summary, location = text(event['summary']), text(event['location'])
        if event['sourceTimezone'] is not None:
            text(event['sourceTimezone'], empty=False, limit=128)
        if all_day:
            start_date, end_date = local_date(event['startDate']), local_date(event['endDate'])
            if end_date <= start_date:
                raise ValueError('all-day end date must be exclusive and later')
            start, end = midnight(start_date, zone), midnight(end_date, zone)
        else:
            start, end = epoch(event['startEpoch']), epoch(event['endEpoch'])
        if end <= start:
            raise ValueError('event end must follow start')
        normalized = dict(id=id, summary=summary, location=location, allDay=int(all_day))
        for prefix, value in [('start', start), ('end', end)]:
            normalized.update({prefix + key: item for key, item in endpoint(value, zone, all_day, prefix == 'end').items()})
        if calendar not in settings.selected_calendar_ids or end <= window_start or start >= window_end:
            continue
        if id in output and output[id] != normalized:
            raise ValueError('conflicting duplicate event ID')
        for prefix in ('start', 'end'):
            instant = normalized[prefix + 'Epoch']
            offset = normalized[prefix + 'UtcOffsetSeconds']
            if (instant + offset) % 86400 == 0:
                for day in table:
                    if day['startEpoch'] < instant < day['endEpoch']:
                        raise ValueError('ambiguous local midnight is unsupported by reader')
        output[id] = normalized
    if len(output) > 200:
        raise ValueError('snapshot exceeds 200 events')
    return sorted(output.values(), key=lambda event: (event['startEpoch'], utf16_key(event['id'])))


def b64(value: str) -> str:
    return base64.b64encode(text(value).encode('utf-8')).decode('ascii')


def render_ini(events: list[dict], settings: Settings, version: str, generated_at: int) -> bytes:
    sections = [('[content]', dict(schema=1, version=b64(version), generatedAt=epoch(generated_at), displayTimezone=b64(settings.display_timezone), background=b64('background.png'))), ('[events]', dict(count=len(events)))]
    for index, event in enumerate(events):
        fields = {key: b64(value) if key in {'id', 'summary', 'location', 'startDisplay', 'endDisplay'} else value for key, value in event.items()}
        sections.append((f'[event{index:03}]', fields))
    table = days(settings)
    sections.append(('[days]', dict(count=len(table))))
    sections.extend((f'[day{index:03}]', value) for index, value in enumerate(table))
    result = ''.join(section + '\n' + ''.join(f'{key}={value}\n' for key, value in fields.items()) + '\n' for section, fields in sections).rstrip('\n').encode('utf-8') + b'\n'
    if len(result) > 131072:
        raise ValueError('content.ini exceeds 128 KiB')
    return result
