# Final Security & Release Gate

**Repository:** `/home/ayman/car-rental-system`
**Remote:** `https://github.com/kariaymane/ATELIER_BERLIN_LOCATION_CAR.git` — **PUBLIC**
**HEAD:** `1f630747440eaeffb845df813286d25922643715` (`1f63074`)
**`origin/main`:** `66088a63c3d2695e14f87047b9f8f8a7c0107f73` (`66088a6`)
**Date:** 2026-09-05

**Actions NOT taken:** no push · no deploy · no production data modified · no `SYNC_7613`
deletion · no purge SQL · no history rewrite · no secret value printed anywhere.

---

## 1. Credential exposure

A **live production administrator credential** (email + password) was committed to a **public**
GitHub repository and was reachable there for **three days**.

| Commit | Date | Public? | File |
| --- | --- | --- | --- |
| `ca77fb0` | 2026-09-02 19:36 | **YES** | `FORENSIC_ROOT_CAUSE_ANALYSIS.md:67` |
| `b84ffe6` | 2026-09-02 19:48 | **YES** | `desktop/tests/test_auth_client.py:54,64,71` |
| `14acb89` | 2026-09-04 17:11 | not yet — the pending push would have published it | `scripts/reconcile_data.py:53` |

Public GitHub is scraped continuously; three days of exposure must be assumed compromised.
Full detail, with no values, in **`SECRET_EXPOSURE_AUDIT.md`**.

## 2. Rotation status

> ### ⛔ **NOT ROTATED — owner action, outstanding.**

This is the single blocking item. It must be performed **outside this repository**, and the new
value must never be pasted into the repo, a report, or this session.

Required:
1. Rotate the production admin password **and** the Fly `ADMIN_PASSWORD` secret.
2. Rotate the PostgreSQL credentials in `.env` / `backend/.env` if that infrastructure is reachable
   beyond the Fly private network.
3. Review the production audit log for unexpected authentications since **2026-09-02 19:36 (+01:00)**.
4. Recommended: enable GitHub **secret scanning + push protection** on this repository.

Because the old credential is compromised, **it was not used again after the finding** — the
`SYNC_7613` analysis in §6/§7 reuses the read-only data captured before that point rather than
re-authenticating.

## 3. Affected commits

Scan of all commits that a push would publish (`origin/main..HEAD`, blob-level):

| Commit | Result |
| --- | --- |
| `14acb89` | ⚠ 2 findings — `scripts/reconcile_data.py:53` |
| `a860c86`, `e0a3b93`, `1781f90`, `53dfed3`, `de6b493`, `99d705c` | clean |
| `1f63074` *(new — the remediation)* | clean |

Already-public: `ca77fb0`, `b84ffe6`.
Verified absent everywhere: AWS keys, GitHub tokens, Fly.io tokens, private-key blocks, bearer JWTs.

## 4. Affected files

| File | Status |
| --- | --- |
| `FORENSIC_ROOT_CAUSE_ANALYSIS.md` | ✅ redacted → `<REDACTED>` / `<PROD_ADMIN_EMAIL>` |
| `desktop/tests/test_auth_client.py` | ✅ synthetic `operator@example.test` / `dummy-password` (mocked transport — the real value was decorative) |
| `scripts/reconcile_data.py` | ✅ env-based `RECONCILE_EMAIL` / `RECONCILE_PASSWORD`, aborts if unset |
| `.env`, `.env.backup.*`, `backend/.env`, `backend/.env.local` | ⚪ never tracked (gitignored); local only — covered by rotation |
| `.github/workflows/backend.yml` | ⚪ ephemeral CI service container on loopback — accepted |
| `mobile/app/build.gradle.kts` | ⚪ Android **debug** keystore password (public by design); release config correctly uses `System.getenv` |
| `docker-compose.prod.yml` | ⚪ `${VAR}` interpolation — false positive |
| `backend/tests/test_auth.py`, `test_rbac.py`, `scripts/{acceptance_chain,final_reconciliation,integration_chain_check,reconciliation_check,vehicle_isolation_matrix}.py` | ⚪ synthetic accounts on `localhost:800x`; fingerprint-verified **not** the compromised value |

## 5. Secret-remediation status

**Current tree contains no real production secret.**

* Zero tracked files contain the compromised value.
* Zero tracked files contain the production admin address.
* Identification used **SHA-256 fingerprint comparison**, so the value was never printed or retyped.

**Permanent guard added — `backend/tests/test_no_hardcoded_secrets.py` (9 tests, runs in CI):**
real-domain email+password pairs · inline DB credentials on reachable hosts · cloud tokens and
private keys · tracked `.env` files · plus a self-test proving the detector can fail. It scans
`git ls-files` — exactly what a push publishes — and reports file, line, domain and value *length*
only. **The compromised value is not embedded in the guard.**

Verified by planting a probe file: both checks fired with precise locations; probe removed.

**Testing strategy:** no test authenticates against production. `reconcile_data.py` **fails safely**
(`SystemExit`) when the environment is unconfigured rather than falling back to any credential.

## 6. Production data findings (read-only; nothing modified)

Live dashboard: `total_vehicles=3 available=2 rented=0 reserved=0 maintenance=1`;
invariant `2+0+0+1 = 3` ✅; `/vehicles/stats` agrees bucket-for-bucket.

| Record | Evidence | Class |
| --- | --- | --- |
| `SYNC_7613` | 3 markers (`SYNC_`, `ForensicBrand`, `ProofModel`); VIN `SYNC_<own-uuid>` synthesised from its own primary key | **FORENSIC/TEST** |
| `ForensicBrand`, `ProofModel` | only on `SYNC_7613` | **FORENSIC/TEST** |
| Clients `Switch Tester` ×2 (`+212600000042`) | explicit test name, duplicated | **FORENSIC/TEST** |
| Reservations by "E2E LiveSync Probe" / "E2E Gate Probe" | explicit probe names | **FORENSIC/TEST** |
| `koo` (VIN `10222222225555555`, brand `ll`, model `kkkk`) | keyboard-mash in every field, 6 reservations, plausible price | **AMBIGUOUS** |
| `pppppppppppppp` (VIN `00000000000000000`, brand `cici`) | same profile | **AMBIGUOUS** |
| 13 of 15 clients (`'''''''''''''''`, `,,,,,,,,,,,,,,,`, `qni;q`, `bobo`, …) | keyboard-mash names, mostly null contact details | **AMBIGUOUS** |
| `CRT-`, `REV-` | **not present** in vehicles or clients | — |
| **LEGITIMATE** | **none identified** | — |

**Material finding: no record in this production database is identifiable as genuine business
data.** All 3 vehicles and 13 of 15 clients are test-shaped. Before any purge is designed, confirm
whether this environment is expected to hold real data — if not, a **full reseed** is safer and
cheaper than surgical deletion.

## 7. `SYNC_7613` recommendation

Dependencies (read-only): **6 reservations** (3 COMPLETED and revenue-eligible, 3 CANCELLED) and
**1 ACTIVE maintenance ticket** (`665d3883…`). It is **not** an isolated orphan.

Revenue impact, computed with the canonical pro-rata engine:

| Period | With | Without | Delta |
| --- | --- | --- | --- |
| today | 700.00 | 450.00 | −250.00 |
| week | 14 950.00 | 11 700.00 | −3 250.00 |
| month | 28 750.00 | 20 250.00 | −8 500.00 |
| **year** | **81 050.00** | **46 800.00** | **−34 250.00 (−42 %)** |

> ### Recommendation: **(B) MARK INACTIVE** — not delete, not archive.

| Criterion | Why MARK INACTIVE wins |
| --- | --- |
| Data integrity | No rows removed; no FK touched |
| Revenue history | Preserved — deletion would silently restate the year by −42 % |
| Foreign keys | No cascade; the 6 reservations and 1 ticket stay consistent |
| Auditability | The record and its history remain inspectable |
| Reversibility | One `UPDATE` restores it |
| Fleet semantics | `INACTIVE` is **already** a structural status in `shared/fleet_status_reference.py`; a structural vehicle is excluded from `total_vehicles` and all four buckets *by the existing, tested rule*, in all three runtimes — no new code |
| Synchronisation | Propagates through the normal sync path; no client resync hazard, no orphan risk |

Expected result: `total_vehicles 3 → 2`, `maintenance 1 → 0`, `available` stays 2, revenue unchanged.

Controlled delete/archive remains fully specified in `FINAL_PRE_PUSH_RELEASE_AUDIT.md` §8 (backup
requirement, FK order, transaction, rollback, before/after values, client-resync implications)
should you prefer it — **not executed.**

## 8. Artifact impact — **NONE**

The security commit changed a **script**, a **test**, and **documentation** only. The PyInstaller
spec bundles only `desktop/app/assets`, `desktop/app/i18n` and `shared/`; neither `scripts/` nor
`tests/` appear in the built application (verified against the built tree).

> ### `APPLICATION ARTIFACTS REMAIN VALID FOR de6b493` — no rebuild required.

| Artifact | SHA256 |
| --- | --- |
| `…_de6b493.apk` | `507d9a7e40e63b8980a8759e3a0a532d2902bf41f175aed34c02460f6fbb1801` |
| `…_de6b493.exe` | `2390d868151f9beb94e5e07a70d2a1ccdc7dc90110029dfbd2677a92b13e5707` |
| `…_WINDOWS_de6b493.zip` | `e80c3032ec1cf94ade2e93a291705efe26a39b0234d04f0e92503919b0e8d626` |

They must continue to be labelled `de6b493` — never `99d705c` or `1f63074`.

## 9. Test results — after the security cleanup, at HEAD `1f63074`

| Suite | Result | Exit |
| --- | --- | --- |
| Backend | **257 passed** (248 + 9 new secret guards), 15.30 s | **0** |
| Desktop | **352 passed**, 802.20 s | **0** |
| Mobile | **79 tests, 0 failed, 0 skipped**, BUILD SUCCESSFUL | **0** |
| Secret scan | **clean** — 0 real candidates in the tracked tree | — |
| Auth configuration | `test_auth_client.py` 12/12 green on synthetic credentials | 0 |
| Cross-runtime parity (R1) | 26/26 vectors × 3 runtimes | 0 |
| R1–R5 guards | all green (`test_naive_datetime_policy` ×2, `NaiveDatetimePolicyTest`, `DashboardVehiclesParityTest`) | 0 |
| Dashboard integrity / reversion | `test_dashboard_cache_reversion` green | 0 |
| Orphan integrity (P0 `53dfed3`) | green, guards unchanged | 0 |

## 10. Push readiness

**Would be pushed: 8 commits** (fast-forward; `origin/main` is 0 behind, 8 ahead).

| SHA | Subject | Required | Risk | Include |
| --- | --- | --- | --- | --- |
| `14acb89` | fix(forensics): data integrity | YES | 🔴 commit body still contains the credential | yes — value dead after rotation |
| `a860c86` | docs(release) | no | none | yes |
| `e0a3b93` | fix(ui) | YES | low | yes |
| `1781f90` | docs(release) | no | none | yes |
| `53dfed3` | fix(data-integrity) — **P0** | YES | low | yes |
| `de6b493` | fix(consistency) — **R1–R5** | YES | low | yes |
| `99d705c` | docs | no | none | yes |
| `1f63074` | **chore(security)** | YES | none | yes |

> ### `DO NOT PUSH` — until rotation is confirmed.

The tree is clean and the guard is in place, so a push is technically safe. It is gated only on
**rotation**: until the value is dead, publishing `14acb89` re-exposes a working credential.
After rotation → **PUSH AS-IS** (fast-forward, no history rewrite; rationale in
`SECRET_EXPOSURE_AUDIT.md` §5).

Remaining historical exposure after push: `ca77fb0`, `b84ffe6`, `14acb89` retain the value in
commit objects. **Rotation is what neutralises this**; rewriting cannot un-publish it and would
invalidate `de6b493`.

## 11. Deployment readiness

* **Production commit:** `de6b493` (later commits are docs/script/test only, deploy-neutral).
* **Artifact revision:** `de6b493` — hashes in §8.
* **Migrations:** **none** — no model, column or index changed.
* **Compatibility:** response shapes unchanged; behaviour differs only for offset-less datetimes,
  impossible under PostgreSQL `TIMESTAMPTZ`, so production numbers should be identical (confirmed:
  server `year_revenue` 81 050.00 == local canonical recompute).
* **Rollback:** `fly releases` → redeploy previous image; no migration, so a pure image swap.
* **Order:** rotate → push → deploy backend → distribute APK → distribute Windows build.
* **Status:** **BLOCKED** behind rotation.

---

# FINAL VERDICT

> # `NO-GO — SECURITY REMEDIATION REQUIRED`

| Condition | Status |
| --- | --- |
| Exposed credential rotated | ⛔ **OUTSTANDING — owner action** |
| Current source contains no real production secret | ✅ **DONE** |
| Secret scan passes | ✅ **DONE** (9/9 guards; 0 real candidates tracked) |
| All tests pass | ✅ **DONE** (257 / 352 / 79, all exit 0) |
| Push manifest reviewed | ✅ **DONE** (§10) |

**Four of five conditions are met. The gate is held open by exactly one item: rotation.**

The release engineering itself was verified `GO` in
`DASHBOARD_CANONICAL_SOURCE_OF_TRUTH_FINAL_REPORT.md` and nothing here weakens that — R1–R5 remain
green and the P0 orphan protection is intact. This is `NO-GO` on **security**, not on correctness.

Two decisions also remain open and are yours, not mine: the `SYNC_7613` disposition (§7 recommends
**MARK INACTIVE**) and whether this production database is expected to contain real business data
at all (§6).

**STOP.** No further release action will be taken until you confirm rotation is complete.
