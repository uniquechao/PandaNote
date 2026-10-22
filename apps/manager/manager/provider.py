"""Injected calendar boundary; the real provider invokes a bounded local app."""


class UnavailableProvider:
    label = 'unavailable'

    @staticmethod
    def status():
        return dict(schema=1, ok=True, authorization='unavailable')

    @staticmethod
    def _failure():
        return dict(schema=1, ok=False, error=dict(code='bridge_unavailable', message='日历桥接尚未接入；现有内容会保留。'))

    def request_access(self):
        return self._failure()

    def calendars(self):
        return self._failure()

    def export(self, query):
        return self._failure()


class CalendarBridgeProvider:
    """Bounded direct child transport to the identifiable project-local .app.

    Construction is inert. Only request_access() sends the permission action.
    No shell, stdout logging, global install, or background/watch child.
    """
    label = 'real'

    def __init__(self, command=None, *, timeout=15, access_timeout=180, max_output=2 * 1024 * 1024):
        from pathlib import Path
        binary = Path(__file__).resolve().parents[2] / 'calendar-bridge/build/app/PandaNoteCalendarBridge.app/Contents/MacOS/PandaNoteCalendarBridge'
        self.command = list(command) if command is not None else [str(binary)]
        self.label = 'real' if self.command and Path(self.command[0]).is_file() else 'unavailable'
        self.timeout, self.access_timeout, self.max_output = timeout, access_timeout, max_output

    @staticmethod
    def _failure(code, message):
        return dict(schema=1, ok=False, error=dict(code=code, message=message))

    def _call(self, action, query=None):
        import json
        import os
        import selectors
        import subprocess
        import time
        fail = self._failure
        raw = json.dumps(query, ensure_ascii=False, allow_nan=False).encode('utf-8') if query is not None else b''
        if len(raw) > 65536:
            return fail('bridge_input', '日历桥接输入过大。')
        process = None
        try:
            process = subprocess.Popen([*self.command, action], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, shell=False, close_fds=True)
            deadline = time.monotonic() + (self.access_timeout if action == 'request-access' else self.timeout)
            result = bytearray()
            with selectors.DefaultSelector() as selector:
                os.set_blocking(process.stdout.fileno(), False)
                selector.register(process.stdout, selectors.EVENT_READ)
                if raw:
                    os.set_blocking(process.stdin.fileno(), False)
                    selector.register(process.stdin, selectors.EVENT_WRITE)
                else:
                    process.stdin.close()
                written = 0
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return fail('bridge_timeout', '日历桥接等待超时；现有内容已保留。')
                    for key, mask in selector.select(remaining):
                        if mask & selectors.EVENT_WRITE:
                            count = os.write(key.fd, raw[written:written+4096])
                            written += count
                            if written == len(raw):
                                selector.unregister(key.fileobj)
                                key.fileobj.close()
                        else:
                            chunk = os.read(key.fd, min(65536, self.max_output + 1 - len(result)))
                            if not chunk:
                                selector.unregister(key.fileobj)
                            else:
                                result.extend(chunk)
                                if len(result) > self.max_output:
                                    return fail('bridge_oversized', '日历桥接输出超过大小限制。')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return fail('bridge_timeout', '日历桥接等待超时。')
                if process.wait(timeout=remaining) != 0:
                    return fail('bridge_process', '日历桥接进程失败。')
            def pairs(items):
                value = {}
                for key, item in items:
                    if key in value:
                        raise ValueError('duplicate JSON key')
                    value[key] = item
                return value
            value = json.loads(result.decode('utf-8'), object_pairs_hook=pairs,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
            if not self._valid(value, action):
                raise ValueError('invalid bridge envelope')
            return value
        except FileNotFoundError:
            return fail('bridge_unavailable', '日历桥接应用尚未打包或不可用。')
        except subprocess.TimeoutExpired:
            return fail('bridge_timeout', '日历桥接等待超时。')
        except (ValueError, UnicodeError, TypeError):
            return fail('bridge_invalid', '日历桥接返回格式无效。')
        except OSError:
            return fail('bridge_process', '无法运行日历桥接应用。')
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()  # only this invocation's exact owned child
                process.wait()
                process.stdin.close()
                process.stdout.close()

    @staticmethod
    def _valid(value, action):
        if not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1 or type(value.get('ok')) is not bool:
            return False
        if not value['ok']:
            error = value.get('error')
            return (set(value) == {'schema', 'ok', 'error'} and isinstance(error, dict) and set(error) == {'code', 'message'}
                    and all(isinstance(error[k], str) and '\0' not in error[k] and len(error[k].encode('utf-8')) <= 4096 for k in error) and bool(error['code']))
        if action in {'status', 'request-access'}:
            return set(value) == {'schema','ok','authorization'} and value['authorization'] in {'not_determined','authorized','denied','restricted','unavailable'}
        if action == 'calendars':
            rows = value.get('calendars')
            return (set(value) == {'schema','ok','calendars'} and isinstance(rows,list) and all(
                isinstance(row,dict) and set(row)=={'id','title'} and isinstance(row['id'],str) and bool(row['id']) and isinstance(row['title'],str)
                and all('\0' not in row[k] and len(row[k].encode('utf-8')) <= 4096 for k in row) for row in rows))
        return (set(value)=={'schema','ok','readAt','calendarIds','missingCalendarIds','events'} and type(value['readAt']) is int
                and all(isinstance(value[key],list) and all(isinstance(item,str) for item in value[key]) for key in ('calendarIds','missingCalendarIds'))
                and isinstance(value['events'],list))  # Store performs exact event/schema/time validation.

    def status(self):
        return self._call('status')

    def request_access(self):
        return self._call('request-access')

    def calendars(self):
        return self._call('calendars')

    def export(self, query):
        return self._call('export', query)
