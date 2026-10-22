#!/usr/bin/env python3
"""Checked immutable disposable lab ONLY; no target execution on Mac/compiler."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
from proof import retain_result
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'build/c1';EVIDENCE=ROOT/'evidence/c1'
BASE='sha256:20ecae4195e6336bf3453516a52af3ba33fecd3052332d6094399a0a354e6cb0'
TAG='pandanote-qt-graphics-master:20261020'
def out(args):return subprocess.check_output([str(x) for x in args],text=True).strip()
def call(args,**kw):return subprocess.run([str(x) for x in args],check=True,**kw)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    label=sys.argv[1]
    if label not in ('initial','final','canary','repro','review'):raise ValueError('fixed evidence label only')
    prefix=EVIDENCE/('offline-'+label)
    if prefix.with_suffix('.pre-run.json').exists():raise FileExistsError('preserve evidence')
    context=OUT/'lab';case=context/'case'
    (case/'runtime/lib').mkdir(parents=True,exist_ok=True);(case/'bin').mkdir(exist_ok=True)
    inputs=json.loads((ROOT/'c1/inputs.json').read_text())
    if out(['docker','exec','pandanote-mips-dev','sha256sum','/work/pandanote-bluetooth-c1/rootfs.img']).split()[0]!=inputs['rootfs_sha256']:raise ValueError('original image copy digest')
    for name,(_,pin) in inputs['runtime'].items():
        path=case/'runtime/lib'/name
        call(['docker','cp','pandanote-mips-dev:/work/pandanote-bluetooth-c1/runtime/'+name,path])
        if sha(path)!=pin:raise ValueError('lab runtime digest '+name)
    for name,(source,pin) in inputs['tools'].items():
        dest='/work/pandanote-bluetooth-c1/'+name
        call(['docker','exec','pandanote-mips-dev','debugfs','-R','dump '+source+' '+dest,'/work/pandanote-bluetooth-c1/rootfs.img'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        path=case/'bin'/name;call(['docker','cp','pandanote-mips-dev:'+dest,path])
        if sha(path)!=pin:raise ValueError('lab tool digest '+name)
    manifest=json.loads((EVIDENCE/'daemon-manifest.json').read_text())
    if sha(OUT/'bluetoothd-5.87.mipsel')!=manifest['artifact_sha256']:raise ValueError('daemon digest mismatch')
    shutil.copyfile(OUT/'bluetoothd-5.87.mipsel',case/'bin/bluetoothd')
    for name in ['main.conf','private-bus.conf','lifecycle.py','proof.py','audit_trace.py']:shutil.copyfile(ROOT/'c1'/name,case/name)
    shutil.copyfile(ROOT/'c1/offline_entry.py',context/'entry.py')
    shutil.copyfile(ROOT/'c1/test-activation-canary.service',case/'activation-canary.service')
    (context/'Dockerfile').write_text('FROM '+TAG+'\nCOPY --chmod=0555 case /case\nCOPY --chmod=0444 entry.py /entry.py\nCOPY --chmod=0444 case/activation-canary.service /usr/share/dbus-1/system-services/org.pandanote.NoActivation.service\nCOPY --chmod=0444 case/activation-canary.service /usr/share/dbus-1/services/org.pandanote.NoActivation.service\nENV PYTHONPATH=/case\nENTRYPOINT ["/usr/bin/timeout","45","/usr/bin/python3","/entry.py"]\n')
    allowed={'runtime/lib/'+n for n in inputs['runtime']}|{'bin/dbus-daemon','bin/dbus-send','bin/bluetoothd','main.conf','private-bus.conf','lifecycle.py','proof.py','audit_trace.py','activation-canary.service'}
    actual={str(p.relative_to(case)) for p in case.rglob('*') if p.is_file()}
    if actual!=allowed:raise ValueError('unexpected lab inputs '+repr(actual-allowed))
    # Hash/triage all target inputs before the disposable execution gate.
    triage=Path(__import__('os').environ.get('PANDANOTE_TRIAGE_TOOL', 'external-inputs/triage.py'))
    with prefix.with_suffix('.triage.txt').open('w') as stream:
        for name in sorted(x for x in allowed if x.startswith(('bin/','runtime/'))):
            call(['python3',triage,case/name],stdout=stream)
    base=json.loads(out(['docker','image','inspect',TAG]))[0]
    assert base['Id']==BASE and set(x.split('=',1)[0] for x in base['Config'].get('Env',[]))=={'PATH'}
    call(['docker','build','--network=none','--pull=false','-t','pandanote-bluetooth-c1-proof:'+label,str(context)],stdout=subprocess.DEVNULL)
    image=out(['docker','image','inspect','pandanote-bluetooth-c1-proof:'+label,'--format','{{.Id}}'])
    layers=json.loads(out(['docker','image','inspect',image,'--format','{{json .RootFS.Layers}}']))
    assert layers[:len(base['RootFS']['Layers'])]==base['RootFS']['Layers']
    args=['docker','create','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--pids-limit','32','--memory','128m','--memory-swap','128m','--cpus','1','--ulimit','core=0','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777',image]
    cid=out(args);inspection=json.loads(out(['docker','inspect',cid]))[0];h=inspection['HostConfig'];c=inspection['Config']
    assert h['NetworkMode']=='none' and h['ReadonlyRootfs'] and h['CapDrop']==['ALL'] and not h['Devices'] and not inspection['Mounts'] and not h.get('Binds') and not h.get('PortBindings') and c['User']=='65534:65534' and 'no-new-privileges' in h['SecurityOpt'] and not h['Privileged'] and not h.get('DeviceRequests') and h['PidsLimit']==32 and h['Memory']==128*1024*1024 and h['MemorySwap']==h['Memory']
    pins={str(p.relative_to(case)):sha(p) for p in case.rglob('*') if p.is_file()}
    prefix.with_suffix('.pre-run.json').write_text(json.dumps({'base':BASE,'image':image,'base_layers':base['RootFS']['Layers'],'inspect':inspection,'argv':args,'input_sha256':pins,'entry_sha256':sha(context/'entry.py'),'monitor':'qemu -strace precedes every target start; immutable baseline+derived image as clean snapshot;45s lab timeout;55s external timeout; exact owned Popen handles with TERM/wait/KILL/reap'},indent=2)+'\n')
    try:result=subprocess.run(['docker','start','-a',cid],capture_output=True,timeout=55)
    except subprocess.TimeoutExpired:
        call(['docker','stop','-t','1',cid]);raise
    prefix.with_suffix('.stdout.json').write_bytes(result.stdout);prefix.with_suffix('.stderr.txt').write_bytes(result.stderr)
    final=json.loads(out(['docker','inspect',cid]))[0]
    summary,status=retain_result(prefix,result.stdout,result.stderr,final['State']['ExitCode'],image)
    print(json.dumps(summary,indent=2));return status
if __name__=='__main__':raise SystemExit(main())
