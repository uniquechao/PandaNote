#!/usr/bin/env python3
"""Create a deterministic, verified application package without vendor libraries."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import stage_ram as stage

ROOT = Path(__file__).resolve().parent
DELIVERY = '''PandaNote 966U2 Reader Shell Phase 1 — application delivery

Status: offline Qt/content/navigation checks passed (SIMULATED input/time).
RAM: controller completed a separately reviewed 120-second bounded run with
developer_timeout/0 on explicitly selected existing ADB5037. Protection/resource
evidence and a later readable Chinese framebuffer are retained in the checkout.
Later real touch Home -> Panel -> Schedule failed: kernel OOM killed the app
(exit137), leaving the visible Panel stale. Human navigation acceptance failed.
The env-only candidate uses QWS_NO_SHARE_FONTS=1 with unchanged native ELF/font,
disabling shared QPF caches; offline validated, physical re-test pending.
CmaTotal/CmaFree are logged read-only; existing guard thresholds are unchanged.
Human ink/readability, five entries/back and real 60-second idle remain pending.
No persistent installation has been performed.

release/ is the unchanged reviewed production output with adjacent assets/.
Its manifest is pinned by SHA256 in source/stage_ram.py. source/ includes owned
application/build source, font/startup/SHA256 attribution and host delivery tools.
No original vendor libraries, storage image, boot transport or installer bundled.
Original Qt4.7.4/glibc runtime dependencies and SHA256 are listed in the release
manifest. Obtain the verified SDK separately; four absent Qt/freetype libraries
may be copied only to checked RAM by the explicit bounded-test command.

From the project checkout (requires the existing guarded RAM device/session):
  python3 apps/reader-shell/stage_ram.py --check-only
  python3 apps/reader-shell/stage_ram.py --run-bounded-test --timeout-ms 120000
  python3 apps/reader-shell/package.py
Select an existing localhost server explicitly with --adb-port 5037 or5039
(default5039). There is no automatic fallback or server startup. The controller
last used the exact RAM serial on5037 after5039 became unavailable.
Default check-only does not transfer or execute anything. The explicit run uses
/tmp/reader-shell, checked stock libraries, and standalone --qws-server plus
--developer-mode --developer-timeout-ms. It refuses existing QWS/factory servers,
unknown/symlink/partial staging trees, missing protections and hash mismatches.
It cannot bootstrap, reset, load drivers, remount, change networking or install.
It does not inject touch. A developer_timeout is not physical navigation proof.
Original minimal application/reference files/backups remain reference-only.

This is an application/source archive, not a standalone SDK. To rebuild, restore
the separately verified Qt4.7.4 headers/sysroot and trusted pandanote-mips-dev compiler
referenced by build.py/tests/run.py. Never execute linked MIPS/vendor ELF on the
Mac or in the compiler container. Read release/README.txt for ABI and interfaces.
All license files remain alongside the font, startup adapter and SHA256 source.
'''


def capture_verified(file, name, expected_sha256, expected_size=None):
    """Validate the one captured buffer, not a separate read of its path."""
    data = file.read_bytes()
    if expected_size is not None and len(data) != expected_size:
        raise ValueError('captured size mismatch: '+name)
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError('captured hash mismatch: '+name)
    return data


def create_package(output=ROOT/'build/package'):
    manifest, release, records = stage.verify_release()
    content = {}
    for name, file in release.items():
        record = records[name]
        expected_sha = stage.REVIEWED_MANIFEST_SHA if name=='manifest.json' else record['sha256']
        content['release/'+name] = capture_verified(file, 'release/'+name, expected_sha, record['bytes'])
    for name, digest in manifest['sources'].items():
        # Build manifest sources pin SHA256 (no separate source-size field).
        content['source/'+name] = capture_verified(stage.safe_file(ROOT,name), 'source/'+name, digest)
    for name in ('stage_ram.py','package.py','tests/test_stage_ram.py','tests/test_package.py'):
        content['source/'+name] = stage.safe_file(ROOT,name).read_bytes()
    content['DELIVERY.txt'] = DELIVERY.encode('utf-8')
    inventory = {'schema':1,'reviewed_build_manifest_sha256':stage.REVIEWED_MANIFEST_SHA,
        'vendor_libraries_bundled':False,'persistently_installed':False,
        'physical_acceptance':'FAILED prior human navigation (OOM exit137); font-cache candidate offline validated; physical re-test pending',
        'files':{name:hashlib.sha256(data).hexdigest() for name,data in sorted(content.items())}}
    content['package-manifest.json'] = (json.dumps(inventory,indent=2)+'\n').encode()
    output.mkdir(parents=True,exist_ok=True)
    archive = output/'reader-shell-phase1.tar.gz'
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w',format=tarfile.USTAR_FORMAT) as bundle:
        for name,data in sorted(content.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name=='release/reader-shell.mipsel' else 0o644
            info.mtime = 0
            bundle.addfile(info,io.BytesIO(data))
    with archive.open('wb') as file:
        with gzip.GzipFile(filename='',mode='wb',fileobj=file,mtime=0) as compressed:
            compressed.write(buffer.getvalue())
    # Reopen and validate every emitted byte/member; never extract untrusted paths.
    with tarfile.open(archive) as bundle:
        if bundle.getnames() != sorted(content):
            raise ValueError('package member mismatch')
        for member in bundle.getmembers():
            if not member.isfile() or bundle.extractfile(member).read() != content[member.name]:
                raise ValueError('package verification failed: '+member.name)
    (output/'package-manifest.json').write_text(json.dumps(inventory,indent=2)+'\n')
    (output/'SHA256SUMS').write_text(stage.sha(archive)+'  '+archive.name+'\n')
    return archive,inventory


def main():
    archive,inventory = create_package()
    print(json.dumps({'status':'package_verified','archive':str(archive.relative_to(stage.PROJECT)),
        'sha256':stage.sha(archive),'files':len(inventory['files']), 'vendor_libraries_bundled':False,
        'physical_acceptance':'PENDING','persistently_installed':False},indent=2))


if __name__=='__main__':
    main()
