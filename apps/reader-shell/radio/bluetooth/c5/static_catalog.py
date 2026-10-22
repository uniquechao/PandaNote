#!/usr/bin/env python3
"""Read retained regular ELF bytes only; never load, execute or emulate a module."""
import hashlib,json,re,stat,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parent;BT=ROOT.parent;IN=BT/'build/c5';E=ROOT/'evidence'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 pins={'aic8800_bsp.ko':'35e0cb9542b2d2e3d9e7889070e4c2659e7ade5c1ab159a9f5b34c0dfa232142','aic8800_fdrv.ko':'82bd636c3f6b91687ec92922bef48e4ae978a4ed9d558c502bd70a91297be1f2','aic8800_btlpm.ko':'4653f15b7cb600fc465e05928dbe0e9031eafceeb93e070611fd0d920c6f7afa','btattach':'746dee0da16884400a32eb89f64df58378824927901e8afe65157d574722ea6f'}
 files={}
 for n,pin in pins.items():
  p=IN/n;assert stat.S_ISREG(p.lstat().st_mode) and sha(p)==pin;files[n]={'bytes':p.stat().st_size,'sha256':pin,'origin':'/usr/bin/btattach' if n=='btattach' else '/module_driver/'+n}
 b=(IN/'aic8800_bsp.ko').read_bytes();assert b[:6]==b'\x7fELF\x01\x01';h=struct.unpack_from('<16sHHIIIIIHHHHHH',b);entries=[struct.unpack_from('<IIIIIIIIII',b,h[6]+i*h[11]) for i in range(h[12])];raw=entries[h[13]];names=b[raw[4]:raw[4]+raw[5]];sections={}
 for e in entries:
  name=names[e[0]:].split(b'\0',1)[0].decode();sections[name]=(e,b[e[4]:e[4]+e[5]])
 strings=sections['.strtab'][1];symbols=[]
 for offset in range(0,len(sections['.symtab'][1]),16):
  name,value,size,info,other,index=struct.unpack_from('<IIIBBH',sections['.symtab'][1],offset);label=strings[name:].split(b'\0',1)[0].decode()
  if not label and info&15==3:label=names[entries[index][0]:].split(b'\0',1)[0].decode()
  symbols.append({'name':label,'value':value,'size':size,'section':index})
 ro=sections['.rodata'][1];text=sections['.rodata.str1.4'][1];relocations={}
 for offset in range(0,len(sections['.rel.rodata'][1]),8):
  pos,info=struct.unpack_from('<II',sections['.rel.rodata'][1],offset);relocations[pos]=(info&255,symbols[info>>8]['name'])
 tables={}
 for s in symbols:
  if not s['name'].startswith('fw_') or s['size']!=48:continue
  rows=[]
  for row in range(2):
   values={}
   for field,label in enumerate(['description','bt_adid','bt_patch','bt_table','wifi_fw','bt_ext_patch']):
    pos=s['value']+row*24+field*4;value=struct.unpack_from('<I',ro,pos)[0]
    if pos in relocations:
     assert relocations[pos]==(2,'.rodata.str1.4');values[label]=text[value:].split(b'\0',1)[0].decode()
    else:assert value==0;values[label]=None
   rows.append(values)
  tables[s['name']]=rows
 info=next(s for s in symbols if s['name']=='aicbt_info');assert info['value']==0x568 and info['size']==120
 uart=[dict(zip(['btmode','btport','uart_baud','uart_flowctrl','lpm_enable','txpwr_lvl'],struct.unpack_from('<6I',ro,info['value']+24*i))) for i in range(5)]
 firmware={}
 for line in (E/'firmware-inventory.txt').read_text().splitlines():
  fields=line.split('/')
  if len(fields)>6 and fields[5].startswith('fw_'):
   p=IN/'firmware'/fields[5]
   if p.exists():firmware[fields[5]]={'bytes':p.stat().st_size,'sha256':sha(p)}
 value={'schema':1,'mode':'static only; no hardware or vendor execution','image_sha256':'acd6fe3202e9c6c87360f9030cf0e79fdac050d24462b502df891d2aa28f68b4','files':files,'bsp_firmware_tables':tables,'field_names_reference':'https://github.com/friendlyarm/aic8800/blob/main/aic8800_bsp/aic_bsp_driver.h#L528','field_names_are_related_source_not_board_proof':True,'aicbt_info':uart,'shipped_bt_firmware':firmware,'power_transition':{'map_2_to_3':'positive-to-positive; shared power branch skipped','map_3_to_2':'positive-to-positive; shared power branch skipped','map_0_to_1':'shared power, SDIO and firmware branch; forbidden in live Wi-Fi candidate','map_1_to_0':'shared power-off branch; forbidden'},'power_activation_ready':False,'reason':'PA7/PD31/PC8 current electrical state unavailable; no verified BT-only power-write boundary'}
 (E/'static-catalog.json').write_text(json.dumps(value,indent=2)+'\n');print('PASS static pinned ELF/catalog parse; no execution')
if __name__=='__main__':main()
