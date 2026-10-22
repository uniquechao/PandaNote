#!/usr/bin/env python3
"""Compile and inspect only. Never execute linked MIPS/vendor ELF here."""
import datetime,json,shutil,sys,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'tests'))
import run as common

def main():
    output=common.ROOT/'build';output.mkdir(exist_ok=True)
    manifest=output/'manifest.json';manifest.unlink(missing_ok=True)
    evidence=output/('production-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'));evidence.mkdir()
    try:
        for item in json.loads((common.ROOT/'assets/font-provenance.json').read_text())['files']:
            if common.sha(common.ROOT/'assets'/item['file'])!=item['sha256']: raise RuntimeError('font input hash failed: '+item['file'])
        startup_reference={}
        for name in ['start.S','entry.h','csu.cpp','libio-init.c']:
            reference=common.MINIMAL/'build-support'/name
            digest=common.sha(reference)
            if common.sha(common.ROOT/'build-support'/name)!=digest: raise RuntimeError('startup adapter differs from retained baseline: '+name)
            startup_reference[name]=digest
        binary=common.build(evidence,['content.cpp','navigation.cpp','sync.cpp','localapps.cpp','shell.cpp','main.cpp'],'reader-shell')
        shutil.copyfile(binary,output/'reader-shell.mipsel')
        shutil.copytree(common.ROOT/'assets',output/'assets',dirs_exist_ok=True)
        shutil.copytree(common.ROOT/'build-support',output/'licenses/startup',dirs_exist_ok=True)
        shutil.copytree(common.ROOT/'third_party/sha256',output/'licenses/sha256',dirs_exist_ok=True)
        shutil.copytree(common.ROOT/'third_party/mbedtls',output/'licenses/mbedtls',dirs_exist_ok=True)
        shutil.copyfile(output/'tls-provenance.json',output/'licenses/mbedtls/build-provenance.json')
        shutil.copyfile(common.ROOT/'README.txt',output/'README.txt')
        shutil.copyfile(common.ROOT/'local_apps_tool.py',output/'local_apps_tool.py')
        shutil.copyfile(evidence/'reader-shell-elf.txt',output/'reader-shell-elf.txt')
        worker=common.build(evidence,['sync.cpp','ota_worker.cpp','ota/json.cpp','ota/storage.cpp','ota/authorization.cpp','ota/device.cpp','ota/crypto.cpp','ota/power.cpp','battery.cpp','battery_posix.cpp'],'ota-worker')
        (output/'ota').mkdir(exist_ok=True)
        shutil.copyfile(worker,output/'ota/ota-worker.mipsel')
        subprocess.run([sys.executable,str(common.ROOT/'deploy/normal_boot/build_apply.py'),'--ota-upgrade'],check=True)
        helper=common.ROOT/'deploy/normal_boot/build/ota-tool'
        shutil.copyfile(helper/'pandanote-ota-upgrade.mipsel',output/'ota/pandanote-ota-upgrade.mipsel')
        shutil.copyfile(helper/'manifest.json',output/'ota/helper-manifest.json')
        artifacts=[output/'ota/pandanote-ota-upgrade.mipsel',output/'ota/helper-manifest.json',output/'ota/ota-worker.mipsel',output/'reader-shell.mipsel' ,output/'reader-shell-elf.txt',output/'README.txt',output/'local_apps_tool.py']
        for folder in ['assets','licenses']:
            artifacts.extend(p for p in (output/folder).rglob('*') if p.is_file())
        source_files=['dnsconfig.h','dnsconfig.cpp','tests/test_dnsconfig.py','tests/dnsconfig_cases.cpp','tests/offline_dnsconfig.py','tests/probe_public_tls.py','tests/device_cases.cpp','tests/tls_cases.cpp','tests/offline_tls.py','resolver.h','resolver.cpp','tlsclock.h','tlsclock.cpp','tests/test_resolver.py','tests/resolver_cases.cpp','tests/test_tlsclock.py','tests/tlsclock_cases.cpp','battery.h','battery.cpp','battery_posix.cpp','powerrequest.h','powerrequest.cpp','powerkeys.h','powerkeys.cpp','powerkeys_posix.cpp','einkrefresh.cpp','einkrefresh_posix.cpp','einkrefresh.h','build.py','startupretry.h','standbypolicy.h','tests/test_timeanchor.py','tests/timeanchor_fixture.cpp','tests/test_standbypolicy.py','tests/standbypolicy_fixture.cpp','tests/test_standby_runtime.py','tests/standby_runtime_fixture.cpp','tests/test_powerkeys.py','tests/test_listkeys.py','tests/listkeys_fixture.cpp','tests/test_powerkeys_boundary.py','tests/power_snapshot_probe.cpp','tests/powerkeys_fixture.cpp','tests/test_suspendrequest.py','tests/suspendrequest_fixture.cpp','tests/shell_cases.cpp','tests/test_startup_retry.py','tests/startup_retry_fixture.cpp','systemclock.cpp','systemclock.h','systemclock_posix.cpp','main.cpp','shell.cpp','systemui.cpp','shell.h','navigation.cpp','navigation.h','localapps.cpp','localapps.h','bluetooth.cpp','bluetooth.h','bluetooth_ui.cpp','bluetooth-ipc-contract.txt','local_apps_tool.py','content.cpp','content.h','sync.cpp','sync.h','tls.cpp','tls.h','build_tls.py','tests/run.py','tests/systemclock_fixture.cpp','tests/systemclock_cases.cpp','tests/test_systemclock.py','README.txt']
        source_files += ['ota_ui.cpp','ota_worker.cpp','deploy/normal_boot/apply_tool.c','deploy/normal_boot/build_apply.py','deploy/normal_boot/upgrade_wire.h','deploy/normal_boot/upgrade_target.h','tests/ota_host.cpp','tests/ota_worker_host.cpp','tests/run_ota_host.py','tests/test_ota.py','deploy/normal_boot/prepare_ota.py']+[str(p.relative_to(common.ROOT)) for p in (common.ROOT/'ota').glob('*') if p.is_file()]
        source_files += [str(p.relative_to(common.ROOT)) for p in (common.ROOT/'tests/tls-fixtures/domain').rglob('*') if p.is_file()]
        source_files += [str(p.relative_to(common.ROOT)) for folder in ['build-support','third_party/sha256','third_party/mbedtls','assets'] for p in (common.ROOT/folder).rglob('*') if p.is_file()]
        data={'capabilities':['normal-suspend-v2','device-ota-v1'],'schema':1,'application':'reader-shell','created_at':datetime.datetime.now().astimezone().isoformat(),
          'abi':{'machine':'MIPS32r2','endian':'little','bits':32,'abi':'o32','nan':'2008','fpu_bits':64,'qreal_bits':32,'loader':'/lib/ld-linux-mipsn8.so.1'},
          'qt_source_commit':'092cd760d5fddf9640a310214fe01929f0fff3a8','startup_reference_sha256':startup_reference,'stock_libraries':json.loads((common.ANALYSIS/'app-development-research/qt-stock-sysroot/original-library-provenance.json').read_text()),
          'sources':{name:common.sha(common.ROOT/name) for name in sorted(source_files)},
          'artifacts':[{'path':str(p.relative_to(output)),'bytes':p.stat().st_size,'sha256':common.sha(p)} for p in sorted(artifacts)],
          'build_evidence':str(evidence.relative_to(common.PROJECT)), 'execution_performed':False,
          'deployment':{'executable':'reader-shell.mipsel','adjacent_assets':'assets','content_default':'data/current','content_not_bundled':True,'licenses':'licenses'}}
        manifest.write_text(json.dumps(data,indent=2)+'\n')
        print('PASS production build: build/reader-shell.mipsel and build/manifest.json (static only)')
        return 0
    except Exception as error: print('FAIL build: '+str(error));return 1
    finally: (evidence/'commands.json').write_text(json.dumps(common.COMMANDS,indent=2)+'\n')

if __name__=='__main__': raise SystemExit(main())
