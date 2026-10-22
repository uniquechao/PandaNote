"""Run exact production directory predicate on real Linux mode700/1777 tmpfs.
Only our extracted stat predicate is compiled; no Qt/vendor ELF or hardware.
"""
import re,subprocess,hashlib,json
from pathlib import Path
source=(Path(__file__).resolve().parents[1]/'bluetooth.cpp').read_text()
trusted=re.search(r'static bool trustedDirectory\(.*?\n',source).group(0)
expression=re.search(r'bool ok=(.*?);if\(!ok\)',source).group(1).replace('i==parts.size()-1','final')
program='''#include <sys/stat.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdio.h>
#define __fxstat(version,fd,s) fstat(fd,s)
'''+trusted+'''static bool predicate(int fd,bool final,bool tmp){struct stat s;return '''+expression+''';}
int main(){int bad=0,n=0;
#define CHECK(name,want) do{++n;if(!(want)){fprintf(stderr,"FAIL %s\\n",name);++bad;}}while(0)
 chmod("/tmp",0700);int fd=open("/tmp",O_RDONLY|O_DIRECTORY|O_NOFOLLOW);
 CHECK("private_tmp_ancestor_accepted",predicate(fd,false,true));
 CHECK("private_tmp_general_ancestor_accepted",predicate(fd,false,false));
 chmod("/tmp",01777);CHECK("public_sticky_tmp_ancestor_accepted",predicate(fd,false,true));
 CHECK("public_tmp_final_rejected",!predicate(fd,true,false));
 chmod("/tmp",0777);CHECK("nonsticky_writable_tmp_rejected",!predicate(fd,false,true));
 chmod("/tmp",01776);CHECK("wrong_sticky_mode_rejected",!predicate(fd,false,true));
 chmod("/tmp",0755);CHECK("trusted_root_tmp_accepted",predicate(fd,false,true));
 close(fd);printf("%s Bluetooth real Linux directory policy %d checks vendor_execution=false hardware_access=false\\n",bad?"FAIL":"PASS",n);return bad?1:0;}
'''
image=subprocess.check_output(['docker','image','inspect','pandanote-bluetooth-c4-native:final-lifecycle','--format','{{.Id}}'],text=True).strip()
print(json.dumps(dict(image=image,production_source_sha256=hashlib.sha256(source.encode()).hexdigest(),native_only=True)),flush=True)
cmd=['docker','run','--rm','-i','--user','0:0','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','16','--memory','128m','--cpus','1','--tmpfs','/tmp:rw,nosuid,nodev,exec,size=4m','--entrypoint','/bin/sh',image,'-c','cat > /tmp/cases.cpp && c++ -Wall -Wextra -Werror /tmp/cases.cpp -o /tmp/cases && exec /tmp/cases']
raise SystemExit(subprocess.run(cmd,input=program.encode()).returncode)
