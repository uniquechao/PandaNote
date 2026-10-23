#!/usr/bin/env python3
"""准备 Mac/Linux 共用的隔离 MIPS 编译环境；默认只编译，不连接设备或发布。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import uuid
import fcntl
from contextlib import contextmanager

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parents[1]
OUT=ROOT/'build/toolchain'
IMAGE='pandanote-mips-toolchain:1'
CONTAINER='pandanote-mips-dev'
QT_COMMIT='092cd760d5fddf9640a310214fe01929f0fff3a8'
WORKS=('native-completion','normal-apply','normal-upgrade','normal-suspend','ota-upgrade','rtc-probe')
RUNTIMES={'libQtCore.so.4','libQtGui.so.4','libc.so.6','ld-linux-mipsn8.so.1','libstdc++.so.6','libgcc_s.so.1'}


def run(args,**kwargs):
    result=subprocess.run(list(map(str,args)),capture_output=True,text=True,**kwargs)
    if result.returncode:raise ValueError((result.stderr or result.stdout).strip() or '命令失败')
    return result.stdout


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def save(name,value):
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


@contextmanager
def build_guard():
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'build.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('已有编译或打包任务运行，请等待其完成')
        yield


def inside_reference(reference,path):
    resolved=path.resolve()
    if not resolved.is_relative_to(reference):raise ValueError('参考材料链接越出指定目录：'+str(path))
    if not resolved.is_file():raise ValueError('缺少参考文件：'+str(path))
    return resolved


def doctor(reference):
    reference=reference.resolve()
    analysis=reference/'pandanote-analysis'
    stock=analysis/'app-development-research/qt-stock-sysroot'
    minimal=analysis/'app-development-research/minimal-qt'
    qt=analysis/'qt-sdk-source/qt-4.7.4'
    errors=[];checked={}
    for name in ('start.S','entry.h','csu.cpp','libio-init.c'):
        try:
            path=inside_reference(reference,minimal/'build-support'/name)
            if sha(path)!=sha(ROOT/'build-support'/name):raise ValueError('启动适配与仓库保留基线不匹配：'+name)
            checked[str(path.relative_to(reference))]=sha(path)
        except (OSError,ValueError) as error:errors.append(str(error))
    for name in ('QtCore/qglobal.h','QtCore/qconfig.h','QtGui/qwidget.h'):
        try:checked[str((minimal/'include'/name).relative_to(reference))]=sha(inside_reference(reference,minimal/'include'/name))
        except (OSError,ValueError) as error:errors.append(str(error))
    try:
        rows=json.loads(inside_reference(reference,stock/'original-library-provenance.json').read_text())
        if not isinstance(rows,list) or not rows:raise ValueError('原厂运行库来源清单无效')
        found=set()
        for item in rows:
            name=item['name']
            if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9._+-]+',name) or name in ('.','..') or name in found:raise ValueError('运行库来源路径或重复项无效')
            found.add(name)
            path=inside_reference(reference,stock/name)
            if path.is_symlink() or sha(path)!=item['sha256']:raise ValueError('原厂运行库摘要不匹配：'+name)
            checked[str(path.relative_to(reference))]=item['sha256']
        if not RUNTIMES<=found:raise ValueError('原厂运行库闭包缺少：'+', '.join(sorted(RUNTIMES-found)))
    except (OSError,ValueError,KeyError,TypeError) as error:errors.append(str(error))
    try:
        if not qt.resolve().is_relative_to(reference):raise ValueError('Qt 源码路径越界')
        if run(['git','-C',qt,'rev-parse','HEAD']).strip()!=QT_COMMIT:raise ValueError('Qt 源码提交不匹配')
    except (OSError,ValueError) as error:errors.append(str(error))
    result=dict(schema=1,reference=str(reference),ready_for_target_build=not errors,errors=errors,checked_sha256=checked,
                qt_commit=QT_COMMIT,target_execution_performed=False,device_access=False)
    save('sdk-check.json',result)
    return result


def require_sdk(reference):
    result=doctor(reference)
    if result['errors']:raise ValueError('参考材料尚未就绪，详见 apps/reader-shell/build/toolchain/sdk-check.json：\n'+'\n'.join(result['errors']))
    return reference.resolve()


def image_id():
    value=run(['docker','image','inspect',IMAGE,'--format','{{.Id}}']).strip()
    if not re.fullmatch('sha256:[0-9a-f]{64}',value):raise ValueError('工具链镜像身份无效')
    return value


def image():
    subprocess.run(['docker','build','--platform','linux/amd64','-t',IMAGE,str(ROOT/'toolchain')],check=True)
    save('image.json',dict(schema=1,image_id=image_id(),dockerfile_sha256=sha(ROOT/'toolchain/Dockerfile'),probe_sha256=sha(ROOT/'toolchain/probe.py')))


def probe():
    identity=image_id()
    raw=run(['docker','run','--rm','--platform','linux/amd64','--network','none','--read-only','--cap-drop','ALL',
             '--security-opt','no-new-privileges','--pids-limit','64','--memory','512m',
             '--tmpfs','/tmp:rw,nosuid,nodev,size=64m,mode=1777',identity,'python3','/opt/pandanote/probe.py'])
    value=json.loads(raw);value['image_id']=identity
    save('compiler-check.json',value)
    return value


def mounts(reference):
    analysis=reference/'pandanote-analysis/app-development-research'
    return [(analysis/'qt-stock-sysroot','/work/pandanote/app-development-research/qt-stock-sysroot',False),
            (analysis/'minimal-qt/include','/work/pandanote/app-development-research/minimal-qt/include',False)]+[
            (OUT/'work'/name,'/work/pandanote-'+name,True) for name in WORKS]


def verify_container(reference,running=True):
    record=json.loads(run(['docker','inspect',CONTAINER]))[0]
    host=record['HostConfig']
    if (running and record['State']['Status']!='running') or record['State']['Status'] not in ('running','created','exited') or record['Image']!=image_id():raise ValueError('编译容器未运行或镜像身份已改变')
    if record['Config']['User']!=str(os.getuid())+':'+str(os.getgid()):raise ValueError('编译容器身份与本机工作目录属主不匹配')
    if host['NetworkMode']!='none' or not host['ReadonlyRootfs'] or host['Privileged'] or host.get('Devices') or host.get('DeviceRequests') or set(host.get('CapDrop') or [])!={'ALL'} or 'no-new-privileges' not in host['SecurityOpt']:raise ValueError('编译容器隔离条件不匹配')
    expected={(str(source.resolve()),target,rw) for source,target,rw in mounts(reference)}
    actual={(m['Source'],m['Destination'],m['RW']) for m in record['Mounts'] if m['Type']=='bind'}
    if actual!=expected or any(m['Type'] not in ('bind','tmpfs') for m in record['Mounts']):raise ValueError('编译容器挂载与当前参考材料不匹配')
    return record


def start(reference):
    reference=require_sdk(reference)
    if run(['docker','ps','-a','--filter','name=^/'+CONTAINER+'$','--format','{{.Names}}']).strip():
        record=verify_container(reference,running=False)
        if record['State']['Status']!='running':run(['docker','start',CONTAINER])
        verify_container(reference)
        return
    args=['docker','create','--name',CONTAINER,'--user',str(os.getuid())+':'+str(os.getgid()),'--env','HOME=/tmp','--platform','linux/amd64','--network','none','--read-only','--cap-drop','ALL',
          '--security-opt','no-new-privileges','--pids-limit','256','--memory','4g','--cpus','2',
          '--tmpfs','/tmp:rw,nosuid,nodev,size=128m,mode=1777']
    for source,target,rw in mounts(reference):
        if rw:source.mkdir(parents=True,exist_ok=True)
        if ',' in str(source):raise ValueError('参考或工作目录不能包含逗号')
        args+=['--mount','type=bind,src='+str(source.resolve())+',dst='+target+('' if rw else ',readonly')]
    run([*args,image_id()]);run(['docker','start',CONTAINER]);record=verify_container(reference)
    save('container.json',dict(schema=1,container_id=record['Id'],image_id=record['Image'],network='none',device_access=False,reference_mounts_read_only=True))


def bundle_native():
    native=ROOT/'build';manifest_path=native/'manifest.json'
    if manifest_path.is_symlink():raise ValueError('原生构建清单不能是链接')
    manifest=json.loads(manifest_path.read_text())
    if manifest.get('execution_performed') is not False or not {'device-ota-v1','normal-suspend-v2'}<=set(manifest.get('capabilities',[])):raise ValueError('原生构建清单不完整')
    entries=[];seen={'manifest.json'};total=manifest_path.stat().st_size
    for item in manifest['artifacts']:
        name=item['path'];relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts or name in seen:raise ValueError('原生构建产物路径无效')
        seen.add(name);path=native/relative
        if path.is_symlink() or not path.resolve().is_relative_to(native.resolve()) or not path.is_file() or path.stat().st_size!=item['bytes'] or sha(path)!=item['sha256']:raise ValueError('原生构建产物摘要不匹配：'+name)
        total+=path.stat().st_size
        if total>256*1024*1024:raise ValueError('原生构建包超过 256 MiB 上限')
        entries.append((name,path))
    required={'reader-shell.mipsel','ota/ota-worker.mipsel','ota/pandanote-ota-upgrade.mipsel','ota/helper-manifest.json'}
    if not required<=seen:raise ValueError('原生 OTA 产物闭包不完整')
    identity=sha(manifest_path);OUT.mkdir(parents=True,exist_ok=True)
    output=OUT/('native-'+identity+'.tar')
    with output.open('xb') as stream:
        with tarfile.open(fileobj=stream,mode='w') as archive:
            for name,path in [('manifest.json',manifest_path),*entries]:archive.add(path,arcname='native/'+name,recursive=False)
    result=dict(schema=1,path=str(output.relative_to(PROJECT)),sha256=sha(output),native_sha256=identity,
                target_execution_performed=False,ota_deployable=False,note='原生构建包仍须由管理端绑定完整 NORMAL 基线、生成候选并审批签名，不能直接刷写。')
    save('native-package.json',result)
    return result


def compile_tls(fetch):
    # TLS 没有 Qt/原厂库依赖，可先在没有私有 SDK 的环境完成实际目标编译。
    name='pandanote-mips-tls-'+uuid.uuid4().hex[:12]
    work=OUT/'work/native-completion';work.mkdir(parents=True,exist_ok=True)
    if ',' in str(work):raise ValueError('工作目录不能包含逗号')
    identity=image_id()
    args=['docker','create','--name',name,'--user',str(os.getuid())+':'+str(os.getgid()),'--env','HOME=/tmp','--platform','linux/amd64','--network','none','--read-only','--cap-drop','ALL',
          '--security-opt','no-new-privileges','--pids-limit','256','--memory','4g','--cpus','2',
          '--tmpfs','/tmp:rw,nosuid,nodev,size=128m,mode=1777',
          '--mount','type=bind,src='+str(work.resolve())+',dst=/work/pandanote-native-completion',identity]
    run(args)
    try:
        run(['docker','start',name])
        env={**os.environ,'PANDANOTE_COMPILER_CONTAINER':name,'PANDANOTE_COMPILER_ARCHIVE_COPY':'1','PANDANOTE_COMPILER_WORK':'/work/pandanote-native-completion'}
        subprocess.run([sys.executable,str(ROOT/'build_tls.py'),*(['--fetch'] if fetch else [])],cwd=PROJECT,env=env,check=True)
        result=dict(schema=1,image_id=identity,tls_provenance=str((ROOT/'build/tls-provenance.json').relative_to(PROJECT)),target_execution_performed=False,device_access=False)
        save('tls-build.json',result)
        return result
    finally:run(['docker','rm','-f',name])


def compile_target(reference,fetch):
    reference=require_sdk(reference);start(reference);verify_container(reference)
    env={**os.environ,'PANDANOTE_REFERENCE_ROOT':str(reference),'PANDANOTE_COMPILER_CONTAINER':CONTAINER,'PANDANOTE_COMPILER_ARCHIVE_COPY':'1','PANDANOTE_COMPILER_WORK':'/work/pandanote-native-completion'}
    for args in ([sys.executable,str(ROOT/'build_tls.py'),*(['--fetch'] if fetch else [])],
                 [sys.executable,str(ROOT/'build.py')],
                 [sys.executable,str(ROOT/'deploy/normal_boot/build_suspend.py')]):
        subprocess.run(args,cwd=PROJECT,env=env,check=True)
    return bundle_native()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    for name in ('image','probe','bundle'):sub.add_parser(name)
    tls=sub.add_parser('tls');tls.add_argument('--fetch',action='store_true',help='显式获取并校验固定 MbedTLS 源码')
    for name in ('doctor','start','compile'):
        command=sub.add_parser(name);command.add_argument('--reference',type=Path,default=PROJECT/'external-inputs',help='已校验设备 SDK 参考根目录，默认 external-inputs')
        if name=='compile':command.add_argument('--fetch',action='store_true',help='显式获取并校验固定 MbedTLS 源码')
    args=parser.parse_args()
    try:
        if args.action=='image':image();result=dict(image_id=image_id())
        elif args.action=='probe':result=probe()
        elif args.action=='tls':
            with build_guard():result=compile_tls(args.fetch)
        elif args.action=='doctor':
            result=doctor(args.reference)
            print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['ready_for_target_build'] else 1
        elif args.action=='start':start(args.reference);result=dict(container=CONTAINER)
        elif args.action=='compile':
            with build_guard():result=compile_target(args.reference,args.fetch)
        else:
            with build_guard():result=bundle_native()
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError) as error:
        print('工具链准备失败：'+str(error),file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
