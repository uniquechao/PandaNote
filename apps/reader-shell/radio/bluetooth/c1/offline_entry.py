"""Only entered inside the verified disposable immutable C1 container.
No execution on Mac/production compiler. Guest syscalls monitored before sample.
"""
import base64,os,platform,subprocess,time
from pathlib import Path
from lifecycle import Children
from proof import collect_cleanup, emit_guest_proof
assert platform.system()=='Linux' and os.geteuid()==65534
assert Path('/case/runtime/lib/ld-linux-mipsn8.so.1').is_file()
ROOT=Path('/tmp/pandanote-connectivity/bluetooth');RESULT={};FILES={};group=Children()
os.umask(0o077)
for p in [ROOT,ROOT/'etc',ROOT/'run',ROOT/'home',ROOT/'var/lib/bluetooth',ROOT/'logs']:
    p.mkdir(mode=0o700,parents=True,exist_ok=True)
(ROOT/'etc/main.conf').write_bytes(Path('/case/main.conf').read_bytes())
# The target config is root-only; this unprivileged lab substitutes exactly UID65534.
(ROOT/'etc/bus.conf').write_text(Path('/case/private-bus.conf').read_text().replace('<policy user="root">','<policy user="65534">'))
ADDRESS='unix:path='+str(ROOT/'run/bus')
ENV={'PATH':'/usr/bin:/bin','HOME':str(ROOT/'home'),'DBUS_SYSTEM_BUS_ADDRESS':ADDRESS,'DBUS_SESSION_BUS_ADDRESS':ADDRESS,'XDG_RUNTIME_DIR':str(ROOT/'run'),'XDG_CONFIG_HOME':str(ROOT/'etc'),'XDG_CACHE_HOME':str(ROOT/'home/cache'),'XDG_DATA_HOME':str(ROOT/'home/data')}
def command(binary,*args):
    return ['/usr/bin/qemu-mipsel','-strace','-L','/case/runtime','-E','LD_LIBRARY_PATH=/lib','/case/bin/'+binary,*args]
def run(label,binary,*args):
    out=ROOT/'logs'/(label+'.out');err=ROOT/'logs'/(label+'.trace')
    with out.open('wb') as of,err.open('wb') as ef:
        child=group.spawn(command(binary,*args),stdout=of,stderr=ef,env=ENV)
        try:rc=child.wait(timeout=8)
        except subprocess.TimeoutExpired:group.stop(child);raise
    RESULT[label]={'exit_code':rc,'stdout':out.read_text(errors='replace')[:4096],'trace_bytes':err.stat().st_size}
    return child
try:
    version=run('version','bluetoothd','--version')
    RESULT['version_ok']=RESULT['version']['exit_code']==0 and RESULT['version']['stdout'].strip()=='5.87'
    busout=(ROOT/'logs/bus.out').open('wb');buserr=(ROOT/'logs/bus.trace').open('wb')
    bus=group.spawn(command('dbus-daemon','--nofork','--nopidfile','--nosyslog','--config-file='+str(ROOT/'etc/bus.conf')),stdout=busout,stderr=buserr,env=ENV)
    deadline=time.monotonic()+3
    while not (ROOT/'run/bus').exists():
        if bus.poll() is not None:raise RuntimeError('private bus exited '+str(bus.returncode))
        if time.monotonic()>=deadline:raise RuntimeError('private bus readiness timeout')
        time.sleep(.02)
    (ROOT/'run/bus').chmod(0o600)
    RESULT['private_bus_ready']=True
    RESULT['activation_canary_installed']=all(Path(x).is_file() for x in ['/usr/share/dbus-1/system-services/org.pandanote.NoActivation.service','/usr/share/dbus-1/services/org.pandanote.NoActivation.service'])
    assert RESULT['activation_canary_installed']
    run('list_names','dbus-send','--bus='+ADDRESS,'--type=method_call','--print-reply','--reply-timeout=1000','--dest=org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus.ListNames')
    run('activation_denied','dbus-send','--bus='+ADDRESS,'--type=method_call','--print-reply','--reply-timeout=1000','--dest=org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus.StartServiceByName','string:org.pandanote.NoActivation','uint32:0')
    # No controller exists in this lab. Expected startup failure is not acceptance.
    run('daemon_startup','bluetoothd','--nodetach','--configfile='+str(ROOT/'etc/main.conf'),'--plugin=gap')
    RESULT['activation_canary_executed']=(ROOT/'activation-unexpected').exists()
    assert not RESULT['activation_canary_executed']
    RESULT['bus_alive_before_cleanup']=bus.poll() is None
    assert RESULT['version_ok']
    assert RESULT['list_names']['exit_code']==0, 'private EXTERNAL-auth bus call failed'
    assert RESULT['activation_denied']['exit_code']==1 and 'ServiceUnknown' in (ROOT/'logs/activation_denied.trace').read_text(), 'activation was not refused as unconfigured service'
    assert RESULT['daemon_startup']['exit_code']==1 and 'Adapter handling initialization failed' in (ROOT/'logs/daemon_startup.trace').read_text(), 'expected no-controller failure not observed'
finally:
    collect_cleanup(group,RESULT)
    for handle in [locals().get('busout'),locals().get('buserr')]:
        if handle:handle.close()
    RESULT['private_paths']={str(p):oct(p.stat().st_mode&0o777) for p in ROOT.rglob('*') if not p.is_symlink()}
    RESULT['oversize_trace']=False
    for p in (ROOT/'logs').glob('*'):
        data=p.read_bytes();FILES[p.name]=base64.b64encode(data).decode()
        if len(data)>2*1024*1024:RESULT['oversize_trace']=True
    # The root is immutable. All accepted write-capable guest file opens must
    # be in this private tmpfs root or /dev/null. Socket/syscall
    # limitations remain distinct from complete hardware/storage execution.
    RESULT['forbidden_state_exists']=Path('/var/lib/bluetooth').exists() or Path('/var/run/sdp').exists()
    if emit_guest_proof(RESULT,FILES):raise RuntimeError('offline proof rejected after evidence emission')
