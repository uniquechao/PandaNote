"""Actual MIPS instruction tests. Offline lab gate required by base harness."""
import struct
from test_storage_guard import StorageGuardTest, HOST, physical, ALLOW, DENY, READ_OPS

class SdioGuardTest(StorageGuardTest):
    def setUp(self):
        super().setUp()
        self.ioaddr = 0xb3450000
        from unicorn import UC_HOOK_MEM_READ
        from test_storage_guard import CMD, DATA, STACK
        def read_ram(uc, access, address, size, value, unused):
            a=physical(address)
            allowed=((physical(HOST)+16 <= a and a+size <= physical(HOST)+20) or
                     (self.follow_error_tail and physical(HOST)+236 <= a and a+size <= physical(HOST)+240) or
                     (physical(CMD) <= a and a+size <= physical(CMD)+64) or
                     (physical(DATA) <= a and a+size <= physical(DATA)+64) or
                     (physical(STACK)-104 <= a and a+size <= physical(STACK)))
            if not allowed: raise AssertionError('Unexpected RAM/MMIO read '+hex(address))
        self.u.hook_add(UC_HOOK_MEM_READ,read_ram)

    def run_command(self, opcode, arg=0, data_flags=None):
        self.u.mem_write(physical(HOST)+16, struct.pack('<I', self.ioaddr))
        return super().run_command(opcode, arg, data_flags)

    def test_msc1_sdio_rw(self):
        self.ioaddr=0xb3460000
        for arg in (0,0x80000000,0x900020ff,0x08000000):
            self.assertEqual(self.run_command(52,arg),(ALLOW,0x12345678))
        for arg,flags in [(0,0x200),(0x80000000,0x100),(0xffffffff,0x100),(0x7fffffff,0x200)]:
            self.assertEqual(self.run_command(53,arg,flags),(ALLOW,0x12345678))

    def test_sdio_malformed_shape_denied(self):
        self.ioaddr=0xb3460000
        for arg in (0x100,0x04000000,0xffffffff):
            self.assertEqual(self.run_command(52,arg),(DENY,-30))
        for flags in (0,0x100,0x200,0x300,0xffffffff):
            self.assertEqual(self.run_command(52,0,flags),(DENY,-30))
        for arg in (0,0x80000000):
            for flags in (None,0,0x300,0x400,0xffffffff,0x100 if arg==0 else 0x200):
                self.assertEqual(self.run_command(53,arg,flags),(DENY,-30))

    def test_host_identity_exact_not_index_or_near_miss(self):
        for host in (0,0xffffffff,0x13460000,0x93460000,0xb3450000,0xb3490000,0xb3460001,0xb345ffff,0xb346ffff,0xb3470000):
            self.ioaddr=host
            for op in (52,53):
                for arg in (0,0xffffffff,0x80000000):
                    for flags in (None,0,0x100,0x200,0x300,0xffffffff):
                        self.assertEqual(self.run_command(op,arg,flags),(DENY,-30))

    def test_msc1_all_non_sdio_commands_preserve_golden_policy(self):
        # Golden base suite remains inherited for MSC0; repeat all tests against
        # MSC1 excluding only newly permitted SDIO opcodes from this matrix.
        self.ioaddr=0xb3460000
        for opcode in list(range(64))+[64,0xffffffff,0x10018]:
            if opcode in (52,53): continue
            for flags in (None,0,0x100,0x200,0x300,0xffffffff):
                allowed=opcode in READ_OPS and flags in (None,0x200)
                error=0x12345678 if allowed else (-77 if opcode==6 and flags in (None,0x200) else -30)
                self.assertEqual(self.run_command(opcode,0,flags),(ALLOW if allowed else DENY,error))

    def test_sdio_argument_bit_and_function_matrix(self):
        self.ioaddr=0xb3460000
        for func in range(8):
            for bit in range(32):
                for write in (0,1):
                    arg=(func<<28)|(write<<31)|(1<<bit)
                    expected=DENY if arg & 0x04000100 else ALLOW
                    self.assertEqual(self.run_command(52,arg)[0],expected)
                    flags=0x100 if arg&0x80000000 else 0x200
                    self.assertEqual(self.run_command(53,arg,flags),(ALLOW,0x12345678))

    def test_golden_body_is_unchanged_machine_code(self):
        from pathlib import Path
        golden=Path('/sample-guard/golden-storage-guard.bin').read_bytes()
        self.assertEqual(len(golden),400)
        self.assertEqual(self.blob[-400:],golden)

    def test_mmc0_and_unknown_full_matrix_matches_golden_registers_stores(self):
        # Prefix fallback must be observationally identical, not merely DENY.
        from pathlib import Path
        from unicorn.mips_const import UC_MIPS_REG_0
        golden=Path('/sample-guard/golden-storage-guard.bin').read_bytes()
        candidate=self.blob
        from test_storage_guard import GUARD, CMD, STACK
        for host in (0xb3450000,0,0xb3490000,0xb3460001):
            self.ioaddr=host
            for opcode in list(range(64))+[64,0xffffffff,0x10018]:
                for arg in (0,0xffffffff,0x03b70101,0x80000001):
                    for flags in (None,0,0x100,0x200,0x300,0xffffffff):
                        states=[]
                        for blob in (golden,candidate):
                            self.blob=blob
                            self.u.mem_write(physical(GUARD),blob)
                            for reg in range(1,32): self.u.reg_write(UC_MIPS_REG_0+reg,0x11110000+reg)
                            result=self.run_command(opcode,arg,flags)
                            # t0/t1 are scratch; all other GPRs and all written RAM
                            # must match. Their final values also match on fallback.
                            regs=[self.u.reg_read(UC_MIPS_REG_0+r) for r in range(32)]
                            stores=[(a,n,bytes(self.u.mem_read(a,n)).hex()) for a,n in self.stores]
                            states.append((result,regs,stores))
                        self.assertEqual(states[0],states[1],(host,opcode,arg,flags))
        self.blob=candidate

    def test_all_data_flag_bits_require_exact_sdio_direction(self):
        self.ioaddr=0xb3460000
        for write,required in ((0,0x200),(1,0x100)):
            for bit in range(32):
                for flags in (1<<bit,required|(1<<bit),0xffffffff^(1<<bit)):
                    allowed=flags==required
                    self.assertEqual(self.run_command(53,write<<31,flags),
                                     (ALLOW,0x12345678) if allowed else (DENY,-30))
