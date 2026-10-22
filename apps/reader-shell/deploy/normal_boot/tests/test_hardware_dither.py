"""Execute real boot hardware policy with only external boundaries substituted."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DITHER = 'devices/platform/jz-spi1.1/spi_master/spi1/spi1.0/eink_dither'


class HardwareDitherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'build')
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        self.sys = self.p / 'sys'
        self.dither = self.sys / DITHER
        self.dither.parent.mkdir(parents=True)
        self.dither.write_text('0\n')
        self.mode = self.dither.with_name('eink_mode')
        self.mode.write_text('0\n')
        self.trace = self.p / 'trace'

    def boot(self, write='ok', read='actual'):
        source = (ROOT / 'hardware.in').read_text().replace('/sys/', str(self.sys) + '/')
        # All sysfs paths are private fixture files. No vendor program or module
        # is run; keep shell redirection and the actual startup policy intact.
        stubs = r'''
trace(){ printf '%s\n' "$*" >> "$TRACE"; }
normal_runtime_ok(){ return 0; }
normal_modules_empty(){ return 0; }
normal_helpers_empty(){ return 0; }
normal_power_hardware(){ trace power; return 0; }
bb(){
 case "$1" in
  insmod) trace "insmod:$2"; return 0;;
  sha256sum) return 0;;
  printf) trace dither-write; [ "$WRITE_MODE" != fail ] || return 1; shift; printf "$@";;
  cat) case "$2" in
   */eink_dither)
    trace dither-read
    case "$READ_MODE" in
     actual) cat "$2";; fail) printf '1\n'; return 1;;
     wrong) printf '0\n';; malformed) printf '1 extra\n';; empty) return 0;;
     *) return 99;;
    esac;;
   */virtual_size) printf '800,960\n';; */bits_per_pixel) printf '16\n';;
   */stride) printf '1600\n';; */graphics/fb0/name) printf 'spi_fb\n';;
   */input/event0/device/name) printf 'fts_ts\n';; *) return 99;;
  esac;;
  *) return 99;;
 esac
}
normal_hardware
'''
        result = subprocess.run(['/bin/sh', '-c', source + stubs], capture_output=True, text=True,
                                env=dict(os.environ, TRACE=str(self.trace), WRITE_MODE=write,
                                         READ_MODE=read, release=str(self.p / 'release')))
        calls = self.trace.read_text().splitlines()
        self.assertEqual(self.mode.read_text(), '0\n', 'dithering must preserve mode0')
        return result, calls

    def rejected(self, result, calls):
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('power', calls, 'failed display setup must not complete hardware startup')
        self.assertFalse(any('soc_i2c.ko' in c or 'focaltech_touch' in c or 'soc_adc.ko' in c for c in calls), calls)

    def test_boot_enables_dither_before_loading_touch_and_finishes(self):
        result, calls = self.boot()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.dither.read_text(), '1\n')
        eink = next(i for i, c in enumerate(calls) if 'eink_qingyue426.ko' in c)
        i2c = next(i for i, c in enumerate(calls) if 'soc_i2c.ko' in c)
        self.assertEqual(calls[eink + 1:i2c], ['dither-write', 'dither-read'])
        self.assertEqual(calls[-1], 'power')

    def test_missing_dither_node_prevents_boot_and_is_not_created(self):
        self.dither.unlink()
        result, calls = self.boot()
        self.rejected(result, calls)
        self.assertFalse(self.dither.exists())

    def test_dither_write_failure_prevents_boot(self):
        result, calls = self.boot(write='fail')
        self.rejected(result, calls)
        self.assertNotIn('dither-read', calls)

    def test_read_error_even_with_correct_output_prevents_boot(self):
        result, calls = self.boot(read='fail')
        self.rejected(result, calls)

    def test_wrong_or_malformed_dither_readback_prevents_boot(self):
        for read in ('wrong', 'malformed', 'empty'):
            with self.subTest(read=read):
                result, calls = self.boot(read=read)
                self.rejected(result, calls)
                self.trace.unlink()


if __name__ == '__main__':
    unittest.main()
