"""Owned shell behavior on Linux fixtures, not physical mount/journal proof."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
import hashlib

ROOT = Path(__file__).resolve().parents[1]


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'policy.sh').is_file(), 'writable policy missing')
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'build')
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        (self.p / 'mounts').write_text('/dev/root / ext4 ro,noload 0 0\n'
            'tmpfs /tmp tmpfs rw,nosuid,nodev 0 0\n'
            'tmpfs /run tmpfs rw,nosuid,nodev 0 0\n')
        (self.p / 'swaps').write_text('Filename Type Size Used Priority\n')
        for n, start, size in ((2,20480,262144),(3,282624,1048576),
                              (5,2379776,1572864),(9,7131136,52019200)):
            node = self.p / 'block' / ('mmcblk0p' + str(n))
            node.mkdir(parents=True)
            (node/'start').write_text(str(start))
            (node/'size').write_text(str(size))
            (node/'partition').write_text(str(n))
            (node/'ro').write_text('0')
        (self.p / 'net/lo').mkdir(parents=True)
        (self.p / 'net/lo/flags').write_text('0x49')
        (self.p / 'run').mkdir()
        (self.p / 'workspace').mkdir()
        (self.p / 'workspace').chmod(0o700)
        supervisor=(ROOT/'child-supervisor.sh').read_bytes()
        (self.p/'supervisor.sh').write_bytes(supervisor)
        (self.p/'supervisor.sh').chmod(0o600)
        self.supervisor_sha=hashlib.sha256(supervisor).hexdigest()

    def shell(self, code, timeout=5):
        script = '. "$1/policy.sh"\nbb(){ [ "$1" != stat ] || return 127; "$@"; }\n'
        script += 'DEV_MOUNTS=$2/mounts; DEV_SWAPS=$2/swaps; DEV_SYS_BLOCK=$2/block; '
        script += 'DEV_NET=$2/net; DEV_RUN=$2/run; DEV_TEST_BASE=$2; DEV_BB=/usr/bin/env; umask 077\n'
        script += 'DEV_SUPERVISOR=$2/supervisor.sh; DEV_SUPERVISOR_SHA='+self.supervisor_sha+'\n'
        return subprocess.run(['/bin/sh','-c',script+code,'fixture',str(ROOT),str(self.p)],
                              capture_output=True,text=True,timeout=timeout)

    def test_pre_usb_private_check_with_stat_absent(self):
        path=self.p/'boot-child.sh';path.write_text('owned fixture\n');path.chmod(0o600)
        source=(ROOT/'pid1.in').read_text().split('main(){',1)[0]
        script=source+'\nbb(){ [ "$1" != stat ] || return 127; "$@"; }\nprivate "$1"\n'
        result=subprocess.run(['/bin/sh','-c',script,'fixture',str(path)],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        path.chmod(0o644)
        self.assertNotEqual(subprocess.run(['/bin/sh','-c',script,'fixture',str(path)],capture_output=True).returncode,0)
        path.chmod(0o600);os.link(path,self.p/'hardlink')
        self.assertNotEqual(subprocess.run(['/bin/sh','-c',script,'fixture',str(path)],capture_output=True).returncode,0)

    def test_ls_metadata_rejects_partial_special_mode_uid_and_bad_nodes(self):
        for fields in ('-rw------- 1 0', '-rw-------+ 1 0 0 2 Jan 1 file',
                       '-rws------ 1 0 0 2 Jan 1 file', '-rw------- 1 root 0 2 Jan 1 file',
                       'brw------- 1 0 0 179 9 Jan 1 node',
                       'brw------- 1 0 0 , 9 Jan 1 node',
                       'brw------- 1 0 0 179, x Jan 1 node'):
            (self.p/'metadata').write_text(fields+'\n')
            result=self.shell('bb(){ case "$1" in ls) cat "$DEV_TEST_BASE/metadata";; stat) return 127;; *) "$@";; esac; }; dev_ls_fields "$DEV_TEST_BASE/fake"')
            self.assertNotEqual(result.returncode,0,fields)
        for fields in ('-rw------- 1 0 0 2 Jan 1 file', 'brw------- 1 0 0 179, 9 Jan 1 node'):
            (self.p/'metadata').write_text(fields+'\n')
            result=self.shell('bb(){ case "$1" in ls) cat "$DEV_TEST_BASE/metadata";; stat) return 127;; *) "$@";; esac; }; dev_ls_fields "$DEV_TEST_BASE/fake"')
            self.assertEqual(result.returncode,0,(fields,result.stderr))

    def post_mounts(self):
        with (self.p/'mounts').open('a') as out:
            out.write('/dev/mmcblk0p3 /home ext4 rw,nosuid,nodev,noatime 0 0\n'
                      '/dev/mmcblk0p9 /user ext4 rw,nosuid,nodev,noatime 0 0\n')

    def test_pre_mount_rejects_any_prior_target_or_source_mount(self):
        self.assertEqual(self.shell('dev_check_mounts pre').returncode,0)
        for line in ('/dev/mmcblk0p9 /other ext4 rw 0 0\n',
                     '/dev/mmcblk0p3 /home ext4 rw 0 0\n',
                     'tmpfs /user tmpfs rw 0 0\n'):
            original=(self.p/'mounts').read_text()
            (self.p/'mounts').write_text(original+line)
            self.assertNotEqual(self.shell('dev_check_mounts pre').returncode,0)
            (self.p/'mounts').write_text(original)

    def test_post_mount_requires_both_exact_rw_ext4_targets(self):
        self.assertNotEqual(self.shell('dev_check_mounts post').returncode,0)
        self.post_mounts()
        self.assertEqual(self.shell('dev_check_mounts post').returncode,0)
        valid=(self.p/'mounts').read_text()
        for bad in (valid.replace('p9 /user','p8 /user'),
                    valid.replace('/user ext4 rw,','/user ext4 ro,'),
                    valid.replace('/user ext4','/user vfat'),
                    valid+'/dev/mmcblk0p9 /user ext4 rw,nosuid,nodev 0 0\n'):
            (self.p/'mounts').write_text(bad)
            self.assertNotEqual(self.shell('dev_check_mounts post').returncode,0)

    def test_partition_start_and_size_must_match_exactly(self):
        self.assertEqual(self.shell('dev_check_partitions').returncode,0)
        (self.p/'block/mmcblk0p9/start').write_text('7131137')
        self.assertNotEqual(self.shell('dev_check_partitions').returncode,0)

    def test_writable_partition_cannot_become_block_readonly(self):
        (self.p/'block/mmcblk0p9/ro').write_text('1')
        self.assertNotEqual(self.shell('dev_check_partitions').returncode,0)

    def test_operator_handoff_matches_exact_payload_and_cmdline_bytes(self):
        pid1=b'owned test pid1\n'; cmdline=b'owned test cmdline\n'
        (self.p/'pid1').write_bytes(pid1);(self.p/'cmdline').write_bytes(cmdline)
        receipt=('profile=writable-development-v1\n'
            'kernel_sha256=c7afae1b766457df618fcb49b47736f27d10616baeddb6082a197094c53ba4d4\n'
            'pid1_sha256='+hashlib.sha256(pid1).hexdigest()+'\n'
            'cmdline_sha256='+hashlib.sha256(cmdline).hexdigest()+'\nbootstrap_status=PASS\n')
        path=self.p/'run/boot-operator-handoff';path.write_text(receipt);path.chmod(0o600)
        command='dev_receipt_ok "$DEV_TEST_BASE/pid1" "$DEV_TEST_BASE/cmdline"'
        self.assertEqual(self.shell(command).returncode,0)
        (self.p/'cmdline').write_bytes(cmdline+b'changed')
        self.assertNotEqual(self.shell(command).returncode,0)
        (self.p/'cmdline').write_bytes(cmdline)
        path.write_text(receipt.replace('PASS','FAIL'))
        self.assertNotEqual(self.shell(command).returncode,0)

    def test_mount_failure_stops_without_format_or_second_mount(self):
        code='''dev_verify_before_mount(){ return 0; }
dev_mount(){ printf '%s\\n' "$*" >> "$DEV_TEST_BASE/calls"; return 1; }
dev_mount_persistent
'''
        self.assertNotEqual(self.shell(code).returncode,0)
        calls=(self.p/'calls').read_text().splitlines()
        self.assertEqual(len(calls),1)
        self.assertIn('/dev/mmcblk0p3',calls[0])

    def test_workspace_modes_and_existing_notes_survive_second_start(self):
        first=self.shell('dev_prepare_workspace "$DEV_TEST_BASE/workspace"')
        self.assertEqual(first.returncode,0,first.stderr)
        root=self.p/'workspace'
        note=root/'notes/first.txt'; note.write_text('retained note')
        second=self.shell('dev_prepare_workspace "$DEV_TEST_BASE/workspace"')
        self.assertEqual(second.returncode,0,second.stderr)
        self.assertEqual(note.read_text(),'retained note')
        for name in ('apps','cache','config','notes','words','logs','state','content','rollback'):
            self.assertEqual((root/name).stat().st_mode & 0o777,0o700)
        self.assertEqual((root/'config/reader-sync.ini').stat().st_mode & 0o777,0o600)

    def test_workspace_symlinks_and_linked_config_are_refused(self):
        root=self.p/'workspace'
        (root/'notes').symlink_to(self.p/'run',target_is_directory=True)
        self.assertNotEqual(self.shell('dev_prepare_workspace "$DEV_TEST_BASE/workspace"').returncode,0)
        (root/'notes').unlink()
        self.assertEqual(self.shell('dev_prepare_workspace "$DEV_TEST_BASE/workspace"').returncode,0)
        os.link(root/'config/reader-sync.ini',self.p/'second-name')
        self.assertNotEqual(self.shell('dev_prepare_workspace "$DEV_TEST_BASE/workspace"').returncode,0)

    def test_log_is_bounded_and_rejects_uncontrolled_text(self):
        code='i=0; while [ "$i" -lt 1600 ]; do dev_log storage-ready || exit; i=$((i+1)); done'
        result=self.shell(code)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertLessEqual(sum(p.stat().st_size for p in (self.p/'run').glob('status.log*')),65536)
        self.assertNotEqual(self.shell('dev_log "password=must-not-log"').returncode,0)

    def test_owned_child_termination_leaves_unrelated_process_alive(self):
        code='''sleep 20 & unrelated=$!
trap 'kill "$unrelated" 2>/dev/null; wait "$unrelated" 2>/dev/null' EXIT
dev_spawn app /bin/sleep 20 || exit 1
dev_stop app || exit 2
kill -0 "$unrelated" || exit 3
[ ! -e "$DEV_RUN/app.pid" ]
'''
        result=self.shell(code)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_exited_leader_does_not_leave_owned_descendant_running(self):
        script=self.p/'launcher.sh'
        script.write_text('sleep 20 &\nprintf "%s\\n" "$!" > "$1"\nsleep 0.5\n')
        code='''dev_spawn app /bin/sh "$DEV_TEST_BASE/launcher.sh" "$DEV_TEST_BASE/grandchild" || exit 1
sleep 1
dev_stop app || exit 2
grandchild=$(cat "$DEV_TEST_BASE/grandchild")
if [ -r "/proc/$grandchild/stat" ]; then
    fields=$(cat "/proc/$grandchild/stat"); fields=${fields##*) }
    set -- $fields; [ "$1" = Z ] || exit 3
fi
'''
        result=self.shell(code,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_stale_pidfile_is_never_adopted(self):
        code='''sleep 20 & unrelated=$!
trap 'kill "$unrelated" 2>/dev/null; wait "$unrelated" 2>/dev/null' EXIT
printf '%s\\n' "$unrelated" > "$DEV_RUN/app.pid"
dev_spawn app /bin/sleep 20 && exit 1
dev_stop app && exit 2
kill -0 "$unrelated"
'''
        result=self.shell(code)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_exit_is_visible_when_new_status_file_cannot_be_created(self):
        code='''dev_spawn app /bin/sh -c 'sleep 0.3; exit 7' || exit 1
chmod 0500 "$DEV_RUN"
sleep 0.6
dev_child_running app && result=3 || result=0
chmod 0700 "$DEV_RUN"
dev_stop app || exit 2
exit "$result"
'''
        result=self.shell(code,timeout=8)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_only_existing_wlan_and_loopback_can_be_active(self):
        self.assertEqual(self.shell('dev_check_network').returncode,0)
        (self.p/'net/wlan0').mkdir();(self.p/'net/wlan0/flags').write_text('0x1003')
        self.assertEqual(self.shell('dev_check_network').returncode,0)
        (self.p/'net/eth0').mkdir();(self.p/'net/eth0/flags').write_text('0x1003')
        self.assertNotEqual(self.shell('dev_check_network').returncode,0)


if __name__=='__main__': unittest.main(verbosity=2)
