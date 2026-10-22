"""Private, isolated stdin/stdout iCalendar worker; never receives URLs or keys.

Run only as a fresh Python -I process. Resource limits precede third-party imports.
There is no network operation, file output, vendor executable or custom RRULE code.
"""
import json
import sys

MAX_INPUT=16*1024*1024
MAX_OUTPUT=2*1024*1024


class Invalid(Exception):
    def __init__(self,code='caldav_invalid'):
        self.code=code


def run(payload):
    from datetime import date,datetime,time,timedelta,timezone
    from zoneinfo import ZoneInfo
    import re
    from icalendar import Calendar
    import recurring_ical_events
    import x_wr_timezone
    if not isinstance(payload,dict) or set(payload)!={'documents','displayTimezone','windowStartDate','dayCount'}:
        raise Invalid()
    zone=ZoneInfo(payload['displayTimezone'])
    begin_date=date.fromisoformat(payload['windowStartDate'])
    if begin_date.isoformat()!=payload['windowStartDate'] or type(payload['dayCount']) is not int or not 1<=payload['dayCount']<=9:
        raise Invalid()
    finish_date=begin_date+timedelta(days=payload['dayCount'])
    begin=datetime.combine(begin_date,time(),zone);finish=datetime.combine(finish_date,time(),zone)
    begin_epoch,end_epoch=int(begin.timestamp()),int(finish.timestamp())
    documents=payload['documents']
    if not isinstance(documents,list) or len(documents)>1000:
        raise Invalid()
    def text(value,limit=4096,empty=True):
        if not isinstance(value,str) or '\0' in value or (not empty and not value) or len(value.encode())>limit:
            raise Invalid()
        return value
    def epoch(value):
        result=int(value.timestamp())
        if not 946684800<=result<4133980800:
            raise Invalid()
        return result
    def aware(value,prop):
        if not isinstance(value,datetime):
            raise Invalid()
        if value.tzinfo is None:
            if prop is not None and prop.params.get('TZID'):
                raise Invalid('caldav_timezone')
            value=value.replace(tzinfo=zone)
        return value
    def identity(event,uid,rule_uids):
        rid=event.get('RECURRENCE-ID')
        if rid is None:
            return None
        # The library gives non-recurring events an RID as well. Preserve their
        # existing UID-only identity, and use RIDs for actual recurring series.
        if uid not in rule_uids:
            return None
        value=rid.dt
        if type(value) is date:
            return 'D:'+value.isoformat()
        return 'T:'+aware(value,rid).astimezone(timezone.utc).isoformat()
    def normalize(event,rule_uids):
        # Cancellation overrides have already participated in library expansion.
        if str(event.get('STATUS','')).upper()=='CANCELLED':
            return None
        if any(key in event for key in ('RRULE','RDATE','EXDATE','EXRULE')):
            raise Invalid('caldav_recurrence')
        uid=text(str(event.get('UID','')),empty=False)
        start=event.decoded('DTSTART');end=event.decoded('DTEND',None);duration=event.decoded('DURATION',None)
        if end is not None and duration is not None:
            raise Invalid()
        all_day=type(start) is date
        if end is None:
            end=start+(duration if duration is not None else timedelta(days=1) if all_day else timedelta(0))
        result=dict(uid=uid,recurrenceIdentity=identity(event,uid,rule_uids),summary=text(str(event.get('SUMMARY',''))),location=text(str(event.get('LOCATION',''))),allDay=all_day,sourceTimezone=None)
        if all_day:
            if type(end) is not date or end<=start:
                raise Invalid()
            if end<=begin_date or start>=finish_date:
                return None
            result.update(startDate=start.isoformat(),endDate=end.isoformat())
        else:
            start=aware(start,event['DTSTART']);end=aware(end,event.get('DTEND'))
            start_value,end_value=epoch(start),epoch(end)
            if end_value<=start_value:
                raise Invalid('caldav_duration')
            if end_value<=begin_epoch or start_value>=end_epoch:
                return None
            tzid=event['DTSTART'].params.get('TZID')
            result.update(startEpoch=start_value,endEpoch=end_value,sourceTimezone=text(str(tzid),128,False) if tzid else 'UTC' if start.utcoffset()==timedelta(0) else payload['displayTimezone'])
        return result
    output={}
    for raw in documents:
        if not isinstance(raw,str) or len(raw.encode())>2*1024*1024:
            raise Invalid('caldav_oversized')
        unfolded=re.sub(r'\r?\n[ \t]','',raw)
        if unfolded.upper().count('BEGIN:')>1024 or max(map(len,unfolded.splitlines()),default=0)>65536:
            raise Invalid('caldav_oversized')
        calendar=Calendar.from_ical(raw)
        if calendar.name!='VCALENDAR' or any(c.errors for c in calendar.walk()):
            raise Invalid()
        original=calendar.walk('VEVENT')
        if not original:
            raise Invalid('caldav_incomplete')
        rule_uids=set()
        has_rules=False
        for event in original:
            uid=text(str(event.get('UID','')),empty=False)
            rules=any(key in event for key in ('RRULE','RDATE','EXDATE','EXRULE'))
            has_rules=has_rules or rules
            if rules or event.get('RECURRENCE-ID') is not None:
                rule_uids.add(uid)
            # Some servers send cancellation tombstones without DTSTART. Supply
            # only their explicit RID to the library adapter; they remain
            # cancelled and can never become a published active occurrence.
            if str(event.get('STATUS','')).upper()=='CANCELLED' and event.get('RECURRENCE-ID') is not None and event.get('DTSTART') is None:
                event.add('DTSTART',event.decoded('RECURRENCE-ID'))
            for name in ('DTSTART','DTEND','RECURRENCE-ID'):
                prop=event.get(name)
                if prop is not None and prop.params.get('TZID') and isinstance(prop.dt,datetime) and prop.dt.tzinfo is None:
                    raise Invalid('caldav_timezone')
        # Apply a source X-WR-TIMEZONE consistently before either the direct
        # server-expanded path or the recurrence library sees floating times.
        # This mature conversion preserves independent UID/RID components.
        calendar=x_wr_timezone.to_standard(calendar)
        original=calendar.walk('VEVENT')
        # Library adapters can repair a reversed span. Reject malformed source
        # data first rather than silently inventing an active event duration.
        for event in original:
            if str(event.get('STATUS','')).upper()=='CANCELLED':
                continue
            start=event.decoded('DTSTART');end=event.decoded('DTEND',None);duration=event.decoded('DURATION',None)
            if end is not None and duration is not None:
                raise Invalid('caldav_duration')
            if end is None:
                end=start+(duration if duration is not None else timedelta(days=1) if type(start) is date else timedelta(0))
            if type(start) is date:
                valid=type(end) is date and end>start
            else:
                valid=aware(end,event.get('DTEND')).timestamp()>aware(start,event.get('DTSTART')).timestamp()
            if not valid:
                raise Invalid('caldav_duration')
        if has_rules:
            # after() includes meetings already in progress at begin. Its
            # internal dateutil work may still be eager: OS limits and the
            # parent's killable deadline, not this iterator, bound resources.
            events=recurring_ical_events.of(calendar,keep_recurrence_attributes=False,components=('VEVENT',),skip_bad_series=False).after(begin)
        else:
            # Already expanded server responses may have many VEVENTs sharing
            # UID plus independent RIDs. Do not regroup or collapse them.
            events=iter(original)
        scanned=0
        for event in events:
            scanned+=1
            if scanned>4096:
                raise Invalid('caldav_limit')
            if has_rules:
                start=event.decoded('DTSTART')
                beyond=start>=finish_date if type(start) is date else aware(start,event.get('DTSTART')).timestamp()>=end_epoch
                if beyond:
                    break
            item=normalize(event,rule_uids)
            if item is None:
                continue
            key=(item['uid'],item['recurrenceIdentity'])
            if key in output and output[key]!=item:
                raise Invalid()
            output[key]=item
            if len(output)>200:
                raise Invalid('caldav_limit')
    return list(output.values())


def verified_run(payload):
    # Both complete document sets run inside this one process's CPU, memory,
    # wall and output limits. Only the reader's normalized consumption model
    # is compared; no hand-written iCalendar metadata canonicalizer is used.
    if not isinstance(payload,dict):
        raise Invalid()
    payload=dict(payload)
    replacements=payload.pop('verificationReplacements',[])
    if not isinstance(replacements,list) or len(replacements)>1000:
        raise Invalid()
    primary=run(payload)
    if not replacements:
        return primary
    alternate=dict(payload);documents=list(payload['documents']);seen=set()
    for entry in replacements:
        if not isinstance(entry,dict) or set(entry)!={'index','document'}:
            raise Invalid()
        index=entry['index']
        if type(index) is not int or not 0<=index<len(documents) or index in seen or not isinstance(entry['document'],str):
            raise Invalid()
        seen.add(index);documents[index]=entry['document']
    alternate['documents']=documents
    repeated=run(alternate)
    def ordered(events):
        return sorted(events,key=lambda item:(item['uid'],item['recurrenceIdentity'] or ''))
    if ordered(primary)!=ordered(repeated):
        raise Invalid('caldav_changed')
    return primary


def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_CPU,(3,4))
        resource.setrlimit(resource.RLIMIT_NOFILE,(32,32))
        if sys.platform.startswith('linux'):
            resource.setrlimit(resource.RLIMIT_AS,(192*1024*1024,192*1024*1024))
        raw=sys.stdin.buffer.read(MAX_INPUT+1)
        if len(raw)>MAX_INPUT:
            raise Invalid('caldav_oversized')
        value=json.loads(raw)
        result=dict(schema=1,ok=True,events=verified_run(value))
        data=json.dumps(result,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
        if len(data)>MAX_OUTPUT:
            raise Invalid('caldav_oversized')
    except Invalid as error:
        data=json.dumps(dict(schema=1,ok=False,code=error.code)).encode()
    except MemoryError:
        data=b'{"schema":1,"ok":false,"code":"caldav_limit"}'
    except BaseException:
        # No exception text, event contents, source URL or credential is logged.
        data=b'{"schema":1,"ok":false,"code":"caldav_recurrence"}'
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


if __name__=='__main__':
    main()
