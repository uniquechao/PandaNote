"""Read-only ELF disassembly; does not load or emulate vendor instructions."""
import hashlib, io, json
from pathlib import Path
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN
ROOT=Path(__file__).resolve().parent
MODULE=Path(__import__('os').environ.get('PANDANOTE_SDIO_MODULE', 'external-inputs/soc_msc.ko'))
b=MODULE.read_bytes()
assert hashlib.sha256(b).hexdigest()=='d26f82b457547d116f453102e4a936dee9bd826416ebbcd6900a592563e0bed7'
e=ELFFile(io.BytesIO(b)); syms=e.get_section_by_name('.symtab'); text=e.get_section_by_name('.text')
cs=Cs(CS_ARCH_MIPS,CS_MODE_MIPS32|CS_MODE_LITTLE_ENDIAN)
relocs={r['r_offset']:syms.get_symbol(r['r_info_sym']).name for r in e.get_section_by_name('.rel.text').iter_relocations()}
lines=[]
for ins in cs.disasm(text.data(),0):
    lines.append(f'{ins.address:08x}: {ins.bytes.hex()} {ins.mnemonic} {ins.op_str} '+relocs.get(ins.address,''))
(ROOT/'evidence/module-disassembly.txt').write_text('\n'.join(line.rstrip() for line in lines)+'\n')
lines=[]
for s in syms.iter_symbols():
    if s.name in ('msc0_device','msc1_device','msc2_device','msc0_resources','msc1_resources','msc2_resources','sdhci_ingenic_probe'):
        lines.append(f'{s.name} {s.entry}')
        if isinstance(s['st_shndx'],int) and s['st_size']:
            sec=e.get_section(s['st_shndx']); value=s['st_value']; data=sec.data()[value:value+s['st_size']]
            if sec.name!='.text': lines.append(f'{sec.name} + {value:x}: {data.hex()}')
for sec in e.iter_sections():
    if sec.name.startswith('.rel') and sec.name!='.rel.text':
        for r in sec.iter_relocations():
            name=syms.get_symbol(r['r_info_sym']).name
            if name in ('msc0_device','msc1_device','msc2_device','msc0_resources','msc1_resources','msc2_resources'): lines.append(f'{sec.name} {r.entry} -> {name}')
(ROOT/'evidence/module-resources.txt').write_text('\n'.join(line.rstrip() for line in lines)+'\n')
print('Static module resource and disassembly evidence written')
k=(Path(__import__('os').environ.get('PANDANOTE_REFERENCE_ROOT', 'external-inputs')) / 'pandanote-analysis/factory-backup-20261020/inspection/kernel-decompressed.bin').read_bytes()
assert hashlib.sha256(k).hexdigest()=='ce4e204c337d342fa9eb39a96cffcd7f03dc74df01a3ef1e6f205262652ed0bf'
lines=[]
for start,end in [(0x800329f0,0x80032a38),(0x8029f740,0x8029f7a0),(0x8035c450,0x8035c590)]:
    for ins in cs.disasm(k[start-0x80010000:end-0x80010000],start):
        lines.append(f'{ins.address:08x}: {ins.bytes.hex()} {ins.mnemonic} {ins.op_str}')
(ROOT/'evidence/kernel-identity-disassembly.txt').write_text('\n'.join(line.rstrip() for line in lines)+'\n')

import struct
resources=[]
data=e.get_section_by_name('.data').data()
for index,expected in enumerate((0x13450000,0x13460000,0x13490000)):
    device=syms.get_symbol_by_name(f'msc{index}_device')[0]['st_value']
    resource=syms.get_symbol_by_name(f'msc{index}_resources')[0]['st_value']
    assert struct.unpack_from('<II',data,device+0x180)==(2,resource)
    assert any(r['r_offset']==device+0x184 and r['r_info_type']==2 and syms.get_symbol(r['r_info_sym'])['st_shndx']==15 for r in e.get_section_by_name('.rel.data').iter_relocations())
    start,end,name,flags=struct.unpack_from('<IIII',data,resource)
    assert (start,end,flags)==(expected,expected+0xffff,0x200)
    resources.append(dict(controller=f'MSC{index}',device_data_offset=hex(device),resource_data_offset=hex(resource),start=hex(start),end=hex(end),flags=hex(flags),ioaddr=hex(start|0xa0000000)))
(ROOT/'evidence/host-identity.json').write_text(json.dumps(dict(module_sha256=hashlib.sha256(b).hexdigest(),kernel_sha256=hashlib.sha256(k).hexdigest(),host_ioaddr_offset=16,resources=resources,execution=False),indent=2)+'\n')
