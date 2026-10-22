"""Manifest-bound LOCAL FILESYSTEM CLONE rehearsal. No device transport.

Durability covers an exclusive, non-hostile local filesystem clone with fsync
and atomic same-directory rename. It does not establish eMMC power-loss behavior,
normal-boot supervision or real display acceptance. Never executes any payload.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile

PROJECT = Path(__file__).resolve().parents[3]
MARKER = 'local-filesystem-rehearsal-v1\n'
BACKUP = '/home/pandanote-reader/rollback'
CHECKS = {'display', 'touch', 'calendar', 'offline', 'stable'}


class InstallError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, indent=2) + '\n'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _path(value, absolute=True):
    if not isinstance(value, str) or not value or '\x00' in value or '\\' in value:
        raise InstallError('invalid path')
    p = PurePosixPath(value)
    if p.is_absolute() != absolute or str(p) != value or '..' in p.parts or value == '/':
        raise InstallError('noncanonical or traversal path')
    return p


def _manifest(manifest, executable=False):
    # Detach caller-owned containers before any mutation starts.
    m = json.loads(canonical(manifest))
    if m.get('schema') != 1 or m.get('target') != 'Guowen 966U2':
        raise InstallError('unsupported manifest target/schema')
    if not isinstance(m.get('blockers'), list):
        raise InstallError('missing blockers')
    if m.get('backup_root') != BACKUP:
        raise InstallError('backup must use separate persistent /home rollback root')
    files = m.get('files')
    if not isinstance(files, list) or len(files) < 2:
        raise InstallError('exact entry and payload file list required')
    paths = []
    entries = 0
    for f in files:
        p = _path(f.get('path'))
        if f.get('role') == 'entry':
            entries += 1
            if str(p) != '/etc/init.d/rcS':
                raise InstallError('entry outside reviewed rcS replacement scope')
        elif f.get('role') == 'payload':
            if not str(p).startswith('/home/pandanote-reader/versions/'):
                raise InstallError('payload outside versioned application scope')
            if f.get('old_sha256') is not None:
                raise InstallError('payload must use a new version path')
        else:
            raise InstallError('unknown role')
        for old in paths:
            if p == old or p in old.parents or old in p.parents:
                raise InstallError('duplicate or shadowing paths')
        paths.append(p)
        if executable:
            _path(f.get('source'), absolute=False)
            if f.get('mode') not in (0o644, 0o755):
                raise InstallError('unsupported mode')
            if f['role'] == 'entry' and f.get('old_mode') not in (0o644, 0o755):
                raise InstallError('exact old mode required')
            for key in ('old_sha256', 'new_sha256'):
                value = f.get(key)
                if value is None and key == 'old_sha256' and f['role'] == 'payload':
                    continue
                if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
                    raise InstallError('missing exact hash')
    if entries != 1:
        raise InstallError('exactly one entry required')
    if executable and (m['blockers'] or m.get('scope') != 'local-clone-only'):
        raise InstallError('blocked: real device application is not implemented')
    return m


def plan(manifest):
    m = _manifest(manifest)
    blocked = bool(m['blockers']) or m.get('scope') != 'local-clone-only'
    if not blocked:
        _manifest(m, executable=True)
    return {'status': 'blocked' if blocked else 'clone-rehearsal-only',
            'manifest_sha256': digest(canonical(m).encode()),
            'blockers': m['blockers'], 'files': m['files'],
            'backup_root': m['backup_root'], 'device_apply_supported': False}


def _safe(base, relative):
    """Reject links, device nodes and traversal at every existing component."""
    p = base
    for component in relative.parts:
        if component in ('', '.', '..', '/'):
            raise InstallError('unsafe path component')
        p = p / component
        try:
            s = p.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(s.st_mode) or not (stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode)):
            raise InstallError('symlink or special file in clone path')
        if stat.S_ISREG(s.st_mode) and s.st_nlink != 1:
            raise InstallError('hardlinked clone file')
    return p


def _target(root, name):
    return _safe(root, _path(name).relative_to('/'))


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _mkdir(path):
    if path.exists():
        if not path.is_dir():
            raise InstallError('parent is not directory')
        return
    _mkdir(path.parent)
    path.mkdir(mode=0o700)
    _sync_dir(path.parent)


def _write(path, data, mode=0o600):
    _mkdir(path.parent)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fchmod(output.fileno(), mode)
            os.fsync(output.fileno())
        os.replace(name, path)
        _sync_dir(path.parent)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


def _read(path):
    try:
        return path.read_bytes()
    except OSError as e:
        raise InstallError('required regular file missing: ' + str(path)) from e


def _hash(path):
    return digest(_read(path)) if path.exists() else None


def _clone(root):
    raw = Path(root).absolute()
    if raw != raw.resolve() or not raw.is_relative_to(PROJECT) or raw == PROJECT:
        raise InstallError('clone must be a non-symlink directory inside this worktree')
    marker = _safe(raw, PurePosixPath('.pandanote-install-clone'))
    if not marker.is_file() or _read(marker).decode() != MARKER:
        raise InstallError('missing exact local clone marker')
    return raw


@contextmanager
def _locked(root):
    path = _safe(root, PurePosixPath('.pandanote-install-lock'))
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise InstallError('clone transaction already locked') from e
        yield
    finally:
        os.close(fd)


def _locations(root, m):
    key = digest(canonical(m).encode())
    backup_name = BACKUP + '/' + key
    backup = _target(root, backup_name)
    return backup_name, backup, backup / 'journal.json'


def _journal(root, m, state):
    name, backup, journal = _locations(root, m)
    _write(journal, canonical({'manifest_sha256': digest(canonical(m).encode()),
                             'state': state}).encode())
    return {'state': state, 'backup': name, 'device_install': False}


def _stored(root, m):
    name, backup, journal = _locations(root, m)
    if _read(_safe(backup, PurePosixPath('manifest.json'))) != canonical(m).encode():
        raise InstallError('stored manifest mismatch; use same verified manifest')
    try:
        state = json.loads(_read(_safe(backup, PurePosixPath('journal.json'))))
    except (ValueError, OSError) as e:
        raise InstallError('invalid transaction journal') from e
    if state.get('manifest_sha256') != digest(canonical(m).encode()):
        raise InstallError('journal manifest mismatch')
    for i, f in enumerate(m['files']):
        if f['old_sha256'] is not None:
            original = _safe(backup, PurePosixPath('old/' + str(i)))
            if _hash(original) != f['old_sha256']:
                raise InstallError('persistent backup missing or hash mismatch')
            if stat.S_IMODE(original.stat().st_mode) != f['old_mode']:
                raise InstallError('persistent backup mode mismatch')
    return name, backup, state


def apply_clone(root, bundle, manifest, checkpoint=lambda event: None):
    m = _manifest(manifest, executable=True)
    root = _clone(root)
    bundle = Path(bundle).absolute()
    if bundle != bundle.resolve() or not bundle.is_relative_to(PROJECT):
        raise InstallError('bundle must be a non-symlink directory inside this worktree')
    with _locked(root):
        name, backup, journal = _locations(root, m)
        if journal.exists():
            _, _, previous = _stored(root, m)
            if previous.get('state') != 'rolled-back':
                raise InstallError('recover previous transaction before retry')
        # Reject other manifests' unfinished transactions in this clone.
        rollback_root = _target(root, BACKUP)
        if rollback_root.exists():
            for other in rollback_root.iterdir():
                _safe(rollback_root, PurePosixPath(other.name))
                if other != backup and other.is_dir():
                    raise InstallError('different manifest transaction present; recover with original manifest')
        contents = []
        originals = []
        for f in m['files']:
            target = _target(root, f['path'])
            if _hash(target) != f['old_sha256']:
                raise InstallError('old hash mismatch: ' + f['path'])
            if f['old_sha256'] is not None and stat.S_IMODE(target.stat().st_mode) != f['old_mode']:
                raise InstallError('old mode mismatch: ' + f['path'])
            source = _safe(bundle, _path(f['source'], absolute=False))
            data = _read(source)
            if digest(data) != f['new_sha256']:
                raise InstallError('source hash mismatch: ' + f['source'])
            contents.append(data)
            originals.append((_read(target), stat.S_IMODE(target.stat().st_mode)) if target.exists() else None)
        _mkdir(backup)
        # Never replace a persistent original with a newly observed version.
        for i, original in enumerate(originals):
            if original is not None:
                dest = _safe(backup, PurePosixPath('old/' + str(i)))
                if dest.exists():
                    if _hash(dest) != m['files'][i]['old_sha256']:
                        raise InstallError('existing backup hash mismatch')
                else:
                    _write(dest, original[0], original[1])
        manifest_file = _safe(backup, PurePosixPath('manifest.json'))
        if manifest_file.exists() and _read(manifest_file) != canonical(m).encode():
            raise InstallError('existing manifest mismatch')
        _write(manifest_file, canonical(m).encode())
        _journal(root, m, 'backed-up')
        checkpoint('backed-up')
        for f, data in zip(m['files'], contents):
            if f['role'] == 'payload':
                _write(_target(root, f['path']), data, f['mode'])
        _journal(root, m, 'payload-staged')
        checkpoint('payload-staged')
        # Write-ahead state survives interruption immediately after entry rename.
        _journal(root, m, 'switching-entry')
        checkpoint('before-entry-switch')
        for f, data in zip(m['files'], contents):
            if f['role'] == 'entry':
                _write(_target(root, f['path']), data, f['mode'])
        checkpoint('entry-switched')
        return _journal(root, m, 'awaiting-verification')


def _rollback(root, m, checkpoint):
    _, backup, state = _stored(root, m)
    # Validate every source/current hash before restoring any path.
    for f in m['files']:
        current = _hash(_target(root, f['path']))
        if current not in (f['old_sha256'], f['new_sha256']):
            raise InstallError('current hash unknown; refusing to overwrite: ' + f['path'])
    _journal(root, m, 'rolling-back')
    # Entry first returns dispatch to last known working bytes.
    ordered = sorted(enumerate(m['files']), key=lambda pair: pair[1]['role'] != 'entry')
    for i, f in ordered:
        target = _target(root, f['path'])
        if f['old_sha256'] is not None:
            old = _safe(backup, PurePosixPath('old/' + str(i)))
            _write(target, _read(old), stat.S_IMODE(old.stat().st_mode))
        elif target.exists():
            target.unlink()
            _sync_dir(target.parent)
        if f['role'] == 'entry':
            checkpoint('entry-restored')
    return _journal(root, m, 'rolled-back')


def rollback_clone(root, manifest, checkpoint=lambda event: None):
    m = _manifest(manifest, executable=True)
    root = _clone(root)
    with _locked(root):
        return _rollback(root, m, checkpoint)


def verify_clone(root, manifest, checks):
    m = _manifest(manifest, executable=True)
    root = _clone(root)
    with _locked(root):
        _, _, state = _stored(root, m)
        if state.get('state') != 'awaiting-verification':
            raise InstallError('transaction is not awaiting verification')
        if set(checks) != CHECKS or any(checks[k] is not True for k in CHECKS):
            _rollback(root, m, lambda event: None)
            raise InstallError('clone boot verification failed; entry restored')
        for f in m['files']:
            target = _target(root, f['path'])
            if _hash(target) != f['new_sha256']:
                _rollback(root, m, lambda event: None)
                raise InstallError('verification current hash mismatch')
            if stat.S_IMODE(target.stat().st_mode) != f['mode']:
                _rollback(root, m, lambda event: None)
                raise InstallError('verification current mode mismatch')
        return _journal(root, m, 'clone-verified')
