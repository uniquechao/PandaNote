"""Real child-process transport, with fixture executables; never EventKit."""
import json
from pathlib import Path
import sys
import pytest
from manager.provider import CalendarBridgeProvider

def child(tmp_path, body):
    script=tmp_path/'fixture child.py'
    script.write_text(body)
    return CalendarBridgeProvider([sys.executable,str(script)], timeout=.3, access_timeout=.3, max_output=1024)

def test_explicit_argv_and_structured_input_no_implicit_permission(tmp_path):
    p=child(tmp_path,"import sys,json\na=sys.argv[1]\nq=json.load(sys.stdin) if a=='export' else None\nprint(json.dumps(dict(schema=1,ok=True,readAt=1773000000,calendarIds=q['calendarIds'],missingCalendarIds=[],events=[])) if q else json.dumps(dict(schema=1,ok=True,authorization='not_determined')))" )
    assert p.status()['authorization']=='not_determined'
    value='opaque; $(no-shell) 日历'
    assert p.export({'calendarIds':[value]})['calendarIds']==[value]

@pytest.mark.parametrize('body,code',[
    ('import time; time.sleep(2)','bridge_timeout'),
    ("print('x'*2000)",'bridge_oversized'),
    ("print('not json')",'bridge_invalid'),
    ("import sys; sys.exit(3)",'bridge_process'),
    ("print('{\"schema\":1,\"ok\":true,\"authorization\":\"bogus\"}')",'bridge_invalid'),
    ("print('{\"schema\":1,\"ok\":false,\"error\":{\"code\":\"denied\",\"message\":\"Fixture\"},\"events\":[]}')",'bridge_invalid'),
])
def test_transport_failures_are_concrete(tmp_path,body,code):
    result=child(tmp_path,body).status()
    assert not result['ok'] and result['error']['code']==code
    assert 'events' not in result

def test_missing_executable_is_unavailable(tmp_path):
    p=CalendarBridgeProvider([str(tmp_path/'absent')])
    assert p.status()['error']['code']=='bridge_unavailable'


def test_timeout_kills_exact_child_and_does_not_leave_resident(tmp_path):
    import os
    import time
    pidfile=tmp_path/'child.pid'
    p=child(tmp_path,f"import os,time,pathlib; pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(20)")
    assert p.status()['error']['code']=='bridge_timeout'
    pid=int(pidfile.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid,0)


def test_real_transport_failure_retains_published_snapshot(tmp_path):
    from datetime import datetime
    import time
    from manager.service import ManagerService, ManagerError
    from manager.content import Settings
    from manager.images import Crop
    state=tmp_path/'fixture.json'
    p=child(tmp_path,f"import json,pathlib; print(pathlib.Path({str(state)!r}).read_text())")
    service=ManagerService(tmp_path/'store',p)
    settings=service.settings()
    settings=Settings(settings.display_timezone,settings.window_start,7,('work',))
    service.store.save_settings(settings)
    event=dict(id='fixture',calendarId='work',summary='Fixture',location='',sourceTimezone=None,allDay=False,startEpoch=int(time.time()),endEpoch=int(time.time())+3600)
    state.write_text(json.dumps(dict(schema=1,ok=True,readAt=int(time.time()),calendarIds=['work'],missingCalendarIds=[],events=[event])))
    first=service.sync()['version']
    state.write_text('malformed')
    with pytest.raises(ManagerError) as error:
        service.sync()
    assert error.value.code=='bridge_invalid'
    assert service.store.load_current().version==first
    state.write_text(json.dumps(dict(schema=1,ok=True,readAt=int(time.time()),calendarIds=[],missingCalendarIds=['work'],events=[])))
    service.sync()
    assert service.preview()['events']==[]
    assert service.settings().selected_calendar_ids==('work',)


def test_status_retains_concrete_transport_error_without_publishing(tmp_path):
    from manager.service import ManagerService
    provider=child(tmp_path,"print('malformed')")
    service=ManagerService(tmp_path/'status-store',provider)
    result=service.status()
    assert result['authorization']=='unavailable'
    assert result['error']['code']=='bridge_invalid'
    assert result['version'] is None
