import subprocess
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
class InitTests(unittest.TestCase):
    def invoke(self,cpu,modules='',guard=True):
        source=ROOT/'deploy/radio_init.sh';self.assertTrue(source.exists(),'radio init missing')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as name:
            root=Path(name);(root/'cpuinfo').write_text(cpu);(root/'modules').write_text(modules)
            lib=source.read_text().split('# RUN INIT',1)[0]
            script=lib+'\nCPUINFO_FILE=$1/cpuinfo;MODULES_FILE=$1/modules\nradio_guard_ready() { return '+('0' if guard else '1')+'; }\nradio_verify_inputs() { return 0; }\nradio_prepare_runtime() { printf RUNTIME; }\nradio_load_clock() { printf CLOCK; }\nradio_load_sdio() { printf SDIO; }\nradio_load_wifi() { printf LOAD; }\nradio_start_children() { printf CHILDREN; }\nradio_initialize_wifi\n'
            return subprocess.run(['/bin/sh','-c',script,'test',str(root)],capture_output=True)
    def test_wrong_board_or_missing_guard_never_loads_modules(self):
        for cpu,guard in [('system type : epd86s2\n',True),('system type : epd86s2_pro\n',False)]:
            p=self.invoke(cpu,guard=guard);self.assertNotEqual(p.returncode,0);self.assertEqual(p.stdout,b'')
    def test_existing_loaded_driver_does_not_fail_board_validation(self):
        p=self.invoke('system type : epd86s2_pro\n',modules='aic8800_fdrv 1 0 - Live 0\n')
        self.assertEqual(p.returncode,0);self.assertEqual(p.stdout,b'CLOCKSDIOLOADRUNTIMECHILDREN')
    def test_supported_board_orders_clock_sdio_wifi_before_runtime_and_children(self):
        p=self.invoke('system type : epd86s2_pro\n')
        self.assertEqual(p.returncode,0);self.assertEqual(p.stdout,b'CLOCKSDIOLOADRUNTIMECHILDREN')
    def test_module_failure_does_not_create_interrupted_prechild_runtime(self):
        lib=(ROOT/'deploy/radio_init.sh').read_text().split('# RUN INIT',1)[0]
        for stage in ('clock','sdio','wifi'):
            script=lib+'\nradio_board_supported() { return 0; };radio_verify_inputs() { return 0; };radio_guard_ready() { return 0; }\nradio_load_clock() { return '+('1' if stage=='clock' else '0')+'; }\nradio_load_sdio() { return '+('1' if stage=='sdio' else '0')+'; }\nradio_load_wifi() { return '+('1' if stage=='wifi' else '0')+'; }\nradio_prepare_runtime() { printf RUNTIME; };radio_start_children() { printf CHILDREN; }\nradio_initialize_wifi\n'
            p=subprocess.run(['/bin/sh','-c',script],capture_output=True)
            self.assertNotEqual(p.returncode,0);self.assertEqual(p.stdout,b'',stage)
    def test_existing_interrupted_runtime_is_preserved_without_loading_or_children(self):
        lib=(ROOT/'deploy/radio_init.sh').read_text().split('# RUN INIT',1)[0]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as name:
            root=Path(name);runtime=root/'runtime';runtime.mkdir();keep=runtime/'unverified';keep.write_bytes(b'preserve failed state')
            script=lib+'\nRADIO_RUNTIME=$1/runtime\nradio_board_supported() { return 0; };radio_verify_inputs() { return 0; };radio_guard_ready() { return 0; }\nradio_load_clock() { printf CLOCK; };radio_load_sdio() { printf SDIO; };radio_load_wifi() { printf WIFI; };radio_prepare_runtime() { printf RUNTIME; };radio_start_children() { printf CHILDREN; }\nradio_initialize_wifi\n'
            p=subprocess.run(['/bin/sh','-c',script,'fixture',str(root)],capture_output=True)
            self.assertNotEqual(p.returncode,0);self.assertEqual(p.stdout,b'');self.assertEqual(keep.read_bytes(),b'preserve failed state')
    def test_preexisting_shared_sdio_is_not_reloaded(self):
        lib=(ROOT/'deploy/radio_init.sh').read_text().split('# RUN INIT',1)[0]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as name:
            mods=Path(name)/'modules';mods.write_text('utils 1 0 - Live 0\nsoc_msc 1 0 - Live 0\n')
            p=subprocess.run(['/bin/sh','-c',lib+'\nMODULES_FILE=$1\ninsmod() { printf UNEXPECTED_LOAD;return 1; }\nradio_load_sdio\n','fixture',str(mods)],capture_output=True)
            self.assertEqual(p.returncode,0);self.assertEqual(p.stdout,b'')
    def test_sdio_load_disables_emmc_controllers_and_requires_existing_utils(self):
        source=ROOT/'deploy/radio_init.sh'
        lib=source.read_text().split('# RUN INIT',1)[0]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as name:
            mods=Path(name)/'modules'
            for loaded in ('', 'utils 10 0 - Live 0\n'):
                mods.write_text(loaded)
                script=lib+'\nMODULES_FILE=$1\ninsmod() { printf "%s\\n" "$@"; }\nradio_load_sdio\n'
                p=subprocess.run(['/bin/sh','-c',script,'test',str(mods)],capture_output=True)
                if not loaded:
                    self.assertNotEqual(p.returncode,0);self.assertEqual(p.stdout,b'')
                else:
                    self.assertEqual(p.returncode,0,p.stderr.decode())
                    args=p.stdout.decode().splitlines()
                    self.assertEqual(args[0],'/module_driver/soc_msc.ko')
                    for field in ('msc0_is_enable=0','msc1_is_enable=1','msc2_is_enable=0','msc1_speed=sdio','msc1_cd_method=cd-internal','wifi_power_on=-1','wifi_reg_on=-1'):
                        self.assertIn(field,args)
if __name__=='__main__':unittest.main()
