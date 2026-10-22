"""Compile only owned assembly using the existing trusted cross-tool container."""
from pathlib import Path
import subprocess,hashlib,json
ROOT=Path(__file__).resolve().parent
WORK='/work/pandanote-sdio-guard'
def run(args): return subprocess.run(args,check=True,capture_output=True)
def main():
    build=ROOT/'build'; build.mkdir(exist_ok=True)
    run(['docker','exec','pandanote-mips-dev','mkdir','-p',WORK])
    run(['docker','cp',str(ROOT/'storage-guard.S'),'pandanote-mips-dev:'+WORK+'/storage-guard.S'])
    commands=[['mipsel-linux-gnu-as','-EL','-mips32r2','-mfp64','-mnan=2008','storage-guard.S','-o','storage-guard.o'],['mipsel-linux-gnu-ld','-EL','-m','elf32ltsmip','-Ttext','0x84010000','-e','storage_guard','storage-guard.o','-o','storage-guard.elf'],['mipsel-linux-gnu-objcopy','-j','.text','-O','binary','storage-guard.elf','storage-guard.bin']]
    records=[]
    for args in commands:
        r=run(['docker','exec','-w',WORK,'pandanote-mips-dev']+args); records.append(dict(argv=args,stdout=r.stdout.decode(),stderr=r.stderr.decode(),exit_code=r.returncode))
    for name in ('storage-guard.bin','storage-guard.elf'):
        run(['docker','cp','pandanote-mips-dev:'+WORK+'/'+name,str(build/name)])
    dis=run(['docker','exec','-w',WORK,'pandanote-mips-dev','mipsel-linux-gnu-objdump','-d','storage-guard.elf']).stdout
    (ROOT/'evidence/guard-disassembly.txt').write_bytes(dis)
    b=(build/'storage-guard.bin').read_bytes()
    (ROOT/'evidence/guard-build.json').write_text(json.dumps(dict(commands=records,bytes=len(b),sha256=hashlib.sha256(b).hexdigest(),source_sha256=hashlib.sha256((ROOT/'storage-guard.S').read_bytes()).hexdigest(),vendor_execution=False,hardware_execution=False),indent=2)+'\n')
    print(len(b),hashlib.sha256(b).hexdigest())
if __name__=='__main__': main()
