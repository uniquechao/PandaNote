"""Explicit-root SQLite selection of immutable, completely generated packages.

No default singleton, background worker, pruning or initialization on import.
A SQLite transaction selects a directory only after every member is fsynced and
its directory rename is durable. Interrupted staging/orphan versions are safe;
old versions are never deleted, including across manager restart.
"""
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
import uuid

from .content import Settings, days, epoch, normalize_events, render_ini
from .images import validate_background


@dataclass(frozen=True)
class PublishedContent:
    version: str
    directory: Path
    generated_at: int
    content_digest: str

    @property
    def background(self) -> Path:
        return self.directory / 'background.png'


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Store:
    def __init__(self, root: str | Path):
        # Keep the supplied path visible to the guard; resolving here would
        # hide an ancestor symlink which redirected writes outside the root.
        self.root = Path(root).absolute()

    def _guard(self):
        for path in [*self.root.parents, self.root, self.root / 'versions', self.root / 'state.sqlite3']:
            if path.is_symlink():
                raise ValueError('symlink storage paths are forbidden')

    def _database(self, *, create: bool = False):
        self._guard()
        if create:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.root.chmod(0o700)
            (self.root / 'versions').mkdir(exist_ok=True)
        db = sqlite3.connect(self.root / 'state.sqlite3', timeout=10)
        db.execute('PRAGMA synchronous=FULL')
        if create:
            db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), version TEXT, generated_at INTEGER, digest TEXT, settings TEXT, last_read INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS manager_values (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS version_sources (version TEXT PRIMARY KEY, value TEXT NOT NULL)')
            (self.root / 'state.sqlite3').chmod(0o600)
            db.execute('INSERT OR IGNORE INTO state(id) VALUES (1)')
            db.commit()
        return db

    @staticmethod
    def _version(version: str):
        if not isinstance(version, str) or re.fullmatch('[0-9a-f]{32}', version) is None:
            raise ValueError('invalid server version identifier')

    def load_version(self, version: str) -> Path:
        """Resolve an immutable preview resource; no user filenames accepted."""
        self._version(version)
        self._guard()
        path = self.root / 'versions' / version
        if path.is_symlink() or not path.is_dir():
            raise ValueError('unknown immutable version')
        return path

    def load_current(self) -> PublishedContent | None:
        self._guard()
        if not (self.root / 'state.sqlite3').exists():
            return None
        with closing(self._database()) as db, db:
            row = db.execute('SELECT version, generated_at, digest FROM state WHERE id=1').fetchone()
        if row is None or row[0] is None:
            return None
        return PublishedContent(row[0], self.load_version(row[0]), row[1], row[2])

    def load_settings(self) -> Settings | None:
        self._guard()
        if not (self.root / 'state.sqlite3').exists():
            return None
        with closing(self._database()) as db, db:
            row = db.execute('SELECT settings FROM state WHERE id=1').fetchone()
        return Settings.from_dict(json.loads(row[0])) if row and row[0] else None

    def save_settings(self, settings: Settings) -> None:
        """Persist explicit selection independently of source-read success."""
        with closing(self._database(create=True)) as db, db:
            db.execute('UPDATE state SET settings=? WHERE id=1', (_json(settings.to_dict()),))

    def record_successful_read(self, read_at: int) -> None:
        """Fresh source-read status is never a content or live-server clock."""
        read_at = epoch(read_at)
        with closing(self._database(create=True)) as db, db:
            db.execute('UPDATE state SET last_read=? WHERE id=1', (read_at,))

    def last_successful_read(self) -> int | None:
        self._guard()
        if not (self.root / 'state.sqlite3').exists():
            return None
        with closing(self._database()) as db, db:
            row = db.execute('SELECT last_read FROM state WHERE id=1').fetchone()
        return row[0] if row else None

    def publish_snapshot(self, events: list[dict], settings: Settings, background: bytes, *, generated_at: int | None = None, source_snapshot: dict | None = None, update_settings: bool = True) -> PublishedContent:
        generated_at = epoch(int(time.time()) if generated_at is None else generated_at)
        validate_background(background)
        normalized = normalize_events(events, settings)
        # Hash exact reader semantics and background, excluding volatile times,
        # opaque version and selection ordering which does not affect display.
        payload = _json(dict(events=normalized, displayTimezone=settings.display_timezone, days=days(settings))).encode('utf-8')
        digest = hashlib.sha256(payload + b'\0' + background).hexdigest()
        version = uuid.uuid4().hex
        content = render_ini(normalized, settings, version, generated_at)
        manifest = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n' for name, data in [('content.ini', content), ('background.png', background)]).encode('ascii')
        db = self._database(create=True)
        staging = self.root / 'versions' / ('.staging-' + uuid.uuid4().hex)
        try:
            # Serialize concurrent publishers across threads/processes. The
            # selected digest is rechecked under the same transaction lock.
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT version, generated_at, digest FROM state WHERE id=1').fetchone()
            if row[0] is not None and row[2] == digest:
                current = PublishedContent(row[0], self.load_version(row[0]), row[1], row[2])
                if update_settings:
                    db.execute('UPDATE state SET settings=? WHERE id=1', (_json(settings.to_dict()),))
                self._write_source(db, current.version, source_snapshot)
                db.commit()
                return current
            staging.mkdir(mode=0o700)
            for name, data in [('content.ini', content), ('background.png', background), ('SHA256SUMS', manifest)]:
                path = staging / name
                path.write_bytes(data)
                with path.open('rb') as handle:
                    os.fsync(handle.fileno())
                path.chmod(0o444)
            _fsync_directory(staging)
            target = self.root / 'versions' / version
            os.replace(staging, target)
            target.chmod(0o555)
            _fsync_directory(target.parent)
            db.execute('UPDATE state SET version=?, generated_at=?, digest=? WHERE id=1', (version, generated_at, digest))
            if update_settings:
                db.execute('UPDATE state SET settings=? WHERE id=1', (_json(settings.to_dict()),))
            self._write_source(db, version, source_snapshot)
            db.commit()
            return PublishedContent(version, target, generated_at, digest)
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
            if staging.exists():
                staging.chmod(0o700)
                shutil.rmtree(staging)

    @staticmethod
    def _write_source(db, version, snapshot):
        if snapshot is not None:
            read_at = epoch(snapshot['readAt'])
            db.execute('INSERT OR REPLACE INTO version_sources VALUES (?, ?)', (version, _json(snapshot)))
            db.execute('UPDATE state SET last_read=? WHERE id=1', (read_at,))

    def load_source(self, version: str) -> dict | None:
        self._version(version)
        if not (self.root / 'state.sqlite3').exists():
            return None
        with closing(self._database()) as db:
            exists = db.execute("SELECT name FROM sqlite_master WHERE name='version_sources'").fetchone()
            row = db.execute('SELECT value FROM version_sources WHERE version=?', (version,)).fetchone() if exists else None
        return json.loads(row[0]) if row else None

    def save_value(self, key: str, value) -> None:
        with closing(self._database(create=True)) as db, db:
            db.execute('INSERT OR REPLACE INTO manager_values VALUES (?, ?)', (key, _json(value)))

    def load_value(self, key: str):
        self._guard()
        if not (self.root / 'state.sqlite3').exists():
            return None
        with closing(self._database()) as db:
            exists = db.execute("SELECT name FROM sqlite_master WHERE name='manager_values'").fetchone()
            row = db.execute('SELECT value FROM manager_values WHERE key=?', (key,)).fetchone() if exists else None
        return json.loads(row[0]) if row else None

    def record_reader(self, contacted_at: int, *, displayed_version: str | None = None) -> None:
        """Atomic reader telemetry; polling never claims successful display."""
        contacted_at = epoch(contacted_at)
        if displayed_version is not None:
            self._version(displayed_version)
        with closing(self._database(create=True)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT value FROM manager_values WHERE key='reader_status'").fetchone()
            state = json.loads(row[0]) if row else dict(last_contact_at=None, last_displayed_at=None, last_displayed_version=None)
            state['last_contact_at'] = contacted_at
            if displayed_version is not None:
                state.update(last_displayed_at=contacted_at, last_displayed_version=displayed_version)
            db.execute("INSERT OR REPLACE INTO manager_values VALUES ('reader_status', ?)", (_json(state),))
