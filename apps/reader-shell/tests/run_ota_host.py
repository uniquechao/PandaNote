#!/usr/bin/env python3
"""用已预置的固定 MbedTLS 源码与 Qt5 主机开发库验证 OTA；不联网、不接触设备。"""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import sysconfig

ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT.parents[1]
OUT=ROOT/'build/ota-tests'

def run(args):
    result=subprocess.run(list(map(str,args)),capture_output=True,text=True)
    if result.returncode:
        (OUT/'compile-failure.log').write_text(result.stderr or result.stdout)
        raise RuntimeError('\n'.join(line for line in (result.stderr or result.stdout).splitlines() if 'error:' in line or 'undefined reference' in line) or result.stderr[-2000:])


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    source=Path(os.environ.get('PANDANOTE_MBEDTLS_SOURCE',str(PROJECT/'build/ota-host/mbedtls-3.6.7')))
    config=ROOT/'third_party/mbedtls'
    version=(source/'include/mbedtls/build_info.h').read_text()
    if '"3.6.7"' not in version:raise RuntimeError('需要仓库固定的 MbedTLS 3.6.7 源码')
    objects=OUT/'mbed-objects';objects.mkdir(exist_ok=True)
    def compile_one(path):
        run(['cc','-Os','-ffunction-sections','-fdata-sections','-DMBEDTLS_CONFIG_FILE="pandanote_config.h"','-I'+str(config),'-I'+str(source/'include'),'-I'+str(source/'library'),'-c',path,'-o',objects/(path.stem+'.o')])
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(compile_one,(source/'library').glob('*.c')))
    archive=OUT/'libmbed.a'
    run(['ar','rcs',archive,*objects.glob('*.o')])
    sha=OUT/'sha256.o';run(['cc','-c',ROOT/'third_party/sha256/sha256.c','-o',sha])
    fallback=PROJECT/'build/ota-host/qt-root/usr'
    prefix=Path(os.environ.get('PANDANOTE_QT_HOST_PREFIX',str(fallback if fallback.exists() else '/usr')))
    arch=sysconfig.get_config_var('MULTIARCH')
    include=prefix/('include/'+arch+'/qt5');library=prefix/('lib/'+arch)
    sources=['tests/ota_worker_host.cpp','sync.cpp','tls.cpp','resolver.cpp','tlsclock.cpp','dnsconfig.cpp','ota/json.cpp','ota/storage.cpp','ota/authorization.cpp','ota/device.cpp','ota/crypto.cpp','ota/power.cpp','battery.cpp','battery_posix.cpp']
    binary=OUT/'ota-worker-host'
    run(['g++','-fPIC','-std=c++11','-O1','-ffunction-sections','-fdata-sections','-I'+str(include),'-I'+str(include/'QtCore'),'-I'+str(include/'QtGui'),'-I'+str(source/'include'),'-I'+str(config),'-DMBEDTLS_CONFIG_FILE="pandanote_config.h"',*[ROOT/s for s in sources],sha,archive,'-L'+str(library),'-Wl,-rpath,'+str(library),'-Wl,--wrap=open,--wrap=lstat,--wrap=time,--gc-sections','-lQt5Core','-o',binary])
    # Qt5 仅用于执行真实 UI 交接；不是 Qt4/MIPS 目标构建证据。
    compat=OUT/'qt-compat/QtGui';compat.mkdir(parents=True,exist_ok=True)
    for name in ('qwidget.h','qapplication.h'):(compat/name).write_text('#include <QtWidgets/'+name+'>\n')
    ui_binary=OUT/'ota-ui-host'
    ui_sources=['tests/ota_ui_host.cpp','shell.cpp','systemui.cpp','ota_ui.cpp','content.cpp','navigation.cpp','localapps.cpp','bluetooth.cpp','bluetooth_ui.cpp','sync.cpp','tls.cpp','resolver.cpp','tlsclock.cpp','dnsconfig.cpp','ota/json.cpp','ota/storage.cpp']
    run(['g++','-fPIC','-std=c++11','-O1','-DPANDANOTE_OTA_UI_FIXTURE','-ffunction-sections','-fdata-sections','-I'+str(compat.parent),'-I'+str(include),'-I'+str(include/'QtCore'),'-I'+str(include/'QtGui'),'-I'+str(include/'QtWidgets'),'-I'+str(source/'include'),'-I'+str(config),'-DMBEDTLS_CONFIG_FILE="pandanote_config.h"',*[ROOT/s for s in ui_sources],sha,archive,'-L'+str(library),'-Wl,-rpath,'+str(library),'-Wl,--wrap=open,--gc-sections','-lQt5Widgets','-lQt5Gui','-lQt5Core','-o',ui_binary])
    for folder in ('runtime','ui-review','cache','config'):(OUT/folder).mkdir(mode=0o700,exist_ok=True)
    shutil.copytree(ROOT/'assets',OUT/'assets',dirs_exist_ok=True)
    env={**os.environ,'PANDANOTE_MBEDTLS_SOURCE':str(source),'PANDANOTE_MBEDTLS_HOST_LIB':str(archive),'PANDANOTE_OTA_WORKER_HOST':str(binary),'PANDANOTE_OTA_UI_HOST':str(ui_binary),'QT_QPA_PLATFORM':'offscreen','PANDANOTE_OTA_UI_SCREENSHOTS':str(OUT/'ui-review'),'XDG_RUNTIME_DIR':str(OUT/'runtime'),'XDG_CACHE_HOME':str(OUT/'cache'),'XDG_CONFIG_HOME':str(OUT/'config'),'QT_PLUGIN_PATH':str(library/'qt5/plugins'),'LD_LIBRARY_PATH':str(library)}
    result=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tests'),'-p','test_ota.py','-v'],env=env)
    (OUT/'verification.json').write_text(json.dumps(dict(test_returncode=result.returncode,worker_fixture=str(binary.relative_to(PROJECT)),ui_fixture=str(ui_binary.relative_to(PROJECT)),mbedtls='3.6.7',host_qt='5',hardware_access=False,target_build_performed=False),ensure_ascii=False,indent=2)+'\n')
    return result.returncode

if __name__=='__main__':raise SystemExit(main())
