#!/usr/bin/env python3
"""Compile only in trusted SDK; execute only in verified disposable offline image.

No USB, hardware, mounts, network or original build-path writes. Task 3 extends
this focused runner. Every invocation preserves unique gate/build/run evidence.
"""
import base64,datetime,hashlib,json,os,shutil,subprocess,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT.parents[1]
REFERENCE=Path(os.environ.get('PANDANOTE_REFERENCE_ROOT', str(PROJECT)))
ANALYSIS=REFERENCE/'pandanote-analysis'
MINIMAL=ANALYSIS/'app-development-research/minimal-qt'
LIB='/work/pandanote/app-development-research/qt-stock-sysroot'
HEADERS='/work/pandanote/app-development-research/minimal-qt/include'
WORK=os.environ.get('PANDANOTE_COMPILER_WORK','/work/pandanote-native-completion')
if not WORK.startswith('/work/pandanote-') or '..' in WORK: raise RuntimeError('unsafe compiler work directory')
CONTAINER='pandanote-mips-dev'
BASE_TAG='pandanote-qt-graphics-master:20261020'
BASE='sha256:20ecae4195e6336bf3453516a52af3ba33fecd3052332d6094399a0a354e6cb0'
COMMANDS=[]


def run(args,**kw):
    result=subprocess.run([str(a) for a in args],capture_output=True,text=True,**kw)
    COMMANDS.append(dict(argv=[str(a) for a in args],returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
    if result.returncode: raise RuntimeError(result.stderr or result.stdout or str(args))
    return result.stdout

def inside(args): return run(['docker','exec','-w',WORK,CONTAINER,*args])
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def build(evidence, sources=None, target_name="content", support_files=None):
    sources = list(sources or ["content.cpp", "tests/content_cases.cpp"])
    ota_worker = target_name == "ota-worker"
    if "shell.cpp" in sources and "ota_ui.cpp" not in sources:sources += ["ota_ui.cpp","ota/json.cpp","ota/storage.cpp"]
    runtime = "main.cpp" in sources or "main.cpp" in (support_files or [])
    production_clock = target_name == "reader-shell" and "main.cpp" in sources
    if runtime:
        sources += ["systemclock.cpp", "systemclock_posix.cpp" if production_clock else "tests/systemclock_fixture.cpp"]
    if 'shell.cpp' in sources and 'systemui.cpp' not in sources:sources.append('systemui.cpp')
    if 'shell.cpp' in sources:sources += [x for x in ['einkrefresh.cpp','einkrefresh_posix.cpp','powerkeys.cpp','powerkeys_posix.cpp','powerrequest.cpp','battery.cpp','battery_posix.cpp'] if x not in sources]
    if 'shell.cpp' in sources and 'localapps.cpp' not in sources:sources.append('localapps.cpp')
    if 'shell.cpp' in sources and 'bluetooth.cpp' not in sources:sources.append('bluetooth.cpp')
    if 'shell.cpp' in sources and 'bluetooth_ui.cpp' not in sources:sources.append('bluetooth_ui.cpp')
    with_tls="sync.cpp" in sources or "tls.cpp" in sources
    if with_tls and "tls.cpp" not in sources:sources.append("tls.cpp")
    if with_tls:sources += [x for x in ["resolver.cpp","tlsclock.cpp","dnsconfig.cpp"] if x not in sources]
    if with_tls:
        tls=json.loads((ROOT/'build/tls-provenance.json').read_text())
        if tls['configSha256']!=sha(ROOT/'third_party/mbedtls/pandanote_config.h') or tls['librarySha256']!=sha(ROOT/'build/libpandanote-tls.a'):raise RuntimeError('TLS source/config/library provenance changed')
        if run(['docker','exec',CONTAINER,'sha256sum',WORK+'/tls/libpandanote-tls.a']).split()[0]!=tls['librarySha256']:raise RuntimeError('compiler TLS archive changed')
    # Verify retained library inputs and fixed Qt revision, without modifying them.
    qt=ANALYSIS/'qt-sdk-source/qt-4.7.4'
    if run(['git','-C',qt,'rev-parse','HEAD']).strip()!='092cd760d5fddf9640a310214fe01929f0fff3a8': raise RuntimeError('Qt source revision changed')
    stock=ANALYSIS/'app-development-research/qt-stock-sysroot'
    for item in json.loads((stock/'original-library-provenance.json').read_text()):
        if sha(stock/item['name'])!=item['sha256']: raise RuntimeError('Stock library hash changed: '+item['name'])
        # Check the existing compiler-side inputs too; never overwrite baseline paths.
        actual=run(['docker','exec',CONTAINER,'sha256sum',LIB+'/'+item['name']]).split()[0]
        if actual!=item['sha256']: raise RuntimeError('Compiler-side stock library changed')
    for name,expected in json.loads((ROOT/'third_party/sha256/provenance.json').read_text())['sha256'].items():
        if sha(ROOT/'third_party/sha256'/name)!=expected: raise RuntimeError('Vendored SHA256 source changed')
    run(['docker','exec',CONTAINER,'mkdir','-p',WORK+'/tests',WORK+'/build-support',WORK+'/ota',WORK+'/third_party/sha256',WORK+'/build'])
    for name in list(dict.fromkeys(['content.h','navigation.h','shell.h','sync.h','tls.h','resolver.h','tlsclock.h','dnsconfig.h','localapps.h','bluetooth.h','systemclock.h','startupretry.h','standbypolicy.h'] if target_name!='content' else ['content.h'])) + list(sources) + list(support_files or []) + ['build-support/start.S','build-support/entry.h','build-support/csu.cpp','build-support/libio-init.c','build-support/qws-cursor.h','einkrefresh.h','powerkeys.h','powerrequest.h','battery.h','ota/core.h','ota/device.h','build-support/qws-display-lock.h','third_party/sha256/sha256.c','third_party/sha256/sha256.h']:
        run(['docker','cp',ROOT/name,CONTAINER+':'+WORK+'/'+name])
    abi=['-EL','-march=mips32r2','-mabi=32','-mhard-float','-mfp64','-mnan=2008','-fPIC']
    cxx=['mipsel-linux-gnu-g++','-std=c++98','-O2','-fno-exceptions','-fno-rtti','-ffunction-sections','-fdata-sections',*abi,'-I'+HEADERS,'-isystem','/usr/mipsisa32r6el-linux-gnu/include']
    if with_tls:cxx += ['-I'+WORK+'/tls/source/include','-I'+WORK+'/tls','-DMBEDTLS_CONFIG_FILE="pandanote_config.h"']
    objects=[(source,Path(source).stem) for source in sources]+[('build-support/csu.cpp','csu')]
    for source,obj in objects:
        inside(cxx+['-c',source,'-o','build/'+obj+'.o'])
    for source,obj in [('build-support/start.S','start'),('build-support/libio-init.c','libio-init'),('third_party/sha256/sha256.c','sha256')]:
        inside(['mipsel-linux-gnu-gcc',*abi,'-Ibuild-support','-isystem','/usr/mipsisa32r6el-linux-gnu/include','-c',source,'-o','build/'+obj+'.o'])
    target='build/'+target_name+'.mipsel'
    inside(['mipsel-linux-gnu-ld','-EL','-m','elf32ltsmip','-e','__start','--dynamic-linker','/lib/ld-linux-mipsn8.so.1','-rpath-link',LIB,'-L',LIB,'--no-allow-shlib-undefined','-z','noexecstack','-z','relro','-z','now','--gc-sections',*[('build/'+x+'.o') for x in ['start']+[obj for source,obj in objects]+['libio-init','sha256']],*([WORK+'/tls/libpandanote-tls.a'] if with_tls else []),* ([] if ota_worker else ['-l:libQtGui.so.4']),'-l:libQtCore.so.4','-l:libstdc++.so.6','-l:libgcc_s.so.1','-l:libc.so.6','-o',target])
    elf=inside(['mipsel-linux-gnu-readelf','-h','-l','-A',target]);dynamic=inside(['mipsel-linux-gnu-readelf','-d','-V',target]);symbols=inside(['mipsel-linux-gnu-readelf','--dyn-syms','--wide',target])
    for marker in ['ELF32','little endian','mips32r2','nan2008','o32','/lib/ld-linux-mipsn8.so.1','Hard float (32-bit CPU, 64-bit FPU)']:
        if marker not in elf: raise RuntimeError('ABI missing '+marker)
    for forbidden in ['system','popen','execve','execvp','settimeofday','clock_settime','stime']:
        if forbidden=='clock_settime' and production_clock:continue
        if forbidden=='execve' and with_tls:continue # resolver child execs this verified ELF only
        if any(line.split()[-1].split('@')[0]==forbidden for line in symbols.splitlines() if ' UND ' in line): raise RuntimeError('Forbidden imported symbol: '+forbidden)
    if ota_worker and 'libQtGui' in dynamic:raise RuntimeError('OTA worker must not link QtGui')
    if 'GLIBC_2.34' in dynamic or '(INIT_ARRAY)' in dynamic or '(FINI_ARRAY)' in dynamic: raise RuntimeError('Unsupported startup/runtime ABI')
    if not any('GLOBAL' in line and 'OBJECT' in line and line.split()[-1]=='_IO_stdin_used' for line in symbols.splitlines()): raise RuntimeError('Missing modern glibc stdio marker')
    (evidence/(target_name+'-elf.txt')).write_text(elf+dynamic+symbols)
    binary=evidence/(target_name+'.mipsel');run(['docker','cp',CONTAINER+':'+WORK+'/'+target,binary]);binary.chmod(0o600)
    return binary

def execute(binary,evidence):
    # Snapshot is retained read-only outside this worktree. Verify bytes before any sample start.
    snapshot_root=ANALYSIS/'app-development-research/ram-linux-research'
    snapshot=json.loads((snapshot_root/'offline-snapshot.json').read_text());saved=snapshot_root/snapshot['file']
    if saved.stat().st_size!=snapshot['bytes'] or sha(saved)!=snapshot['sha256']: raise RuntimeError('Preserved offline snapshot hash failed')
    image_id=run(['docker','image','inspect',BASE_TAG,'--format','{{.Id}}']).strip()
    if image_id!=BASE: raise RuntimeError('Offline base image mismatch')
    context=evidence/'image';context.mkdir();shutil.copyfile(binary,context/'content.mipsel');shutil.copyfile(ROOT/('tests/offline_dnsconfig.py' if binary.stem=='dnsconfig' else 'tests/offline_tls.py' if binary.stem=='tls' else 'tests/offline_device.py' if binary.stem=='device' else 'tests/offline_runtime.py' if binary.stem=='runtime' else 'tests/offline_bluetooth.py' if binary.stem=='bluetooth' else 'tests/offline_navigation.py' if binary.stem in ('navigation','bluetooth') else 'tests/offline_content.py'),context/'offline_content.py');shutil.copytree(PROJECT/'apps/shared/fixtures',context/'fixtures',symlinks=True)
    if binary.stem=='tls':
        shutil.copytree(ROOT/'tests/tls-fixtures',context/'fixtures',dirs_exist_ok=True)
    if binary.stem=='device':
        shutil.copytree(ROOT/'tests/device-fixtures',context/'fixtures',dirs_exist_ok=True)
    extra_copy=''
    if binary.stem in ('navigation','bluetooth'):
        shutil.copyfile(evidence/'shell.mipsel',context/'shell.mipsel')
        shutil.copytree(ROOT/'assets',context/'assets')
        extra_copy='COPY --chmod=0555 shell.mipsel /content-test/shell.mipsel\nCOPY assets /content-test/assets\n'
    if binary.stem=='dnsconfig':
        dns_dir=ROOT/'evidence/raw/cloud-dns-libs'
        expected={'libnss_dns-2.29.so':'0dd2b7cf336cf3e8ab9864e2a38b6370359f623cdb8debd8813670283edab89d','libnss_files-2.29.so':'b9ac1c1ad2b34e971e8b0b5e487e40cde1123a5976922bd3427b8e233bf2a49a','libresolv-2.29.so':'113935359a9992558435a66142acbe2988915fc4f701af4147b716db3089c1c0'}
        for name,digest in expected.items():
            if sha(dns_dir/name)!=digest:raise RuntimeError('stock DNS library hash changed: '+name)
            destination={'libnss_dns-2.29.so':'libnss_dns.so.2','libnss_files-2.29.so':'libnss_files.so.2','libresolv-2.29.so':'libresolv.so.2'}[name]
            shutil.copyfile(dns_dir/name,context/destination)
            extra_copy+='COPY --chmod=0444 '+destination+' /sample-qt/sysroot/lib/'+destination+'\n'
        (context/'nsswitch.conf').write_text('hosts: files dns\n')
        (context/'resolv.conf').write_text('nameserver 192.0.2.250\n')
        extra_copy+='COPY --chmod=0444 nsswitch.conf /sample-qt/sysroot/etc/nsswitch.conf\nCOPY --chmod=0444 resolv.conf /sample-qt/sysroot/etc/resolv.conf\n'
    if binary.stem=='runtime':
        shutil.copytree(ROOT/'tests/device-fixtures',context/'fixtures',dirs_exist_ok=True)
        shutil.copyfile(evidence/'reader-shell.mipsel',context/'reader-shell.mipsel')
        shutil.copytree(ROOT/'assets',context/'assets')
        extra_copy='COPY --chmod=0555 reader-shell.mipsel /content-test/reader-shell.mipsel\nCOPY assets /content-test/assets\n'
        shutil.copyfile(ROOT/'tests/tls-fixtures/server.crt',context/'test.crt')
        extra_copy+='USER 0:0\nRUN mkdir -p /user/pandanote/config && chmod 0755 /user && chown 65534:65534 /user/pandanote /user/pandanote/config && chmod 0700 /user/pandanote /user/pandanote/config\nCOPY --chown=65534:65534 --chmod=0600 test.crt /user/pandanote/config/test.crt\n'
    (context/'Dockerfile').write_text('FROM '+BASE_TAG+'\n'+extra_copy+'COPY --chmod=0555 content.mipsel /content-test/content.mipsel\nCOPY --chmod=0444 offline_content.py /content-test/offline_content.py\nCOPY fixtures /content-test/fixtures\nUSER 65534:65534\nWORKDIR /tmp\nENTRYPOINT ["/usr/bin/timeout","30","/usr/bin/python3","/content-test/offline_content.py"]\n')
    tag='pandanote-content:'+evidence.name
    run(['docker','build','--network','none','--pull=false','-t',tag,context],timeout=60)
    image=run(['docker','image','inspect',tag,'--format','{{.Id}}']).strip()
    base_layers=json.loads(run(['docker','image','inspect',BASE,'--format','{{json .RootFS.Layers}}']))
    derived_layers=json.loads(run(['docker','image','inspect',image,'--format','{{json .RootFS.Layers}}']))
    if derived_layers[:len(base_layers)]!=base_layers: raise RuntimeError('Offline derived image has unexpected base layers')
    command=['docker','create','--name','pandanote-content-'+evidence.name,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--pids-limit','32','--memory','512m','--cpus','1','--ulimit','core=0','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777','--env','PANDANOTE_OFFLINE_GUARD_TEST=1',image]
    container=run(command).strip();before=json.loads(run(['docker','inspect',container]))[0];host=before['HostConfig'];config=before['Config']
    if not (host['NetworkMode']=='none' and host['ReadonlyRootfs'] and host['CapDrop']==['ALL'] and not host['Devices'] and not before['Mounts'] and not host.get('Binds') and not host.get('PortBindings') and config['User']=='65534:65534' and 'no-new-privileges' in host['SecurityOpt'] and not host['Privileged'] and host['PidsLimit']==32 and host['Memory']==512*1024*1024): raise RuntimeError('Isolation gates failed; container not started')
    (evidence/'pre-run.json').write_text(json.dumps(dict(checked_at=datetime.datetime.now().astimezone().isoformat(),image=image,container=container,args=command,inspect=before,baseline_snapshot=snapshot,baseline_path=str(saved),baseline_sha256_verified=True,binary_sha256=sha(binary),additional_samples_sha256=({'shell.mipsel':sha(evidence/'shell.mipsel')} if binary.stem in ('navigation','bluetooth') else {'reader-shell.mipsel':sha(evidence/'reader-shell.mipsel')} if binary.stem=='runtime' else {}),font_provenance_sha256=(sha(ROOT/'assets/font-provenance.json') if binary.stem in ('navigation','bluetooth','runtime') else None)),indent=2)+'\n')
    # Retain a fresh complete derived-image snapshot before any sample entry.
    snapshot_path=evidence/'pre-run-image.tar'
    run(['docker','image','save','-o',snapshot_path,image],timeout=60)
    (evidence/'pre-run-image.json').write_text(json.dumps(dict(file=snapshot_path.name,bytes=snapshot_path.stat().st_size,sha256=sha(snapshot_path),image=image),indent=2)+'\n')
    try: result=subprocess.run(['docker','start','-a',container],capture_output=True,timeout=35)
    except subprocess.TimeoutExpired:
        run(['docker','stop','-t','1',container]);raise
    (evidence/'stdout.txt').write_bytes(result.stdout);(evidence/'stderr.txt').write_bytes(result.stderr)
    after=json.loads(run(['docker','inspect',container]))[0];exit_code=after['State']['ExitCode']
    (evidence/'result.json').write_text(json.dumps(dict(exit_code=exit_code,finished_at=after['State']['FinishedAt'],hardware_access=False,reader_execution=False),indent=2)+'\n')
    for line in result.stdout.decode(errors='replace').splitlines():
        if line.startswith('PANDANOTE_FRAME_BASE64='):
            name,data=line.split('=',1)[1].split(':',1)
            if not name.replace('-','').isalnum(): raise RuntimeError('invalid frame name')
            (evidence/(name+'.png')).write_bytes(base64.b64decode(data,validate=True))
        elif line.startswith('PANDANOTE_TRACE_BASE64='):
            (evidence/'syscalls.txt').write_bytes(base64.b64decode(line.split('=',1)[1],validate=True))
        else: print(line)
    print(result.stderr.decode(errors='replace'),end='')
    return exit_code

def main():
    if sys.argv[1:]==['offline']:
        from check_offline import main as offline_main
        return offline_main()
    if sys.argv[1:]==['navigation']:
        from run_navigation import main as navigation_main
        return navigation_main()
    if sys.argv[1:]!=['content']: raise SystemExit('usage: run.py content|navigation|offline')
    evidence=ROOT/'build'/('content-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'));evidence.mkdir(parents=True)
    try:
        missing=[name for name in ('content.h','content.cpp') if not (ROOT/name).is_file()]
        if missing: print('FAIL content contract missing: '+', '.join(missing));return 1
        return execute(build(evidence),evidence)
    except Exception as error: print('FAIL content: '+str(error));return 1
    finally:
        (evidence/'commands.json').write_text(json.dumps(COMMANDS,indent=2)+'\n');print('evidence: '+str(evidence))

if __name__=='__main__': raise SystemExit(main())
