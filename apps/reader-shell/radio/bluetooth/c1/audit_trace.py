"""Audit named guest filesystem mutation attempts in QEMU traces.
This is scoped startup evidence, not an assertion about unexecuted radio paths or
all kernel side effects. FD writes are separately bound to owned log handles.
"""
import re
ROOT='/tmp/pandanote-connectivity/bluetooth'
MUTATE={'creat','mkdir','mkdirat','unlink','unlinkat','rename','renameat','renameat2','chmod','chown','lchown','truncate','link','linkat','symlink','symlinkat','rmdir','utime','utimes','utimensat','bind'}
def allowed_path(path):
    # QEMU renders escapes lexically. Never decode or normalize an ambiguous
    # token into permission: reject dot components, repeated/trailing separators,
    # C/percent escapes and control bytes before checking the component boundary.
    if not isinstance(path,str) or not path.startswith('/') or '\\' in path or '%' in path:
        return False
    if any(ord(c)<32 or ord(c)==127 for c in path):return False
    if any(c in ('','.','..') for c in path.split('/')[1:]):return False
    return path==ROOT or path.startswith(ROOT+'/') or path=='/dev/null'
def violations(text):
    result=[]
    for line in text.splitlines():
        call=re.match(r'^\d+\s+(\w+)\(',line)
        if not call:continue
        operation=call[1]
        if operation in {'open','openat'}:
            if not any(x in line for x in ['O_WRONLY','O_RDWR','O_CREAT','O_TRUNC','O_APPEND']):continue
        elif operation not in MUTATE:continue
        paths=re.findall(r'"([^"\n]*)"',line)
        if any(not allowed_path(p) for p in paths):result.append(line)
    return result
