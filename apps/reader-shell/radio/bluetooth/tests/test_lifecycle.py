import importlib.util,select,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bt_lifecycle',ROOT/'c1/lifecycle.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class LifecycleTests(unittest.TestCase):
    def test_kills_only_owned_term_ignoring_child_and_reaps_it(self):
        group=mod.Children();sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'])
        child=group.spawn([sys.executable,'-u','-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("ready");time.sleep(5)'],stdout=subprocess.PIPE)
        try:
            self.assertTrue(select.select([child.stdout],[],[],1)[0]);self.assertEqual(child.stdout.readline(),b'ready\n')
            self.assertEqual(group.stop(child,.05),'killed')
            self.assertIsNotNone(child.poll());self.assertIsNone(sentinel.poll())
        finally:
            for p in [child,sentinel]:
                if p.poll() is None:p.kill()
                p.wait(timeout=1)
            child.stdout.close()
    def test_refuses_to_adopt_an_unowned_process(self):
        group=mod.Children();sentinel=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'])
        try:
            with self.assertRaises(ValueError):group.stop(sentinel,.05)
            self.assertIsNone(sentinel.poll())
        finally:sentinel.kill();sentinel.wait(timeout=1)
if __name__=='__main__':unittest.main()
