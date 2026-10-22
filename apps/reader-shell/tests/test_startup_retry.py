"""Deterministic execution of the actual production syncTick scheduling body.

The Qt/UI/transport boundary is simulated; no socket, secret or clock syscall is
used. This compiles the method directly from main.cpp, not a copied algorithm.
"""
import pathlib, subprocess, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class StartupRetryTests(unittest.TestCase):
 def test_production_startup_tick_recovers_transport_without_waiting_five_minutes(self):
  output=ROOT/'build/startup-retry-host';output.mkdir(parents=True,exist_ok=True)
  source=(ROOT/'main.cpp').read_text()
  method=source[source.index('    void syncTick() {'):source.index('    bool loadDirectory(')]
  sync_requested=source[source.index('    void syncRequested() {'):source.index('    void syncTick() {')]
  standby_changed=source[source.index('    void standbyChanged('):source.index('    bool shutdownRequested(')]
  policy='#include "startupretry.h"\n#include "standbypolicy.h"\n' if (ROOT/'startupretry.h').exists() else ''
  member='StartupSyncRetry startupRetry_;StandbyMaintenance maintenance_;' if policy else ''
  http_source=(ROOT/'sync.cpp').read_text()
  http_cancel=http_source[http_source.index('void DeviceHttp::cancel('):http_source.index('bool DeviceHttp::connectAddress(')]
  http_poll=http_source[http_source.index('int DeviceHttp::poll('):http_source.index('QByteArray radioRequest(')]
  template=(ROOT/'tests/startup_retry_fixture.cpp').read_text()
  target=output/'runtime.cpp';target.write_text(policy+template.replace('/* POLICY MEMBER */',member).replace('/* ACTUAL SYNC REQUESTED */',sync_requested).replace('/* ACTUAL STANDBY CHANGED */',standby_changed).replace('/* ACTUAL PRODUCTION METHOD */',method).replace('/* ACTUAL DEVICE HTTP POLL */',http_poll).replace('/* ACTUAL HTTP CANCEL */',http_cancel.replace('void DeviceHttp::','void ').replace('bool DeviceHttp::','bool ')))
  binary=output/'runtime'
  built=subprocess.run(['c++','-std=c++98','-Wall','-Wextra','-Werror','-I'+str(ROOT),str(target),'-o',str(binary)],capture_output=True,text=True)
  self.assertEqual(built.returncode,0,built.stdout+built.stderr)
  result=subprocess.run([str(binary)],capture_output=True,text=True)
  (output/'stdout.txt').write_text(result.stdout);(output/'stderr.txt').write_text(result.stderr)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
if __name__=='__main__':unittest.main()
