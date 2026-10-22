"""Explicit simulated calendar for bounded browser acceptance; no EventKit access.

Run from repository root with the manager project interpreter. Stop after manual
browser checks; default manager.app always uses UnavailableProvider.
"""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from manager.app import create_server


class ExampleProvider:
    label = 'example'
    def status(self):
        return dict(schema=1, ok=True, authorization='authorized')
    def request_access(self):
        return self.status()
    def calendars(self):
        return dict(schema=1, ok=True, calendars=[dict(id='example-work',title='示例 · 工作日程'),dict(id='example-life',title='示例 · 个人安排')])
    def export(self, query):
        now=int(time.time())
        events=[]
        if 'example-work' in query['calendarIds']:
            events.append(dict(id='example-event-1',calendarId='example-work',summary='示例 · 阅读与项目复盘',location='示例工作室',allDay=False,sourceTimezone='Asia/Singapore',startEpoch=now-60,endEpoch=now+3600))
        return dict(schema=1,ok=True,readAt=now,calendarIds=query['calendarIds'],missingCalendarIds=[],events=events)


if __name__=='__main__':
    server=create_server(Path('apps/manager/build/task2-example-data'),ExampleProvider(),port=8767)
    try:
        server.serve_forever()
    finally:
        server.server_close()
