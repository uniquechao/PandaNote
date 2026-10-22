"""Real checksum verification on isolated data fixtures; no init or firmware run."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
class FirmwareTests(unittest.TestCase):
    def invoke(self,mutation=None):
        lib=(ROOT/'deploy/radio_init.sh').read_text().split('# RUN INIT',1)[0]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as name:
            root=Path(name).resolve();fw=root/'module_driver/firmware';fw.mkdir(parents=True)
            image=fw/'fmacfw.bin';image.write_bytes(b'approved fixture, not radio firmware')
            provider=root/'module_driver/soc_utils.ko';provider.write_bytes(b'reviewed clock provider fixture')
            session_tool=root/'bin/busybox';session_tool.parent.mkdir();session_tool.write_bytes(b'reviewed session-tool fixture, never executed')
            factory=root/'radio-factory-inputs.sha256';factory.write_text(digest(image)+'  '+str(image)+'\n'+digest(provider)+'  '+str(provider)+'\n'+digest(session_tool)+'  '+str(session_tool)+'\n')
            (root/'radio-stage-inputs.sha256').write_text(digest(factory)+'  radio-factory-inputs.sha256\n')
            if mutation=='provider-missing':provider.unlink()
            elif mutation=='provider-changed':provider.write_bytes(b'changed provider')
            elif mutation=='session-tool-missing':session_tool.unlink()
            elif mutation=='session-tool-changed':session_tool.write_bytes(b'changed session tool')
            elif mutation=='missing':image.unlink()
            elif mutation=='changed':image.write_bytes(b'changed firmware')
            elif mutation=='extra':(fw/'unreviewed.bin').write_bytes(b'unknown')
            elif mutation=='symlink':(fw/'linked.bin').symlink_to(image)
            script=lib+'\nRADIO_SCRIPTS=$1;RADIO_FIRMWARE=$1/module_driver/firmware\nradio_board_supported() { return 0; }\nradio_guard_ready() { return 0; }\nradio_prepare_runtime() { printf MUTATED; }\nradio_load_clock() { return 0; }\nradio_load_sdio() { printf LOAD; }\nradio_load_wifi() { return 0; }\nradio_start_children() { return 0; }\nradio_initialize_wifi\n'
            return subprocess.run(['/bin/sh','-c',script,'fixture',str(root)],capture_output=True)
    def test_reviewed_firmware_preflight_allows_next_stage(self):
        p=self.invoke();self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout,b'LOADMUTATED')
    def test_missing_changed_extra_or_linked_firmware_stops_before_side_effects(self):
        for mutation in ('missing','changed','extra','symlink','provider-missing','provider-changed','session-tool-missing','session-tool-changed'):
            p=self.invoke(mutation);self.assertNotEqual(p.returncode,0,mutation);self.assertEqual(p.stdout,b'',mutation)
if __name__=='__main__':unittest.main()
