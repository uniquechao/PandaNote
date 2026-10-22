#!/usr/bin/env python3
"""Pinned, fail-closed RAM-only application staging. Default: read-only check.

No driver loading, reset, boot transport, persistent writes or synthetic input.
Mutating entries require --run-bounded-test or the fixed --run-soak-test.
"""
import argparse
import base64
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import struct
import zlib

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
PREFLIGHT_PATH = PROJECT / 'pandanote-analysis/app-development-research/reader_runtime_preflight.py'
spec = importlib.util.spec_from_file_location('reader_runtime_preflight', PREFLIGHT_PATH)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)
# Exact independently reviewed Wi-Fi native release; prior 25e55d00 and
# f09685a7 releases remain rollback captures. Only this manifest is accepted.
REVIEWED_MANIFEST_SHA = 'c17a4d133f7953ae54720611a378c1640cdd3cf427db1d4fcd680a9a80ec8a99'
LEGACY_PROFILE = 'legacy-network-down'
NETWORK_PROFILE = 'msc1-sdio-wlan0-opt-ro-v1'
PID1_SHA = '1ed1ef64aa71af447679e179efa69e6852902255e1ff056de9ee710b86cd354d'
PROFILE_COMMANDS = {
    'profile': 'if [ -f /tmp/pandanote-network-profile-wlan0-v1 ]; then /bin/busybox cat /tmp/pandanote-network-profile-wlan0-v1; else /bin/busybox echo ABSENT; fi',
    'pid1': '/bin/busybox sha256sum /tmp/pid1',
    'receipt': 'if [ -f /tmp/pandanote-reviewed-boot-receipt ]; then /bin/busybox cat /tmp/pandanote-reviewed-boot-receipt; else /bin/busybox echo ABSENT; fi',
}
TOUCH_SHA = 'c54b0fca356b3109f1b6823fe644600ab08294c97aa6950c8236d840628cbbaa'
TARGET = '/tmp/reader-shell'
TMP_LIMIT = 28 * 1024 * 1024
# Conservative measured operating ceiling, not the reader's unknown true max.
# Completion trailer is included; shell: plus NUL leaves281B below AOSP's4096B.
MAX_WRAPPED_UTF8 = 3808
# Controller's BusyBox child /proc/self/limits proof: ulimit -f512 =>262144B.
# The network app must write the complete maximum2MiB authenticated PNG. Host
# shells can use1024B units; do not infer target limits from a host shell probe.
TARGET_FSIZE_UNIT_BYTES = 512
NETWORK_APP_FILE_BLOCKS = 4096
NETWORK_RUNTIME_BUDGET = 12*1024*1024
NETWORK_RUNTIME_WORST_CASE = (768000 + 2097152 + 262144 + 1048576 + 65536 +
                              3*2240512 + 32768)
STOCK_STAGED = ('libQtGui.so.4', 'libQtCore.so.4', 'libQtNetwork.so.4', 'libfreetype.so.6')
SDK = PROJECT / '.local-deps/reference-root/pandanote-analysis/app-development-research/qt-stock-sysroot'
Q = shlex.quote
B = '/bin/busybox '
EXTRA_COMMANDS = {
    'exclusive': 'for p in /proc/[0-9]*; do '
        'if /bin/busybox grep -q libQtGui "$p/maps" 2>/dev/null; then /bin/busybox echo "QT_PROCESS=$p"; fi; '
        'if [ -r "$p/comm" ]; then case "$(/bin/busybox cat "$p/comm")" in '
        'qpe|qpeentry|quicklauncher|reader-shell*|pandanote-qt*) /bin/busybox echo "QWS_PROCESS=$p";; esac; fi; done; '
        'for p in /tmp/qtembedded-*; do [ ! -e "$p" ] || /bin/busybox echo "QWS_PATH=$p"; done; '
        '/bin/busybox printf "PANDANOTE_UNIX_TABLE\\n"; '
        'if [ -r /proc/net/unix ]; then /bin/busybox cat /proc/net/unix && '
        '/bin/busybox printf "PANDANOTE_QWS_SCAN_COMPLETE\\n"; else false; fi',
    'capacity': '/bin/busybox df -Pk /tmp | /bin/busybox awk \'NR==2 {printf "%.0f\\n", $4*1024}\'',
    'stage_tree': 'if [ -L /tmp/reader-shell ]; then /bin/busybox echo UNTRUSTED; '
        'elif [ ! -e /tmp/reader-shell ]; then /bin/busybox echo ABSENT; '
        'elif [ ! -d /tmp/reader-shell ]; then /bin/busybox echo UNTRUSTED; '
        'else /bin/busybox find /tmp/reader-shell ! -type f ! -type d; '
        '/bin/busybox find /tmp/reader-shell -type d | /bin/busybox sed \'s/^/DIR /\'; '
        '/bin/busybox find /tmp/reader-shell -type f -exec /bin/busybox sha256sum {} \\;; fi',
    'hardware': '/bin/busybox printf "fb="; /bin/busybox cat /sys/class/graphics/fb0/virtual_size; '
        '/bin/busybox cat /sys/class/graphics/fb0/bits_per_pixel; '
        '/bin/busybox cat /sys/class/graphics/fb0/stride; '
        '/bin/busybox cat /sys/class/graphics/fb0/name; '
        '/bin/busybox cat /sys/class/input/event0/device/name; '
        '/bin/busybox sha256sum /tmp/reader-hw/focaltech_touch-RAM-NO-UPGRADE.ko',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_file(base, name):
    pure = PurePosixPath(name)
    if pure.is_absolute() or not pure.parts or any(x in ('..', '.') for x in pure.parts) or str(pure) != name:
        raise ValueError('unsafe artifact path: ' + name)
    current = base
    if base.is_symlink():
        raise ValueError('symlink release directory')
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('symlink artifact/source: ' + name)
    if not current.is_file():
        raise ValueError('missing artifact/source: ' + name)
    return current


def verify_release(build=ROOT/'build', source=ROOT):
    manifest = safe_file(build, 'manifest.json')
    manifest_bytes = manifest.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != REVIEWED_MANIFEST_SHA:
        raise ValueError('not the exact reviewed manifest')
    data = json.loads(manifest_bytes)
    files = {'manifest.json': manifest}
    records = {'manifest.json':{'bytes':len(manifest_bytes), 'sha256':REVIEWED_MANIFEST_SHA}}
    for item in data['artifacts']:
        name = item['path']
        file = safe_file(build, name)
        if name in files or file.stat().st_size != item['bytes'] or sha(file) != item['sha256']:
            raise ValueError('artifact hash/size/duplicate mismatch: ' + name)
        files[name] = file
        records[name] = {'bytes':item['bytes'], 'sha256':item['sha256']}
    for name, digest in data['sources'].items():
        if sha(safe_file(source, name)) != digest:
            raise ValueError('source hash mismatch: ' + name)
    return data, files, records


def library_command(data, *, opt_libraries=False):
    # Consume the validated manifest snapshot, never reread mutable metadata.
    parts = []
    for item in data['stock_libraries']:
        name = item['name']
        if not re.fullmatch(r'[A-Za-z0-9.+_-]+', name):
            raise ValueError('unsafe library name')
        paths = ('/run/pandanote-opt/opt/image/opt/Qtopia/lib' +
                 ('' if name in STOCK_STAGED else ' /lib /usr/lib')) if opt_libraries else '/lib /usr/lib /opt/Qtopia/lib'
        resolved_check=''
        if opt_libraries:
            real_name=PurePosixPath(item['source_path']).name
            if not re.fullmatch(r'[A-Za-z0-9.+_-]+',real_name):
                raise ValueError('unsafe library provenance')
            resolved_check=('if [ "$d" = /run/pandanote-opt/opt/image/opt/Qtopia/lib ] && '
                '[ "$(/bin/busybox readlink -f "$d/'+name+'")" != "$d/'+real_name+'" ]; then '
                '/bin/busybox echo "'+name+' INVALID"; found=1; break; fi; ')
        parts.append('found=0; for d in '+paths+'; do '
            'if [ -f "$d/'+name+'" ]; then '+resolved_check+'/bin/busybox printf "'+name+' "; '
            '/bin/busybox sha256sum "$d/'+name+'" | /bin/busybox cut -d " " -f1; found=1; break; fi; done; '
            '[ "$found" = 1 ] || /bin/busybox echo "'+name+' MISSING"')
    return '\n'.join(parts)


def library_commands(data, *, opt_libraries=False):
    command=library_command(data,opt_libraries=opt_libraries)
    if not opt_libraries:
        return [command]
    batches=[];batch=[]
    for assertion in command.splitlines():
        candidate='\n'.join(batch+[assertion])
        try:
            wrap_shell(candidate)
        except ValueError:
            if not batch:
                raise
            batches.append('\n'.join(batch));batch=[assertion]
            wrap_shell(assertion)
        else:
            batch.append(assertion)
    if batch:
        batches.append('\n'.join(batch))
    return batches



def wrap_shell(command):
    wrapped = command.rstrip() + '\npandanote_shell_status=$?; /bin/busybox printf "\\nPANDANOTE_SHELL_EXIT=%s\\n" "$pandanote_shell_status"'
    if len(wrapped.encode('utf-8')) > MAX_WRAPPED_UTF8:
        raise ValueError('legacy ADB wrapped command exceeds proven 3808-byte UTF8 operating budget')
    return wrapped


def verification_commands(payload_hashes):
    """Greedy complete-assertion batches; each gets its own checked exit trailer."""
    batches, assertions = [], []
    prefix = '# VERIFY_FILES\n'
    for name, digest in payload_hashes.items():
        assertion = '[ "$('+B+'sha256sum '+Q(TARGET+'/'+name)+' | '+B+'cut -d " " -f1)" = '+Q(digest)+' ]'
        candidate = prefix+' && '.join(assertions+[assertion])
        try:
            wrap_shell(candidate)
        except ValueError:
            if not assertions:
                raise
            batches.append(prefix+' && '.join(assertions))
            assertions = [assertion]
            wrap_shell(prefix+assertion)
        else:
            assertions.append(assertion)
    if assertions:
        batches.append(prefix+' && '.join(assertions))
    return batches


class ExistingAdb(preflight.Adb):
    def __init__(self, port=5039):
        super().__init__(port)
        self.port = port
        # Explicit host: adb must not auto-start a missing local server.
        self.base[1:1] = ['-H', '127.0.0.1']

    def shell(self, command):
        wrapped = wrap_shell(command)
        timeout = 340 if command.startswith('# BOUNDED_RUN\n') else 20
        if re.fullmatch(r'# SOAK_RUN_SECONDS=1800\n/bin/busybox sh /tmp/reader-shell-run-[0-9T]+/soak-controller.sh', command):
            timeout = 1840
        result = self.run(['shell', wrapped], timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'existing ADB server unavailable')
        body, marker, code = result.stdout.replace('\r\n', '\n').rpartition('\nPANDANOTE_SHELL_EXIT=')
        if not marker or code != '0\n':
            raise RuntimeError('remote command failed or missing completed-success trailer')
        return body


def boot_receipt_literal():
    # Root controller publishes only after the attempt journal AND a fresh USB
    # runtime recheck. This is an operator handoff marker, not attestation.
    return ('profile='+NETWORK_PROFILE+'\nmanifest='+REVIEWED_MANIFEST_SHA+'\n'
            'pid1='+PID1_SHA+'\nbootstrap=d050610bd76deadf4d7ef8b4c6a265cd80fcba73f5538899dd0f1e2c6e36edac\n')


def validate_profile(diagnostics, profile=LEGACY_PROFILE, *, opt_libraries=False):
    if profile not in (LEGACY_PROFILE,NETWORK_PROFILE):
        raise ValueError('Unknown runtime profile')
    if profile==LEGACY_PROFILE:
        if opt_libraries:
            raise ValueError('Optional library mount requires reviewed network profile')
        return preflight.validate_runtime(diagnostics)
    if diagnostics.get('receipt')!=boot_receipt_literal():
        raise ValueError('Missing or mixed reviewed boot receipt')
    if (diagnostics.get('profile')!='wlan0-only-listeners-loopback-storage-ro-v1\n' or
        diagnostics.get('pid1')!=PID1_SHA+'  /tmp/pid1\n'):
        raise ValueError('Missing or mixed reviewed PID1/network marker')
    # Reuse all golden validation. Only exact wlan0 and optional exact p5 mount
    # are removed from its deny-all inputs after their own strict checks.
    filtered=dict(diagnostics)
    network=[];seen=set()
    for line in diagnostics.get('network','').splitlines():
        match=re.fullmatch(r'(/sys/class/net/[A-Za-z0-9_.-]+/flags) (0x[0-9a-fA-F]{1,8})',line)
        if not match or match[1] in seen:
            raise ValueError('Invalid/duplicate interface flags')
        seen.add(match[1])
        network.append(match[1]+' '+('0x0' if match[1]=='/sys/class/net/wlan0/flags' else match[2]))
    if '/sys/class/net/lo/flags' not in seen:
        raise ValueError('Missing loopback flag evidence')
    filtered['network']='\n'.join(network)+'\n'
    mounts=[];opt_count=0
    for line in diagnostics.get('mounts','').splitlines():
        fields=line.split()
        if len(fields)!=6:
            raise ValueError('Unrecognized mount record')
        if fields[1]=='/run/pandanote-opt' and opt_libraries:
            options=set(fields[3].split(','))
            if fields[0]!='/dev/mmcblk0p5' or fields[2]!='ext4' or 'ro' not in options or 'rw' in options or not options & {'noload','norecovery'}:
                raise ValueError('Optional p5 mount must be exact readonly ext4 without recovery')
            opt_count+=1
        else:
            mounts.append(line)
    if opt_libraries and opt_count!=1:
        raise ValueError('Optional p5 mount must appear exactly once')
    filtered['mounts']='\n'.join(mounts)+'\n'
    result=preflight.validate_runtime(filtered)
    return dict(result,profile=profile,wlan0_allowed=True,opt_libraries=opt_libraries)


def protection(adb, profile=LEGACY_PROFILE, *, opt_libraries=False):
    serial = adb.run(['get-serialno'])
    if serial.returncode or serial.stdout.strip() != preflight.SERIAL:
        raise ValueError('exact RAM serial mismatch or unavailable')
    diagnostics = {key: adb.shell(cmd) for key, cmd in preflight.COMMANDS.items()}
    if profile!=LEGACY_PROFILE:
        diagnostics.update({key:adb.shell(cmd) for key,cmd in PROFILE_COMMANDS.items()})
    validation = validate_profile(diagnostics,profile,opt_libraries=opt_libraries)
    if diagnostics['uid'].strip() != '0':
        raise ValueError('diagnostic identity mismatch')
    return {'diagnostics': diagnostics, 'validation': validation}


def verify_payload(payload, records, build):
    """Recheck paths/size/bytes against immutable reviewed metadata, not a new hash baseline."""
    for name in payload:
        base, relative = (SDK, name[4:]) if name.startswith('lib/') else (build, name)
        file = safe_file(base, relative)
        content = file.read_bytes()
        if len(content)!=records[name]['bytes'] or hashlib.sha256(content).hexdigest()!=records[name]['sha256']:
            raise ValueError('artifact/library changed before transfer: '+name)


def validate_exclusive(output):
    lines = output.splitlines()
    if (len(lines)<3 or lines[0]!='PANDANOTE_UNIX_TABLE' or
            lines[-1]!='PANDANOTE_QWS_SCAN_COMPLETE' or
            lines[1].split()!=['Num','RefCount','Protocol','Flags','Type','St','Inode','Path']):
        raise ValueError('missing/invalid QWS completed Unix-table scan or occupied process evidence')
    for line in lines[2:-1]:
        fields = line.split(maxsplit=7)
        if (len(fields)<7 or not re.fullmatch(r'(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{16}):',fields[0]) or
                any(not re.fullmatch(r'[0-9a-fA-F]{8}',x) for x in fields[1:4]) or
                not re.fullmatch(r'[0-9a-fA-F]{4}',fields[4]) or
                not re.fullmatch(r'[0-9a-fA-F]{2}',fields[5]) or not fields[6].isdigit()):
            raise ValueError('malformed QWS Unix-socket table record')
        if len(fields)==8 and re.search(r'QtEmbedded|qtembedded',fields[7],re.I):
            raise ValueError('QWS Unix socket already exists')


def inspect(adb, manifest, files, records, data, *, opt_libraries=False,network_profile=False):
    validate_exclusive(data['exclusive'])
    hw = data['hardware']
    if ('800,960' not in hw or '\n16\n1600\nspi_fb\nfts_ts\n' not in hw or 'fts_ts' not in hw or TOUCH_SHA not in hw):
        raise ValueError('hardware identity/framebuffer/guarded touch evidence mismatch')
    data['libraries'] = ''.join(adb.shell(cmd).rstrip()+'\n' for cmd in library_commands(manifest,opt_libraries=opt_libraries))
    lines = data['libraries'].splitlines()
    dependencies = {}
    for line in lines:
        fields = line.split()
        if len(fields) != 2 or fields[0] in dependencies:
            raise ValueError('invalid library evidence')
        dependencies[fields[0]] = fields[1]
    staged = {}
    for item in manifest['stock_libraries']:
        actual = dependencies.pop(item['name'], None)
        if actual == 'MISSING' and item['name'] in STOCK_STAGED and not opt_libraries:
            file = safe_file(SDK, item['name'])
            if sha(file) != item['sha256'] or file.stat().st_size != item['bytes']:
                raise ValueError('SDK library hash/size mismatch')
            staged['lib/'+item['name']] = file
            records['lib/'+item['name']] = {'bytes':item['bytes'], 'sha256':item['sha256']}
        elif actual != item['sha256']:
            raise ValueError('root runtime library missing or hash mismatch: '+item['name'])
    if dependencies:
        raise ValueError('unknown library evidence')
    payload = dict(files, **staged)
    expected = {TARGET+'/'+name: records[name]['sha256'] for name in payload}
    present = data['stage_tree'].strip()
    reuse = present != 'ABSENT'
    if reuse:
        tree = {}
        directories = set()
        expected_dirs = {TARGET}
        for path in expected:
            parent = PurePosixPath(path).parent
            while str(parent).startswith(TARGET):
                expected_dirs.add(str(parent))
                if str(parent)==TARGET:
                    break
                parent = parent.parent
        for line in present.splitlines():
            fields = line.split()
            if len(fields)==2 and fields[0]=='DIR':
                if fields[1] in directories:
                    raise ValueError('duplicate stage directory')
                directories.add(fields[1])
                continue
            if len(fields) != 2 or not re.fullmatch('[0-9a-f]{64}', fields[0]) or fields[1] in tree:
                raise ValueError('untrusted stage tree/symlink')
            tree[fields[1]] = fields[0]
        if tree != expected or directories != expected_dirs:
            raise ValueError('existing stage must exactly match pinned release; no repair/retransmission')
    size = sum(records[name]['bytes'] for name in payload)
    try:
        free = int(data['capacity'].strip())
    except ValueError:
        raise ValueError('missing tmpfs capacity evidence')
    runtime_budget=NETWORK_RUNTIME_BUDGET if network_profile else 3*1024*1024
    required = (0 if reuse else size) + runtime_budget
    if size + runtime_budget > TMP_LIMIT or free < required:
        raise ValueError('tmpfs capacity insufficient or payload exceeds 28MiB bound')
    return data, payload, reuse, {'payload_bytes':size, 'free_bytes':free, 'required_bytes':required, 'limit_bytes':TMP_LIMIT, 'runtime_budget_bytes':runtime_budget,
        'ordinary_ram_reserve_bytes':(24 if network_profile else 10)*1024*1024,
        'app_file_limit_bytes':(NETWORK_APP_FILE_BLOCKS if network_profile else 512)*TARGET_FSIZE_UNIT_BYTES,
        'monitor_file_limit_bytes':512*TARGET_FSIZE_UNIT_BYTES,
        'worst_case_runtime_bytes':NETWORK_RUNTIME_WORST_CASE if network_profile else 2930688,
        'budget_derivation':('frame768000 + app stdout2097152 + monitor262144 + Qt state1048576 + controls65536 + three allocated package versions2240512 each + private config32768 =10995712 bytes; rounded to12MiB. Ordinary RAM reserve24MiB includes mapped Qt/freetype19MiB and bounded transient buffers; live memory guard remains mandatory' if network_profile else 'visible frame 768000 + stdout/memory caps 2*524288 + Qt state 1048576 + controls 65536 = 2930688; rounded to 3MiB'),
        'state_scope':'run directory plus /tmp/pandanote-reader-cache' if network_profile else 'run directory',
        'run_guard':'sample tmpfs free/RAM/state usage every second; terminate this child if free<1MiB, MemAvailable<4MiB or state>'+str(runtime_budget//(1024*1024))+'MiB; app per-file cap '+str((NETWORK_APP_FILE_BLOCKS if network_profile else 512)*TARGET_FSIZE_UNIT_BYTES)+' bytes, monitor262144 bytes (measured target512-byte units); core disabled'}


def navigation_observation(records):
    navigation = [r for r in records if r.get('event') == 'NAVIGATION']
    return {'records': navigation, 'release_count': sum(x.get('source')=='release' for x in navigation),
            'idle_count':sum(x.get('source')=='idle' for x in navigation),
            'human_proof_accepted':False,
            'acceptance':'PENDING human observation and five entries/back plus actual 60-second idle review'}


def png_frame(raw):
    if len(raw) != 768000:
        raise ValueError('visible framebuffer must be exactly 768000 bytes RGB565')
    rows = bytearray()
    for y in range(480):
        rows.append(0)
        for x in range(800):
            pixel = struct.unpack_from('<H', raw, (y*800+x)*2)[0]
            rows.extend((((pixel>>11)&31)*255//31, ((pixel>>5)&63)*255//63, (pixel&31)*255//31))
    def chunk(kind, data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',800,480,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')


# Original runtime derivation remains unchanged: 2930688 rounded to 3MiB.
# Optional content must fit the unused rounding allowance, including filesystem
# allocation of each file and its new directory. Never increase the state cap.
PACKET_ALLOWANCE = 3*1024*1024 - 2930688


def capture_content_packet(directory):
    directory = Path(directory).absolute()
    if any(path.is_symlink() for path in [directory, *directory.parents]):
        raise ValueError('symlink content packet path')
    limits = {'content.ini':131072, 'background.png':2097152, 'SHA256SUMS':512}
    if not directory.is_dir() or {p.name for p in directory.iterdir()} != set(limits):
        raise ValueError('content packet must contain exactly three frozen-format files')
    captured = {}
    for name, limit in limits.items():
        file = safe_file(directory, name)
        if file.stat().st_size > limit:
            raise ValueError('content packet member exceeds frozen reader limit')
        captured[name] = file.read_bytes()
        if len(captured[name]) > limit:
            raise ValueError('captured content packet exceeds frozen reader limit')
    allocated = 4096 + sum(((len(data)+4095)//4096)*4096 for data in captured.values())
    if allocated > PACKET_ALLOWANCE:
        raise ValueError('content packet exceeds unused 3MiB runtime state allowance')
    hashes = {name:hashlib.sha256(data).hexdigest() for name,data in captured.items()}
    expected = ''.join(hashes[name]+'  '+name+'\n' for name in ('content.ini','background.png')).encode('ascii')
    if captured['SHA256SUMS'] != expected:
        raise ValueError('content packet captured hash manifest mismatch')
    return captured, {'bytes':sum(map(len,captured.values())), 'reserved_state_bytes':allocated,
                      'state_allowance_bytes':PACKET_ALLOWANCE, 'sha256':hashes}


def content_commands(state, captured):
    """Transfer only already captured buffers, never reopen their source paths."""
    commands = ['# CONTENT_PACKAGE\n'+B+'mkdir '+state+'/content']
    for name, data in captured.items():
        encoded = base64.b64encode(data).decode('ascii')
        for offset in range(0, len(encoded), 3000):
            # 3000 encoded bytes leave room for prefix/path and exit trailer.
            op = '>' if offset == 0 else '>>'
            commands.append(
                '# CONTENT_PACKAGE\n'+B+'printf %s '+encoded[offset:offset+3000]+
                ' | '+B+'base64 -d '+op+' '+state+'/content/'+name)
    assertions = [
        '[ "$('+B+'sha256sum '+state+'/content/'+name+
        ' | '+B+'cut -d " " -f1)" = '+hashlib.sha256(data).hexdigest()+' ]'
        for name,data in captured.items()]
    commands.append('# VERIFY_CONTENT\n'+' && '.join(assertions))
    for command in commands:
        wrap_shell(command)
    return commands


def application_command(state, *, opt_libraries=False):
    env = {'PATH':'/bin:/usr/bin','HOME':state+'/home','TMPDIR':state,'XDG_CACHE_HOME':state+'/cache',
        'XDG_CONFIG_HOME':state+'/config','LD_LIBRARY_PATH':TARGET+'/lib:/lib:/usr/lib',
        'QTDIR':TARGET+'/', 'QT_QWS_FONTDIR':TARGET+'/assets', 'QT_PLUGIN_PATH':state+'/empty-plugins',
        'POINTERCAL_FILE':state+'/pointercal', 'QWS_DISPLAY':'Transformed:Rot270:LinuxFb:mmWidth200:mmHeight120:0',
        'QWS_KEYBOARD':'none','QWS_MOUSE_PROTO':'evdevtouch:/dev/input/event0','QWS_NO_SHARE_FONTS':'1'}
    if opt_libraries:
        env['LD_LIBRARY_PATH']='/run/pandanote-opt/opt/image/opt/Qtopia/lib:/lib:/usr/lib'
    return B+'env -i '+' '.join(Q(k+'='+v) for k,v in env.items())+' '+TARGET+'/reader-shell.mipsel --qws-server'


def launch_command(state, timeout_ms, *, content=False, simulated_epoch=None, opt_libraries=False,network_profile=False):
    app = application_command(state,opt_libraries=opt_libraries)+' --developer-mode --developer-timeout-ms '+str(timeout_ms)
    if content:
        app += ' --content-dir '+Q(state+'/content')+' --developer-simulated-epoch '+str(simulated_epoch)
    state_command=B+'du -sk '+state+' | '+B+'cut -f1'
    if network_profile:
        state_command=B+'du -sk '+state+' /tmp/pandanote-reader-cache 2>/dev/null | '+B+"awk '{v+=$1} END {printf \"%.0f\",v}'"
    state_limit=NETWORK_RUNTIME_BUDGET//1024 if network_profile else 3072
    app_file_blocks=NETWORK_APP_FILE_BLOCKS if network_profile else 512
    # This supervisor owns only the child PID it starts. It never touches an
    # existing QWS/factory process. Values below are generated, not user paths.
    return f'''# BOUNDED_RUN
umask 077
( ulimit -c 0; ulimit -f {app_file_blocks}; exec {app} ) > {state}/stdout.txt 2>&1 & app_pid=$!
( /bin/busybox sleep {timeout_ms//1000+8}
  if /bin/busybox kill -0 "$app_pid" 2>/dev/null; then
    /bin/busybox echo HOST_WATCHDOG > {state}/watchdog.txt
    /bin/busybox kill "$app_pid"
  fi
) & guard_pid=$!
( ulimit -c 0; ulimit -f 512
  while /bin/busybox kill -0 "$app_pid" 2>/dev/null; do
    /bin/busybox printf "SAMPLE_UPTIME="; /bin/busybox cat /proc/uptime
    /bin/busybox grep -E "^(Name|Pid|VmRSS|VmPeak|VmSize):" /proc/"$app_pid"/status
    /bin/busybox grep -E "^(MemAvailable|MemFree|Shmem|CmaTotal|CmaFree):" /proc/meminfo
    free_kb=$(/bin/busybox df -Pk /tmp | /bin/busybox awk 'NR==2 {{print $4}}')
    ram_kb=$(/bin/busybox awk '/^MemAvailable:/ {{print $2}}' /proc/meminfo)
    state_kb=$({state_command})
    /bin/busybox printf "TMP_FREE_KIB=%s RAM_AVAILABLE_KIB=%s STATE_KIB=%s\\n" "$free_kb" "$ram_kb" "$state_kb"
    reason=
    case "$free_kb:$ram_kb:$state_kb" in
      *[!0-9:]*|:*|*::*|*:) reason=missing_resource_metrics ;;
      *) if [ "$free_kb" -lt 1024 ]; then reason=tmpfs_low
         elif [ "$ram_kb" -lt 4096 ]; then reason=ram_low
         elif [ "$state_kb" -gt {state_limit} ]; then reason=state_budget; fi ;;
    esac
    if [ -n "$reason" ]; then
      /bin/busybox echo "$reason" > {state}/resource-guard.txt
      /bin/busybox kill "$app_pid"; break
    fi
    /bin/busybox sleep 1
  done
) > {state}/memory.txt 2>&1 & monitor_pid=$!
( /bin/busybox sleep 1
  /bin/busybox dd if=/dev/fb0 of={state}/framebuffer.rgb565 bs=1600 count=480 2>{state}/frame-dd.txt
) & frame_pid=$!
wait "$app_pid"; app_status=$?
/bin/busybox kill "$guard_pid" "$monitor_pid" 2>/dev/null
wait "$guard_pid" 2>/dev/null; wait "$monitor_pid" 2>/dev/null
wait "$frame_pid"; frame_status=$?
/bin/busybox printf "PANDANOTE_APP_EXIT=%s\\nFRAME_EXIT=%s\\n" "$app_status" "$frame_status"
'''


def soak_monitor_budget():
    # Numeric-only line, eleven <=10-digit values, labels/newline <160B. Use
    # 512B conservatively; at most one sample/5s through the hard1808s stop.
    return {'sample_interval_seconds':5, 'maximum_samples':363,
            'maximum_line_bytes':512, 'worst_case_bytes':363*512,
            'limit_bytes':512*TARGET_FSIZE_UNIT_BYTES}


def soak_script(state):
    if not re.fullmatch(r'/tmp/reader-shell-run-[0-9T]+',state):
        raise ValueError('unsafe soak state path')
    # Separate private RAM script avoids weakening the legacy3808B wire ceiling.
    # Main shell waits for the critical monitor; every failed metric/write
    # terminates its owned app. Independent watchdog bounds a stuck monitor or TERM handler.
    return r'''#!/bin/sh
umask 077
cd @STATE@ || exit 1
b() { /bin/busybox "$@"; }
uptime_s() { IFS=' ' read -r clock rest < /proc/uptime || return 1; clock=${clock%%.*}; number "$clock" || return 1; printf '%s\n' "$clock"; }
number() { case "$1" in ''|*[!0-9]*) return 1;; esac; [ "${#1}" -le 10 ]; }
app_pid= frame_pid= guard_pid= stop_pid= monitor_pid=
child_wait() {
  /bin/busybox "$@" & owned=$!; wait "$owned"; code=$?; owned=; return "$code"
}
child_trap() {
  [ -z "$owned" ] || b kill -KILL "$owned" 2>/dev/null
  wait 2>/dev/null; exit 1
}
# Each measurement is one direct executable, never a pipeline/command substitution.
# Its live PID remains published until wait reaps it; the parent can also clean
# that exact leaf after an unexpected monitor death. No global process scans.
monitor_leaf() {
  output=$1; shift
  /bin/busybox "$@" > "$output" 2> metric-error.txt & owned=$!
  printf '%s\n' "$owned" > monitor-child.txt || return 1
  wait "$owned"; code=$?
  reaped=$((reaped+1)); printf 'REAPED=%s STATUS=%s COUNT=%s\n' "$owned" "$code" "$reaped" > monitor-reaped.txt
  owned=; : > monitor-child.txt
  return "$code"
}
monitor_trap() {
  if [ -n "$owned" ]; then
    kill -KILL "$owned" 2>/dev/null
    wait "$owned"; code=$?
    reaped=$((reaped+1)); printf 'REAPED=%s STATUS=%s COUNT=%s\n' "$owned" "$code" "$reaped" > monitor-reaped.txt
    owned=; : > monitor-child.txt
  fi
  exit 1
}
stop_monitor() {
  if [ -n "$monitor_pid" ]; then
    kill -TERM "$monitor_pid" 2>/dev/null
    for retry in 1 2; do
      kill -0 "$monitor_pid" 2>/dev/null || break
      b sleep 1
    done
    kill -KILL "$monitor_pid" 2>/dev/null
    wait "$monitor_pid" 2>/dev/null; monitor_pid=
  fi
  leaf=
  IFS= read -r leaf < monitor-child.txt || :
  if [ -n "$leaf" ]; then
    number "$leaf" && [ "$leaf" -gt 1 ] || { b echo monitor_cleanup_failed > resource-guard.txt; return 1; }
    kill -KILL "$leaf" 2>/dev/null
    for retry in 1 2; do
      kill -0 "$leaf" 2>/dev/null || break
      b sleep 1
    done
    if kill -0 "$leaf" 2>/dev/null; then
      b echo monitor_cleanup_failed > resource-guard.txt
      return 1
    fi
    printf 'ORPHAN_DISAPPEARED=%s\n' "$leaf" >> monitor-reaped.txt
    : > monitor-child.txt
  fi
  printf 'MONITOR_CLEANUP=verified\n' > monitor-cleanup.txt
}
cleanup() {
  [ -z "$app_pid" ] || b kill -KILL "$app_pid" 2>/dev/null
  stop_monitor
  for p in "$frame_pid" "$guard_pid" "$stop_pid"; do
    [ -z "$p" ] || b kill -TERM "$p" 2>/dev/null
  done
  wait 2>/dev/null
}
trap 'exit 1' HUP INT TERM
trap cleanup EXIT
( ulimit -c 0; ulimit -f 4096; exec @APP@ ) > stdout.txt 2>&1 & app_pid=$!
# Ceiling after child creation avoids losing a fractional second of lifetime.
start=$(uptime_s); number "$start" || exit 1; start=$((start+1))
deadline=$((start+1800)); next=$start
b printf 'START_UPTIME=%s\n' "$start" > controller.txt || exit 1
( ulimit -c 0; ulimit -f 1536
  owned=; trap child_trap HUP INT TERM
  child_wait sleep 10
  while b kill -0 "$app_pid" 2>/dev/null; do
    child_wait dd if=/dev/fb0 of=framebuffer.rgb565 bs=1600 count=480 2>frame-dd.txt || exit 1
    t=$(uptime_s); number "$t" || exit 1
    b printf 'FRAME_UPTIME=%s\n' "$t" >> frames.txt || exit 1
    child_wait sleep 300
  done
) & frame_pid=$!
controller_pid=$$
( timer=; trap '[ -z "$timer" ] || b kill "$timer" 2>/dev/null; wait "$timer" 2>/dev/null; exit' HUP INT TERM
  /bin/busybox sleep 1808 & timer=$!; wait "$timer"
  b echo HOST_WATCHDOG > watchdog.txt
  b kill -KILL "$app_pid" 2>/dev/null
  b kill -TERM "$frame_pid" 2>/dev/null
  b kill -TERM "$controller_pid"
) & guard_pid=$!
b printf '%s\n' "$((start-1))" > heartbeat.txt || exit 1
: > monitor-child.txt
# Only memory.txt inherits512 blocks; frame requires1536 to hold768000B.
( ulimit -c 0; ulimit -f 512
  owned=; reaped=0; trap monitor_trap HUP INT TERM
  trap 'status=$?; [ -z "$owned" ] || monitor_trap; exit "$status"' EXIT
  while b kill -0 "$app_pid" 2>/dev/null; do
    now=$(uptime_s); number "$now" || exit 1
    printf '%s\n' "$now" > heartbeat-next.txt || exit 1
    monitor_leaf metric-mv.txt mv heartbeat-next.txt heartbeat.txt || exit 1
    [ "$now" -ge $((start-1)) ] && [ "$now" -le $((start+1808)) ] || exit 1
    if [ "$now" -ge "$deadline" ]; then
      b printf 'STOP_UPTIME=%s\nCONTROL_STOP=term_at_deadline\n' "$now" >> controller.txt || exit 1
      b kill -TERM "$app_pid" || exit 1
      exit 0
    fi
    b kill -0 "$frame_pid" 2>/dev/null || exit 1
    monitor_leaf metric-df.txt df -Pk /tmp || exit 1
    monitor_leaf metric-free.txt awk 'NR==2 {v=$4} END {if(v=="" || v<0 || v>4294967295) exit 1; printf "%.0f\n",v}' metric-df.txt || exit 1
    IFS= read -r free_kb < metric-free.txt || exit 1
    monitor_leaf metric-ram.txt awk '/^MemAvailable:/ {v=$2} END {if(v=="" || v<0 || v>4294967295) exit 1; printf "%.0f\n",v}' /proc/meminfo || exit 1
    IFS= read -r ram_kb < metric-ram.txt || exit 1
    roots=1
    if [ -e /tmp/pandanote-reader-cache ] || [ -L /tmp/pandanote-reader-cache ]; then
      [ -d /tmp/pandanote-reader-cache ] && [ ! -L /tmp/pandanote-reader-cache ] || exit 1
      roots=2
      monitor_leaf metric-du.txt du -sk . /tmp/pandanote-reader-cache || exit 1
    else
      monitor_leaf metric-du.txt du -sk . || exit 1
    fi
    monitor_leaf metric-state.txt awk -v roots="$roots" 'NF!=2 || $1!~/^[0-9]+$/ || length($1)>10 || $1>4294967295 {bad=1} {if($2==".") a++; else if($2=="/tmp/pandanote-reader-cache") c++; else bad=1;v+=$1;n++} END {if(bad || a!=1 || c!=roots-1 || n!=roots || v>4294967295) exit 1; printf "%.0f\n",v}' metric-du.txt || exit 1
    IFS= read -r state_kb < metric-state.txt || exit 1
    number "$free_kb" && number "$ram_kb" && number "$state_kb" || exit 1
    [ "$free_kb" -ge 1024 ] && [ "$ram_kb" -ge 4096 ] && [ "$state_kb" -le 12288 ] || exit 1
    if [ "$now" -ge "$next" ]; then
      monitor_leaf metric-sample.txt awk '/^(VmRSS|VmPeak|VmSize|MemAvailable|MemFree|Shmem|CmaTotal|CmaFree):/ {if($2!~/^[0-9]+$/ || length($2)>10 || $2>4294967295) bad=1; a[$1]=$2;n++} END {if(bad||n!=8) exit 1; printf "RSS=%s Peak=%s Size=%s MemAvailable=%s MemFree=%s Shmem=%s CmaTotal=%s CmaFree=%s",a["VmRSS:"],a["VmPeak:"],a["VmSize:"],a["MemAvailable:"],a["MemFree:"],a["Shmem:"],a["CmaTotal:"],a["CmaFree:"]}' /proc/"$app_pid"/status /proc/meminfo || exit 1
      IFS= read -r metrics < metric-sample.txt || [ -n "$metrics" ] || exit 1
      b printf 't=%s %s tmp=%s state=%s\n' "$now" "$metrics" "$free_kb" "$state_kb" || exit 1
      next=$((now+5))
    fi
    monitor_leaf metric-sleep.txt sleep 1 || exit 1
  done
  exit 1
) > memory.txt 2>&1 & monitor_pid=$!
heartbeat_failure=
while b kill -0 "$monitor_pid" 2>/dev/null; do
  IFS= read -r beat < heartbeat.txt || beat=
  now=$(uptime_s)
  if ! number "$beat" || ! number "$now" || [ "$now" -lt "$beat" ] || [ "$((now-beat))" -gt 3 ]; then
    heartbeat_failure=1
    b echo monitor_heartbeat_failure > resource-guard.txt
    b kill -TERM "$app_pid" 2>/dev/null
    stop_monitor
    break
  fi
  b sleep 1
done
if [ -n "$monitor_pid" ]; then
  wait "$monitor_pid"; monitor_status=$?; monitor_pid=
else
  monitor_status=1
fi
stop_monitor || monitor_status=1
if [ "$monitor_status" != 0 ]; then
  [ -n "$heartbeat_failure" ] || b echo monitor_or_resource_failure > resource-guard.txt
  b kill -TERM "$app_pid" 2>/dev/null
fi
# A failing monitor cannot leave its app alive until the30-minute watchdog.
( owned=; trap child_trap HUP INT TERM; child_wait sleep 5; b echo STOP_ESCALATION > watchdog.txt; b kill -KILL "$app_pid" 2>/dev/null ) & stop_pid=$!
wait "$app_pid"; app_status=$?; app_pid=
b kill "$stop_pid" "$guard_pid" "$frame_pid" 2>/dev/null
wait "$stop_pid" 2>/dev/null; stop_pid=
wait "$guard_pid" 2>/dev/null; guard_pid=
wait "$frame_pid" 2>/dev/null; frame_pid=
end=$(uptime_s); number "$end" || exit 1
b printf 'END_UPTIME=%s\n' "$end" >> controller.txt || exit 1
frame_status=1
[ -s frames.txt ] && [ "$(b wc -c < framebuffer.rgb565)" -eq 768000 ] && frame_status=0
b printf 'PANDANOTE_APP_EXIT=%s\nFRAME_EXIT=%s\n' "$app_status" "$frame_status"
'''.replace('@STATE@',Q(state)).replace('@APP@',application_command(state,opt_libraries=True))


def soak_commands(state):
    data=soak_script(state).encode()
    commands=[]
    for offset in range(0,len(data),1800):
        encoded=base64.b64encode(data[offset:offset+1800]).decode()
        commands.append('# SOAK_SCRIPT\n'+B+'printf %s '+Q(encoded)+' | '+B+'base64 -d '+('>' if offset==0 else '>>')+' '+state+'/soak-controller.sh')
    commands.append('# VERIFY_SOAK_SCRIPT\n[ "$('+B+'sha256sum '+state+'/soak-controller.sh | '+B+'cut -d " " -f1)" = '+Q(hashlib.sha256(data).hexdigest())+' ]')
    for command in commands:
        wrap_shell(command)
    return commands


def soak_launch_command(state):
    soak_script(state)  # same strict owned path grammar as the script writer
    return '# SOAK_RUN_SECONDS=1800\n/bin/busybox sh '+state+'/soak-controller.sh'


def validate_soak(control,trailer,events,memory,frames,watchdog):
    match=re.fullmatch(r'START_UPTIME=(\d{1,10})\nSTOP_UPTIME=(\d{1,10})\nCONTROL_STOP=term_at_deadline\nEND_UPTIME=(\d{1,10})\n',control)
    if not match or watchdog or trailer.strip()!='PANDANOTE_APP_EXIT=143\nFRAME_EXIT=0' or any(r.get('event')=='EXIT_REASON' for r in events):
        raise ValueError('soak missing exact controlled SIGTERM stop, native crashed/exited, frame failed or watchdog intervened')
    start,stop,end=map(int,match.groups())
    sample_pattern=r't=(\d{1,10}) RSS=\d{1,10} Peak=\d{1,10} Size=\d{1,10} MemAvailable=\d{1,10} MemFree=\d{1,10} Shmem=\d{1,10} CmaTotal=\d{1,10} CmaFree=\d{1,10} tmp=\d{1,10} state=\d{1,10}'
    lines=memory.splitlines()
    if (not lines or len(memory.encode())>soak_monitor_budget()['worst_case_bytes'] or
            len(lines)>363 or any(not re.fullmatch(sample_pattern,line) for line in lines)):
        raise ValueError('soak invalid/missing bounded monitor samples')
    times=[int(line.split(' ',1)[0][2:]) for line in lines]
    frame_lines=frames.splitlines()
    if not frame_lines or any(not re.fullmatch(r'FRAME_UPTIME=\d{1,10}',line) for line in frame_lines):
        raise ValueError('soak invalid/missing frame timeline')
    captures=[int(line.split('=')[1]) for line in frame_lines]
    if not (1800<=stop-start<=1803 and stop<=end<=start+1808 and
            len(times)>=300 and start<=times[0]<=start+3 and 0<=stop-times[-1]<=7 and
            all(5<=b-a<=7 for a,b in zip(times,times[1:])) and
            6<=len(captures)<=7 and start+8<=captures[0]<=start+20 and 0<=stop-captures[-1]<=310 and
            all(300<=b-a<=310 for a,b in zip(captures,captures[1:]))):
        raise ValueError('soak missing full1800s lifetime, continuous samples or meaningful frames')
    return {'requested_seconds':1800,'measured_seconds':stop-start,'start_uptime':start,'stop_uptime':stop,'end_uptime':end,
            'sample_count':len(times),'frame_uptimes':captures,'termination':'intentional_controller_SIGTERM',
            'normal_native_exit':False,'monitor_budget':soak_monitor_budget(),
            'event_boundary_accepted':False,'network_sync_accepted':False}


def collect_command(state, *, soak=False):
    cmd = '# COLLECT\n'
    for key, file in [('stdout','stdout.txt'), ('rss','memory.txt'),('frame','framebuffer.rgb565'),('dd','frame-dd.txt'),('guard','resource-guard.txt')]:
        cmd += B+'printf "'+key+'="; if [ -f '+state+'/'+file+' ]; then '+B+'base64 '+state+'/'+file+' | '+B+'tr -d "\\n"; fi; '+B+'printf "\\n"; '
    if soak:
        for key,file in [('control','controller.txt'),('frames','frames.txt'),('cleanup','monitor-cleanup.txt'),('reaped','monitor-reaped.txt')]:
            cmd += B+'printf "'+key+'="; if [ -f '+state+'/'+file+' ]; then '+B+'base64 '+state+'/'+file+' | '+B+'tr -d "\\n"; fi; '+B+'printf "\\n"; '
    cmd += 'if [ -f '+state+'/watchdog.txt ]; then /bin/busybox echo WATCHDOG; fi'
    return cmd


def execute(adb, build, source, evidence, run=False, timeout_ms=120000, *, content_package=None, simulated_epoch=None,
            profile=LEGACY_PROFILE,opt_libraries=False,run_soak=False):
    if run_soak and (run or profile!=NETWORK_PROFILE or not opt_libraries or content_package is not None or simulated_epoch is not None or timeout_ms!=120000):
        raise ValueError('soak requires its separate fixed1800s entry, network profile, opt libraries and ordinary mode')
    authorized_run=run or run_soak
    if profile not in (LEGACY_PROFILE,NETWORK_PROFILE) or (opt_libraries and profile!=NETWORK_PROFILE):
        raise ValueError('Unknown or mixed runtime profile/library selection')
    if (content_package is None) != (simulated_epoch is None):
        raise ValueError('content package and explicit development time must be supplied together')
    if simulated_epoch is not None and (type(simulated_epoch) is not int or not 946684800 <= simulated_epoch < 4133980800):
        raise ValueError('invalid explicit SIMULATED development time')
    if not 2000 <= timeout_ms <= 300000:
        raise ValueError('bounded timeout must be 2000..300000 ms')
    report = {'time':datetime.datetime.now().astimezone().isoformat(), 'serial':preflight.SERIAL,
        'adb_port':getattr(adb,'port',5039),'mode':'monitored_soak' if run_soak else ('bounded_test' if run else 'check_only'),'copied_to_device':False,'app_executed':False,
        'physical_navigation_accepted':False,'physical_display_accepted':False,'persistently_installed':False,
        'manifest_sha256':REVIEWED_MANIFEST_SHA,'runtime_profile':profile,'opt_libraries':opt_libraries,'protections':{}}
    private_evidence=content_package is not None or profile==NETWORK_PROFILE
    evidence.mkdir(parents=True, exist_ok=False, mode=0o700 if private_evidence else 0o755)
    try:
        captured = None
        if content_package is not None:
            captured, packet_info = capture_content_packet(content_package)
            report['content_package'] = packet_info
            report['development_time'] = {'source':'SIMULATED', 'epoch':simulated_epoch, 'production_authenticated_clock':False}
            snapshot = evidence/'content-snapshot'
            snapshot.mkdir(mode=0o700)
            for name, data in captured.items():
                file = snapshot/name
                file.write_bytes(data)
                file.chmod(0o600)
        manifest, files, records = verify_release(build, source)
        report['protections']['before'] = protection(adb,profile,opt_libraries=opt_libraries)
        checks = {key: adb.shell(cmd) for key, cmd in EXTRA_COMMANDS.items()}
        report['checks'] = checks
        checks, payload, reuse, capacity = inspect(adb, manifest, files, records, checks,opt_libraries=opt_libraries,network_profile=profile==NETWORK_PROFILE)
        report.update(capacity=capacity, reused_verified_payload=reuse)
        payload_hashes = {name:records[name]['sha256'] for name in payload}
        verify_batches = verification_commands(payload_hashes)
        report['verification_batches_wrapped_utf8'] = [len(wrap_shell(cmd).encode('utf-8')) for cmd in verify_batches]
        verify_payload(payload, records, build)
        memory = report['protections']['before']['diagnostics']['memory']
        available = re.search(r'^MemAvailable:\s+(\d+) kB$', memory, re.M)
        needed = (0 if reuse else capacity['payload_bytes']) + capacity['ordinary_ram_reserve_bytes']
        if not available or int(available[1])*1024 < needed:
            raise ValueError('insufficient verified available RAM')
        report['status'] = 'check_only_passed'
        if not authorized_run:
            return report
        # Recheck protection immediately before the first authorized mutation.
        report['protections']['before_transfer'] = protection(adb,profile,opt_libraries=opt_libraries)
        report['before_transfer_exclusive'] = adb.shell(EXTRA_COMMANDS['exclusive'])
        validate_exclusive(report['before_transfer_exclusive'])
        verify_payload(payload, records, build)
        if not reuse:
            dirs = sorted({str(PurePosixPath(name).parent) for name in payload if '/' in name})
            report['remote_mutation_requested'] = True
            adb.shell('# STAGE_FILES\n'+B+'mkdir '+TARGET+' && '+B+'mkdir -p '+' '.join(Q(TARGET+'/'+x) for x in dirs))
            for name, file in payload.items():
                transfer = adb.run(['push','-Z',str(file),TARGET+'/'+name], timeout=30)
                if transfer.returncode:
                    raise RuntimeError('transfer failed; no automatic retry: '+transfer.stderr.strip())
                report['copied_to_device'] = True
        for verify in verify_batches:
            adb.shell(verify)
        state = '/tmp/reader-shell-run-'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f')
        report['runtime_state_directory'] = state
        setup = '# RUNTIME_STATE\numask 077\n'+B+'mkdir -m 0700 '+state+' && '+B+'mkdir '+state+'/home '+state+'/home/Settings '+state+'/cache '+state+'/config '+state+'/empty-plugins && '+\
            B+'printf "4498 18 -817313 -41 2747 -763357 35540\\n" > '+state+'/pointercal && '+\
            B+'printf "[global]\\npoint_need_tramsform=false\\ntouchpad=true\\n" > '+state+'/home/Settings/minimalview.ini && '+\
            B+'chmod 0700 '+TARGET+'/reader-shell.mipsel'
        report['remote_mutation_requested'] = True
        adb.shell(setup)
        if captured is not None:
            for transfer in content_commands(state, captured):
                adb.shell(transfer)
        if run_soak:
            (evidence/'soak-controller.sh').write_text(soak_script(state))
            for transfer in soak_commands(state):
                adb.shell(transfer)
        command = (soak_launch_command(state) if run_soak else launch_command(state, timeout_ms, content=captured is not None, simulated_epoch=simulated_epoch,opt_libraries=opt_libraries,network_profile=profile==NETWORK_PROFILE))
        wrap_shell(command)
        (evidence/'launch-command.txt').write_text(command+'\n')
        report['app_execution_requested'] = True
        try:
            report['exit_trailer'] = adb.shell(command)
            report['app_executed'] = True
        except Exception as error:
            if not run_soak:
                raise
            report['launch_error']=str(error)
            report['exit_trailer']=''
            # Preserve private controller/resource/frame diagnostics even when
            # its hard watchdog exits without a successful transport trailer.
        encoded = adb.shell(collect_command(state,soak=run_soak))
        fields = dict(line.split('=',1) for line in encoded.splitlines() if '=' in line)
        report['resource_guard'] = base64.b64decode(fields['guard'],validate=True).decode()
        if run_soak:
            for key,file in [('control','controller.txt'),('frames','frames.txt'),('cleanup','monitor-cleanup.txt'),('reaped','monitor-reaped.txt')]:
                (evidence/file).write_bytes(base64.b64decode(fields.get(key,''),validate=True))
        logs = base64.b64decode(fields['stdout'], validate=True).decode('utf-8',errors='replace')
        (evidence/'stdout.txt').write_text(logs)
        (evidence/'memory.txt').write_bytes(base64.b64decode(fields['rss'],validate=True))
        (evidence/'frame-dd.txt').write_bytes(base64.b64decode(fields['dd'],validate=True))
        raw = base64.b64decode(fields['frame'],validate=True)
        (evidence/'framebuffer.rgb565').write_bytes(raw)
        if report.get('launch_error'):
            raise RuntimeError(report['launch_error'])
        (evidence/'framebuffer.png').write_bytes(png_frame(raw))
        records = [json.loads(line) for line in logs.splitlines() if line.startswith('{')]
        report['navigation_observation'] = navigation_observation(records)
        report['framebuffer'] = {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(), 'format':'800x480 little-endian RGB565 stride1600, visible single frame', 'capture':'1 second after launch; actual display still requires human observation'}
        if report['resource_guard']:
            raise ValueError('resource guard stopped this run: '+report['resource_guard'])
        if run_soak:
            control=(evidence/'controller.txt').read_text()
            frames=(evidence/'frames.txt').read_text()
            if (evidence/'monitor-cleanup.txt').read_text()!='MONITOR_CLEANUP=verified\n':
                raise ValueError('soak monitor cleanup not verified')
            report['soak']=validate_soak(control,report['exit_trailer'],records,(evidence/'memory.txt').read_text(),frames,'WATCHDOG' in encoded)
            report['framebuffer']['capture']='overwritten owned visible frame at10s then every300s; physical ink observation required'
            report['status']='soak_controlled_stop_verified'
            return report
        exits = [x for x in records if x.get('event')=='EXIT_REASON']
        if exits != [{'event':'EXIT_REASON','reason':'developer_timeout','code':0}] or 'WATCHDOG' in encoded or report['exit_trailer'].strip() != 'PANDANOTE_APP_EXIT=0\nFRAME_EXIT=0':
            raise ValueError('missing successful developer_timeout exit or watchdog intervened')
        report['status'] = 'bounded_timeout_verified'
        return report
    except Exception as error:
        report.update(status='stopped', error=str(error))
        raise
    finally:
        if authorized_run and report.get('remote_mutation_requested'):
            try:
                report['protections']['after'] = protection(adb,profile,opt_libraries=opt_libraries)
            except Exception as error:
                report.update(status='stopped',after_protection_error=str(error))
        report['evidence_files'] = {str(p.relative_to(evidence)):sha(p) for p in sorted(evidence.iterdir()) if p.is_file() and p.name!='report.json'}
        (evidence/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        if private_evidence:
            for file in evidence.rglob('*'):
                if file.is_file():
                    file.chmod(0o600)
        if report.get('after_protection_error'):
            raise RuntimeError('after-run protection verification failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-only', action='store_true')
    mode.add_argument('--run-bounded-test', action='store_true')
    mode.add_argument('--run-soak-test', action='store_true',help='Explicit fixed1800s ordinary native run; requires network profile and opt libraries')
    parser.add_argument('--timeout-ms',type=int,default=120000)
    parser.add_argument('--adb-port',type=int,choices=(5037,5039),default=5039,
                        help='Explicit existing localhost server; no automatic fallback or start')
    parser.add_argument('--content-package', type=Path, help='Explicit frozen-format packet for development RAM test only')
    parser.add_argument('--developer-simulated-epoch', type=int, help='Explicit SIMULATED development UTC seed; requires content package')
    parser.add_argument('--runtime-profile',choices=(LEGACY_PROFILE,NETWORK_PROFILE),default=LEGACY_PROFILE)
    parser.add_argument('--opt-libraries',action='store_true',help='Check already-mounted exact read-only p5 libraries; never mounts automatically')
    args = parser.parse_args()
    private_evidence=args.content_package is not None or args.runtime_profile==NETWORK_PROFILE
    evidence_root = ROOT/'evidence/raw' if private_evidence else ROOT/'evidence'
    if private_evidence:
        evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        evidence_root.chmod(0o700)
    evidence = evidence_root/('ram-'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f'))
    try:
        result = execute(ExistingAdb(args.adb_port), ROOT/'build', ROOT, evidence, run=args.run_bounded_test,timeout_ms=args.timeout_ms,
                         content_package=args.content_package, simulated_epoch=args.developer_simulated_epoch,
                         profile=args.runtime_profile,opt_libraries=args.opt_libraries,run_soak=args.run_soak_test)
        print(json.dumps({'status':result['status'],'evidence':str(evidence.relative_to(PROJECT)),
                          'physical_acceptance':'PENDING','persistently_installed':False},indent=2))
        return 0
    except Exception as error:
        print('STOPPED: '+str(error)+'; evidence='+str(evidence.relative_to(PROJECT)))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
