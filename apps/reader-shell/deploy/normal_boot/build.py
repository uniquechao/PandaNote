#!/usr/bin/env python3
"""Offline ordinary-file normal boot candidate; no device apply or execution."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

ROOT=Path(__file__).resolve().parent
DEPLOY=ROOT.parent
PRIMITIVES=('ls_fields','private_file','root_owner','root_single_file','private_directory',
 'prepare_workspace','log','child_identity','spawn','child_running','stop','check_network','check_listeners')
TOUCH_SHA='c54b0fca356b3109f1b6823fe644600ab08294c97aa6950c8236d840628cbbaa'
ADC_SHA='794b959cb02c27a06ba814447236abb90c368d82710090c35132d4e39ccc6ba4'
KEYBOARD_SHA='3629e5b1e58339aa7ce09b8408dfb3453a6458aa77f6f3183c1e71b8de44c78a'
COMMON_SHA='2510ba42b0cba39bf602d120065c57d31c30ed9cb2b541cd3ac9f34fc9c869c5'

def sha(data):return hashlib.sha256(data).hexdigest()
def canon(data):return (json.dumps(data,sort_keys=True,indent=2)+'\n').encode()
def regular(root,name):
 p=PurePosixPath(name)
 if p.is_absolute() or str(p)!=name or '..' in p.parts or not p.parts or not re.fullmatch('[A-Za-z0-9._/-]+',name):raise ValueError('unsafe artifact path')
 target=root
 for part in p.parts:
  target=target/part
  if target.is_symlink():raise ValueError('symlink input')
 if not target.is_file() or target.stat().st_nlink!=1:raise ValueError('not single regular input')
 return target.read_bytes()
def pinned(root,name,digest,size=None):
 data=regular(root,name)
 if sha(data)!=digest or (size is not None and len(data)!=size):raise ValueError('input changed: '+name)
 return data

def suspend_capture(directory,expected):
 if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):raise ValueError('explicit reviewed suspend helper SHA required')
 raw=pinned(directory,'manifest.json',expected);m=json.loads(raw)
 if m.get('application')!='pandanote-normal-suspend' or m.get('execution_performed') is not False:raise ValueError('not suspend helper provenance')
 required={'suspend_helper.c','suspend.in','build_suspend.py','sha256.c','sha256.h'}
 if set(m['source_sha256'])!=required or set(m['startup_sha256'])!={'start.S','entry.h','csu.cpp','libio-init.c'} or set(m['stock_runtime_sha256'])!={'libc.so.6','ld-linux-mipsn8.so.1'}:raise ValueError('suspend helper closure incomplete')
 for name,h in m['source_sha256'].items():
  base=ROOT if name not in ('sha256.c','sha256.h') else ROOT.parents[1]/'third_party/sha256'
  pinned(base,name,h)
 for name,h in m['startup_sha256'].items():pinned(ROOT.parents[1]/'build-support',name,h)
 elf=pinned(directory,'pandanote-normal-suspend.mipsel',m['artifact_sha256'],m['artifact_bytes'])
 return raw,elf

def functions(source,names):
 found={m[1]:m.start() for m in re.finditer(r'(?m)^([a-z][a-z0-9_]*)\(\)\s*\{',source)}
 positions=sorted((pos,name) for name,pos in found.items())
 result=[]
 for name in names:
  if name not in found:raise ValueError('missing function '+name)
  pos=found[name];end=next((other for other,_ in positions if other>pos),len(source))
  result.append(source[pos:end].strip()+'\n')
 return '\n'.join(result)

def build(native, native_sha, reference, radio_binary, output,native_source=None,old_normal_package=None,old_normal_package_sha256=None,live_superblock_sha256=None,suspend_helper_dir=None,suspend_helper_sha256=None):
 upgrade=None
 if any(v is not None for v in (old_normal_package,old_normal_package_sha256,live_superblock_sha256)):
  if not all(v is not None for v in (old_normal_package,old_normal_package_sha256,live_superblock_sha256)):raise ValueError('all explicit NORMAL upgrade inputs required')
  import importlib.util
  spec=importlib.util.spec_from_file_location('normal_upgrade_profile',ROOT/'upgrade_profile.py');profile=importlib.util.module_from_spec(spec);spec.loader.exec_module(profile)
  upgrade=profile.bind(old_normal_package,old_normal_package_sha256,live_superblock_sha256)
 if not re.fullmatch('[0-9a-f]{64}',native_sha):raise ValueError('explicit reviewed native SHA required')
 manifest=pinned(native,'manifest.json',native_sha);meta=json.loads(manifest)
 power_sources={'powerkeys.h','powerkeys.cpp','powerkeys_posix.cpp','powerrequest.h','powerrequest.cpp'}
 if not power_sources<=set(meta.get('sources',{})):raise ValueError('native power keys/request source closure required for current normal service')
 release={'manifest.json':manifest}
 for item in meta['artifacts']:
  name=item['path']
  if name in release:raise ValueError('duplicate native artifact')
  release[name]=pinned(native,name,item['sha256'],item['bytes'])
 native_source=DEPLOY.parent if native_source is None else native_source
 for name,digest in meta['sources'].items():
  pinned(native_source,name,digest)
 if 'normal-suspend-v2' not in meta.get('capabilities',[]):raise ValueError('native normal-suspend-v2 capability required')
 helper_raw,helper_elf=suspend_capture(ROOT/'build/suspend-helper' if suspend_helper_dir is None else suspend_helper_dir,suspend_helper_sha256)
 release['power/suspend-helper.mipsel']=helper_elf;release['power/suspend-helper-manifest.json']=helper_raw
 analysis=reference/'pandanote-analysis/app-development-research'
 release['hardware/focaltech_touch-NO-UPGRADE.ko']=pinned(analysis/'touch-ram-guard','focaltech_touch-RAM-NO-UPGRADE.ko',TOUCH_SHA)
 radio_root=radio_binary.parent if (radio_binary.parent/'radio-stage-inputs.sha256').is_file() else DEPLOY
 stage=(radio_root/'radio-stage-inputs.sha256').read_text()
 if radio_root!=DEPLOY and sha(stage.encode())!='46539141942f2617b1821b8e6f1649eec4f129a95ec5b7302ae1c11ead24feb9':raise ValueError('not approved persistent radio stage')
 for line in stage.splitlines():
  digest,name=line.split()
  if name=='pandanote-radio.mipsel':data=radio_binary.read_bytes()
  else:data=regular(radio_root,name)
  if sha(data)!=digest:raise ValueError('radio stage changed '+name)
  release['radio/'+name]=data
 release['radio/radio-stage-inputs.sha256']=stage.encode()
 common=pinned(radio_root,'radio_init.sh',COMMON_SHA).decode().split('# RUN INIT\n',1)[0]
 names=re.findall(r'(?m)^(radio_[a-z0-9_]+)\(\)',common)
 common=functions(common,[n for n in names if n!='radio_guard_ready'])
 common=common.replace('radio_prepare_runtime() {','radio_prepare_volatile_runtime() {')
 source_files=('early.in','service.in','hardware.in','policy.in','inittab.in','suspend.in','suspend_helper.c','build_suspend.py','build.py','tests/test_list_keys_hardware.py','tests/test_hardware_dither.py')
 sources={n:sha(regular(ROOT,n)) for n in source_files}
 if upgrade is not None:sources['upgrade_profile.py']=sha(regular(ROOT,'upgrade_profile.py'))
 sources['../writable_boot/policy.sh']=sha((DEPLOY/'writable_boot/policy.sh').read_bytes())
 sources['../writable_boot/child-supervisor.sh']=sha((DEPLOY/'writable_boot/child-supervisor.sh').read_bytes())
 sources['../radio_init.sh']=COMMON_SHA
 sources['reviewed-radio-stage-inputs.sha256']=sha(stage.encode())
 adc_base=ROOT.parents[1]/'evidence/battery-static-20261022'
 adc_raw=regular(adc_base,'inputs.json');adc=json.loads(adc_raw)
 if adc['soc_adc.ko']['sha256']!=ADC_SHA or adc['factory_paths']['soc_adc.ko']!='/module_driver/soc_adc.ko':raise ValueError('ADC provenance mismatch')
 pinned(adc_base,'soc_adc.ko',ADC_SHA,adc['soc_adc.ko']['bytes'])
 sources['../../evidence/battery-static-20261022/inputs.json']=sha(adc_raw)
 sources['../../evidence/battery-static-20261022/soc_adc.ko']=ADC_SHA
 boot_id=sha(canon(dict(sources=sources,native_sha256=native_sha,suspend_helper_manifest_sha256=sha(helper_raw))))[:24]
 system='/etc/pandanote-system/'+boot_id
 radio=common+'''\n# Independent normal profile; no RAM/readonly marker or receipt.
. @SYSTEM@/policy.sh
N_PROC=/proc;N_SYS=/sys;N_DEV=/dev
DEV_NET=/sys/class/net
radio_prepare_runtime(){
 normal_wifi_store && radio_prepare_volatile_runtime && normal_wifi_pointer
}
radio_guard_ready(){
 normal_runtime_ok && normal_check_network && normal_check_listeners && radio_check_memory && radio_session_tools_ready || return 1
 if pidof wpa_supplicant udhcpc >/dev/null 2>&1;then return 1;fi
}
umask 077
PATH=/sbin:/bin:/usr/sbin:/usr/bin;export PATH
unset LD_PRELOAD LD_LIBRARY_PATH ENV BASH_ENV
[ "$#" = 1 ] && [ "$1" = --wifi-normal ] || exit 2
RADIO_SCRIPTS=$(CDPATH= cd -P "$(dirname "$0")" && pwd) || exit 1
RADIO_RUNTIME=/tmp/pandanote-connectivity;RADIO_FIRMWARE=/module_driver/firmware
CPUINFO_FILE=/proc/cpuinfo;MODULES_FILE=/proc/modules;KALLSYMS_FILE=/proc/kallsyms
radio_initialize_wifi || exit 1
restore_status=0
printf '[request]\nschema=1\naction=wifi-restore\n' | /tmp/pandanote-connectivity/pandanote-radio.mipsel wifi-restore > /run/pandanote-normal/wifi-restore.status || restore_status=$?
restore_code=$(sed -n 's/^code=//p' /run/pandanote-normal/wifi-restore.status)
case "$restore_code" in
 saved_network_absent) exit 0;;
 association_requested) [ "$restore_status" = 0 ];;
 *) exit 1;;
esac
'''
 release['radio/radio-normal-library.sh']=common.encode()
 release['radio/radio-normal-init.sh']=radio.replace('@SYSTEM@',system).encode()
 index=''.join(sha(data)+'  '+name+'\n' for name,data in sorted(release.items())).encode()
 release['release.sha256']=index
 provenance=json.loads((analysis/'display-runtime-audit/provenance.json').read_text())
 paths={item['source_path']:item['sha256'] for item in provenance}
 drivers=('utils','soc_spi','spi_fb','eink_qingyue426','soc_i2c','keyboard_gpio_add')
 factory={('/module_driver/'+n+'.ko'):paths['/module_driver/'+n+'.ko'] for n in drivers}
 factory['/module_driver/soc_adc.ko']=ADC_SHA
 if factory['/module_driver/keyboard_gpio_add.ko']!=KEYBOARD_SHA:raise ValueError('keyboard factory provenance mismatch')
 for item in meta['stock_libraries']:
  path=item['source_path']
  if '/opt/'==path[:5]:path='/run/pandanote-opt'+path
  factory[path]=item['sha256']
 primitive_source=(DEPLOY/'writable_boot/policy.sh').read_text()
 primitive=functions(primitive_source,['dev_'+n for n in PRIMITIVES]).replace('dev_','normal_')
 replacements={'@SYSTEM@':system,'@BOOT_ID@':boot_id,'@NATIVE_SHA@':native_sha,
  '@RELEASE_INDEX_SHA@':sha(index),'@OWNED_PRIMITIVES@':primitive}
 def render(name):
  text=(ROOT/name).read_text()
  for old,new in replacements.items():text=text.replace(old,new)
  if re.search('@[A-Z_]+@',text):raise ValueError('unexpanded template')
  return text.encode()
 system_files={n[:-3]+'.sh':render(n) for n in ('early.in','service.in','hardware.in','policy.in','suspend.in')}
 system_files['child-supervisor.sh']=(DEPLOY/'writable_boot/child-supervisor.sh').read_bytes()
 system_files['factory.sha256']=''.join(d+'  '+p+'\n' for p,d in sorted(factory.items())).encode()
 system_files['SHA256SUMS']=''.join(sha(d)+'  '+n+'\n' for n,d in sorted(system_files.items())).encode()
 targets=[];output.mkdir(parents=True,exist_ok=False)
 def store(path,data,mode,role):
  source='files/'+path.lstrip('/');p=output/source;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);p.chmod(mode)
  targets.append(dict(path=path,source=source,sha256=sha(data),bytes=len(data),mode=mode,role=role))
 for name,data in sorted(release.items()):store('/user/pandanote/apps/releases/'+native_sha+'/'+name,data,0o700 if name in ('reader-shell.mipsel','power/suspend-helper.mipsel') else 0o600,'release')
 for name,data in sorted(system_files.items()):store(system+'/'+name,data,0o600,'system')
 store('/user/pandanote/apps/current',(native_sha+'\n').encode(),0o600,'pointer')
 store('/etc/inittab',render('inittab.in'),0o644,'entry')
 old=reference/'pandanote-analysis/factory-backup-20261020/inspection/etc__inittab.txt'
 result=dict(schema=1,profile='normal-persistent-v1',boot_id=boot_id,native_sha256=native_sha,
  device_apply_supported=False,transport=None,capabilities=['normal-suspend-v2'],suspend_helper_manifest_sha256=sha(helper_raw),adc_module_sha256=ADC_SHA,scope='offline ordinary-file clone candidate',
  old_inittab_sha256=upgrade['old_inittab_sha256'] if upgrade is not None else sha(old.read_bytes()),files=targets,sources=sources,
  forbidden_writes=['p1/kernel','bootloader','GPT','DDR','touch-firmware','boot0','boot1','RPMB'],
  pending=['physical normal boot before-userspace helper/touch check','normal boot display/touch/USB acceptance',
   'physical normal-boot saved Wi-Fi restore and reconnection','physical interrupted-update durability'],
  root_mount_note='stock boot ro may replay ext4 journal; no noload claim',
  rollback_note='restore exact previous ordinary inittab and current bytes; not whole-device restoration')
 if upgrade is not None:result['upgrade_from']=upgrade
 (output/'manifest.json').write_bytes(canon(result));return result

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--native-build',type=Path,required=True);p.add_argument('--native-sha256',required=True)
 p.add_argument('--native-source',type=Path,help='explicit reviewed source checkout; defaults to this reader-shell checkout')
 p.add_argument('--reference-root',type=Path,required=True);p.add_argument('--radio-binary',type=Path,required=True)
 p.add_argument('--suspend-helper-dir',type=Path);p.add_argument('--suspend-helper-sha256')
 p.add_argument('--output',type=Path,default=ROOT/'build/candidate')
 p.add_argument('--old-normal-package',type=Path);p.add_argument('--old-normal-package-sha256');p.add_argument('--live-superblock-sha256')
 a=p.parse_args();m=build(a.native_build,a.native_sha256,a.reference_root,a.radio_binary,a.output,a.native_source,a.old_normal_package,a.old_normal_package_sha256,a.live_superblock_sha256,a.suspend_helper_dir,a.suspend_helper_sha256)
 print(json.dumps(dict(boot_id=m['boot_id'],files=len(m['files']),bytes=sum(f['bytes'] for f in m['files']),
  manifest_sha256=sha(canon(m)),device_apply_supported=False),indent=2))
if __name__=='__main__':main()
