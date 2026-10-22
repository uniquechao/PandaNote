"""RTC provider ordering/failure contracts; kernel boundaries are fixtures only."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
LIB = (ROOT / 'deploy/radio_init.sh').read_text().split('# RUN INIT', 1)[0]

class ClockTests(unittest.TestCase):
    def invoke(self, modules='utils 10 0 - Live 0\n', diagnostic='', export=True, fail=False, parameter='0', owner='soc_utils'):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as name:
            root = Path(name)
            (root/'modules').write_text(modules)
            (root/'kallsyms').write_text('00000001 T ingenic_rtc32k_enable [soc_utils]\n00000002 T ingenic_rtc32k_disable [soc_utils]\n' if 'soc_utils ' in modules and export else '')
            (root/'diagnostic').write_text(diagnostic)
            (root/'soc_utils/parameters').mkdir(parents=True)
            (root/'soc_utils/parameters/rtc32k_init_on').write_text(parameter+'\n')
            script = LIB + '''
MODULES_FILE=$1/modules;KALLSYMS_FILE=$1/kallsyms;SYS_MODULE_BASE=$1
# Only kernel interfaces are fixtures; the provider guard runs unmodified.
dmesg() { cat "$1/diagnostic"; }
'''.replace('cat "$1/diagnostic"', 'cat "'+str(root)+'/diagnostic"') + '''
insmod() {
    printf '%s\\n' "$*"
    [ "$2" = rtc32k_init_on=0 ] || return 1
''' + ('    return 1\n' if fail else '') + '''
    printf 'soc_utils 1 0 - Live 0\\n' >> "$MODULES_FILE"
''' + ('''    printf '00000001 T ingenic_rtc32k_enable [soc_utils]\\n00000002 T ingenic_rtc32k_disable [soc_utils]\\n' > "$KALLSYMS_FILE"
''' if export else '') + '''
}
radio_load_clock
'''
            script=script.replace('T ingenic_rtc32k_enable [soc_utils]', 'T ingenic_rtc32k_enable ['+owner+']').replace('T ingenic_rtc32k_disable [soc_utils]', 'T ingenic_rtc32k_disable ['+owner+']')
            return subprocess.run(['/bin/sh', '-c', script, 'fixture', str(root)], capture_output=True)

    def test_provider_loads_with_stock_zero_parameter_then_verifies_exports(self):
        p=self.invoke(); self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout,b'/module_driver/soc_utils.ko rtc32k_init_on=0\n')

    def test_missing_utils_does_not_load_provider(self):
        p=self.invoke(modules='');self.assertNotEqual(p.returncode,0);self.assertEqual(p.stdout,b'')

    def test_failed_load_or_missing_exports_prevents_success(self):
        for kwargs in ({'fail':True},{'export':False}):
            p=self.invoke(**kwargs);self.assertNotEqual(p.returncode,0)

    def test_wrong_parameter_or_unrelated_export_provider_is_refused(self):
        for kwargs in ({'parameter':'1'},{'owner':'unreviewed'}):
            p=self.invoke(**kwargs);self.assertNotEqual(p.returncode,0)

    def test_vendor_gpio_failure_is_failure_even_when_insmod_returns_success(self):
        for diagnostic in ('[1] request rtc32k gpio fail!\n','[1] rtc32k is not init ok\n'):
            p=self.invoke(diagnostic=diagnostic);self.assertNotEqual(p.returncode,0)

    def test_verified_preexisting_provider_is_not_reloaded(self):
        p=self.invoke(modules='utils 10 0 - Live 0\nsoc_utils 1 0 - Live 0\n')
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout,b'')

    def test_preexisting_provider_without_verified_exports_is_refused(self):
        p=self.invoke(modules='utils 10 0 - Live 0\nsoc_utils 1 0 - Live 0\n',export=False)
        self.assertNotEqual(p.returncode,0);self.assertEqual(p.stdout,b'')

if __name__=='__main__':unittest.main()
