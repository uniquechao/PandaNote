# Ordinary-file apply handoff (independent review required)

Default `apply_transport.py` performs a local dry run only: no ADB/server/device access. `--inspect-target` reads USB serial/current PID1+cmdline/mounts only, without staging or process changes. Only `--execute-once` uses the separately built C transaction helper; normal preparation metadata stays `device_apply_supported=false` and is never forged or flipped.

## Latest reviewed candidate (Wi-Fi save feedback)

Use `build/candidate-wifi-save-2d343ca7` for the next normal installation. Candidate SHA256 is `82a7dfa3c9a78ebc18e2957b072f6828a94a180afd80ff1fc01fd731a0e957de`, native manifest is `2d343ca756c86711fdae5c9c3c1bdf7764a7bc1d205e2ae3ffbc5e9558f0ee52`, and boot ID is `10f37f8095b6ca35d0feaed8`. New bundle SHA256 is `9034878357e9d517edcb8f58fe60aa1bce1fdffd19d81ea2a7fde8f0dbf74c07`, 6,641,402 bytes. Independent closure review and offline transport capture passed; all radio bytes and normalized startup logic match the prior reviewed candidate.

The corrected tool manifest is `7a9f042f41bbe5924d8f3e61a0eec59665f32f3e324b832e63f3c901ba02b51c`; ELF is `b43f64a67a134f4729a40793aef27c611d7dde26b8a4943489bf43f04c98f842`, 72,576 bytes. Independent review and 55 tests passed after the actual ext4 parser rejected the old tool's `rw` filesystem data. The fix passes NULL data while keeping VFS flags and every guard unchanged. Existing norecovery is preserved: this session does not gain journal protection. The first failed attempt/backup must remain archived with explicit no-RW proofs before another reviewed attempt; no blind retry or marker deletion.

The native UI now retains profile-save results separately from live association/IP. Root staged and launched this release in the current writable RAM system; existing IP and note/config/certificate hashes were preserved. Real network profile save and normal reboot remain pending. The old candidate below remains available as historical rollback material; do not mix its candidate/bundle pins with the new directory.

Root lifecycle update 2026-10-21 19:04 +08: real network save/restore succeeded; corrected-tool attempt `normal-install-20261021T185800` installed all48 files and restored root RO. All48 hashes, original p1/GPT and user data were verified. One authorized normal reboot produced actual `PANDANOTE966U2_NORMAL`, original stock boot arguments, automatic guarded hardware/Wi-Fi/app startup, same IP and unchanged note/config/certificate hashes. Reader-originated calendar contact and paint ACK at1792580673 and actual UTC within about1s of host were subsequently observed without manual sync. First retry currently waits5min if boot precedes DHCP. Physical post-reboot screen/note acceptance and normal Bluetooth remain pending. Current session is NORMAL; do not run the RAM-only installer again against it. Failed first pre-RW transaction remains intact under `/home/pandanote-system/failed-pre-rw-20261021T185100/transaction`.

## Prior reviewed candidate pins

- candidate_sha256: `6d4be82c432fd64d0fad102da8549de9bb3da3d3653a87cd72b78af7068e4700`
- tool_manifest_sha256: `43c92c2be0786f6ced84e3187c26bf64aad0d3d1b762a590d032dce341c4eb63`
- tool_sha256: `c2fc0c5001ecba56c4630e10f4af7b5d13b4178c26915266fc64a08af16cbdcf`
- bundle_sha256: `6ef23a74b5e8dad75af4c8c2cd2ba1110536479f0338442cd22bc092a21f45b3`
- bundle_bytes: `6641166`

Current package uses the independently approved and physically RAM-tested native a0396eeffafd04ab86f5825fb945c6939e01a9915a74411d45c0fc72ba73ccc6 (system CLOCK_REALTIME correction after authenticated HTTPS, no RTC write) and reviewed Wi-Fi fe7f3cbb. All52 native source pins were checked against the explicit central source checkout. This normal-boot package remains offline pending independent source/tool review and physical normal-boot acceptance. Build the trusted own helper with `python3 apps/reader-shell/deploy/normal_boot/build_apply.py`; no fixture mode is compiled into the target MIPS ELF, and no MIPS/vendor program was executed to build it. GLIBC2.29 MIPS stat converter version3 and original reviewed startup/runtime inputs are pinned. Tool manifest also binds host transport/bundle/transaction source bytes.

## Root-operated sequence

1. Independent source review first. Current app/controller/session are outside PID1 runtime. Read-only inspection can run while app is visible. Root must verify and stop its exact external controller/session during the commit window; this tool never kills guessed Qt PIDs. It refuses any still-mapped libQtGui process before guard handoff/RW.
2. Local capture verifies the exact normal candidate, every payload byte and mode, helper/transport/startup source freshness. Explicit serial is only PANDANOTE966U2_DEVELOPMENT; ADB devices must contain exactly one matching ready serial. New O_EXCL0600 host audit and exclusive host lease prevent reuse.
3. Create one new0700 RAM staging directory under /tmp; push only captured bundle and own tool, read back both SHA values, chmod only own tool. Device staging remains for diagnosis. Tool then independently verifies UID, exact current PID1/proc-cmdline hashes for11a16c58, primaryGPT34sectors, exact p2/3/5/9 geometry and block node numbers, current ext4 mounts, old inittab hash/mode, regular-file ownership/links, immutable collision and per-filesystem free-space budget.
4. Hold private p9 transaction flock. Verify runtime/adbd PID files and direct PID1-owned PGID/SID identities. TERM only the verified runtime session and await PID1's halt marker; recheck the separate adbd supervisor still alive. Existing PID1 halt stops runtime but deliberately leaves adbd: do not signal PID1, stop the USB gadget, or claim external Qt stopped as a side effect. No old RAM proof is changed or synthesized.
5. Back up old inittab/current and hashes on p3 with file/directory fsync; exclusive attempt marker prevents reuse. Before the only attempted RW remount, read p2 superblock1024B at1024 and require exact clean SHA `acd494b26f7b2c51105670d9cbf2b00b89f38a7da82eeeb758c47b4b6db4ed4e` (actual root read, state1/incompat0x242/needs_recovery=false). One direct remount syscall `rw`; failure refuses immediately, with no noload clearing, fsck, format or retry. Actual root mount options are printed into audit; do not assume this remount enables a journal.
6. Write only listed regular files using descriptor-relative O_NOFOLLOW checks. Each file is fully written/fchmod/fsync, same-directory rename, parent-directory fsync. Prepare current only after immutable payload is durable; final inittab rename/fsync is last. Restore root ro before success. No bootloader/kernel/GPT/raw block write, swap, reboot or factory init call exists.

## Command shape

Run only after source review and root's actual app quiescence. Remove execution flags for offline dry run; add only `--inspect-target` for read-only live detection.

```sh
python3 apps/reader-shell/deploy/normal_boot/apply_transport.py \
  --package apps/reader-shell/deploy/normal_boot/build/candidate \
  --candidate-sha256 CANDIDATE_SHA \
  --tool-manifest-sha256 TOOL_MANIFEST_SHA \
  --serial PANDANOTE966U2_DEVELOPMENT --adb-port 5039 \
  --execute-once --attempt-id UNIQUE_OPERATOR_ATTEMPT \
  --journal apps/reader-shell/deploy/normal_boot/evidence/UNIQUE_OPERATOR_ATTEMPT.jsonl
```

Use the exact pins above; existing attempts are never overwritten or automatically retried. The installer does not reset or claim normal-boot acceptance.

## Error / recovery semantics

C errors before entry commit preserve the old entry; after pointer/entry mutation, restore old pointer then old entry and remount root ro. File and directory sync errors are checked. Catchable HUP/TERM/INT and120s ALRM request rollback; kernel uninterruptible write/fsync/mount can exceed that budget. SIGKILL, kernel crash or power loss cannot be caught: persistent p3 old-entry/current/meta and journal remain. This is not a hardware power-loss guarantee.

`--rollback --execute-once` uses the same exact candidate/bundle and private backups; validates old-entry and old-pointer hashes and current entry/pointer are one of the known old/new values. It accepts the exact reviewed RAM rescue profile with root ro or an interrupted root rw state, restores old current then inittab, and restores root ro. If transitioning a changed root from ro, it requires ext4 magic, clean state and needs_recovery=false rather than pretending the factory superblock SHA is unchanged. It never clears dirty flags. No rollback is allowed through an arbitrary normal-system serial/context. If normal boot fails, root may return through the already proven USB Boot +11a RAM rescue, then use this bounded rollback; routine normal boot itself does not require Mac or RAM upload.

Rollback retains newly written immutable files; no unbounded filesystem cleanup or whole-disk restoration claim. Root must review unsuccessful attempts rather than deleting markers and retrying blindly. Missing completion trailer/ADB timeout is uncertain execution, not proof that no write happened: inspect the independent rescue layer and persistent exact journal/backups before another action.

## Evidence

54 tests pass:30 normal/clone,8 actual native C tests (including per-call file/directory fsync fault positions1..64, six phase failures, fresh-process crash rollback, corrupted backup and immutable input rejection),5 fake ADB tests,5 exact production mount-table tests and6 exact production SB/supervisor boundary tests. Actual complete48-file bundle was also applied and rolled back by own native C on a local ordinary-file clone. Target MIPS ELF was compiled/inspected only. Fixture build disables real device checks and remounts; it is not the uploaded binary. All device identity, remount, adbd handoff, display and reboot durability remain unexecuted in this worker.

Review corrections: mount_table accepts only the explicit current RAM targets/types, rejects duplicates/unknown ancestors and descendants and malformed/failed/truncated mount streams. Rollback RO-to-RW requires exact state1 and known compatible ext4 flags; state3/5 or needs_recovery cannot begin RW. Active interrupted RW rollback also rejects filesystem error state/unknown features. Runtime and adbd must have distinct IDs, exact fixed BusyBox argv/executable and PID1-owned PGID/SID, with captured starttimes rechecked before signal and throughout handoff. Root independently read the live argv and confirmed both match; this worker did not access or signal them. Halt requires a0600 marker and actual ENOENT runtime.pid.
