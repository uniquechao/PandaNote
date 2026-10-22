"""Trusted host persistence integration: real files/locks/fsync and fake WPA.

Only the block-device stat is simulated: this worker cannot mount/use p9 on the
host. Mount bytes, permissions, nofollow opens, links, atomic updates and the
stdin protocol exercise production code. All credentials below are synthetic.
"""
import base64
import configparser
import fcntl
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
# macOS sockaddr_un.sun_path is 104 bytes. Keep the real private socket fixture
# under this worktree but short enough for the central worktree's absolute path.
RUN = ROOT/'.pt'
BIN = RUN/'radio-host'
SECRET = 'TEST_ONLY_"\\$(touch NEVER);!'
SSID = 'Fixture $(touch NEVER)'


def request(action, ssid=None, password=None):
    raw = '[request]\nschema=1\naction='+action+'\n'
    if ssid is not None:
        raw += 'ssid64='+base64.b64encode(ssid.encode()).decode()+'\n'
        raw += 'password64='+base64.b64encode(password.encode()).decode()+'\n'
    return raw.encode()


class PersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RUN.mkdir(mode=0o700, exist_ok=True)
        # Faults wrap only kernel/error boundaries; no production test branches.
        wrapper = RUN/'wrapper.c'
        wrapper.write_text('''#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int fixture_lstat(const char *,struct stat *);
int fixture_fstat(int,struct stat *);
int fixture_fsync(int);
int fixture_renameat(int,const char *,int,const char *);
int fixture_unlinkat(int,const char *,int);
#define lstat fixture_lstat
#define fstat fixture_fstat
#define fsync fixture_fsync
#define renameat fixture_renameat
#define unlinkat fixture_unlinkat
#include "../radio.c"
#undef lstat
#undef fstat
#undef fsync
#undef renameat
#undef unlinkat
static int did_rename,failed_dir,did_cleanup;
int fixture_lstat(const char *path,struct stat *st) {
 int rc=lstat(path,st);
 if(!rc&&!strcmp(path,RADIO_PERSIST_BLOCK)) {
  struct stat mount;
  if(stat(RADIO_USER_ROOT,&mount))return -1;
  st->st_mode=(st->st_mode&0777)|S_IFBLK;st->st_rdev=mount.st_dev;
  if(getenv("PERSIST_TEST_FAULT")&&!strcmp(getenv("PERSIST_TEST_FAULT"),"wrong-block-identity"))st->st_rdev++;
 }
 return rc;
}
int fixture_fstat(int fd,struct stat *st) {
 int rc=fstat(fd,st);const char *fault=getenv("PERSIST_TEST_FAULT");
 if(!rc&&fault&&((S_ISDIR(st->st_mode)&&!strcmp(fault,"wrong-directory-owner"))||
                (S_ISREG(st->st_mode)&&!strcmp(fault,"wrong-file-owner"))))st->st_uid++;
 return rc;
}
int fixture_fsync(int fd) {
 struct stat st;const char *fault=getenv("PERSIST_TEST_FAULT");
 if(fault&&!fstat(fd,&st)) {
  if(!strcmp(fault,"file-fsync")&&S_ISREG(st.st_mode)){errno=EIO;return -1;}
  if(!strcmp(fault,"cleanup-dir-fsync")&&S_ISDIR(st.st_mode)&&did_cleanup){errno=EIO;return -1;}
  if((!strcmp(fault,"commit-dir-fsync")||!strcmp(fault,"commit-and-rollback"))&&S_ISDIR(st.st_mode)&&did_rename&&!failed_dir++) {errno=EIO;return -1;}
 }
 return fsync(fd);
}
int fixture_renameat(int a,const char *old,int b,const char *new) {
 const char *fault=getenv("PERSIST_TEST_FAULT");
 if(fault&&!strcmp(fault,"rename")){errno=EIO;return -1;}
 if(fault&&!strcmp(fault,"commit-and-rollback")&&did_rename&&!strcmp(old,".previous.tmp")){errno=EIO;return -1;}
 int rc=renameat(a,old,b,new);
 if(!rc&&!strcmp(new,"requested.ini"))did_rename=1;
 return rc;
}
int fixture_unlinkat(int fd,const char *name,int flags) {
 const char *fault=getenv("PERSIST_TEST_FAULT");
 if(fault&&!strcmp(fault,"cleanup-unlink")&&!strcmp(name,".previous.tmp")){errno=EIO;return -1;}
 int rc=unlinkat(fd,name,flags);
 if(!rc&&!strcmp(name,".previous.tmp"))did_cleanup=1;
 return rc;
}
''')
        build = subprocess.run(['cc','-D_DARWIN_C_SOURCE','-std=c99','-D_POSIX_C_SOURCE=200809L',
            '-Wall','-Wextra','-Werror',
            '-DRADIO_CTRL="apps/reader-shell/radio/.pt/wlan0"',
            '-DRADIO_LOCAL="'+str(RUN.resolve())+'"',
            '-DRADIO_USER_ROOT="'+str((RUN/'user').resolve())+'"',
            '-DRADIO_PERSIST_BLOCK="'+str((RUN/'p9-fixture').resolve())+'"',
            '-DRADIO_PERSIST_MOUNTS="'+str((RUN/'mounts').resolve())+'"',
            '-DRADIO_STORE_UID='+str(os.geteuid()),str(wrapper),'-o',str(BIN)],
            capture_output=True,text=True)
        if build.returncode:
            raise AssertionError('persistence helper build failed: '+build.stderr)

    def setUp(self):
        self.pointer = RUN/'wifi-persistence'
        self.user = RUN/'user'
        self.store = self.user/'pandanote/config/wifi'
        self.config = self.store/'requested.ini'
        for path in (self.pointer,RUN/'mounts',RUN/'p9-fixture',RUN/'wlan0'):
            if path.exists() or path.is_symlink():path.unlink()
        if self.user.exists():shutil.rmtree(self.user)
        self.store.mkdir(mode=0o700,parents=True)
        for path in (self.user,self.user/'pandanote',self.user/'pandanote/config',self.store):path.chmod(0o700)
        (RUN/'p9-fixture').write_bytes(b'inert stat-only block fixture')
        (RUN/'mounts').write_text(str((RUN/'p9-fixture').resolve())+' '+str(self.user.resolve())+' ext4 rw,noatime 0 0\n')
        self.pointer.write_text('schema=1\nstore='+str(self.store.resolve())+'\n')
        self.pointer.chmod(0o600)

    def write_config(self, data=None):
        self.config.write_bytes(data if data is not None else request('wifi-connect',SSID,SECRET))
        self.config.chmod(0o600)

    def call(self, action='wifi-connect', ssid=SSID, password=SECRET, fault=None, reject=None):
        commands = []
        path = 'apps/reader-shell/radio/.pt/wlan0'
        server = socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
        server.bind(path);server.settimeout(.1)
        stopped = threading.Event()
        def respond():
            while not stopped.is_set():
                try:data,addr=server.recvfrom(65536)
                except socket.timeout:continue
                commands.append(data)
                response=b'FAIL\n' if reject and data.startswith(reject) else b'3\n' if data==b'ADD_NETWORK' else b'OK\n'
                try:server.sendto(response,addr)
                except FileNotFoundError:pass
        thread = threading.Thread(target=respond);thread.start()
        env = dict(os.environ)
        if fault:env['PERSIST_TEST_FAULT']=fault
        raw = request(action,ssid,password) if action=='wifi-connect' else request(action)
        try:p=subprocess.run([str(BIN),action],input=raw,capture_output=True,env=env,timeout=8)
        finally:stopped.set();thread.join(2);server.close();(RUN/'wlan0').unlink()
        self.assertEqual(p.stderr,b'')
        secrets = {SECRET.encode(), password.encode()}
        for raw_secret in tuple(secrets):
            if raw_secret:secrets.add(base64.b64encode(raw_secret))
        for secret in secrets-{b''}:
            self.assertNotIn(secret,p.stdout+p.stderr)
        reply = configparser.ConfigParser(interpolation=None)
        reply.read_string(p.stdout.decode())
        return reply,commands

    def test_opt_in_connect_saves_canonical_pending_request_and_restores_without_shell(self):
        reply,commands=self.call()
        self.assertEqual(reply['reply']['code'],'association_requested')
        self.assertTrue(self.config.exists(),'opted-in connection did not save its pending request')
        self.assertEqual(self.config.read_bytes(),request('wifi-connect',SSID,SECRET))
        self.assertEqual(self.config.stat().st_mode&0o777,0o600)
        first=commands[:]
        restored,commands=self.call('wifi-restore')
        self.assertEqual(restored['reply']['code'],'association_requested')
        self.assertEqual(commands,first)
        self.assertFalse((Path.cwd()/'NEVER').exists())

    def test_default_without_opt_in_remains_volatile(self):
        self.pointer.unlink()
        reply,commands=self.call()
        self.assertEqual(reply['reply']['code'],'association_requested')
        self.assertTrue(commands)
        self.assertFalse(self.config.exists())

    def test_open_network_roundtrip_and_explicit_forget(self):
        reply,_=self.call(ssid='Fixture Open',password='')
        self.assertEqual(reply['reply']['ok'],'1')
        restored,commands=self.call('wifi-restore')
        self.assertEqual(restored['reply']['ok'],'1')
        self.assertIn(b'SET_NETWORK 3 key_mgmt NONE',commands)
        forgot,commands=self.call('wifi-forget')
        self.assertEqual(forgot['reply']['code'],'saved_network_forgotten')
        self.assertEqual(commands,[])
        self.assertFalse(self.config.exists())

    def test_wrong_mount_and_nested_mount_refuse_before_supplicant_or_config_mutation(self):
        self.write_config();old=self.config.read_bytes()
        good=(RUN/'mounts').read_text()
        for bad in (good.replace(' ext4 rw,',' ext4 ro,'),good.replace(' ext4 ',' vfat '),
                    good.replace(str((RUN/'p9-fixture').resolve()),'/dev/not-p9'),
                    good+good,good+'none '+str(self.store.resolve())+' tmpfs rw 0 0\n'):
            (RUN/'mounts').write_text(bad)
            reply,commands=self.call(password='AnotherTestSecret')
            self.assertEqual(reply['reply']['ok'],'0')
            self.assertEqual(commands,[])
            self.assertEqual(self.config.read_bytes(),old)

    def test_unsafe_existing_profile_and_private_ancestors_are_preserved(self):
        self.write_config();old=self.config.read_bytes()
        self.config.chmod(0o644)
        reply,commands=self.call();self.assertEqual(reply['reply']['ok'],'0');self.assertEqual(commands,[])
        self.assertEqual(self.config.read_bytes(),old)
        self.config.chmod(0o600)
        link=self.store/'hardlink';os.link(self.config,link)
        reply,commands=self.call();self.assertEqual(reply['reply']['ok'],'0');self.assertEqual(commands,[])
        link.unlink()
        self.config.unlink();self.config.symlink_to('outside')
        reply,commands=self.call();self.assertEqual(reply['reply']['ok'],'0');self.assertEqual(commands,[])
        self.assertTrue(self.config.is_symlink())
        self.config.unlink();self.write_config();self.user.joinpath('pandanote').chmod(0o755)
        reply,commands=self.call();self.assertEqual(reply['reply']['ok'],'0');self.assertEqual(commands,[])

    def test_file_sync_rename_and_commit_sync_failure_preserve_old_profile(self):
        for fault in ('file-fsync','rename','commit-dir-fsync'):
            self.write_config();old=self.config.read_bytes()
            reply,_=self.call(ssid='Changed Fixture',password='ChangedTestSecret',fault=fault)
            self.assertEqual(reply['reply']['ok'],'0',fault)
            self.assertEqual(self.config.read_bytes(),old,fault)

    def test_unsafe_or_malformed_opt_in_is_never_treated_as_disabled(self):
        for content,mode in (('bad\n',0o600),('schema=1\nstore=/tmp/elsewhere\n',0o600),
                             (self.pointer.read_text(),0o644)):
            self.pointer.write_text(content);self.pointer.chmod(mode)
            reply,commands=self.call()
            self.assertEqual(reply['reply']['ok'],'0')
            self.assertEqual(commands,[])
            self.assertFalse(self.config.exists())

    def test_forget_does_not_claim_success_with_an_unreviewed_stale_secret_transaction(self):
        self.write_config();old=self.config.read_bytes()
        stale=self.store/'.requested.tmp'
        stale.write_bytes(request('wifi-connect','Interrupted Fixture','InterruptedSecret'))
        stale.chmod(0o600);saved_stale=stale.read_bytes()
        reply,commands=self.call('wifi-forget')
        self.assertEqual(reply['reply']['ok'],'0')
        self.assertEqual(commands,[])
        self.assertEqual(self.config.read_bytes(),old)
        self.assertEqual(stale.read_bytes(),saved_stale)

    def test_malformed_oversized_linked_and_fifo_profile_never_reaches_supplicant(self):
        for content in (b'', b'x'*513, b'\x00hidden\n', request('run-shell'),
                        request('wifi-connect',SSID,SECRET)+b'password64=duplicated\n'):
            self.write_config(content)
            reply,commands=self.call('wifi-restore')
            self.assertEqual(reply['reply']['ok'],'0')
            self.assertEqual(commands,[])
            self.assertEqual(self.config.read_bytes(),content)
        self.config.unlink();os.mkfifo(self.config,0o600)
        reply,commands=self.call('wifi-restore')
        self.assertEqual(reply['reply']['ok'],'0');self.assertEqual(commands,[])

    def test_config_ancestor_and_pointer_symlinks_are_rejected(self):
        self.write_config();old=self.config.read_bytes()
        directory=self.user/'pandanote';moved=self.user/'pandanote-real'
        directory.rename(moved);directory.symlink_to(moved.name)
        reply,commands=self.call();self.assertEqual(reply['reply']['ok'],'0');self.assertEqual(commands,[])
        self.assertEqual(self.config.read_bytes(),old)
        directory.unlink();moved.rename(directory)
        moved_pointer=RUN/'pointer-real'
        self.pointer.rename(moved_pointer);self.pointer.symlink_to(moved_pointer.name)
        try:
            reply,commands=self.call();self.assertEqual(reply['reply']['ok'],'0');self.assertEqual(commands,[])
            self.assertEqual(self.config.read_bytes(),old)
        finally:self.pointer.unlink();moved_pointer.rename(self.pointer)

    def test_wrong_owner_or_actual_block_identity_rejects_without_mutation(self):
        self.write_config();old=self.config.read_bytes()
        for fault in ('wrong-file-owner','wrong-directory-owner','wrong-block-identity'):
            reply,commands=self.call(fault=fault)
            self.assertEqual(reply['reply']['ok'],'0',fault)
            self.assertEqual(commands,[],fault)
            self.assertEqual(self.config.read_bytes(),old)

    def test_locked_store_refuses_concurrent_connect_and_keeps_previous_request(self):
        self.write_config();old=self.config.read_bytes()
        lock=self.store/'.lock';lock.touch(mode=0o600)
        with lock.open('r+b') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            reply,commands=self.call(password='NewTestSecret')
            self.assertEqual(reply['reply']['code'],'persistence_unavailable')
            self.assertEqual(commands,[])
            self.assertEqual(self.config.read_bytes(),old)

    def test_supplicant_rejection_and_explicit_disconnect_do_not_erase_saved_request(self):
        self.write_config();old=self.config.read_bytes()
        reply,commands=self.call(ssid='Rejected Fixture',password='RejectedTestSecret',reject=b'SELECT_NETWORK')
        self.assertEqual(reply['reply']['ok'],'0')
        self.assertIn(b'REMOVE_NETWORK 3',commands)
        self.assertEqual(self.config.read_bytes(),old)
        reply,commands=self.call('wifi-disconnect')
        self.assertEqual(reply['reply']['code'],'disconnected')
        self.assertEqual(commands,[b'DISCONNECT'])
        self.assertEqual(self.config.read_bytes(),old)

    def test_failed_rollback_reports_uncertainty_and_retains_previous_private_copy(self):
        self.write_config();old=self.config.read_bytes()
        reply,_=self.call(ssid='New Fixture',password='NewTestSecret',fault='commit-and-rollback')
        self.assertEqual(reply['reply']['ok'],'0')
        self.assertEqual(reply['reply']['code'],'persistence_uncertain')
        self.assertEqual((self.store/'.previous.tmp').read_bytes(),old)
        self.assertEqual((self.store/'.previous.tmp').stat().st_mode&0o777,0o600)
        self.assertEqual(self.config.read_bytes(),request('wifi-connect','New Fixture','NewTestSecret'))

    def test_forget_cleanup_unlink_failure_reports_uncertainty_and_preserves_evidence(self):
        self.write_config();old=self.config.read_bytes()
        reply,commands=self.call('wifi-forget',fault='cleanup-unlink')
        self.assertEqual(reply['reply']['ok'],'0')
        self.assertEqual(reply['reply']['code'],'persistence_uncertain')
        self.assertEqual(commands,[])
        self.assertFalse(self.config.exists())
        self.assertEqual((self.store/'.previous.tmp').read_bytes(),old)

    def test_cleanup_directory_sync_failure_never_acknowledges_forget_or_save(self):
        for action in ('wifi-forget','wifi-connect'):
            self.write_config()
            reply,_=self.call(action,ssid='New Fixture',password='NewTestSecret',fault='cleanup-dir-fsync')
            self.assertEqual(reply['reply']['ok'],'0',action)
            self.assertEqual(reply['reply']['code'],'persistence_uncertain',action)
            self.assertFalse((self.store/'.previous.tmp').exists())
            if action=='wifi-forget':self.assertFalse(self.config.exists())
            else:self.assertEqual(self.config.read_bytes(),request('wifi-connect','New Fixture','NewTestSecret'))


if __name__=='__main__':unittest.main()
