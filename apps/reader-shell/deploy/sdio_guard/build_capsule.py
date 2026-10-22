"""Build pinned capsule and regenerate CRC bootstrap using trusted assembler only."""
import hashlib,json,subprocess,zlib,shutil
from pathlib import Path
from ram_capsule import build_capsule,KERNEL_SHA,GUARD_SHA,PID1_SHA
ROOT=Path(__file__).resolve().parent
REF=(Path(__import__('os').environ.get('PANDANOTE_REFERENCE_ROOT', 'external-inputs')) / 'pandanote-analysis/app-development-research/ram-linux-research')
WORK='/work/pandanote-sdio-guard'
def run(args): return subprocess.run(args,check=True,capture_output=True)
def main():
    build=ROOT/'build'; build.mkdir(exist_ok=True)
    kernel=(REF/'kernel-RAM-ANALYSIS-ONLY-NOT-FOR-FLASH.bin').read_bytes()
    guard=(build/'storage-guard.bin').read_bytes(); pid1=(ROOT/'pid1-ram.sh').read_bytes()
    capsule=build_capsule(kernel,guard,pid1)
    (build/'kernel-RAM-ANALYSIS-ONLY-NOT-FOR-FLASH.bin').write_bytes(kernel)
    (build/'pid1-ram.sh').write_bytes(pid1)
    entries=[]; lines=['crc_ranges:']; ranges=[]
    for address,blob in capsule['segments'].items():
        name='ram-'+format(address,'08x')+'.bin'; (build/name).write_bytes(blob)
        entries.append(dict(address=hex(address),file=name,bytes=len(blob),sha256=hashlib.sha256(blob).hexdigest()))
        uncached=address&0x1fffffff|0xa0000000
        ranges.append([uncached,len(blob)])
        lines.append('    .word '+','.join(hex(v) for v in (uncached,len(blob),zlib.crc32(blob))))
    lines+=['crc_ranges_end:','crc_table:']
    for i in range(256):
        for bit in range(8): i=(i>>1)^(0xedb88320 if i&1 else 0)
        lines.append('    .word '+hex(i))
    (build/'bootstrap-capsule-inputs.inc').write_text('\n'.join(lines)+'\n')
    source=(REF/'bootstrap-selfcheck.S').read_bytes()
    # Preserve exact existing bootstrap and memory probes; only its CRC inputs change.
    assert hashlib.sha256(source).hexdigest()=='0ee242bcf70b50bdf6eb4707fe7137638ddbe207c959d91e6cfeebbcd4fd2b6b'
    (build/'bootstrap-selfcheck.S').write_bytes(source)
    for name in ('bootstrap-selfcheck.S','bootstrap-capsule-inputs.inc'):
        run(['docker','cp',str(build/name),'pandanote-mips-dev:'+WORK+'/'+name])
    commands=[['mipsel-linux-gnu-as','-EL','-mips32r2','-mfp64','-mnan=2008','bootstrap-selfcheck.S','-o','bootstrap-selfcheck.o'],['mipsel-linux-gnu-ld','-EL','-m','elf32ltsmip','-Ttext','0x81000000','-e','boot_selfcheck','bootstrap-selfcheck.o','-o','bootstrap-selfcheck.elf'],['mipsel-linux-gnu-objcopy','-j','.text','-O','binary','bootstrap-selfcheck.elf','bootstrap-selfcheck.bin']]
    for args in commands: run(['docker','exec','-w',WORK,'pandanote-mips-dev']+args)
    for name in ('bootstrap-selfcheck.elf','bootstrap-selfcheck.bin'): run(['docker','cp','pandanote-mips-dev:'+WORK+'/'+name,str(build/name)])
    symbols=run(['docker','exec','-w',WORK,'pandanote-mips-dev','mipsel-linux-gnu-nm','-n','bootstrap-selfcheck.elf']).stdout.decode()
    names={row.split()[2]:hex(int(row.split()[0],16)&0xffffffff) for row in symbols.splitlines() if len(row.split())==3 and row.split()[2] in ('boot_selfcheck','crc32_ram','halt')}
    blob=(build/'bootstrap-selfcheck.bin').read_bytes()
    assert len(blob)<=4096 and names['boot_selfcheck']=='0x81000000'
    result=dict(bytes=len(blob),sha256=hashlib.sha256(blob).hexdigest(),address='0x81000000',status_address='0x8100f000',symbols=names,crc_ranges=ranges,hardware_execution_permitted=False)
    (build/'bootstrap-build-result.json').write_text(json.dumps(result,indent=2)+'\n')
    manifest=dict(profile='msc1-sdio-wlan0-opt-ro-v1',segments=entries,bootstrap=result,kernel_sha256=KERNEL_SHA,guard_sha256=GUARD_SHA,pid1_sha256=PID1_SHA,guard_host_ioaddr='0xb3460000',guard_host_ioaddr_offset=16,additional_opcodes=[52,53],mmc0_policy='golden unchanged',linux_memory='64M@0',physical_128m_confirmed=False,commandline_bytes=len(capsule['commandline']),hardware_execution_permitted=False,flash_image=False,guard_proof_marker='/tmp/pandanote-sdio-host1-guard-v1',guard_proof_literal='msc1-only-sdio-cmd52-cmd53-emmc-filter-unchanged-v1',guard_proof_publisher='root controller only after artifact/boot verification; not PID1',optional_mount='/dev/mmcblk0p5 /run/pandanote-opt ext4 ro,noload; not automatically mounted')
    (ROOT/'evidence/build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))
if __name__=='__main__': main()
