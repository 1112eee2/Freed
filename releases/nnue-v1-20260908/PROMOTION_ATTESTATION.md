# ThaiMakhosEngine NNUE v1 Promotion Attestation

- **Release ID**: 
nue-v1-20260908
- **Promotion Status**: **CONFIRMED & PROMOTED AS PRODUCTION DEFAULT**
- **Attestation Date**: 2026-09-08
- **Active Release Pointer**: config/gui_release.json (Profile: 
nue)
- **Release Manifest**: 
eleases/nnue-v1-20260908/manifest.json (SHA-256: 8A8F15B0E0864D54D6E86E05A0AD9E6F0AF10AA5F245CF53790CB7C8C89A89B1)
- **Promoted Git Commit**: 2cec9f471e9a26388414ba6cfdbf15ae1c70eeb2

---

## 1. Provenance & Artifact Integrity

1. **Gate C Verification (Both Controls Finished PASS)**:
   - 1000ms / move (12T / 512 MiB): 546 pairs (1,092 games) | W 472 D 396 L 224 | LLR +2.946 | Elo +80.3 +/- 13.5 vs HCE
   - 2000ms / move (12T / 512 MiB): 554 pairs (1,108 games) | W 477 D 404 L 227 | LLR +2.946 | Elo +79.8 +/- 12.9 vs HCE
   - Both results published to repository and verified.

2. **Git Head & Script Provenance**:
   - manifest.json records git_head: d0b34aa4a2466e81faebd46928f2f5a53f6a89bc (the commit concluding Gate C matches).
   - manifest.json records initial freeze script SHA-256: 528FCF91C2B15249D2E5F60EEDD4004456D1A30A83DBA49695AE9EC142CB2274.
   - Subsequent commit 2cec9f4 introduced the secure release pointer config/gui_release.json, frontend lifecycle safeguards (AbortController in web/app.js), Node lifecycle tests (work/test_gui_lifecycle.cjs), and expanded CLI smoke options in work/nnue_production_smoke.py (SHA-256: 8F349984C087C494527DBFB3D940FBD3508EDF705CEE0AA213FF27D871039CB6).
   - The frozen manifest is preserved immutably as evidentiary record.

3. **Software & Test Inventories**:
   - Source files count: 155 (SHA-256: 3F6B6FA4FDB3C10FE3C82782F2F417E1915C99DE47CF297B415662972E3D77A4)
   - Test files count: 53 (SHA-256: 5253316EE5CF646DDC72A39B061702B220B3BF94DDEC3BA5018FC8C67ECF1B47)

---

## 2. Verification Evidence

1. **Full Python Test Suite**:
   - Discovered and ran 403 test cases (python -m unittest discover -s tests -p 'test_*.py').
   - **403 passed, 0 failures, 0 errors (100% OK)**.

2. **Frontend Client Lifecycle Tests**:
   - Ran 
ode --test work/test_gui_lifecycle.cjs.
   - **3 passed, 0 failures (100% OK)**. Validated that delayed engine searches from stale games cannot overwrite newly started games.

3. **HTTP Production Smoke Test**:
   - Executed via python work/nnue_production_smoke.py smoke --output ... --launcher.
   - Tested:
     - Cold start readiness (< 3s).
     - 1.0s time budget move (irst_move: 1026ms, backend 
ative-root-split).
     - 2.0s time budget move (second_budget: 2006ms, backend 
ative-root-split).
     - Forced move (orced: 2.8ms, backend orced).
     - Tablebase 4-piece probe (	ablebase4: 619ms, hit confirmed).
     - Terminal status detection (
o_legal_move, 
o_progress, 
epetition).

4. **Reversible Rollback Assurance**:
   - Launching with --release-profile hce boots uild/makhos_native_accepted.dll with 
nue_enabled: false.
   - Missing or corrupted release files fail visibly with HTTP 503 instead of silent fallback.
