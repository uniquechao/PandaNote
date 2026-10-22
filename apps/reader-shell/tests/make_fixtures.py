"""Deterministic, non-production package fixtures; no Qt or device operations."""
import base64, hashlib, shutil, struct, zlib
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def b64(s):
    if isinstance(s,str): s=s.encode('utf-8')
    return base64.b64encode(s).decode('ascii')

def png(width=480,height=800):
    def chunk(kind,data): return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,0,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\xcc'*width)*height))+chunk(b'IEND',b'')

def render(events,zone='Asia/Singapore',date='2026-10-19',version='v1'):
    lines=['[content]','schema=1','version='+b64(version),'generatedAt=1792458000','displayTimezone='+b64(zone),'background='+b64('background.png'),'','[events]','count='+str(len(events))]
    tz=ZoneInfo(zone)
    for i,(eid,title,start,end,allday) in enumerate(events):
        a=datetime.fromisoformat(start).replace(tzinfo=tz); b=datetime.fromisoformat(end).replace(tzinfo=tz)
        lines += ['', '[event%03d]'%i,'id='+b64(eid),'summary='+b64(title),'startEpoch='+str(int(a.timestamp())),'endEpoch='+str(int(b.timestamp())),'startDate='+a.strftime('%Y-%m-%d'),'endDate='+b.strftime('%Y-%m-%d'),'startUtcOffsetSeconds='+str(int(a.utcoffset().total_seconds())),'endUtcOffsetSeconds='+str(int(b.utcoffset().total_seconds())),'startDisplay='+b64('全天' if allday else a.strftime('%H:%M')),'endDisplay='+b64('' if allday else b.strftime('%H:%M')),'allDay='+str(int(allday)),'location='+b64('地点,一楼\n东侧')]
    lines += ['','[days]','count=9']
    d=datetime.fromisoformat(date)
    for i in range(9):
        a=(d+timedelta(days=i)).replace(tzinfo=tz); b=(d+timedelta(days=i+1)).replace(tzinfo=tz)
        lines += ['','[day%03d]'%i,'date='+a.strftime('%Y-%m-%d'),'startEpoch='+str(int(a.timestamp())),'endEpoch='+str(int(b.timestamp()))]
    return '\n'.join(lines)+'\n'

def manifest(path):
    (path/'SHA256SUMS').write_text(''.join(hashlib.sha256((path/name).read_bytes()).hexdigest()+'  '+name+'\n' for name in ('content.ini','background.png')))

def generate(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    events=[('cross','跨日','2026-10-19T23:00','2026-10-20T10:00',False),('all-day','全天活动','2026-10-20T00:00','2026-10-21T00:00',True),('meeting','会议,中文\n第二行','2026-10-20T09:30','2026-10-20T10:00',False),('empty','','2026-10-20T11:00','2026-10-20T12:00',False),('long','中'*1365,'2026-10-20T12:00','2026-10-20T13:00',False),('past','已结束','2026-10-20T07:00','2026-10-20T08:00',False),('tomorrow','明天','2026-10-21T01:00','2026-10-21T02:00',False)]
    def package(name,text,image=None):
        p=root/name
        if p.exists(): shutil.rmtree(p)
        p.mkdir();(p/'content.ini').write_text(text,encoding='utf-8');(p/'background.png').write_bytes(image if image is not None else png());manifest(p);return p
    valid=render(events)
    package('valid',valid)
    package('cancelled',render([],version='v2'))
    package('long-running',render([('long-timed','持续计时','2026-10-01T09:00','2026-10-25T10:00',False),('long-all-day','持续全天','2026-10-01T00:00','2026-10-25T00:00',True)]))
    package('long-dst',render([('long-dst','跨时制','2026-10-01T09:00','2026-11-25T10:00',False)],zone='America/Los_Angeles',date='2026-10-31'))
    package('next-only',render(events[-1:]))
    package('dst',render([],zone='America/Los_Angeles',date='2026-10-31'))
    package('max-events',render([(str(i),'event','2026-10-20T11:00','2026-10-20T12:00',False) for i in range(200)]))
    package('max-text',render([('text','x'*4096,'2026-10-20T11:00','2026-10-20T12:00',False)]))
    package('corrupt-png',valid,png()[:60])
    package('huge-png',valid,b'\x89PNG\r\n\x1a\n'+b'\0\0\0\rIHDR'+struct.pack('>II',60000,60000)+b'0'*20)
    package('extra-key',valid+'surprise=1\n')
    package('extra-section',valid+'\n[event999]\n')
    package('duplicate-section',valid+'\n[day000]\n')
    package('duplicate-key',valid.replace('schema=1','schema=1\nschema=1'))
    package('bad-all-day',valid.replace('allDay=0','allDay=1',1))
    package('bad-offset-range',valid.replace('startUtcOffsetSeconds=28800','startUtcOffsetSeconds=50401',1))
    package('bad-offset-format',valid.replace('startUtcOffsetSeconds=28800','startUtcOffsetSeconds=-0',1))
    package('bad-offset-date',valid.replace('endUtcOffsetSeconds=28800','endUtcOffsetSeconds=-50400',1))
    package('bad-offset-table-midnight',valid.replace('startEpoch=1792425600','startEpoch=1792425601',1).replace('startUtcOffsetSeconds=28800\nendUtcOffsetSeconds=28800\nstartDisplay=5YWo5aSp','startUtcOffsetSeconds=28799\nendUtcOffsetSeconds=28800\nstartDisplay=5YWo5aSp',1))
    package('bad-offset-midnight',valid.replace('startUtcOffsetSeconds=28800\nendUtcOffsetSeconds=28800\nstartDisplay=5YWo5aSp','startUtcOffsetSeconds=28801\nendUtcOffsetSeconds=28800\nstartDisplay=5YWo5aSp',1))
    p=package('malformed-manifest',valid);(p/'SHA256SUMS').write_text((p/'SHA256SUMS').read_text().upper())
    changes={'unknown-schema':('schema=1','schema=99'),'bad-base64':('summary='+b64(events[0][1]),'summary=AAAAA'),'bad-utf8':('summary='+b64(events[0][1]),'summary=/w=='),'too-long':('summary='+b64(events[0][1]),'summary='+b64('中'*1366)),'bad-path':('background='+b64('background.png'),'background='+b64('../background.png')),'bad-date':('startDate=2026-10-19','startDate=2026-02-30'),'bad-epoch':('startEpoch=1792422000','startEpoch=0'),'duplicate-id':('id='+b64('meeting'),'id='+b64('cross')),'bad-days':('[day001]\ndate=2026-10-20\nstartEpoch=1792425600\nendEpoch=1792512000','[day001]\ndate=2026-10-20\nstartEpoch=1792425600\nendEpoch=1792512001')}
    for name,(a,b) in changes.items():
        assert a in valid,(name,a)
        package(name,valid.replace(a,b,1))
    package('bad-background',valid,png(800,480))
    package('too-many',render([(str(i),'event','2026-10-20T11:00','2026-10-20T12:00',False) for i in range(201)]))
    package('oversize-ini',render([(str(i),'x'*500,'2026-10-20T11:00','2026-10-20T12:00',False) for i in range(200)]))
    for name in ['truncated','bad-hash','missing-manifest','missing-background','extra-file','symlink']:
        p=package(name,valid)
        if name=='truncated': (p/'content.ini').write_bytes((p/'content.ini').read_bytes()[:50])
        elif name=='bad-hash': (p/'background.png').write_bytes(png()+b'bad')
        elif name=='missing-manifest': (p/'SHA256SUMS').unlink()
        elif name=='missing-background': (p/'background.png').unlink()
        elif name=='extra-file': (p/'surprise.sh').write_text('no execution')
        elif name=='symlink':
            (p/'background.png').unlink();(p/'background.png').symlink_to('../valid/background.png')

if __name__=='__main__': generate(Path(__file__).resolve().parents[2]/'shared/fixtures')
