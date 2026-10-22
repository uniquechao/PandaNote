# Exact NORMAL upgrade implementation plan

Goal: Upgrade the independently verified current NORMAL release using a new profile, preserving the RAM installer and its pins.

Architecture: Bind the old normal package closure and a freshly captured clean root superblock SHA into the new candidate. A separate transport and C build mode share only the existing regular-file/fsync transaction implementation. Process proof is independently hashed so a fresh post-reboot rollback proof does not change the persistent transaction key.

Constraints: No device operations in development; no service/hardware template edits; no guessed process signals; preserve USB rescue; retain immutable old files; current before inittab; rollback current before entry; restore root RO.

- [x] Add failing old-package closure, protocol, clone transaction, rollback and fake-transport tests.
- [x] Implement explicit builder metadata and independent NORMAL wire/transport.
- [x] Implement separately compiled NORMAL identity/handoff/remount hooks, retaining the existing RAM branch.
- [x] Verify native clone transactions including interruption, corrupt inputs and mismatched proofs.
- [x] Run old normal/RAM regressions and compile/inspect the new target helper without executing it.

Final native package policy tests remain pending the parent-owned frozen native build. No device operation or target ELF execution was performed.
