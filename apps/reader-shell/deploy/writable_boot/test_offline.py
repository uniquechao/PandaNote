#!/usr/bin/env python3
"""Run ONLY owned shell policy fixtures in a device-less, network-less container."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parent
BASE_TAG='pandanote-boot-preflight-all:20261020'
BASE_SHA='sha256:da7a976507f52e9be36c3207351b1045c9360e65775fce4c059178871bbac7f0'


def out(args):return subprocess.check_output(args,text=True).strip()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label',required=True)
    label=parser.parse_args().label
    if not re.fullmatch('[a-z][a-z0-9-]{1,35}',label):raise ValueError('invalid evidence label')
    evidence=ROOT/'evidence';evidence.mkdir(exist_ok=True)
    record=evidence/(label+'-pre-run.json')
    if record.exists():raise FileExistsError('preserve prior run evidence')
    if out(['docker','image','inspect',BASE_TAG,'--format','{{.Id}}'])!=BASE_SHA:
        raise ValueError('trusted test image changed')
    context=ROOT/'build'/('policy-tests-'+label);context.mkdir(parents=True)
    (context/'tests').mkdir()
    for name in ('policy.sh','child-supervisor.sh','pid1.in'):(context/name).write_bytes((ROOT/name).read_bytes())
    (context/'tests/test_policy.py').write_bytes((ROOT/'tests/test_policy.py').read_bytes())
    (context/'Dockerfile').write_text('FROM '+BASE_TAG+'\nCOPY policy.sh child-supervisor.sh pid1.in /sample-policy/\nCOPY tests /sample-policy/tests\nWORKDIR /sample-policy\nENTRYPOINT ["/usr/bin/python3","-m","unittest","discover","-s","tests","-p","test_policy.py","-v"]\n')
    image='pandanote-owned-writable-policy-'+label+':20261021'
    build=subprocess.run(['docker','build','--pull=false','--network=none','-t',image,str(context)],capture_output=True,check=True)
    (evidence/(label+'-build.txt')).write_bytes(build.stdout+build.stderr)
    if out(['docker','image','inspect',BASE_TAG,'--format','{{.Id}}'])!=BASE_SHA:
        raise ValueError('trusted test tag changed during build')
    image_id=out(['docker','image','inspect',image,'--format','{{.Id}}'])
    args=['docker','create','--name','pandanote-writable-policy-'+label,'--network=none','--read-only',
          '--cap-drop=ALL','--security-opt=no-new-privileges','--user=0:0','--pids-limit=64',
          '--memory=128m','--cpus=1','--ulimit=core=0',
          '--tmpfs','/sample-policy/build:rw,nosuid,nodev,noexec,size=16m,mode=0700',image_id]
    cid=out(args)
    before=json.loads(out(['docker','inspect',cid]))[0]
    host=before['HostConfig']
    if (host['NetworkMode']!='none' or not host['ReadonlyRootfs'] or host['Privileged'] or
        host.get('Devices') or host.get('Binds') or before['Mounts'] or host['CapDrop']!=['ALL']):
        raise ValueError('fixture sandbox differs from intended isolation')
    record.write_text(json.dumps(dict(argv=args,inspect=before,base_sha256=BASE_SHA,
        vendor_execution=False,physical_devices=False,scope='owned POSIX policy and native Linux tools only'),indent=2)+'\n')
    try:result=subprocess.run(['docker','start','-a',cid],capture_output=True,timeout=45)
    except subprocess.TimeoutExpired:
        subprocess.run(['docker','stop','-t','1',cid],capture_output=True,check=True)
        raise
    (evidence/(label+'-stdout.txt')).write_bytes(result.stdout)
    (evidence/(label+'-stderr.txt')).write_bytes(result.stderr)
    after=json.loads(out(['docker','inspect',cid]))[0]
    (evidence/(label+'-result.json')).write_text(json.dumps(dict(exit_code=after['State']['ExitCode'],
        image=image_id,container=cid,physical_devices=False,vendor_execution=False),indent=2)+'\n')
    print(result.stdout.decode()+result.stderr.decode())
    if after['State']['ExitCode']!=0:raise SystemExit(after['State']['ExitCode'])


if __name__=='__main__':main()
