#!/usr/bin/env python3
"""Verify official pinned source and compile project-local MIPS TLS, never execute."""
import concurrent.futures,hashlib,json,subprocess,sys,tarfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'tests'))
import run as common

def build():
    reference=common.PROJECT/'.local-deps/tls';archive=reference/'mbedtls-3.6.7.tar.bz2'
    provenance=json.loads((common.ROOT/'third_party/mbedtls/provenance.json').read_text())
    if '--fetch' in sys.argv[1:]:
        import urllib.request
        reference.mkdir(parents=True,exist_ok=True)
        sums=urllib.request.urlopen(provenance['checksumSource'],timeout=30).read(4097)
        if hashlib.sha256(sums).hexdigest()!=provenance['checksumFileSha256']:raise RuntimeError('official checksums download mismatch')
        data=urllib.request.urlopen(provenance['source'],timeout=30).read(16*1024*1024+1)
        if len(data)>16*1024*1024 or hashlib.sha256(data).hexdigest()!=provenance['sha256'] or provenance['sha256'].encode() not in sums:raise RuntimeError('official source download mismatch')
        archive.write_bytes(data);(reference/'official-sha256sum.txt').write_bytes(sums)
    if not archive.is_file() or common.sha(archive)!=provenance['sha256']: raise RuntimeError('pinned MbedTLS archive absent/hash mismatch; provision project .local-deps/tls first')
    if common.sha(reference/'official-sha256sum.txt')!=provenance['checksumFileSha256']:raise RuntimeError('official checksum manifest mismatch')
    source=reference/'mbedtls-3.6.7'
    # Always reconstruct from the verified archive; never compile a mutable cache.
    import shutil
    if source.exists():shutil.rmtree(source)
    with tarfile.open(archive) as t:
        for m in t.getmembers():
            if m.name.startswith('/') or '..' in Path(m.name).parts or not (m.isfile() or m.isdir()):raise RuntimeError('unsafe source archive')
        t.extractall(reference)
    path=common.WORK+'/tls'
    common.run(['docker','exec',common.CONTAINER,'mkdir','-p',path])
    common.run(['docker','exec',common.CONTAINER,'rm','-rf',path+'/source'])
    common.run(['docker','cp',source,common.CONTAINER+':'+path+'/source'])
    # docker cp to existing folder nests differently: use explicit empty source target.
    common.run(['docker','cp',common.ROOT/'third_party/mbedtls/pandanote_config.h',common.CONTAINER+':'+path+'/pandanote_config.h'])
    files=sorted(p.name for p in (source/'library').glob('*.c'))
    def compile(name):
        args=['docker','exec',common.CONTAINER,'mipsel-linux-gnu-gcc','-std=c99','-Os','-ffunction-sections','-fdata-sections','-EL','-march=mips32r2','-mabi=32','-mhard-float','-mfp64','-mnan=2008','-fPIC','-isystem','/usr/mipsisa32r6el-linux-gnu/include','-DMBEDTLS_CONFIG_FILE="pandanote_config.h"','-I'+path,'-I'+path+'/source/include','-I'+path+'/source/library','-c',path+'/source/library/'+name,'-o',path+'/'+name+'.o']
        r=subprocess.run(args,capture_output=True,text=True)
        if r.returncode:raise RuntimeError(name+': '+r.stderr)
        return name
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(compile,files))
    common.run(['docker','exec',common.CONTAINER,'mipsel-linux-gnu-ar','rcs',path+'/libpandanote-tls.a',*[path+'/'+x+'.o' for x in files]])
    out=common.ROOT/'build';out.mkdir(exist_ok=True)
    common.run(['docker','cp',common.CONTAINER+':'+path+'/libpandanote-tls.a',out/'libpandanote-tls.a'])
    (out/'tls-provenance.json').write_text(json.dumps(dict(upstream=provenance,configSha256=common.sha(common.ROOT/'third_party/mbedtls/pandanote_config.h'),librarySha256=common.sha(out/'libpandanote-tls.a'),compileOnly=True,compilerWork=common.WORK),indent=2)+'\n')
    print('PASS MbedTLS static compilation; archive bytes', (out/'libpandanote-tls.a').stat().st_size)
if __name__=='__main__':build()
