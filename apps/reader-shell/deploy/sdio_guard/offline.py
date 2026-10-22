"""Build and verify a disposable immutable test image; no mounts or devices."""
import hashlib,json,subprocess,sys,re
from pathlib import Path
ROOT=Path(__file__).resolve().parent
REF=(Path(__import__('os').environ.get('PANDANOTE_REFERENCE_ROOT', 'external-inputs')) / 'pandanote-analysis/app-development-research/ram-linux-research')
def run(args,**kw): return subprocess.run(args,check=True,**kw)
def out(args): return subprocess.check_output(args,text=True).strip()
def main():
    label=sys.argv[1]
    if not re.fullmatch(r'[a-z][a-z0-9-]{1,40}',label): raise ValueError('label')
    if (ROOT/'evidence'/(label+'-pre-run.json')).exists(): raise FileExistsError('Preserve prior run evidence')
    ctx=ROOT/'build'/label; ctx.mkdir(parents=True,exist_ok=True)
    for name in ('test_storage_guard.py','test_memory_parameter.py','test_kernel_boot_gates.py'):
        (ctx/name).write_bytes((REF/name).read_bytes())
    (ctx/'golden-storage-guard.bin').write_bytes((REF/'storage-guard.bin').read_bytes())
    (ctx/'test_sdio_guard.py').write_bytes((ROOT/'test_sdio_guard.py').read_bytes())
    (ctx/'storage-guard.bin').write_bytes((REF/'storage-guard.bin' if label=='red' else ROOT/'build/storage-guard.bin').read_bytes())
    if label not in ('red','green'):
        for name in ('ram_capsule.py','pid1-ram.sh','test_profile.py'):
            (ctx/name).write_bytes((ROOT/name).read_bytes())
        for name in ('bootstrap-selfcheck.bin','bootstrap-build-result.json'):
            (ctx/name).write_bytes((ROOT/'build'/name).read_bytes())
        old=(REF/'test_pid1_policy.py').read_text().replace("net/wlan0","net/eth0")
        old=old.replace("            script = library","            (root / 'net/lo').mkdir()\n            (root / 'net/lo/flags').write_text('0x49')\n            script = library")
        (ctx/'test_pid1_policy.py').write_text(old)
    base=out(['docker','image','inspect','pandanote-boot-preflight-all:20261020','--format','{{.Id}}'])
    (ctx/'Dockerfile').write_text('FROM pandanote-boot-preflight-all:20261020'+'\nCOPY --chmod=0444 * /sample-guard/\nENTRYPOINT ["/usr/bin/timeout","45","/usr/bin/python3","-m","unittest","discover","-s","/sample-guard","-p","test_*.py","-v"]\n')
    image='pandanote-sdio-'+label+':20261021'
    run(['docker','build','--network=none','-t',image,str(ctx)],stdout=subprocess.DEVNULL)
    image=out(['docker','image','inspect',image,'--format','{{.Id}}'])
    snapshot=json.loads((REF/'offline-snapshot.json').read_text()); snap=REF/snapshot['file']
    h=hashlib.sha256()
    with snap.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    assert h.hexdigest()==snapshot['sha256']
    args=['docker','create','--name','pandanote-sdio-'+label,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--pids-limit','32','--memory','512m','--cpus','1','--ulimit','core=0','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777','--env','PANDANOTE_OFFLINE_GUARD_TEST=1',image]
    cid=out(args); inspect=json.loads(out(['docker','inspect',cid]))[0]
    h,c=inspect['HostConfig'],inspect['Config']
    assert h['NetworkMode']=='none' and h['ReadonlyRootfs'] and h['CapDrop']==['ALL'] and not h['Devices'] and not inspect['Mounts'] and not h.get('Binds') and not h.get('PortBindings') and c['User']=='65534:65534' and 'no-new-privileges' in h['SecurityOpt']
    assert base=='sha256:da7a976507f52e9be36c3207351b1045c9360e65775fce4c059178871bbac7f0'
    assert not h['Privileged'] and not h.get('DeviceRequests')
    ev=ROOT/'evidence'
    (ev/(label+'-pre-run.json')).write_text(json.dumps(dict(image=image,baseline_snapshot_sha256=snapshot['sha256'],snapshot_hash_verified=True,args=args,inspect=inspect,monitor='Unicorn instruction and every-store hooks before emu_start; timeout; no hardware mapped',authorized_scope='existing disposable offline lab; no vendor ELF in compiler'),indent=2)+'\n')
    try:
        result=subprocess.run(['docker','start','-a',cid],capture_output=True,timeout=55)
    except subprocess.TimeoutExpired:
        run(['docker','stop','-t','1',cid])
        raise
    (ev/(label+'-stdout.txt')).write_bytes(result.stdout); (ev/(label+'-stderr.txt')).write_bytes(result.stderr)
    after=json.loads(out(['docker','inspect',cid]))[0]
    (ev/(label+'-result.json')).write_text(json.dumps(dict(exit_code=after['State']['ExitCode'],image=image,hardware_access=False),indent=2)+'\n')
    print(result.stderr.decode()); print('EXIT',after['State']['ExitCode'])
if __name__=='__main__': main()
