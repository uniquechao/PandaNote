# Writable-profile Wi-Fi integration contract

This is a controller integration interface. This worker has not changed
`build_development_radio.py`, installed the candidate, read the active WPA
password, or touched the device. The current live helper stays unchanged.

## Enable only in the reviewed RW entry

Keep common `radio_init.sh` and its default temporary behavior unchanged. In the
independent development entry, after the actual writable storage guard succeeds:

1. Prepare `/user/pandanote/config/wifi`, with each of `pandanote`, `config` and `wifi`
   owned by UID 0 and mode 0700. Existing ancestors must be real directories,
   not symlinks; do not silently chmod or replace an unknown existing object.
   `/user` must be UID 0, without group/world write permissions (0755 is fine).
2. After `radio_prepare_runtime` creates the new UID-0/mode-0700
   `/tmp/pandanote-connectivity`, publish a regular, single-link, UID-0/mode-0600
   `wifi-persistence` file in that private directory. Its **exact** contents are:

   ```ini
   schema=1
   store=/user/pandanote/config/wifi
   ```

   Include one final newline. This pointer contains no credential and accepts no
   alternate location. Publish it before exposing the runtime to the app.
3. After the owned supplicant/DHCP startup succeeds, invoke the same reviewed
   helper with action `wifi-restore` and this fixed stdin request:

   ```ini
   [request]
   schema=1
   action=wifi-restore
   ```

   Use the fixed executable `/tmp/pandanote-connectivity/pandanote-radio.mipsel` and a
   direct stdin pipe; do not source the saved file or pass any credential in
   arguments/environment. The helper itself revalidates the RW mount and reads
   its private file through descriptors. Do not call factory startup scripts.

`saved_network_absent` is the normal first-boot result. `association_requested`
means only that the stored request reached WPA; actual authentication/IP still
require status polling. Treat `persistence_unavailable`, `persistence_failed`
and `persistence_uncertain` as separate configuration diagnostics, not as a
fabricated connection success. Missing/unsafe pointer or mount cannot turn into
an alternate persistence root. No pointer means the old volatile default.

## Existing device UI and explicit forget

Existing `wifi-connect` stdin requests are unchanged. With a valid opt-in,
successful `SELECT_NETWORK` atomically saves the last requested open/personal
network. This is a saved **pending authentication** request, even if a password
later proves wrong. A nonsecret `saved_network=pending_authentication` status
field accompanies the existing `association_requested` code. WPA/IP status
continues to come from the actual supplicant and interface.

The currently connected old helper's in-memory password is **not** extracted or
automatically migrated. After a reviewed candidate is installed and enabled,
the next explicit connection submitted on the reader saves its request.

`wifi-disconnect`, scanning and status do not erase saved credentials. Only a
future explicit user forget control should send:

```ini
[request]
schema=1
action=wifi-forget
```

The executable action argument is also `wifi-forget`. It removes this store's
saved configuration without disconnecting the active WPA session. The native
request builder currently does not expose restore/forget; automatic restore is
an init/controller integration, and the future forget button needs its own UI
change. No such UI change is claimed here.

## Failure and recovery boundaries

The store holds `requested.ini` (UID 0, 0600, single regular inode, at most 512
bytes), containing a canonical schema-1 `wifi-connect` request. Base64 is an
encoding, not encryption. Only one current network is stored. `.lock` serializes
writers. The private fixed `.requested.tmp` and `.previous.tmp` transaction names
exist only during updates; the old independent copy is synced before commit.

Normal write/rename/sync failure preserves the old visible request. A failed
commit-directory sync triggers rollback. If rollback/sync also fails, the helper
reports `persistence_uncertain` and retains the old private copy for review.
The same uncertainty result applies when final backup deletion or its directory
sync fails after commit; neither save nor forget is acknowledged as successful.
The committed visible request may already have changed. An undeleted owned
backup is retained, and a failed cleanup sync does not establish durable removal.
Stale transaction files are preserved; save/forget refuse rather than adopting
or deleting unreviewed secret material. Restore may still use a separately
validated canonical `requested.ini`. The controller must review those exact
objects before recovery; no wildcard cleanup or secure-flash-erasure claim.

Before physical acceptance, check the opt-in's permissions/mount identity with
an absent-config restore, then an explicit reader connection/save, actual
authentication and IP, a new-process restore, and finally restart persistence.
Calendar/time acceptance remains a separate end-to-end gate.
