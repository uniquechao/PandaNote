#!/bin/sh
# Stable owned session leader; never exits while descendants may remain alive.
# Parent verifies this group's identity before releasing the start token.
bb(){ "$DEV_BB" "$@"; }
run=$1; name=$2; shift 2
case "$name" in app|adbd|runtime) ;; *) exit 1;; esac
trap ':' TERM INT HUP
while [ ! -f "$run/$name.go" ]; do bb sleep 0.1; done
"$@" </dev/null >/dev/null 2>&1 &
child=$!
wait "$child"
result=$?
(umask 077; bb printf '%s\n' "$result" > "$run/$name.exit")
# Reuse an already allocated status inode if a full/unwritable directory prevents
# creating .exit. If even truncation fails, kill our own verified session group.
if ! (: > "$run/$name.go"); then bb kill -KILL "-$$"; exit 1; fi
# Parent signals the whole verified group; keeping the session leader alive
# until SIGKILL preserves its identity even after the application has exited.
while :; do bb sleep 3600; done
