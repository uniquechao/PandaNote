"""隔离编译环境的输入、挂载和产物边界；夹具不是原厂 SDK。"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pandanote_toolchain',ROOT/'toolchain.py')
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)


class ToolchainTests(unittest.TestCase):
    def setUp(self):
        output=ROOT/'build/toolchain-tests';output.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=output);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        self.patches=[patch.object(tool,'OUT',self.root/'receipt')]
        for item in self.patches:item.start();self.addCleanup(item.stop)

    def sdk(self):
        ref=self.root/'reference';analysis=ref/'pandanote-analysis'
        minimal=analysis/'app-development-research/minimal-qt'
        stock=analysis/'app-development-research/qt-stock-sysroot';stock.mkdir(parents=True)
        for name in ('start.S','entry.h','csu.cpp','libio-init.c'):
            path=minimal/'build-support'/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/'build-support'/name,path)
        for name in ('QtCore/qglobal.h','QtCore/qconfig.h','QtGui/qwidget.h'):
            path=minimal/'include'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('/* 合成 SDK 夹具 */')
        rows=[]
        for name in sorted(tool.RUNTIMES):
            path=stock/name;path.write_bytes(name.encode());rows.append(dict(name=name,sha256=tool.sha(path)))
        (stock/'original-library-provenance.json').write_text(json.dumps(rows))
        (analysis/'qt-sdk-source/qt-4.7.4').mkdir(parents=True)
        return ref,stock

    def test_missing_sdk_reports_all_prerequisites_without_docker(self):
        with patch.object(tool,'run',side_effect=ValueError('缺少 Qt 源码')) as run:
            report=tool.doctor(self.root/'absent')
        self.assertFalse(report['ready_for_target_build']);self.assertGreaterEqual(len(report['errors']),9)
        self.assertFalse(report['target_execution_performed']);self.assertEqual(run.call_args.args[0][0],'git')

    def test_sdk_hashes_and_qt_revision_are_checked(self):
        ref,stock=self.sdk()
        with patch.object(tool,'run',return_value=tool.QT_COMMIT):
            self.assertTrue(tool.doctor(ref)['ready_for_target_build'])
            (stock/'libc.so.6').write_bytes(b'changed')
            self.assertFalse(tool.doctor(ref)['ready_for_target_build'])
        with patch.object(tool,'run',return_value='0'*40):self.assertFalse(tool.doctor(ref)['ready_for_target_build'])

    def test_sdk_does_not_follow_links_outside_reference(self):
        ref,stock=self.sdk();outside=self.root/'outside';outside.write_bytes(b'outside')
        (stock/'libc.so.6').unlink();(stock/'libc.so.6').symlink_to(outside)
        with patch.object(tool,'run',return_value=tool.QT_COMMIT):
            self.assertTrue(any('越出' in error for error in tool.doctor(ref)['errors']))

    def container(self):
        reference=self.root/'reference'
        record=dict(Config=dict(User=str(os.getuid())+':'+str(os.getgid())),State=dict(Status='running'),Image='sha256:'+'1'*64,
                    HostConfig=dict(NetworkMode='none',ReadonlyRootfs=True,Privileged=False,Devices=[],DeviceRequests=None,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
                    Mounts=[dict(Type='bind',Source=str(source.resolve()),Destination=target,RW=rw) for source,target,rw in tool.mounts(reference)])
        return reference,record

    def test_container_rejects_network_devices_and_extra_mounts(self):
        reference,record=self.container()
        for change in ('network','device','mount','readonly','image','user'):
            value=copy.deepcopy(record)
            if change=='network':value['HostConfig']['NetworkMode']='host'
            elif change=='device':value['HostConfig']['Devices']=[dict(PathOnHost='/dev/usb')]
            elif change=='mount':value['Mounts'].append(dict(Type='bind',Source='/var/run/docker.sock',Destination='/var/run/docker.sock',RW=True))
            elif change=='readonly':value['HostConfig']['ReadonlyRootfs']=False
            elif change=='user':value['Config']['User']='other'
            else:value['Image']='sha256:'+'2'*64
            with self.subTest(change=change),patch.object(tool,'image_id',return_value=record['Image']),patch.object(tool,'run',return_value=json.dumps([value])):
                with self.assertRaises(ValueError):tool.verify_container(reference)

    def test_existing_stopped_container_is_checked_before_restart(self):
        reference,record=self.container();record['State']['Status']='exited'
        with patch.object(tool,'image_id',return_value=record['Image']),patch.object(tool,'run',return_value=json.dumps([record])):
            tool.verify_container(reference,running=False)
            with self.assertRaises(ValueError):tool.verify_container(reference)

    def test_concurrent_build_is_rejected_before_mutation(self):
        with tool.build_guard():
            with self.assertRaises(ValueError):
                with tool.build_guard():self.fail('并发编译不应获得同一工作目录')

    def test_archive_copy_preserves_owner_only_when_explicitly_enabled(self):
        for path in (ROOT/'tests/run.py',ROOT/'deploy/normal_boot/build_apply.py',ROOT/'deploy/normal_boot/build_suspend.py'):
            name='copy_fixture_'+path.stem
            spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            for enabled in ('0','1'):
                with self.subTest(path=path.name,enabled=enabled),patch.dict(os.environ,{'PANDANOTE_COMPILER_ARCHIVE_COPY':enabled}),patch.object(module.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')) as call:
                    module.run(['docker','cp','from','to'])
                    self.assertEqual(call.call_args.args[0],['docker','cp',*(['--archive'] if enabled=='1' else []),'from','to'])

    def test_compile_uses_verified_container_and_packages_only_after_all_builds(self):
        reference=self.root/'reference';events=[]
        def compile_step(args,**kwargs):
            events.append(Path(args[1]).name)
            self.assertEqual(kwargs['env']['PANDANOTE_COMPILER_CONTAINER'],tool.CONTAINER)
            self.assertEqual(kwargs['env']['PANDANOTE_REFERENCE_ROOT'],str(reference))
            self.assertEqual(kwargs['env']['PANDANOTE_COMPILER_ARCHIVE_COPY'],'1')
            self.assertEqual(kwargs['env']['PANDANOTE_COMPILER_WORK'],'/work/pandanote-native-completion')
            self.assertTrue(kwargs['check'])
        def package():events.append('bundle');return {'packaged':True}
        with patch.dict(os.environ,{'PANDANOTE_COMPILER_CONTAINER':'unverified-container'}),patch.object(tool,'require_sdk',return_value=reference),patch.object(tool,'start'),patch.object(tool,'verify_container'),patch.object(tool.subprocess,'run',side_effect=compile_step),patch.object(tool,'bundle_native',side_effect=package):
            self.assertTrue(tool.compile_target(reference,True)['packaged'])
        self.assertEqual(events,['build_tls.py','build.py','build_suspend.py','bundle'])

    def test_failed_target_build_stops_before_packaging(self):
        reference=self.root/'reference'
        with patch.object(tool,'require_sdk',return_value=reference),patch.object(tool,'start'),patch.object(tool,'verify_container'),patch.object(tool.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['compiler'])),patch.object(tool,'bundle_native') as package:
            with self.assertRaises(subprocess.CalledProcessError):tool.compile_target(reference,False)
            package.assert_not_called()

    def test_tls_failure_removes_only_its_temporary_container(self):
        with patch.object(tool,'image_id',return_value='sha256:'+'1'*64),patch.object(tool,'run',return_value='') as docker,patch.object(tool.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['compiler'])):
            with self.assertRaises(subprocess.CalledProcessError):tool.compile_tls(False)
        calls=[call.args[0] for call in docker.call_args_list]
        name=calls[0][calls[0].index('--name')+1]
        self.assertTrue(name.startswith('pandanote-mips-tls-'))
        self.assertEqual(calls[-1],['docker','rm','-f',name])
        self.assertNotEqual(name,tool.CONTAINER)

    def native(self):
        app=self.root/'project/apps/reader-shell';native=app/'build';native.mkdir(parents=True)
        rows=[]
        for name in ('reader-shell.mipsel','ota/ota-worker.mipsel','ota/pandanote-ota-upgrade.mipsel','ota/helper-manifest.json'):
            path=native/name;path.parent.mkdir(exist_ok=True);path.write_bytes(b'fixture-'+name.encode());rows.append(dict(path=name,sha256=tool.sha(path),bytes=path.stat().st_size))
        manifest=dict(execution_performed=False,capabilities=['device-ota-v1','normal-suspend-v2'],artifacts=rows)
        (native/'manifest.json').write_text(json.dumps(manifest))
        return app,native,manifest

    def test_bundle_contains_only_manifest_artifacts_and_is_not_deployable(self):
        app,native,manifest=self.native();(native/'private-token').write_text('此文件不得进入构建包')
        with patch.object(tool,'ROOT',app),patch.object(tool,'PROJECT',self.root/'project'),patch.object(tool,'OUT',app/'build/toolchain'):
            result=tool.bundle_native()
            with tarfile.open(self.root/'project'/result['path']) as archive:
                self.assertEqual(set(archive.getnames()),{'native/manifest.json',*('native/'+row['path'] for row in manifest['artifacts'])})
        self.assertFalse(result['ota_deployable']);self.assertFalse(result['target_execution_performed'])

    def test_bundle_rejects_changed_artifact_or_path_escape(self):
        app,native,manifest=self.native()
        with patch.object(tool,'ROOT',app),patch.object(tool,'OUT',app/'build/toolchain'):
            (native/'reader-shell.mipsel').write_bytes(b'changed')
            with self.assertRaises(ValueError):tool.bundle_native()
            manifest['artifacts'][0]['path']='../private-token';(native/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):tool.bundle_native()


if __name__=='__main__':unittest.main()
