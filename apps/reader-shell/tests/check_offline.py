"""Check the production release, then use the retained isolated runner only."""
import datetime,json
from pathlib import Path
import run as common

def check_manifest():
    path=common.ROOT/'build/manifest.json'
    if not path.is_file(): raise RuntimeError('production build/manifest.json missing; run build.py first')
    manifest=json.loads(path.read_text())
    if manifest['abi']!={'machine':'MIPS32r2','endian':'little','bits':32,'abi':'o32','nan':'2008','fpu_bits':64,'qreal_bits':32,'loader':'/lib/ld-linux-mipsn8.so.1'}: raise RuntimeError('production ABI contract mismatch')
    files={item['path']:item for item in manifest['artifacts']}
    for needed in ['reader-shell.mipsel','assets/wqy-microhei.ttc','assets/neutral-background.png','licenses/startup/LICENSE.LGPL','licenses/startup/LGPL_EXCEPTION.txt','assets/LICENSE_Apache2.txt']:
        if needed not in files: raise RuntimeError('required release artifact missing: '+needed)
    for name,item in files.items():
        path=Path(name)
        if path.is_absolute() or '..' in path.parts: raise RuntimeError('unsafe manifest path')
        file=common.ROOT/'build'/path
        if file.stat().st_size!=item['bytes'] or common.sha(file)!=item['sha256']: raise RuntimeError('release hash mismatch: '+name)
    for name,digest in manifest['sources'].items():
        if common.sha(common.ROOT/name)!=digest: raise RuntimeError('source provenance changed: '+name)
    return manifest

def main():
    evidence=common.ROOT/'build'/('offline-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'));evidence.mkdir(parents=True)
    try:
        check_manifest()
        binary=common.build(evidence,['content.cpp','navigation.cpp','sync.cpp','shell.cpp','tests/runtime_cases.cpp'],'runtime',support_files=['main.cpp'])
        import shutil
        shutil.copyfile(common.ROOT/'build/reader-shell.mipsel',evidence/'reader-shell.mipsel')
        result=common.execute(binary,evidence)
        if result: return result
        for name in ['production-home','runtime-panel','runtime-retained','runtime-midnight']:
            if not (evidence/(name+'.png')).is_file(): raise RuntimeError('actual Qt frame missing: '+name)
        print('PASS production manifest, actual Qt runtime, bounded developer exit, ordinary lifetime and atomic reload')
        return 0
    except Exception as error: print('FAIL offline: '+str(error));return 1
    finally:
        (evidence/'commands.json').write_text(json.dumps(common.COMMANDS,indent=2)+'\n');print('evidence: '+str(evidence))

if __name__=='__main__': raise SystemExit(main())
