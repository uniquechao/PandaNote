"""Rebuild original neutral landscape; does not read external imagery."""
import math,struct,zlib
from pathlib import Path
raw=bytearray()
for y in range(800):
    raw.append(0)
    for x in range(480):
        c=239
        if (x-361)**2+(y-500)**2<36**2:c=252
        if y>565+35*math.sin(x/140.0):c=210
        if y>625+44*math.sin(x/125.0+1.5):c=167
        if y>696+24*math.sin(x/100.0+3):c=110
        raw.append(c)
def chunk(kind,data):
    return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
image=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',480,800,8,0,0,0,0))+chunk(b'IDAT',zlib.compress(raw,9))+chunk(b'IEND',b'')
(Path(__file__).resolve().parents[1]/'assets/neutral-background.png').write_bytes(image)
