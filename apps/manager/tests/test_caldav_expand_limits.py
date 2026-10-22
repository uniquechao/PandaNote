"""Actual owned subprocess/pipe/deadline cleanup, with fake worker only."""
import importlib
import os
from pathlib import Path
import time

import pytest
from test_caldav_provider import provider_class,configured,query
from manager.content import Settings


@pytest.mark.parametrize('mode',['stalled_input','stalled_exit','oversized_output'])
def test_worker_pipe_deadline_and_output_limit_reap_exact_owned_child(tmp_path,monkeypatch,mode):
    module=importlib.import_module(provider_class().__module__)
    script=tmp_path/'fake_worker.py';pidfile=tmp_path/'worker.pid'
    body='import os,time\nfrom pathlib import Path\nPath('+repr(str(pidfile))+').write_text(str(os.getpid()))\n'
    if mode=='oversized_output':
        body+='os.write(1,b"x"*1000000)\ntime.sleep(10)\n'
    elif mode=='stalled_exit':
        body+='os.close(1)\ntime.sleep(10)\n'
    else:
        body+='time.sleep(10)\n'
    script.write_text(body)
    monkeypatch.setattr(module,'_EXPAND_SCRIPT',script)
    monkeypatch.setattr(module,'EXPAND_TIMEOUT',.15)
    monkeypatch.setattr(module,'MAX_EXPAND_OUTPUT',1024)
    p,source=configured(tmp_path)
    settings=Settings.from_dict(dict(display_timezone='Asia/Shanghai',window_start='2026-10-22',day_count=7,selected_calendar_ids=[]))
    began=time.monotonic()
    with pytest.raises(Exception):
        p._expand_documents(['x'*(1024*1024)],{'id':source['id']},{'id':'fixture-calendar'},settings,{'deadline':began+2})
    assert time.monotonic()-began<1
    assert pidfile.is_file()
    pid=int(pidfile.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid,0)
    assert not module._EXPAND_PENDING
