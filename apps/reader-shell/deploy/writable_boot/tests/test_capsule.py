"""Pure byte/layout tests. No MIPS execution or USB access."""
import base64
import gzip
import json
import importlib.util
from pathlib import Path
import random
import re
import struct
import unittest
import zlib

ROOT=Path(__file__).resolve().parents[1]
module=None
if (ROOT/'build.py').exists():
    spec=importlib.util.spec_from_file_location('writable_build',ROOT/'build.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class CapsuleTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module,'writable capsule builder missing')
        kernel=ROOT.parents[1]/'build/writable-development/kernel-WRITABLE-OFFLINE-CANDIDATE.bin'
        if not kernel.exists(): self.skipTest('approved local writable kernel absent')
        self.kernel=kernel.read_bytes()

    def test_payload_roundtrip_and_byte_regions(self):
        pid1=b'#!/bin/sh\nprintf development-test\n'
        result=module.capsule(self.kernel,pid1)
        self.assertLess(len(result['commandline'].encode()),4095)
        self.assertEqual(set(result['segments']),(set((0x80010000,0x84000000,0x84001000))))
        match=re.search(r'echo ([A-Za-z0-9+/=]+) ',result['commandline'])
        self.assertEqual(gzip.decompress(base64.b64decode(match[1])),pid1)
        self.assertNotIn('rootflags=noload rw',result['commandline'])
        argv=result['segments'][0x84001000]
        a,b,end=struct.unpack_from('<III',argv)
        self.assertEqual((a,end),(0x8400100c,0))
        self.assertEqual(argv[b-0x84001000:-1],result['commandline'].encode())
        self.assertNotIn(0x84010000,result['segments'])

    def test_changed_kernel_and_oversized_pid1_refused(self):
        changed=bytearray(self.kernel);changed[0]^=1
        with self.assertRaises(ValueError):module.capsule(changed,b'owned pid1')
        rng=random.Random(123)
        too_large=bytes(rng.randrange(256) for _ in range(5000))
        with self.assertRaisesRegex(ValueError,'commandline'):
            module.capsule(self.kernel,too_large)

    def test_crc_inputs_cover_every_segment_and_match_bytes(self):
        result=module.capsule(self.kernel,b'#!/bin/sh\nexit 1\n')
        text=module.crc_include(result['segments'])
        lines=text.split('crc_ranges_end:')[0].splitlines()[1:]
        self.assertEqual(len(lines),3)
        for (addr,blob),line in zip(result['segments'].items(),lines):
            values=[int(x,16) for x in line.strip().split(' ',1)[1].split(',')]
            self.assertEqual(values,[(addr&0x1fffffff)|0xa0000000,len(blob),zlib.crc32(blob)])

    def test_bootstrap_usb_has_same_stable_supervisor_before_host_upload(self):
        generated=ROOT/'build/candidate/pid1.sh'
        if not generated.exists():self.skipTest('build candidate first')
        text=generated.read_text()
        match=re.search(r"<<'PANDANOTE_BOOT_CHILD'\n(.*?)\nPANDANOTE_BOOT_CHILD\n",text,re.S)
        self.assertIsNotNone(match,'USB child has no pre-upload owned supervisor')
        self.assertEqual(match[1].encode()+b'\n',(ROOT/'child-supervisor.sh').read_bytes())

    def test_assembled_bootstrap_embeds_exact_segment_crcs(self):
        output=ROOT/'build/candidate'
        if not (output/'manifest.json').exists():self.skipTest('build candidate first')
        manifest=json.loads((output/'manifest.json').read_text())
        binary=(output/'bootstrap-selfcheck.bin').read_bytes()
        symbols=manifest['bootstrap']['symbols']
        begin=int(symbols['crc_ranges'],16)-0x81000000
        end=int(symbols['crc_ranges_end'],16)-0x81000000
        self.assertEqual(end-begin,3*12)
        for index,entry in enumerate(manifest['segments']):
            payload=(output/entry['file']).read_bytes()
            self.assertEqual(struct.unpack_from('<III',binary,begin+index*12),(
                int(entry['address'],16)&0x1fffffff|0xa0000000,len(payload),zlib.crc32(payload)))
        table=int(symbols['crc_table'],16)-0x81000000
        self.assertLessEqual(table+256*4,len(binary))
        self.assertEqual(struct.unpack_from('<II',binary,table),(0,0x77073096))


if __name__=='__main__': unittest.main(verbosity=2)
