"""Fail-closed offline proof gate shared by guest and parent; no target execution.
Raw evidence is emitted/retained before rejection. The parent independently checks
bytes, not the guest exit status or its claimed size/audit flags alone.
"""
import base64
import json
import sys
from audit_trace import ROOT, allowed_path, violations

LOG_LIMIT = 2 * 1024 * 1024
RUNS = {'version': 0, 'list_names': 0, 'activation_denied': 1, 'daemon_startup': 1}
LOG_NAMES = {name + suffix for name in [*RUNS, 'bus'] for suffix in ['.out', '.trace']}


def collect_cleanup(group, result):
    try:
        result['owned_cleanup'] = group.close()
    except Exception as error:
        result['cleanup_error'] = str(error)
    try:
        result['all_children_reaped'] = all(x.poll() is not None for x in group.children)
    except Exception as error:
        result['cleanup_error'] = str(error)
        result['all_children_reaped'] = False


def inspect_payload(payload):
    """Return explicit errors and safely decoded evidence, including failed logs."""
    errors, decoded = [], {}
    if not isinstance(payload, dict):
        return ['missing proof object'], decoded
    result, files = payload.get('result'), payload.get('files')
    if not isinstance(files, dict):
        errors.append('missing files object')
    else:
        if set(files) != LOG_NAMES:
            errors.append('missing or unexpected log evidence')
        for name, data in files.items():
            if name not in LOG_NAMES or not isinstance(data, str):
                errors.append('unsafe evidence name or encoding')
                continue
            try:
                decoded[name] = base64.b64decode(data, validate=True)
            except (ValueError, UnicodeError):
                errors.append('invalid base64: ' + name)
                continue
            if len(decoded[name]) > LOG_LIMIT:
                errors.append('oversize log: ' + name)
            if name.endswith('.trace') and not decoded[name]:
                errors.append('empty trace: ' + name)
            if name.endswith('.trace') and violations(decoded[name].decode(errors='replace')):
                errors.append('forbidden or ambiguous named mutation: ' + name)
    if not isinstance(result, dict):
        return errors + ['missing result object'], decoded
    for key in ['version_ok', 'private_bus_ready', 'activation_canary_installed',
                'bus_alive_before_cleanup', 'all_children_reaped']:
        if result.get(key) is not True:
            errors.append('missing or false ' + key)
    for key in ['activation_canary_executed', 'forbidden_state_exists', 'oversize_trace']:
        if result.get(key) is not False:
            errors.append('missing or non-false ' + key)
    if 'cleanup_error' in result:
        errors.append('cleanup_error recorded')
    cleanup = result.get('owned_cleanup')
    if (not isinstance(cleanup, list) or len(cleanup) != 5
            or any(x not in ('already_exited', 'terminated', 'killed') for x in cleanup)
            or cleanup[3] not in ('terminated', 'killed')):
        errors.append('missing or unsuccessful exact five-child cleanup')
    for name, code in RUNS.items():
        record = result.get(name)
        trace, stdout = decoded.get(name + '.trace'), decoded.get(name + '.out')
        if (not isinstance(record, dict) or type(record.get('exit_code')) is not int
                or record['exit_code'] != code or not isinstance(record.get('stdout'), str)
                or type(record.get('trace_bytes')) is not int or trace is None or stdout is None
                or record['trace_bytes'] != len(trace)
                or record['stdout'] != stdout.decode(errors='replace')[:4096]):
            errors.append('missing or inconsistent request proof: ' + name)
    version = result.get('version')
    if (not isinstance(version, dict) or not isinstance(version.get('stdout'), str)
            or version['stdout'].strip() != '5.87'):
        errors.append('wrong daemon version proof')
    for name, required in [('activation_denied.trace', ['ServiceUnknown']),
                           ('daemon_startup.trace', ['Failed to access management interface',
                                                     'Adapter handling initialization failed'])]:
        if any(text.encode() not in decoded.get(name, b'') for text in required):
            errors.append('missing expected diagnostic: ' + name)
    paths = result.get('private_paths')
    directories = ['etc', 'run', 'home', 'logs', 'var', 'var/lib', 'var/lib/bluetooth']
    expected = {ROOT + '/' + name: '0o700' for name in directories}
    expected.update({ROOT + '/etc/' + name: '0o600' for name in ['bus.conf', 'main.conf']})
    expected.update({ROOT + '/logs/' + name: '0o600' for name in LOG_NAMES})
    if (not isinstance(paths, dict) or paths != expected
            or any(not allowed_path(p) for p in paths)):
        errors.append('missing or unexpected private path/mode proof (including stale bus socket)')
    return errors, decoded


def emit_guest_proof(result, files, stream=sys.stdout):
    payload = {'result': result, 'files': files}
    # Preserve even rejected proof before returning failure to the guest entry.
    print(json.dumps(payload, sort_keys=True), file=stream, flush=True)
    errors, _ = inspect_payload(payload)
    return 1 if errors else 0


def retain_result(prefix, stdout, stderr, exit_code, image):
    # Raw bytes remain reviewable even when JSON, fields, encodings or paths fail.
    prefix.with_suffix('.stdout.json').write_bytes(stdout)
    prefix.with_suffix('.stderr.txt').write_bytes(stderr)
    payload = None
    try:
        payload = json.loads(stdout)
        errors, decoded = inspect_payload(payload)
    except (ValueError, UnicodeError) as error:
        errors, decoded = ['malformed proof: ' + str(error)], {}
    for name, data in decoded.items():
        (prefix.parent / (prefix.name + '-' + name)).write_bytes(data)
    if type(exit_code) is not int or exit_code != 0:
        errors.append('guest did not exit successfully')
    summary = {'exit_code': exit_code, 'result': payload.get('result') if isinstance(payload, dict) else None,
               'proof_errors': errors, 'hardware_access': False, 'image': image}
    prefix.with_suffix('.result.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary, 1 if errors else 0
