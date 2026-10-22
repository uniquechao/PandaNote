"""One in-process owner for periodic reads and bounded bridge watch children.

No OS resident registration. Signals invalidate snapshots; only ManagerService
may export and publish. Wall/monotonic divergence and local-day changes force a
fresh read after wake even on platforms whose monotonic clock excludes sleep.
"""
import json
import os
import sqlite3
import subprocess
import threading
import time
from typing import TypedDict

from .service import ManagerError


class SyncResult(TypedDict):
    schema: int
    ok: bool
    published: bool
    version: str
    source_state: str


class SyncCoordinator:
    def __init__(self, service, *, wall_clock=time.time, monotonic=time.monotonic):
        self.service = service
        self.wall_clock, self.monotonic = wall_clock, monotonic
        self._state = threading.RLock()
        self._serial = threading.Lock()
        self._wake = threading.Event()
        self._thread = None
        self._closed = False
        self._last_attempt = None
        self._last_settings_failure = None
        self._last_day = None
        self._observed = (wall_clock(), monotonic())
        self._pending = self._first_signal = None
        self._generation = 0
        self._watch = None
        self._watch_buffer = bytearray()
        self._watch_bytes = 0
        self._watch_deadline = 0
        self._watch_retry = 0
        self._can_watch = False
        self.watch_state = 'idle'

    def start(self):
        with self._state:
            if self._closed:
                raise RuntimeError('stopped coordinator cannot restart')
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name='pandanote-calendar-sync', daemon=True)
                self._thread.start()

    def notify_change(self):
        with self._state:
            if self._closed:
                return
            now = self.monotonic()
            if self._first_signal is None:
                self._first_signal = now
            self._pending = now
            self._generation += 1
            self._wake.set()

    def sync_once(self, now=None) -> SyncResult:
        with self._serial:
            with self._state:
                if self._closed:
                    raise ManagerError('sync_stopped', '日历同步已停止。')
                generation = self._generation
                wall = self.wall_clock() if now is None else now
            day = self.service.settings(wall).window_start
            try:
                result = self.service.sync(wall, should_publish=lambda:not self._closed)
            finally:
                with self._state:
                    self._last_attempt = (self.wall_clock(), self.monotonic())
                    self._last_day = day
                    if generation == self._generation:
                        self._pending = self._first_signal = None
            with self._state:
                self._can_watch = True
                self._wake.set()
            return result

    def poll(self):
        """One bounded scheduler step, also used with controlled test clocks."""
        with self._state:
            if self._closed:
                return None
            self._supervise_watch()
            wall, mono = self.wall_clock(), self.monotonic()
            previous_wall, previous_mono = self._observed
            self._observed = wall, mono
            wake = abs((wall-previous_wall)-(mono-previous_mono)) > 2
            changed = self._pending is not None and (mono-self._pending >= .25 or mono-self._first_signal >= 2)
            generation = self._generation
            if self._last_settings_failure is not None:
                failed_wall, failed_mono = self._last_settings_failure
                retry = mono-failed_mono >= 300 or wall-failed_wall >= 300
                if not (retry or wake or changed):
                    return None
        settings_loaded = False
        try:
            # Configuration reads can fail too. Do not hold coordinator state
            # while waiting for the service lock.
            with self.service.lock:
                settings = self.service.settings(wall)
                configured = self.service.store.load_settings() is not None
            settings_loaded = True
            with self._state:
                self._last_settings_failure = None
                initial = self._last_attempt is None
                periodic = not initial and (mono-self._last_attempt[1] >= 300 or wall-self._last_attempt[0] >= 300)
                rollover = self._last_day is not None and settings.window_start != self._last_day
                changed = self._pending is not None and (mono-self._pending >= .25 or mono-self._first_signal >= 2)
                if not configured and initial and not changed:
                    return None
                if not (initial or periodic or rollover or wake or changed):
                    return None
            return self.sync_once(wall)
        except ManagerError:
            return None  # service records concrete read/auth error and retains current
        except (OSError, sqlite3.Error, ValueError) as error:
            with self.service.lock:
                self.service.last_error = dict(code='storage_failure', message='本地存储失败：' + str(error))
                self.service.fresh_read = False
            if not settings_loaded:
                with self._state:
                    # Failed configuration reads miss sync_once's bookkeeping.
                    # Bound retries and consume only the observed signal.
                    self._last_settings_failure = (self.wall_clock(), self.monotonic())
                    if generation == self._generation:
                        self._pending = self._first_signal = None
            return None

    def _run(self):
        while True:
            with self._state:
                if self._closed:
                    return
                self._wake.clear()
            self.poll()
            self._wake.wait(.25)

    def _end_watch(self, *, retry=True):
        process, self._watch = self._watch, None
        if process is not None:
            if process.poll() is None:
                process.kill()  # exact owned child only; no shell or process groups
            process.wait()
            process.stdout.close()
        self._watch_buffer.clear()
        self._watch_bytes = 0
        self._watch_retry = self.monotonic() + (5 if retry else 0)
        self.watch_state = 'retrying' if retry else 'idle'

    def _supervise_watch(self):
        # Called only by the owner under _state. Manual sync never owns a child.
        mono = self.monotonic()
        if self._watch is not None:
            process = self._watch
            try:
                while True:
                    try:
                        chunk = os.read(process.stdout.fileno(), 4096)
                    except BlockingIOError:
                        break
                    if not chunk:
                        self._end_watch(retry=process.poll() != 0)
                        break
                    self._watch_bytes += len(chunk)
                    self._watch_buffer.extend(chunk)
                    if self._watch_bytes > 65536 or len(self._watch_buffer) > 4096:
                        raise ValueError('oversized watch')
                    while b'\n' in self._watch_buffer:
                        line, _, rest = self._watch_buffer.partition(b'\n')
                        self._watch_buffer = bytearray(rest)
                        def unique(items):
                            value = {}
                            for key, item in items:
                                if key in value:
                                    raise ValueError('duplicate watch key')
                                value[key] = item
                            return value
                        value = json.loads(line, object_pairs_hook=unique)
                        if not isinstance(value, dict) or set(value) != {'schema','changed'} or type(value['schema']) is not int or value['schema'] != 1 or value['changed'] is not True:
                            raise ValueError('invalid watch signal')
                        self.notify_change()
                if self._watch is not None and (process.poll() is not None or mono >= self._watch_deadline):
                    self._end_watch(retry=process.poll() != 0)
            except (ValueError, UnicodeError, OSError):
                self._end_watch()
        command = getattr(self.service.provider, 'command', None)
        if self._watch is None and self._can_watch and command and mono >= self._watch_retry:
            try:
                self._watch = subprocess.Popen([*command, 'watch', '60'], stdin=subprocess.DEVNULL,
                                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False, close_fds=True)
                os.set_blocking(self._watch.stdout.fileno(), False)
                self._watch_deadline = mono + 62
                self.watch_state = 'watching'
            except OSError:
                self._end_watch()

    def stop(self):
        with self._state:
            self._closed = True
            self._wake.set()
            self._end_watch(retry=False)
            thread = self._thread
        # Wait for any bounded in-flight export; its commit guard sees _closed.
        with self._serial:
            pass
        if thread is not None and thread is not threading.current_thread():
            thread.join()
