"""Execute the real board registration function against a temporary sysfs fixture."""
import pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class ListKeysHardwareTests(unittest.TestCase):
 def test_registers_factory_pins_and_only_power_wakes(self):
  source=(ROOT/'hardware.in').read_text().split('normal_hardware(){',1)[0]
  with tempfile.TemporaryDirectory() as temporary:
   path=pathlib.Path(temporary);(path/'sys/module/keyboard_gpio_add/parameters').mkdir(parents=True)
   (path/'sys/class/input/event1/device').mkdir(parents=True)
   (path/'sys/class/input/event1/device/name').write_text('md-gpio-keys\n')
   # Module absent before insmod; create its directory from the bb fixture.
   (path/'sys/module/keyboard_gpio_add/parameters').rmdir();(path/'sys/module/keyboard_gpio_add').rmdir()
   trace=path/'trace'
   stub='''normal_helpers_empty(){ return 0; }
bb(){ op="$1"; shift; case "$op" in
sha256sum) printf '3629e5b1e58339aa7ce09b8408dfb3453a6458aa77f6f3183c1e71b8de44c78a  %s\\n' "$1";;
cut) cut "$@";;
insmod) mkdir -p SYS/module/keyboard_gpio_add/parameters; touch SYS/module/keyboard_gpio_add/parameters/keyboard;;
printf) printf "$@"; printf '%s\\n' "$2" >> TRACE;;
cat) cat "$@";; *) return 1;; esac; }
'''.replace('SYS',str(path/'sys')).replace('TRACE',str(trace))
   source=source.replace('/sys/',str(path/'sys')+'/')
   # The real shell opens redirection before invoking bb; the sysfs parameter
   # fixture lives in a separate path so the initial module guard stays real.
   source=source.replace(str(path/'sys/module/keyboard_gpio_add/parameters/keyboard'),str(path/'keyboard'))
   result=subprocess.run(['/bin/sh','-c',stub+source+'\nnormal_power_hardware\n'],capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stdout+result.stderr)
   self.assertEqual(trace.read_text().splitlines(),['alloc=3','gpio=PC04 key_code=104 tag=KEY_PAGEUP active_level=0 wakeup=n','gpio=PC10 key_code=109 tag=KEY_PAGEDOWN active_level=0 wakeup=n','gpio=PE31 key_code=87 tag=KEY_F11 active_level=0 wakeup=y','register'])
if __name__=='__main__':unittest.main()
