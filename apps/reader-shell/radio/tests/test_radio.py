"""Host-only trusted C test. Fake UNIX supplicant, no device/network interfaces."""
import base64
import configparser
import os
from pathlib import Path
import socket
import subprocess
import threading
import platform
import shlex
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / '.test'
BIN = RUN / 'radio-host'
RUNNER=shlex.split(os.environ.get('RADIO_TEST_RUNNER',''))

def b64(value):
    return base64.b64encode(value.encode()).decode()

def request(action, **fields):
    return ('[request]\nschema=1\naction=' + action + '\n' + ''.join(k+'='+v+'\n' for k,v in fields.items())).encode()

class RadioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RUN.mkdir(mode=0o700, exist_ok=True)
        if os.environ.get('RADIO_TEST_PREBUILT')=='1': return
        build = subprocess.run(['cc','-D_DARWIN_C_SOURCE','-std=c99','-D_POSIX_C_SOURCE=200809L','-Wall','-Wextra','-Werror',
            '-DRADIO_CTRL="apps/reader-shell/radio/.test/wlan0"',
            '-DRADIO_LOCAL="apps/reader-shell/radio/.test"',
            '-DRADIO_ROUTE="apps/reader-shell/radio/.test/route"',
            str(ROOT/'radio.c'), '-o', str(BIN)], capture_output=True, text=True)
        if build.returncode:
            raise AssertionError('helper is not buildable: '+build.stderr)
    def call(self, action='status', payload=None, **fields):
        p = subprocess.run(RUNNER+[str(BIN), action], input=payload if payload is not None else request(action, **fields), capture_output=True, timeout=8)
        self.assertLessEqual(len(p.stdout),65536)
        self.assertEqual(p.stderr,b'')
        reply=configparser.ConfigParser(interpolation=None)
        reply.read_string(p.stdout.decode())
        return reply
    def test_syscall_interrupt_and_wouldblock_retries(self):
        binary=RUN/'io-cases'
        if os.environ.get('RADIO_TEST_PREBUILT')!='1':
            p=subprocess.run(['cc','-D_DARWIN_C_SOURCE','-std=c99','-Wall','-Wextra','-Werror',str(ROOT/'tests/io_cases.c'),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
        p=subprocess.run(RUNNER+[str(binary)],capture_output=True,timeout=5)
        self.assertEqual(p.returncode,0,'production I/O failed EINTR/EAGAIN retries; case='+str(p.returncode))
    @unittest.skipUnless(platform.system()=='Linux','Linux UNIX datagram queue behavior')
    def test_saturated_send_queue_has_two_second_deadline(self):
        self.saturated_queue(False)
    @unittest.skipUnless(platform.system()=='Linux','Linux UNIX datagram queue behavior')
    def test_send_wait_and_reply_share_one_absolute_deadline(self):
        self.saturated_queue(True)
    def saturated_queue(self,drain):
        path='apps/reader-shell/radio/.test/wlan0'
        try: os.unlink(path)
        except FileNotFoundError:pass
        server=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);server.bind(path);server.settimeout(4)
        filler=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);filler.setblocking(False);filler.connect(path)
        count=0
        try:
            while count<4096:
                try:filler.send(b'occupied');count+=1
                except BlockingIOError:break
            self.assertGreater(count,0);self.assertLess(count,4096,'fixture failed to fill queue')
            worker=None;failures=[]
            if drain:
                def respond():
                    try:
                        time.sleep(1.1)
                        while True:
                            payload,addr=server.recvfrom(4096)
                            if payload==b'STATUS':break
                        time.sleep(1.2)
                        try:server.sendto(b'wpa_state=COMPLETED\n',addr)
                        except (FileNotFoundError,ConnectionRefusedError):pass
                    except Exception as e:failures.append(e)
                worker=threading.Thread(target=respond);worker.start()
            start=time.monotonic()
            proc=subprocess.Popen(RUNNER+[str(BIN),'status'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                try:out,err=proc.communicate(request('status'),timeout=3.5)
                except subprocess.TimeoutExpired:self.fail('helper blocked beyond transaction deadline on full Linux queue')
                elapsed=time.monotonic()-start
                self.assertEqual(err,b'');self.assertIn(b'code=supplicant_timeout',out)
                self.assertGreater(elapsed,1.7);self.assertLess(elapsed,2.7,'send and reply must share the same two-second budget')
            finally:
                if proc.poll() is None:proc.kill();proc.communicate()
                if worker:worker.join(5)
            self.assertFalse(failures,repr(failures))
        finally:filler.close();server.close();os.unlink(path)
    def test_stdin_deadline_rejects_stalled_writer(self):
        import time
        p=subprocess.Popen(RUNNER+[str(BIN),'status'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            p.wait(timeout=3.5)
            self.assertIn(b'code=invalid_request',p.stdout.read())
        finally:
            if p.poll() is None: p.kill();p.wait()
            p.stdin.close();p.stdout.close();p.stderr.close()
    def test_unknown_action_rejected_before_io(self):
        self.assertEqual(self.call('run-shell')['reply']['code'],'invalid_request')
    def test_duplicate_fields_rejected(self):
        self.assertEqual(self.call(payload=b'[request]\nschema=1\naction=status\naction=status\n')['reply']['code'],'invalid_request')
    def test_action_mismatch_rejected(self):
        self.assertEqual(self.call(payload=request('wifi-scan'))['reply']['code'],'invalid_request')
    def test_input_limit_and_unknown_fields(self):
        for raw in [b'x'*16385,request('status',unexpected='x')]:
            self.assertEqual(self.call(payload=raw)['reply']['code'],'invalid_request')
    def test_secret_encoding_and_lengths_rejected(self):
        for fields in [dict(ssid64='YQ',password64=b64('password')),dict(ssid64=b64('a'*33),password64=b64('password')),dict(ssid64=b64('ok'),password64=b64('short')),dict(ssid64='wK8=',password64=b64('password'))]:
            self.assertEqual(self.call('wifi-connect',**fields)['reply']['code'],'invalid_request')
    def test_missing_runtime_reports_unavailable(self):
        self.assertEqual(self.call()['reply']['code'],'wifi_unavailable')
    def test_pair_explicitly_requires_iphone_service_and_agent(self):
        result=self.call('bluetooth-pair',peer64=b64('00:11:22:33:44:55'))
        self.assertEqual(result['reply']['code'],'pairing_agent_required')
        self.assertEqual(result['status']['iphone_service'],'unavailable')
    def with_supplicant(self, replies, action, **fields):
        path='apps/reader-shell/radio/.test/wlan0'
        try: os.unlink(path)
        except FileNotFoundError: pass
        server=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
        server.bind(path);server.settimeout(4)
        commands=[]; failures=[]
        def respond():
            try:
                for expected,reply in replies:
                    data,addr=server.recvfrom(65536);commands.append(data.decode())
                    if expected is not None: self.assertEqual(data.decode(),expected)
                    server.sendto(reply,addr)
            except Exception as e: failures.append(e)
        thread=threading.Thread(target=respond);thread.start()
        try: result=self.call(action,**fields)
        finally: thread.join(5);server.close();os.unlink(path)
        self.assertFalse(failures,repr(failures));self.assertFalse(thread.is_alive())
        return result,commands
    def test_status_returns_actual_state_and_no_fabricated_address(self):
        r,_=self.with_supplicant([('STATUS',b'wpa_state=SCANNING\nssid=private\n')],'status')
        self.assertEqual(r['status']['wifi_state'],'SCANNING')
        self.assertNotIn('private',str(dict(r['status'])))
        self.assertEqual(r['status']['application_reachable'],'unverified')
    # Missing/gating/escaping SSID or trusting supplicant IP must fail these cases.
    def test_status_exposes_only_completed_valid_ssid_as_canonical_base64(self):
        cases = [
            (b'wpa_state=COMPLETED\nssid=Cafe\\x20A\n', 'Q2FmZSBB'),
            (b'wpa_state=COMPLETED\nssid=A\\n\\r\\t\\eB\n', 'QQoNCRtC'),
            (b'wpa_state=COMPLETED\nwpa_state=SCANNING\nssid=Example\n', ''),
            (b'wpa_state=COMPLETED\nssid=\\xe4\\xb8\\xad\n', '5Lit'),
            (b'wpa_state=COMPLETED\nssid='+b'a'*32+b'\n', b64('a'*32)),
            (b'wpa_state=SCANNING\nssid=Example\n', ''),
            (b'wpa_state=COMPLETED\nssid='+b'a'*33+b'\n', ''),
            (b'wpa_state=COMPLETED\nssid=bad\\x00name\n', ''),
            (b'wpa_state=COMPLETED\nssid=bad\\xff\n', ''),
            (b'wpa_state=COMPLETED\nssid=bad\\q\n', ''),
            (b'wpa_state=COMPLETED\nssid=\n', ''),
            (b'wpa_state=COMPLETED\n', ''),
            (b'wpa_state=COMPLETED\nssid=one\nssid=two\n', ''),
        ]
        for payload,want in cases:
            with self.subTest(payload=payload):
                r,commands=self.with_supplicant([('STATUS',payload+b'ip_address=203.0.113.7\n')],'status')
                self.assertEqual(r['status'].get('wifi_ssid64'),want)
                self.assertNotEqual(r['status']['ipv4'],'203.0.113.7')
                self.assertEqual(commands,['STATUS'])

    @unittest.skipIf(os.environ.get('RADIO_TEST_PREBUILT')=='1','host-only ioctl fixture requires trusted host compiler')
    def test_kernel_fields_come_from_independent_readonly_queries(self):
        # Only the external ioctl boundary is substituted. The collector and
        # address canonicalization are production C, with a portable Linux ABI
        # test stand-in on macOS; no interface is changed or activated.
        source=RUN/'kernel-cases.c';binary=RUN/'kernel-cases'
        source.write_text(r'''#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <net/if.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <string.h>
#ifndef __linux__
#define __linux__ 1
#undef ifr_name
#undef ifr_flags
#undef ifr_addr
#undef ifr_netmask
#undef ifr_hwaddr
#define ifreq test_ifreq
struct test_ifreq { char ifr_name[16]; short ifr_flags;
    struct sockaddr ifr_addr,ifr_netmask,ifr_hwaddr; };
#define SIOCGIFHWADDR 0x8927
#undef IFF_UP
#define IFF_UP 1
#endif
static int mode,queries;
static int fixture_ioctl(int fd,unsigned long op,void *arg) {
    struct ifreq *r=arg;
    (void)fd;
    if(strcmp(r->ifr_name,"wlan0")) return -1;
    queries++;
    if(mode==2 || (mode==3 && op==SIOCGIFFLAGS))return -1;
    if(op==SIOCGIFFLAGS)r->ifr_flags=mode==1?0:IFF_UP;
    else if(op==SIOCGIFADDR || op==SIOCGIFNETMASK) {
        struct sockaddr_in *a=(struct sockaddr_in *)(op==SIOCGIFADDR?&r->ifr_addr:&r->ifr_netmask);
        a->sin_family=mode==4?AF_UNIX:AF_INET;
        inet_pton(AF_INET,op==SIOCGIFADDR?"192.0.2.7":"255.255.255.0",&a->sin_addr);
    } else if(op==SIOCGIFHWADDR) {
        r->ifr_hwaddr.sa_family=mode==4?0:1;
        memcpy(r->ifr_hwaddr.sa_data,"\x02\xaa\xbb\xcc\xdd\xee",6);
    } else return -1;
    return 0;
}
#define ioctl fixture_ioctl
#define main helper_main
#include "../radio.c"
#undef main
int main(int argc,char **argv) {
    char ip[INET_ADDRSTRLEN]="",mask[INET_ADDRSTRLEN]="",mac[18]="";
    const char *state="unknown";
    if(argc!=2)return 2;
    mode=atoi(argv[1]);kernel_status(ip,mask,mac,&state);
    printf("%s|%s|%s|%s|%d\n",state,ip,mask,mac,queries);
    return 0;
}
''')
        p=subprocess.run(['cc','-D_DARWIN_C_SOURCE','-std=c99','-Wall','-Wextra','-Werror',str(source),'-o',str(binary)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        for mode,want in [(0,'up|192.0.2.7|255.255.255.0|02:aa:bb:cc:dd:ee|4\n'),
                          (1,'down|192.0.2.7|255.255.255.0|02:aa:bb:cc:dd:ee|4\n'),
                          (2,'unknown||||4\n'),
                          (3,'unknown|192.0.2.7|255.255.255.0|02:aa:bb:cc:dd:ee|4\n'),
                          (4,'up||||4\n')]:
            p=subprocess.run(RUNNER+[str(binary),str(mode)],capture_output=True,text=True,timeout=3)
            self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout,want)

    def test_status_has_truthful_interface_defaults_and_bounded_route(self):
        header='Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n'
        # Literal Linux /proc hex byte order, foreign/non-default/down/reject rows,
        # malformed and truncated data, no route guessing from STATUS.
        cases=[
            ('wlan0 00000000 010200C0 0003 0 0 600 00000000 0 0 0\n','192.0.2.1'),
            ('eth0 00000000 010200C0 0003 0 0 0 00000000 0 0 0\n',''),
            ('wlan0 000200C0 010200C0 0003 0 0 0 00FFFFFF 0 0 0\n',''),
            ('wlan0 00000000 010200C0 0002 0 0 0 00000000 0 0 0\n',''),
            ('wlan0 00000000 010200C0 0203 0 0 0 00000000 0 0 0\n',''),
            ('wlan0 00000000 010200C0 0003 0 0 0 00FFFFFF 0 0 0\n',''),
            ('wlan0 00000000 XXXXXXXX 0003 0 0 0 00000000 0 0 0\n',''),
            ('wlan0 00000000 010200C0 0003 0 0 0 00000000 0 0',''),
            ('x'*16384+'\n',''),
        ]
        route=RUN/'route'
        try:
            for rows,want in cases:
                with self.subTest(rows=rows[:100]):
                    route.write_text(header+rows)
                    r,_=self.with_supplicant([('STATUS',b'wpa_state=DISCONNECTED\n')],'status')
                    self.assertEqual(r['status'].get('interface_name'),'wlan0')
                    self.assertIn(r['status'].get('interface_state'),('up','down','unknown'))
                    self.assertIn('netmask',r['status']);self.assertIn('mac',r['status'])
                    self.assertEqual(r['status'].get('gateway'),want)
                    self.assertEqual(r['status']['application_reachable'],'unverified')
        finally: route.unlink(missing_ok=True)

    def test_scan_keeps_unsupported_security_separate_from_personal_and_open(self):
        cases = [
            ('[WPA2-EAP-CCMP][ESS]', 'enterprise'),
            ('[WPA-EAP-TKIP][ESS]', 'enterprise'),
            ('[WPA2-PSK-CCMP][ESS]', 'wpa2'),
            ('[WPA-PSK-TKIP][ESS]', 'wpa'),
            ('[WPA2-PSK+SAE-CCMP][ESS]', 'wpa2'),
            ('[WPA2-SAE-CCMP][ESS]', 'wpa3'),
            ('[WEP][ESS]', 'wep'),
            ('[OWE-CCMP][ESS]', 'unsupported'),
            ('[WPA2-CCMP][ESS]', 'unsupported'),
            ('[ESS]', 'open'),
            ('', 'unknown'),
        ]
        rows = b'bssid / frequency / signal level / flags / ssid\n'
        for i, (flags, _) in enumerate(cases):
            rows += ('02:00:00:00:00:%02x\t2412\t-42\t%s\tSameName\n' % (i, flags)).encode()
        result, commands = self.with_supplicant(
            [('SCAN', b'OK\n'), ('SCAN_RESULTS', rows)], 'wifi-scan')
        self.assertEqual(commands, ['SCAN', 'SCAN_RESULTS'])
        for i, (_, expected) in enumerate(cases):
            with self.subTest(index=i):
                self.assertEqual(result['wifi%d' % i]['security'], expected)

    def test_scan_encodes_ssid_and_caps_untrusted_rows(self):
        r,_=self.with_supplicant([('SCAN',b'OK\n'),('SCAN_RESULTS',b'bssid / frequency / signal level / flags / ssid\n00:11:22:33:44:55\t2412\t-42\t[WPA2-PSK-CCMP][ESS]\tCafe\\x20A\n')],'wifi-scan')
        self.assertEqual(r['wifi0']['ssid64'],b64('Cafe A'))
        self.assertEqual(r['wifi0']['security'],'wpa2')
        self.assertEqual(r['status']['scan_freshness'],'unverified')
    def test_connect_sends_secret_only_over_owned_socket_then_reports_pending(self):
        r,cmd=self.with_supplicant([('ADD_NETWORK',b'7\n'),('SET_NETWORK 7 ssid 4e6577204150',b'OK\n'),('SET_NETWORK 7 psk "pa\\"ssword"',b'OK\n'),('SET_NETWORK 7 key_mgmt WPA-PSK',b'OK\n'),('SELECT_NETWORK 7',b'OK\n')],'wifi-connect',ssid64=b64('New AP'),password64=b64('pa"ssword'))
        self.assertEqual(r['reply']['code'],'association_requested')
        self.assertNotIn('password',str(dict(r['reply'])))
        self.assertFalse(any('SAVE_CONFIG' in x for x in cmd))
    def test_failed_connect_removes_only_new_network(self):
        r,cmd=self.with_supplicant([('ADD_NETWORK',b'9\n'),(None,b'FAIL\n'),('REMOVE_NETWORK 9',b'OK\n')],'wifi-connect',ssid64=b64('New'),password64=b64('password'))
        self.assertEqual(r['reply']['code'],'supplicant_rejected')
        self.assertNotIn('REMOVE_NETWORK all',cmd)
    def test_disconnect_is_explicit_control_command(self):
        r,_=self.with_supplicant([('DISCONNECT',b'OK\n')],'wifi-disconnect')
        self.assertEqual(r['reply']['code'],'disconnected')

if __name__=='__main__':unittest.main()
