"""Production NORMAL handoff/remount decisions with syscall-only substitutions."""
import hashlib,struct,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def function(path,name):
 text=path.read_text();start=text.index('static int '+name+'(');at=text.index('{',start)+1;depth=1
 while depth:depth+=(text[at]=='{')-(text[at]=='}');at+=1
 return text[start:at]
class UpgradeBoundariesTests(unittest.TestCase):
 def compile_run(self,source):
  with tempfile.TemporaryDirectory(dir=ROOT/'build') as temp:
   p=Path(temp);binary=p/'contract';sha=ROOT.parents[1]/'third_party/sha256';r=subprocess.run(['cc','-std=c99','-Wall','-Wextra','-Werror','-I'+str(sha),'-x','c','-',str(sha/'sha256.c'),'-o',str(binary)],input=source,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
   r=subprocess.run([str(binary)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
 def test_production_handoff_only_signals_exact_native_and_retains_usb_owners(self):
  code=r'''#include <signal.h>
#include <stdio.h>
struct process {long pid;};static struct process upgrade_processes[4]={{101},{201},{202},{203}};
static int upgrade_handed_off,cancelled,signals,otherqt,owners_bad,rescue_ready,waits,identity_bad,qt_after,native_changed,change_during_scan;
static int identity(void){return identity_bad;}
static int qt_stopped(void){return qt_after;}
static int qt_stopped_except(long pid){if(change_during_scan)native_changed=1;return pid!=203||otherqt;}
static int upgrade_process(unsigned role){return role==3?native_changed:(role>1||owners_bad);}
static int upgrade_rescue(void){return rescue_ready?0:-1;}
static int fake_kill(long pid,int sig){if(pid!=203||sig!=SIGTERM)return -1;signals++;return 0;}
static int fake_usleep(unsigned delay){if(delay!=100000)return -1;waits++;return 0;}
#define kill fake_kill
#define usleep fake_usleep
'''+function(ROOT/'upgrade_target.h','rescue_handoff')+r'''
int main(void){int bad=0;
#define CHECK(name,want) do{if(!(want)){fprintf(stderr,"FAIL %s\n",name);bad++;}}while(0)
 otherqt=1;CHECK("other Qt refuses before signal",rescue_handoff()!=0&&signals==0);otherqt=0;
 cancelled=1;CHECK("cancel refuses before signal",rescue_handoff()!=0&&signals==0);cancelled=0;
 identity_bad=1;CHECK("changed identity refuses",rescue_handoff()!=0&&signals==0);identity_bad=0;
 change_during_scan=1;CHECK("PID changed during Qt scan sends zero signals",rescue_handoff()!=0&&signals==0);change_during_scan=native_changed=signals=0;
 rescue_ready=1;CHECK("exact native TERM reaches rescue",rescue_handoff()==0&&signals==1&&upgrade_handed_off==1);
 CHECK("already rescued sends no further signal",rescue_handoff()==0&&signals==1);
 upgrade_handed_off=0;owners_bad=1;CHECK("lost USB owner aborts wait",rescue_handoff()!=0&&signals==2);owners_bad=0;
 rescue_ready=0;waits=0;CHECK("missing rescue bounded timeout",rescue_handoff()!=0&&waits==150&&signals==3);
 rescue_ready=1;qt_after=1;CHECK("remaining Qt aborts before filesystem transaction",rescue_handoff()!=0);
 return bad?1:0;
}
'''
  self.compile_run(code)
 def test_production_remount_binds_fresh_sb_and_keeps_legacy_pin_out_of_normal_path(self):
  sb=bytearray(1024)
  for off,fmt,value in [(4,'<I',131072),(24,'<I',0),(56,'<H',0xef53),(58,'<H',1),(92,'<I',0x3c),(96,'<I',0x242),(100,'<I',0x46b)]:struct.pack_into(fmt,sb,off,value)
  pin=hashlib.sha256(sb).hexdigest()
  prefix=r'''#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include "sha256.h"
#define O_RDONLY 0
#define O_NOFOLLOW 1
#define O_CLOEXEC 2
#define MS_RDONLY 1UL
#define MS_REMOUNT 32UL
static int root_rw,rollback_mode,mount_calls,fail_mount,guard_calls,badflags,reads;
static char upgrade_sb[65];
static unsigned char sb[1024]={'''+','.join(map(str,sb))+r'''};
static int fake_open(const char*p,int flags){(void)flags;return strcmp(p,"/dev/mmcblk0p2")?-1:7;}
static ssize_t fake_pread(int fd,void*p,size_t n,off_t at){if(fd!=7||n!=1024||at!=1024)return -1;memcpy(p,sb,n);reads++;return n;}
static int fake_close(int fd){return fd==7?0:-1;}
static void hex(const void*p,size_t n,char out[65]){SHA256_CTX c;unsigned char h[32];sha256_init(&c);sha256_update(&c,p,n);sha256_final(&c,h);for(unsigned i=0;i<32;i++)sprintf(out+2*i,"%02x",h[i]);out[64]=0;}
static unsigned sb16(const unsigned char*b){return b[0]|((unsigned)b[1]<<8);}
static uint32_t sb32(const unsigned char*b){return b[0]|((uint32_t)b[1]<<8)|((uint32_t)b[2]<<16)|((uint32_t)b[3]<<24);}
static int mountcontext(int rw){if(root_rw!=rw)badflags++;guard_calls++;return 0;}
static int fake_mount(const char*src,const char*dst,const char*type,unsigned long flags,const void*data){mount_calls++;if(strcmp(src,"/dev/mmcblk0p2")||strcmp(dst,"/")||strcmp(type,"ext4")||data||(flags!=MS_REMOUNT&&flags!=(MS_REMOUNT|MS_RDONLY)))badflags++;return fail_mount?-1:0;}
#define open fake_open
#define pread fake_pread
#define close fake_close
#define mount fake_mount
'''
  code=prefix+function(ROOT/'apply_tool.c','superblock_compatible')+'\n'+function(ROOT/'upgrade_target.h','remountroot')+r'''
int main(void){int bad=0;
#define CHECK(name,want) do{if(!(want)){fprintf(stderr,"FAIL %s\n",name);bad++;}}while(0)
 strcpy(upgrade_sb,"'''+pin+r'''");
 CHECK("fresh reviewed SB RW accepted",remountroot(1)==0&&root_rw==1&&mount_calls==1&&guard_calls==1);
 CHECK("RO uses exact remount syscall",remountroot(0)==0&&root_rw==0&&mount_calls==2);
 upgrade_sb[0]=upgrade_sb[0]=='0'?'1':'0';CHECK("unreviewed SB refuses before syscall",remountroot(1)!=0&&mount_calls==2);
 rollback_mode=1;CHECK("rollback clean SB uses structure",remountroot(1)==0&&root_rw==1);CHECK("rollback restores RO",remountroot(0)==0&&root_rw==0);
 sb[58]=0;CHECK("dirty SB refuses even rollback from RO",remountroot(1)!=0&&root_rw==0&&mount_calls==4);sb[58]=1;
 fail_mount=1;CHECK("failed syscall keeps root state",remountroot(1)!=0&&root_rw==0&&mount_calls==5&&guard_calls==4);
 CHECK("no fs options or wrong flags",badflags==0&&reads==5);return bad?1:0;
}
'''
  self.compile_run(code)
