"""Canonical bounded ordinary-file wire image. Never opens a device."""
import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('normal_transaction',ROOT/'transaction.py');tx=importlib.util.module_from_spec(spec);spec.loader.exec_module(tx)
def capture(package,expected):
 m,key,files=tx.capture(package)
 if 'upgrade_from' in m:raise ValueError('NORMAL upgrade requires its separate exact profile transport')
 if key!=expected:raise ValueError('not exact reviewed candidate manifest')
 header=f"PANDANOTE-FILES-1 {m['boot_id']} {m['native_sha256']} {m['old_inittab_sha256']} {len(files)}\n".encode()
 body=bytearray(header)
 for path,(entry,data) in files.items():
  if any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/._-' for c in path):raise ValueError('unsupported wire path')
  body.extend(f"{entry['role']} {entry['mode']:o} {len(data)} {tx.sha(data)} {path}\n".encode());body.extend(data);body.extend(b'\n')
 if len(body)>24*1024*1024:raise ValueError('bounded wire image exceeded')
 return bytes(body),m
