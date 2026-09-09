# Loadable TB3

`tb3_np80.tb3` is the prebuilt, portable 80-ply WDL + distance oracle used by
the GUI. It includes all valid one-, two- and three-piece boards, both sides,
and clocks 0 through 80. The loader verifies rules/core identities and checksum.
Repetition remains history-dependent and is handled by the search layer.

The artifact is tracked in Git so a fresh checkout does not build TB3 on startup.
Do not generate or overwrite it from a game request. Build provenance is recorded
in `tb3_np80.manifest.json`; runtime provenance uses the artifact SHA-256.

Format, build commands, acceptance evidence and rollback:
[Phase 1B](../docs/architecture/TB3_ARTIFACT_PHASE1B_TH.md).
