# Exact NORMAL ordinary-file upgrade

This is a distinct `normal-exact-upgrade-v1` profile. The RAM transport, RAM identity and factory-superblock pin remain separate. Default invocations are offline; this document is not evidence of a device installation or reboot.

Build a candidate with the three explicit additional inputs:

```
python3 build.py --native-build NATIVE --native-sha256 REVIEWED_NATIVE_MANIFEST_SHA \
  --native-source READER_SOURCE --reference-root REFERENCE --radio-binary RADIO \
  --old-normal-package RETAINED_NORMAL_PACKAGE \
  --old-normal-package-sha256 REVIEWED_OLD_PACKAGE_SHA \
  --live-superblock-sha256 REVIEWED_FRESH_ROOT_SUPERBLOCK_SHA --output FRESH_PACKAGE
python3 build_apply.py --normal-upgrade
```

The retained package must contain the exact old current pointer, boot entry, full native release and full system closure, with matching release/system indexes. The candidate binds that closure and the clean current root superblock hash. Its manifest hash and the separately compiled tool manifest hash must both be reviewed. The keyboard factory module is bound into `factory.sha256` using its reviewed provenance; no factory modules are executed during building.

All transport invocations below additionally require `--package`, `--candidate-sha256`, `--tool-dir`, `--tool-manifest-sha256`, `--serial PANDANOTE966U2_NORMAL`, and explicit `--adb-port 5037` or `5039`. No invocation starts an ADB server.

1. `normal_upgrade.py ... --capture-proof FRESH_HOST_PROOF.json` reads live process information only. `--active new` captures a fresh post-reboot rollback proof. It follows the existing app/adbd pidfiles, the PID1-owned service, and one native child with the candidate's exact executable hash. Review and retain the printed proof-file SHA.
2. `normal_upgrade.py ... --proof HOST_PROOF.json --proof-sha256 REVIEWED_PROOF_SHA` captures and checks all host inputs offline. Add `--inspect-target` for a separate read-only live comparison.
3. Only after review, add `--execute-once --attempt-id FRESH_ID --journal FRESH_HOST_AUDIT.jsonl`. The journal and remote stage are exclusive and retained on failure. The transport stages immutable captured tool/bundle/proof bytes and verifies their hashes before invocation. It never issues a host-side mount, signal, reboot, or block write.

The C helper independently checks root/PID1, boot arguments, GPT, partition geometry/nodes, helper-disable state, mount topology, the complete retained old closure, live entry/current, ready markers, process ownership/starttimes/executable inode/argv and proof hashes. A concurrent unrelated Qt process refuses the handoff. It signals only the exact verified native PID with TERM, waits for `app-exited`, both app processes to disappear and the app pidfile to be removed, while rechecking the service and USB supervisor. An already verified rescue state needs no additional signal. Stale PIDs that have been reused cause refusal.

The helper then holds the p9 transaction lease, makes fsync-durable backups on p3, checks the exact clean root superblock before its one RW remount, writes immutable payloads, commits current before inittab, and remounts RO. Existing versions are retained. A normal completion leaves the existing service and USB rescue running; starting the new default requires a separately authorized reboot. An in-process error attempts exact current/entry restoration and RO remount. An abrupt interruption still needs explicit recovery; host fixtures do not establish physical flash durability.

## Rollback

Retain the **same captured candidate, tool and stable bundle SHA**. C backups are under `/home/pandanote-system/transactions/<bundle-sha256>/`, distinct from the Python local-clone transaction key. Never substitute a newly generated candidate or reuse another backup directory.

Use `normal_upgrade.py ... --proof PROOF --proof-sha256 SHA --rollback --execute-once --attempt-id FRESH_ID --journal FRESH_JOURNAL`. Before reboot, the original proof can be reused only while the same service/USB owners remain alive and the original app/supervisor PIDs are absent in the exact `app-exited` rescue state. After reboot into the new service, capture a new proof with `--active new`; this proof changes neither the bundle nor backup key. Rollback verifies the retained old closure, checks backup hashes against both old entry and old-current pins, admits only known old/new live pointers and entries, stops only the proven active native, restores old current then old entry, and returns root RO. Clean post-install superblocks are structurally checked for rollback because an ordinary-file installation changes their dynamic bytes.

A lost/replaced service/USB owner, unexpected pointer/entry, modified retained file, extra mount, dirty/unsupported superblock, competing Qt process, reused attempt or corrupted backup causes refusal. Do not remove evidence or weaken pins to retry. No automatic reboot, raw partition restoration, firmware update, bootloader or GPT mutation is implemented.
