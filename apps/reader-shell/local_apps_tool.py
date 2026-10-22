#!/usr/bin/env python3
"""Offline workspace import/export. Stop reader-shell before changing snapshots.
No device transport, mounts, credentials or network. Explicit directory only.
"""
import argparse,base64,contextlib,os,secrets,stat
from pathlib import Path
CAP=2*1024*1024

def read_file(path,private=False,dir_fd=None):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=dir_fd)
 try:
  s=os.fstat(fd)
  if not stat.S_ISREG(s.st_mode) or s.st_size>CAP:raise ValueError('not bounded regular file')
  if private and (s.st_uid!=os.geteuid() or stat.S_IMODE(s.st_mode)!=0o600 or s.st_nlink!=1):raise ValueError('unsafe private file')
  data=b''
  while True:
   part=os.read(fd,4096)
   if not part:break
   data+=part
   if len(data)>CAP:raise ValueError('file limit')
  return data
 finally:os.close(fd)

def check_dir(fd):
 s=os.fstat(fd)
 if not stat.S_ISDIR(s.st_mode) or s.st_uid!=os.geteuid() or stat.S_IMODE(s.st_mode)!=0o700:raise ValueError('directory must be private 0700 and owned by current user')

@contextlib.contextmanager
def directory(root,kind):
 root=Path(root)
 if not root.is_absolute() or '..' in root.parts or root==Path('/'):raise ValueError('absolute workspace required')
 fd=os.open('/'+root.parts[1],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:
  for part in root.parts[2:]:
   new=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=new
  check_dir(fd)
  try:os.mkdir(kind,0o700,dir_fd=fd)
  except FileExistsError:pass
  try:child=os.open(kind,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
  except OSError as e:raise ValueError('unsafe workspace directory') from e
  try:check_dir(child);yield child
  finally:os.close(child)
 finally:os.close(fd)

def atomic(fd,data):
 if len(data)>CAP:raise ValueError('snapshot limit')
 try:read_file('data',True,fd)
 except FileNotFoundError:pass
 name='.pending-'+secrets.token_hex(12);out=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
 try:
  with os.fdopen(out,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.rename(name,'data',src_dir_fd=fd,dst_dir_fd=fd);os.fsync(fd)
 finally:
  try:os.unlink(name,dir_fd=fd)
  except FileNotFoundError:pass

def text(data,limit):
 if len(data)>limit or b'\0' in data:raise ValueError('text limit or NUL')
 return data.decode('utf-8',errors='strict')

def encode(s):return base64.b64encode(s.encode())
def decode(s,limit):
 b=base64.b64decode(s,validate=True)
 if base64.b64encode(b)!=s:raise ValueError('noncanonical base64')
 return text(b,limit)

def parse_tsv(data):
 if len(data)>CAP:raise ValueError('input limit')
 rows=data.split(b'\n')
 if rows[-1]==b'':rows.pop()
 if not rows or len(rows)>1000:raise ValueError('word count')
 words=[]
 for row in rows:
  cols=row.removesuffix(b'\r').split(b'\t')
  if len(cols)!=2:raise ValueError('expected front TAB back')
  a,b=text(cols[0],256),text(cols[1],1024)
  if not a.strip() or not b.strip():raise ValueError('empty word')
  words.append((a,b,False))
 return words

def import_words(root,source):
 words=parse_tsv(read_file(source));data=b'PANDANOTE-WORDS-1\n'+b''.join(encode(a)+b'\t'+encode(b)+b'\t0\n' for a,b,_ in words)
 with directory(root,'words') as fd:atomic(fd,data)

def load_words(root):
 with directory(root,'words') as fd:data=read_file('data',True,fd)
 rows=data.split(b'\n')
 if len(rows)<2 or rows.pop(0)!=b'PANDANOTE-WORDS-1' or rows.pop()!=b'' or len(rows)>1000:raise ValueError('invalid words snapshot')
 words=[]
 for row in rows:
  a,b,known=row.split(b'\t')
  if known not in (b'0',b'1'):raise ValueError('invalid progress')
  words.append((decode(a,256),decode(b,1024),known==b'1'))
 return words

def load_notes(fd):
 try:data=read_file('data',True,fd)
 except FileNotFoundError:return []
 rows=data.split(b'\n')
 if len(rows)<2 or rows.pop(0)!=b'PANDANOTE-NOTES-1' or rows.pop()!=b'' or len(rows)>100:raise ValueError('invalid notes snapshot')
 notes=[]
 for row in rows:
  ident,body=row.split(b'\t');name=ident.decode('ascii')
  if not name.isdecimal() or not 1<=int(name)<=999999999 or str(int(name))!=name or any(a==name for a,_ in notes):raise ValueError('invalid note id')
  notes.append((name,decode(body,16384)))
 return notes

def import_note(root,source):
 body=text(read_file(source),16384)
 with directory(root,'notes') as fd:
  notes=load_notes(fd);ident=max([int(i) for i,_ in notes]+[0])+1
  if len(notes)>=100 or ident>999999999:raise ValueError('notes limit')
  notes.append((str(ident),body));atomic(fd,b'PANDANOTE-NOTES-1\n'+b''.join(i.encode()+b'\t'+encode(b)+b'\n' for i,b in notes))

def export_notes(root,target):
 with directory(root,'notes') as fd:notes=load_notes(fd)
 target=Path(target);target.mkdir(mode=0o700)
 for ident,body in notes:
  fd=os.open(target/(ident+'.txt'),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'wb') as f:f.write(body.encode());f.flush();os.fsync(f.fileno())

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace-dir',required=True,type=Path);p.add_argument('action',choices=['import-words','import-note','export-notes']);p.add_argument('path',type=Path);args=p.parse_args()
 try:{'import-words':import_words,'import-note':import_note,'export-notes':export_notes}[args.action](args.workspace_dir,args.path)
 except (ValueError,OSError) as e:p.exit(1,'Failed: '+str(e)+'\n')
 print('Completed offline workspace operation; restart reader-shell to reload. Mount persistence is not verified by this tool.')
if __name__=='__main__':main()
