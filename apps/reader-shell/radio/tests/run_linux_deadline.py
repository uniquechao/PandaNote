#!/usr/bin/env python3
"""Compile trusted static test samples; run only in checked disposable Linux lab.
No vendor ELF/runtime loaded, services, hardware, host mounts or network.
"""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'evidence/fix1'
BASE='sha256:da7a976507f52e9be36c3207351b1045c9360e65775fce4c059178871bbac7f0'
CONTAINER='pandanote-mips-dev'
WORK='/work/pandanote-radio-fix1-tests'
def call(args,**kwargs):return subprocess.run([str(x) for x in args],check=True,**kwargs)
def out(args):return subprocess.check_output([str(x) for x in args],text=True).strip()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    label=sys.argv[1]
    if label not in ('red','green'):raise ValueError('red or green')
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    if (EVIDENCE/(label+'-pre-run.json')).exists():raise FileExistsError('preserve prior evidence')
    context=ROOT/'build'/('deadline-'+label);case=context/'case/apps/reader-shell/radio'
    (case/'.test').mkdir(parents=True,mode=0o700,exist_ok=True);(case/'tests').mkdir(exist_ok=True)
    call(['docker','exec',CONTAINER,'mkdir','-p',WORK+'/tests'])
    for name in ('radio.c','persistence.h','tests/io_cases.c'):
        call(['docker','cp',ROOT/name,CONTAINER+':'+WORK+'/'+name])
    for source,binary in [('radio.c','radio-host'),('tests/io_cases.c','io-cases')]:
        call(['docker','exec','-w',WORK,CONTAINER,'mipsel-linux-gnu-gcc','-static','-std=c99','-O2','-D_POSIX_C_SOURCE=200809L','-DRADIO_CTRL="apps/reader-shell/radio/.test/wlan0"','-DRADIO_LOCAL="apps/reader-shell/radio/.test"',source,'-o',binary])
        call(['docker','cp',CONTAINER+':'+WORK+'/'+binary,case/'.test'/binary])
    shutil.copyfile(ROOT/'tests/test_radio.py',case/'tests/test_radio.py')
    (context/'entry.py').write_text('import os,shutil,subprocess\nshutil.copytree("/case","/tmp/radio-case")\nos.chdir("/tmp/radio-case")\nos.chmod("apps/reader-shell/radio/.test",0o700)\nos.environ["RADIO_TEST_PREBUILT"]="1"\nos.environ["RADIO_TEST_RUNNER"]="/usr/bin/qemu-mipsel"\nraise SystemExit(subprocess.call(["/usr/bin/python3","-m","unittest","discover","-s","apps/reader-shell/radio/tests","-p","test_radio.py","-v"]))\n')
    (context/'Dockerfile').write_text('FROM pandanote-boot-preflight-all:20261020\nCOPY --chmod=0755 case /case\nCOPY --chmod=0444 entry.py /entry.py\nENTRYPOINT ["/usr/bin/timeout","45","/usr/bin/python3","/entry.py"]\n')
    if out(['docker','image','inspect','pandanote-boot-preflight-all:20261020','--format','{{.Id}}'])!=BASE:raise RuntimeError('immutable lab base changed')
    call(['docker','build','--network=none','--pull=false','-t','pandanote-radio-deadline-'+label,str(context)],stdout=subprocess.DEVNULL)
    image=out(['docker','image','inspect','pandanote-radio-deadline-'+label,'--format','{{.Id}}'])
    old_layers=json.loads(out(['docker','image','inspect',BASE,'--format','{{json .RootFS.Layers}}']))
    layers=json.loads(out(['docker','image','inspect',image,'--format','{{json .RootFS.Layers}}']))
    if layers[:len(old_layers)]!=old_layers:raise RuntimeError('base layer mismatch')
    args=['docker','create','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534','--pids-limit','32','--memory','128m','--cpus','1','--ulimit','core=0','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777',image]
    cid=out(args);inspection=json.loads(out(['docker','inspect',cid]))[0];h=inspection['HostConfig'];c=inspection['Config']
    assert h['NetworkMode']=='none' and h['ReadonlyRootfs'] and h['CapDrop']==['ALL'] and not h['Devices'] and not inspection['Mounts'] and not h.get('Binds') and not h.get('PortBindings') and c['User']=='65534:65534' and 'no-new-privileges' in h['SecurityOpt'] and not h['Privileged'] and not h.get('DeviceRequests') and h['PidsLimit']==32 and h['Memory']==128*1024*1024
    (EVIDENCE/(label+'-pre-run.json')).write_text(json.dumps({'image':image,'base':BASE,'args':args,'inspect':inspection,'source_sha256':sha(ROOT/'radio.c'),'test_sha256':{p.name:sha(p) for p in (ROOT/'tests').iterdir() if p.is_file() and p.name in ('test_radio.py','io_cases.c')},'sample_sha256':{p.name:sha(p) for p in (case/'.test').iterdir()},'runtime':'trusted compiler static libc; no vendor linked/runtime ELF','monitor':'45-second lab timeout, bounded subprocesses, nonroot readonly network-none/no-host-mount gates checked before start'},indent=2)+'\n')
    try:result=subprocess.run(['docker','start','-a',cid],capture_output=True,timeout=55)
    except subprocess.TimeoutExpired:
        call(['docker','stop','-t','1',cid]);raise
    (EVIDENCE/(label+'-stdout.txt')).write_bytes(result.stdout);(EVIDENCE/(label+'-stderr.txt')).write_bytes(result.stderr)
    final=json.loads(out(['docker','inspect',cid]))[0]
    (EVIDENCE/(label+'-result.json')).write_text(json.dumps({'exit_code':final['State']['ExitCode'],'hardware_access':False,'image':image},indent=2)+'\n')
    print(result.stderr.decode());print('EXIT',final['State']['ExitCode'])
if __name__=='__main__':main()
