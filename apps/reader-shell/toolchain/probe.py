"""编译一个 C++ 物件并静态检查 ABI，不执行目标代码，也不接触设备。"""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def command(args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def main():
    with tempfile.TemporaryDirectory(prefix='pandanote-probe-') as folder:
        root=Path(folder)
        source=root/'probe.cpp'
        source.write_text('#include <string>\nextern "C" unsigned probe(){std::string s("ota");return s.size();}\n')
        target=root/'probe.o'
        flags=['-EL','-march=mips32r2','-mabi=32','-mhard-float','-mfp64','-mnan=2008','-fPIC']
        command(['mipsel-linux-gnu-g++','-std=c++98',*flags,'-isystem','/usr/mipsisa32r6el-linux-gnu/include','-c',str(source),'-o',str(target)])
        elf=command(['mipsel-linux-gnu-readelf','-h','-A',str(target)])
        markers=['ELF32','little endian','mips32r2','nan2008','o32','Hard float (32-bit CPU, 64-bit FPU)']
        if any(marker not in elf for marker in markers):raise ValueError('编译器输出不符合设备 ABI')
        result=dict(schema=1,compiler=command(['mipsel-linux-gnu-g++','--version']).splitlines()[0],
                    compiler_sha256=hashlib.sha256(Path('/usr/bin/mipsel-linux-gnu-g++').read_bytes()).hexdigest(),
                    packages=Path('/opt/pandanote/packages.txt').read_text(),abi_markers=markers,
                    object_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),elf=elf,
                    target_execution_performed=False,device_access=False,qt_sdk_verified=False)
        print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
