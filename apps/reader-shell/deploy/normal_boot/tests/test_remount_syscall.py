"""Compile the real remountroot function at its syscall boundary; no real mount."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class RemountSyscallTests(unittest.TestCase):
 def test_vfs_flags_and_no_filesystem_options_for_both_transitions(self):
  # Extract production code rather than the PANDANOTE_FIXTURE remount stub. Only
  # syscall boundaries are substituted: the actual production decision runs.
  source = (ROOT / 'apply_tool.c').read_text()
  start = source.index('static int remountroot(int rw){')
  begin = source.index('{', start)
  depth = 1
  end = begin + 1
  while depth:
   depth += (source[end] == '{') - (source[end] == '}')
   end += 1
  function = source[start:end]
  program = r'''#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#define O_RDONLY 0
#define O_NOFOLLOW 1
#define O_CLOEXEC 2
#define MS_RDONLY 1UL
#define MS_REMOUNT 32UL
static int root_rw, rollback_mode, mount_calls, fail_mount;
static int guard_calls, flags_bad, options_bad, path_bad, reads;
static int fake_open(const char *p,int flags){(void)flags;if(strcmp(p,"/dev/mmcblk0p2"))path_bad++;return 7;}
static ssize_t fake_pread(int fd,void *p,size_t n,off_t at){if(fd!=7||n!=1024||at!=1024)path_bad++;memset(p,0,n);reads++;return n;}
static int fake_close(int fd){if(fd!=7)path_bad++;return 0;}
static void hex(const void *p,size_t n,char *out){(void)p;(void)n;strcpy(out,"acd494b26f7b2c51105670d9cbf2b00b89f38a7da82eeeb758c47b4b6db4ed4e");}
static int superblock_compatible(const unsigned char *p,int clean){(void)p;(void)clean;return 1;}
static int mountcontext(int rw){if(root_rw!=rw)flags_bad++;guard_calls++;return 0;}
static int fake_mount(const char *src,const char *dst,const char *type,unsigned long flags,const void *data){
 mount_calls++;if(strcmp(src,"/dev/mmcblk0p2")||strcmp(dst,"/")||strcmp(type,"ext4"))path_bad++;
 if(flags!=(mount_calls==2?MS_REMOUNT|MS_RDONLY:MS_REMOUNT))flags_bad++;
 if(data){options_bad++;return -1;}return fail_mount?-1:0;
}
#define open fake_open
#define pread fake_pread
#define close fake_close
#define mount fake_mount
''' + function + r'''
int main(void){int bad=0;
#define CHECK(name,want) do {if(!(want)){fprintf(stderr,"FAIL %s\n",name);bad++;}}while(0)
 CHECK("rw_remount_accepted",remountroot(1)==0&&root_rw==1);
 CHECK("ro_remount_accepted",remountroot(0)==0&&root_rw==0);
 CHECK("post_mount_context_checked",guard_calls==2);
 fail_mount=1;CHECK("failed_mount_keeps_root_state",remountroot(1)==-1&&root_rw==0&&guard_calls==2);
 CHECK("exact_vfs_flags",!flags_bad);
 CHECK("no_filesystem_option_data",!options_bad);
 CHECK("exact_device_and_root",!path_bad&&mount_calls==3&&reads==2);
 return bad?1:0;
}
'''
  (ROOT / 'build').mkdir(exist_ok=True)
  with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
   binary = Path(directory) / 'remount-contract'
   compiled = subprocess.run(['cc','-std=c99','-Wall','-Wextra','-Werror','-x','c','-','-o',str(binary)],input=program,text=True,capture_output=True)
   self.assertEqual(compiled.returncode,0,compiled.stderr)
   result = subprocess.run([str(binary)],text=True,capture_output=True)
   self.assertEqual(result.returncode,0,result.stderr)

if __name__ == '__main__': unittest.main(verbosity=2)
