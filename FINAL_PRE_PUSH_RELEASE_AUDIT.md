# Final Pre-Push / Pre-Deployment Audit

**Repository:** `/home/ayman/car-rental-system`
**Remote:** `https://github.com/kariaymane/ATELIER_BERLIN_LOCATION_CAR.git` — **visibility: PUBLIC**
**Date:** 2026-09-05
**Actions taken:** none. No push, no deploy, no history rewrite, no production write, no purge.

---

## ⛔ 0. STOP-THE-LINE FINDING (supersedes the release question)

**The production owner's live credentials are ALREADY PUBLIC on GitHub, and have been since
2026-09-02 (~3 days).**

| Commit | Reachable from `origin/main` | File |
| --- | --- | --- |
| `ca77fb0` (2026-09-02 19:36) | **YES — PUBLIC** | `FORENSIC_ROOT_CAUSE_ANALYSIS.md:67` |
| `b84ffe6` (2026-09-02 19:48) | **YES — PUBLIC** | `desktop/tests/test_auth_client.py:54` |
| `14acb89` (2026-09-04 17:11) | not yet — **would be published by this push** | `scripts/reconcile_data.py:53` |

The exposed value is the real `berlinecar@gmail.com` account password. I verified it is live by
using it for this audit's read-only probes. Public GitHub is scraped continuously by credential
harvesters; three days of exposure must be treated as compromised.

**Required first action, ahead of any release activity — yours to perform, not mine:**

1. **Rotate the `berlinecar@gmail.com` password now** (and the Fly `ADMIN_PASSWORD` secret).
2. Review the production audit log for unexpected authentications since 2026-09-02.
3. Only then continue with the release sequence below.

Rotation — not history rewriting — is the remedy. Force-rewriting already-public commits does not
recall what has already been cloned or indexed, and carries its own risk; see §4.

**This does not invalidate any engineering finding in `DASHBOARD_CANONICAL_SOURCE_OF_TRUTH_FINAL_REPORT.md`.**
The R1–R5 work is sound and fully green. This is an orthogonal, higher-priority defect that the
pre-push audit surfaced.

---

## 1. EXACT REMOTE DIVERGENCE

```
HEAD        = 99d705c4a6e5a393bc0e3b55786d4fc118dc846c
origin/main = 66088a63c3d2695e14f87047b9f8f8a7c0107f73
git rev-list --left-right --count origin/main...HEAD   ->   0   7
```

`origin/main` is **0 behind, 7 ahead** — no divergence; a push would be a clean fast-forward.
Local `main` sits at `53dfed3`; the audited branch is 2 commits ahead of local `main`.

```
99d705c (HEAD -> fix/cross-runtime-datetime-policy-and-fleet-authority) docs: final cross-runtime consistency report for de6b493
de6b493 fix(consistency): unify the naive-datetime policy across all three runtimes
53dfed3 (main) fix(data-integrity): eliminate orphan fleet count inflation and unify dashboard source-of-truth
1781f90 docs(release): update RELEASE_MANIFEST.md for fresh v1.1.2 build e0a3b93
e0a3b93 fix(ui): eliminate reservations table overflow, fix mnemonic accelerator, and resolve header truncations
a860c86 docs(release): publish v1.1.2 release manifest and build report
14acb89 fix(forensics): remediate reservation, vehicle, and dashboard data integrity across architecture
```

---

## 2. COMMIT-BY-COMMIT REVIEW

### `14acb89` — 2026-09-04 17:11 — *fix(forensics): remediate reservation, vehicle and dashboard data integrity*
27 files, **+3327 / −107**. Source: **YES** (backend `rentals.py`, `base.py`,
`rental_repository.py`, `dashboard_service.py`, `rental_service.py`; desktop `config.py`,
`database.py`, `domain_store.py`, `dashboard_cache.py`, `engine.py`, `dashboard.py`,
`reservation_list.py`, `vehicle_list.py`, `datetime_utils.py`, i18n). Tests: **YES**
(+`test_reservation_data_integrity_forensic.py`, conftest). Production behaviour: **YES**.
Artifacts: **YES**. Docs: 3 forensic proof `.md` files. Also adds **`scripts/reconcile_data.py`**.
Required for release: **YES (source)**. Include: **YES, but only after scrubbing the credential** — see §0.
Note: the three `*_PROOF_*.md` files and `reconcile_data.py` are forensic-only and not required by
the product; they are the commit's only questionable payload.

### `a860c86` — 2026-09-04 17:33 — *docs(release): v1.1.2 manifest and build report*
2 files, +120 / −24. Source: no. Tests: no. Behaviour: no. Artifacts: no.
Documentation-only. Required: no. Include: **yes** (harmless; preserves release auditability).

### `e0a3b93` — 2026-09-04 18:12 — *fix(ui): reservations table overflow, mnemonic, header truncation*
5 files, +58 / −36. Source: **YES** (desktop UI + i18n). Tests: yes (1 adjusted).
Behaviour: **YES, user-visible desktop UI**. Artifacts: **YES**. Forensic-only: no.
Required: **YES**. Include: **yes**.

### `1781f90` — 2026-09-04 18:17 — *docs(release): update RELEASE_MANIFEST for e0a3b93*
1 file, +13 / −13. Documentation-only. Required: no. Include: **yes**.

### `53dfed3` — 2026-09-04 20:01 — *fix(data-integrity): orphan fleet count inflation* — **the P0**
6 files, +599 / −67. Source: **YES** (`domain_store.py`, `main_window.py`, `fleet_status.py`).
Tests: **YES** (+450-line forensic suite). Behaviour: **YES**. Artifacts: **YES**.
Required: **YES — this is the P0 orphan protection.** Include: **yes, mandatory.**

### `de6b493` — 2026-09-04 22:44 — *fix(consistency): unify naive-datetime policy* — **R1–R5**
18 files, +1789 / −110. Source: **YES** (`shared/money_time.py`, backend `fleet_status.py`,
`sync_service.py`, `maintenance.py`, mobile `FleetStatus.kt`, `FleetRepository.kt`).
Tests: **YES** (4 new suites + 12 shared vectors). Behaviour: **YES**. Artifacts: **YES**.
Required: **YES.** Include: **yes, mandatory.**

### `99d705c` — 2026-09-04 22:49 — *docs: final cross-runtime consistency report*
1 file, +283 / −345. **Documentation-only — verified in §6.** Source: no. Tests: no.
Behaviour: no. Artifacts: **no**. Required: no. Include: **yes**.

**Summary:** 4 functional commits (`14acb89`, `e0a3b93`, `53dfed3`, `de6b493`) — all required.
3 documentation commits — all harmless. **No obsolete fixes, no debug experiments, no commits that
should be dropped on technical grounds.** The only blocker is the embedded credential in `14acb89`.

---

## 3. RELEASE DAG

```
origin/main 66088a6  (PUBLIC — already contains the leaked credential via ca77fb0 / b84ffe6)
    │
    ├─ 14acb89  fix(forensics)      SOURCE + tests + 3 forensic docs + scripts/reconcile_data.py ⚠ CREDENTIAL
    ├─ a860c86  docs(release)       docs only
    ├─ e0a3b93  fix(ui)             SOURCE (desktop UI)
    ├─ 1781f90  docs(release)       docs only
    ├─ 53dfed3  fix(data-integrity) SOURCE  ← P0 orphan protection · artifacts v1.1.2 built here
    ├─ de6b493  fix(consistency)    SOURCE  ← R1–R5 · CURRENT ARTIFACT REVISION
    └─ 99d705c  docs                docs only  ← HEAD
```

* Unrelated changes: **none**
* Obsolete fixes: **none** (each functional commit fixes a distinct defect class)
* Debug experiments: **none in application code**; `scripts/reconcile_data.py` and the three
  `*_PROOF_*.md` files are forensic artefacts riding along in `14acb89`
* Safely squashable: the doc pairs (`a860c86`+`1781f90`) — cosmetic only, no benefit
* Must remain separate: `53dfed3` and `de6b493` — each is the provenance anchor for a distinct
  artifact set and is referenced by SHA in shipped reports

---

## 4. RECOMMENDED GIT-HISTORY STRATEGY

| Option | Assessment |
| --- | --- |
| **A — push all unchanged** | ❌ Publishes a third copy of a live credential to a public repo. |
| **B — squash/rebase into a clean series** | ❌ Squashing does not remove a secret that survives into the final tree, and it destroys the `53dfed3` / `de6b493` SHAs that shipped artifacts and reports are anchored to. |
| **C — new branch from `origin/main`, cherry-pick only required commits** | ❌ Same SHA-invalidation problem, and every functional commit is required anyway, so it buys nothing. |
| **D — rotate, scrub forward, then push unchanged** | ✅ **RECOMMENDED** |

**Option D, in order:**

1. **Rotate the production password + Fly `ADMIN_PASSWORD`.** This is the only action that actually
   neutralises the exposure, because `ca77fb0`/`b84ffe6` are already public.
2. Add **one new commit** on top of `99d705c` replacing the credential with an env-var lookup in all
   three files (`scripts/reconcile_data.py`, `desktop/tests/test_auth_client.py`,
   `FORENSIC_ROOT_CAUSE_ANALYSIS.md`). Both code sites are trivially scrubbable: the test drives a
   mocked transport (`AuthClient("https://x")`), so its credential is decorative, and the `.md` line
   is a forensic log entry.
3. Push all **8** commits as a fast-forward.

**Do NOT rewrite the already-public commits.** Force-rewriting `ca77fb0`/`b84ffe6` cannot recall
what has already been cloned or indexed, breaks every existing clone, and would give false comfort.
Rotation is the remedy; scrubbing forward stops the bleeding.

Why not rewrite the *unpushed* commits either: the secret is already public, so rewriting `14acb89`
would remove one copy of an already-disclosed value while invalidating `de6b493` — under which the
current artifacts were built and are named. The cost is real and the benefit is nil.

**Rationale against the stated criteria:** preserves every functional fix (all 4 kept intact);
introduces no unrelated change; preserves auditability (no SHA churn, reports stay accurate);
minimises risk (no history surgery on a public repo); keeps `de6b493` artifacts valid.

---

## 5–6. ARTIFACT PROVENANCE & SOURCE DIFFERENCE

```
git diff de6b493..HEAD --stat
 DASHBOARD_CANONICAL_SOURCE_OF_TRUTH_FINAL_REPORT.md | 628 +++++++++---------
 1 file changed, 283 insertions(+), 345 deletions(-)

git diff de6b493..HEAD --name-only
 DASHBOARD_CANONICAL_SOURCE_OF_TRUTH_FINAL_REPORT.md
```

Exactly one file differs between `de6b493` and `HEAD`, and it is a Markdown report. No
application, shared, test or build-input file changed.

> ### `APPLICATION ARTIFACTS REMAIN VALID FOR de6b493`

Hashes re-verified this session (unchanged since the build):

| Artifact | SHA256 |
| --- | --- |
| `ATELIER_BERLIN_LOCATION_CAR_de6b493.apk` | `507d9a7e40e63b8980a8759e3a0a532d2902bf41f175aed34c02460f6fbb1801` |
| `ATELIER_BERLIN_LOCATION_CAR_de6b493.exe` | `2390d868151f9beb94e5e07a70d2a1ccdc7dc90110029dfbd2677a92b13e5707` |
| `ATELIER_BERLIN_LOCATION_CAR_WINDOWS_de6b493.zip` | `e80c3032ec1cf94ade2e93a291705efe26a39b0234d04f0e92503919b0e8d626` |

Provenance re-confirmed: the Windows bundle's `_internal/shared/money_time.py` contains the new
`to_utc`; the APK's `classes3.dex` contains the `Africa/Casablanca` policy string.

**The artifacts were built from `de6b493` and must be labelled `de6b493`, never `99d705c`.** The
scrub commit proposed in §4 touches only a script, a test and a `.md`, so it will **not** invalidate
them either — but the artifact label stays `de6b493` regardless.

---

## 7. PRODUCTION CONTAMINATION — READ-ONLY DEPENDENCY AUDIT

Access was GET-only (plus one login POST). The API exposes no raw FK/constraint metadata, so
foreign keys below are inferred from the documented schema and from observed reference behaviour,
not read from `information_schema`.

### `SYNC_7613` — full record

```
table            : vehicles
id (PK)          : 41f1ff38-43c8-47c2-8fe8-7cc0e665e16e
registration     : SYNC_7613
vin              : SYNC_41f1ff381234
brand / model    : ForensicBrand / ProofModel
year / colour    : 2026 / Black
status           : MAINTENANCE     effective_status: MAINTENANCE
daily_rental_price: 250.0          current_mileage: 0
created_at       : 2026-08-21T03:43:25.426802Z
updated_at       : 2026-09-04T20:37:08.800803Z
version          : 9
```

Marker hits: `SYNC_`, `ForensicBrand`, `ProofModel` — **three independent markers from the PART 24
list in one row.** Classification is *not* inferred from naming alone: the VIN is synthesised from
the row's own UUID (`SYNC_41f1ff381234`), which no vehicle registry would ever produce.

### Dependent rows — **this is NOT an isolated orphan**

| Table | Rows referencing `41f1ff38…` |
| --- | --- |
| `reservations` | **6** (3 COMPLETED, 3 CANCELLED) |
| `maintenance` | **1** — `665d3883-58fa-4697-8327-acc4bf207b88`, status **ACTIVE**, 2026-09-04 20:37 → exp 2026-09-11 |

```
7c665b6d COMPLETED  2026-08-27 -> 2026-09-04   total=  2 000.0   revenue-eligible: YES
833ab76f COMPLETED  2026-08-31 -> 2027-03-04   total= 46 250.0   revenue-eligible: YES
90f87394 COMPLETED  2026-08-27 -> 2026-09-02   total=  1 500.0   revenue-eligible: YES
7acc6aec CANCELLED  2026-08-25 -> 2026-08-26   total=    250.0   revenue-eligible: no
16e10721 CANCELLED  2026-08-26 -> 2027-04-07   total= 56 000.0   revenue-eligible: no
fbaf55f8 CANCELLED  2026-12-23 -> 2027-12-22   total= 91 000.0   revenue-eligible: no
```

**Deleting the vehicle would cascade to 6 reservations and 1 active maintenance ticket, and would
change historical financial reporting.** Quantified with the canonical pro-rata engine
(`shared/revenue_reference.py`):

| Period | With probe | Without probe | Delta |
| --- | --- | --- | --- |
| today | 700.00 | 450.00 | **−250.00 (−36 %)** |
| week | 14 950.00 | 11 700.00 | **−3 250.00 (−22 %)** |
| month | 28 750.00 | 20 250.00 | **−8 500.00 (−30 %)** |
| **year** | **81 050.00** | **46 800.00** | **−34 250.00 (−42 %)** |

*(The local recompute of year revenue, 81 050.00, matches the server's `year_revenue` exactly —
an additional independent cross-runtime parity confirmation.)*

**Desktop/mobile sync:** both clients pull the full vehicle set, so `SYNC_7613` is present in every
installed client's SQLite/Room cache today. Deleting it server-side requires a client resync to
disappear; a stale client would then hold a reservation row whose vehicle no longer exists — the
exact orphan class `53dfed3` hardened against. The `53dfed3` guards would neutralise its fleet
effect, but its **revenue** rows would still be counted locally until resync.

### Other markers

| Record | Evidence | Class |
| --- | --- | --- |
| `SYNC_7613` | 3 markers, self-referential synthetic VIN, `ForensicBrand`/`ProofModel` | **B — clearly forensic contamination** |
| `koo` (VIN `10222222225555555`, brand `ll`, model `kkkk`) | keyboard-mash across every field, but no forensic marker, 6 reservations, real-looking price 450 | **C — ambiguous (demo/manual test data, not a forensic probe)** |
| `pppppppppppppp` (VIN `00000000000000000`, brand `cici`) | same profile; 2 reservations by clients "E2E LiveSync Probe" / "E2E Gate Probe" | **C — ambiguous, with B-class reservations attached** |
| Clients `'''''''''''''''`, `,,,,,,,,,,,,,,,`, `kkkkkkkkkk`, `qni;q`, `bobo`, … (13 of 15) | keyboard-mash names, mostly null phone/email | **C — ambiguous** |
| Clients `Switch Tester` ×2 (`+212600000042`) | explicit test name, duplicated | **B — test contamination** |
| `ForensicBrand`, `ProofModel` | only on `SYNC_7613` | **B** |
| `CRT-`, `REV-` | **not present** anywhere in vehicles or clients | — |

**Material conclusion:** this is not one contaminated row in an otherwise real dataset. **All 3
vehicles and 13 of 15 clients are non-business data.** There is no evidence of any genuine customer
record in this production database. Before any purge is designed, you need to confirm whether this
environment holds real business data at all — if it does not, a **full reseed** is far safer and
cheaper than surgical deletion.

---

## 8. SAFE REMEDIATION PLAN (design only — NOT EXECUTED)

**Nothing below has been run. `scripts/purge_forensic_probes.sql` remains unexecuted.**

**Recommended action: `MARK INACTIVE`, not `DELETE`, not `ARCHIVE`.**

Rationale — `vehicle.status = 'INACTIVE'` is already a **structural** status in the canonical spec
(`shared/fleet_status_reference.py`: `STRUCTURAL_STATUSES = ("SOLD", "INACTIVE")`). A structural
vehicle is excluded from `total_vehicles` and from all four operational buckets *by the existing,
tested rule*, in all three runtimes, with no schema change, no cascade, and no data loss. It is
reversible with a single UPDATE, propagates through the normal sync path, and needs no new code.

| Option | Fleet counts fixed | Revenue effect | Reversible | Cascade risk | Verdict |
| --- | --- | --- | --- | --- | --- |
| **MARK INACTIVE** | ✅ immediately | revenue rows retained (history preserved) | ✅ one UPDATE | none | ✅ **recommended** |
| ARCHIVE (copy out + delete) | ✅ | removes 34 250 DH from year revenue | partial | medium | acceptable if history must go |
| DELETE | ✅ | removes 34 250 DH; destroys 7 dependent rows | ❌ | **high** | not recommended |

**If you nonetheless require deletion,** the safe order is:

1. **Pre-flight (mandatory):** `pg_dump` of `vehicles`, `reservations`, `maintenance`, `audit_logs`
   filtered to the vehicle id; store off-box; verify the dump restores into a scratch database.
2. Announce a maintenance window — every client must resync afterwards.
3. Single transaction:
   ```
   BEGIN;
     -- children first (FK: reservations.vehicle_id, maintenance.vehicle_id -> vehicles.id)
     DELETE FROM maintenance    WHERE vehicle_id = '41f1ff38-43c8-47c2-8fe8-7cc0e665e16e';  -- expect 1
     DELETE FROM reservations   WHERE vehicle_id = '41f1ff38-43c8-47c2-8fe8-7cc0e665e16e';  -- expect 6
     DELETE FROM vehicle_images WHERE vehicle_id = '41f1ff38-43c8-47c2-8fe8-7cc0e665e16e';
     DELETE FROM vehicles       WHERE id         = '41f1ff38-43c8-47c2-8fe8-7cc0e665e16e';  -- expect 1
   -- verify row counts match expectations BEFORE committing
   COMMIT;   -- else ROLLBACK;
   ```
   Audit-log rows referencing the entity should be **retained** (they are an audit trail, and
   deleting them defeats their purpose) — confirm the FK permits this before running.
4. **Rollback plan:** `ROLLBACK` inside the window; after commit, restore from the §8.1 dump.
5. **Expected dashboard, before → after:**
   `total_vehicles 3 → 2` · `maintenance 1 → 0` · `available 2 → 2` · `rented 0 → 0` · `reserved 0 → 0`
   `year_revenue 81 050 → 46 800` · `month 28 750 → 20 250` · `week 14 950 → 11 700` · `today 700 → 450`
6. **Post-delete verification:** re-run `/dashboard/stats` and `/vehicles/stats`; assert
   `available + rented + reserved + maintenance == total_vehicles`; assert the two endpoints agree
   bucket-for-bucket; force a desktop and mobile resync and confirm both report `total = 2`.
7. **Client implication:** every desktop/mobile install must complete a full sync before its numbers
   match the server; until then a stale client shows the old fleet and the old revenue.

---

## 9. LIVE PRODUCTION DASHBOARD (read-only, 2026-09-05)

```
/api/v1/dashboard/stats : total_vehicles=3  available=2  rented=0  reserved=0  maintenance=1
invariant               : 2 + 0 + 0 + 1 = 3 == total_vehicles          ✅
/api/v1/vehicles/stats  : {AVAILABLE: 2, MAINTENANCE: 1}               ✅ agrees bucket-for-bucket
```

**Counterfactual excluding `SYNC_7613`:**
`total_vehicles=2  available=2  rented=0  reserved=0  maintenance=0` (invariant still holds), plus
the revenue deltas in §7.

---

## 10. KPI SEMANTICS

**Unchanged and correct — `Véhicules en location` = `RENTED`, `Prêts à louer` = `AVAILABLE`.
Not merged; guarded by bucket-disjointness assertions in all three suites.**

Two label pairs reviewed against source. **No change made** — a UI edit would invalidate the
`de6b493` artifacts and force a rebuild, which the audit rules forbid doing unnecessarily. Both are
labelling defects, not calculation defects, and belong in a follow-up release:

| Pair | Source | Assessment |
| --- | --- | --- |
| `Réservations (Ce jour)` = 0 vs `Chiffre d'affaires` = 700 DH | `dashboard.py:_render_reservations_card` uses `{period}_rentals`; revenue uses the pro-rata engine — both driven by the *same* period combo, rendered adjacently | **Materially ambiguous.** "Réservations (Ce jour)" counts rentals *starting* today; revenue is accrual *across* today. Suggested: **"Locations démarrées (Ce jour)"**. |
| `Maintenances en cours` (= `active_maintenance_tickets`) vs `En maintenance` (= fleet bucket) | `dashboard_service.get_overview` counts *all* tickets `NOT IN (COMPLETED, CANCELLED)`, including future-dated ones; the fleet bucket counts vehicles occupied **now** | **Materially misleading.** "En cours" means "in progress", but a ticket scheduled for next month is counted. Currently both read 1 so it is invisible; it will diverge. Suggested: **"Tickets de maintenance ouverts"**. |

---

## 11. SQLITE TIMEZONE RISK — RESOLVED AS P2, NO MIGRATION

Tested against the three conditions:

1. **Does production desktop use the affected storage path?** **NO — proven.**
   `grep -rnE "Column\((DateTime|TIMESTAMP)" desktop/app/models/` returns **nothing**. Every desktop
   datetime is a `String` column (`start_datetime`/`end_datetime` `String(50)`, `created_at`/
   `updated_at` `String(30)`, `*_expiry` `String(10)`). SQLAlchemy's offset-dropping `DateTime`
   binding is never exercised; ISO strings round-trip verbatim with their explicit offsets.
2. **Does it produce a user-visible contradiction?** **No.** The behaviour is confined to the
   backend's SQLite test harness; production backend is PostgreSQL/`TIMESTAMPTZ`.
3. **Is it contained by the current policy?** **Yes** — and the interval predicate now runs in
   Python under the single policy, so SQLite and PostgreSQL agree regardless.

**Verdict: remains documented P2. No migration, and this is not a NO-GO axis.**

---

## 12. REGRESSION GATE — FRESH RUNS AT HEAD `99d705c`

Not carried over from earlier runs; all three re-executed for this audit.

| Suite | Command | Result | Exit |
| --- | --- | --- | --- |
| Backend | `backend/venv/bin/python -m pytest tests -q` | **248 passed**, 7 warnings, 13.19 s | **0** |
| Desktop | `desktop/venv/bin/python -m pytest tests -q` | **352 passed**, 778.31 s | **0** |
| Mobile | `./gradlew :app:testDebugUnitTest --offline --rerun-tasks` | **79 tests, 0 failed, 0 skipped**, BUILD SUCCESSFUL | **0** |

Included in the above: shared parity (26 vectors × 3 runtimes), naive-datetime policy
(`test_naive_datetime_policy` ×2 + `NaiveDatetimePolicyTest`), dashboard/reversion
(`test_dashboard_cache_reversion`), cross-window parity (`test_cross_window_convergence`,
`DashboardVehiclesParityTest`), orphan integrity
(`test_reservation_data_integrity_forensic`), lifecycle/reconnect (`test_sync_*`,
`test_refresh_integrity`, mobile offline/sparse-cache), synchronisation (`test_sync_lifecycle`,
`test_sync_client_pull`, `test_sync_pull_cursor_rewind`), API contract
(`test_api_contract_release_gate`, `test_contract_consistency`), reconciliation
(`test_reconciliation`).

---

## 13. ARTIFACT DECISION

HEAD differs from `de6b493` **only by documentation** (§6). → **Keep the `de6b493` artifacts.
No rebuild.** They must continue to be labelled `de6b493`, never `99d705c`.

---

## 14. PUSH MANIFEST

| SHA | Subject | Required for release? | Risk | Include? |
| --- | --- | --- | --- | --- |
| `14acb89` | fix(forensics): reservation/vehicle/dashboard integrity | **YES** (source) | 🔴 **Publishes a live credential** (`scripts/reconcile_data.py`) | **Only after scrub + rotation** |
| `a860c86` | docs(release): v1.1.2 manifest | no | none | yes |
| `e0a3b93` | fix(ui): table overflow / mnemonic / headers | **YES** | low | yes |
| `1781f90` | docs(release): manifest refresh | no | none | yes |
| `53dfed3` | fix(data-integrity): orphan fleet inflation (**P0**) | **YES** | low | yes |
| `de6b493` | fix(consistency): naive-datetime policy (**R1–R5**) | **YES** | low | yes |
| `99d705c` | docs: final consistency report | no | none | yes |
| *(new)* | chore(security): remove hardcoded credentials | **YES** | none | **add before pushing** |

> ### Recommendation: `DO NOT PUSH`

Not because of the engineering — the engineering is ready. Because pushing today adds a third
public copy of a live production credential, and because the correct first move is **rotation**,
which must happen before anything else. After rotation + the scrub commit, this becomes
**PUSH AS-IS** (fast-forward, no history rewrite).

---

## 15. DEPLOYMENT DECISION — **DO NOT DEPLOY YET**

* **Commit that should become production:** `de6b493` (plus the §4 scrub commit, which is
  deploy-neutral). `99d705c` is docs-only and deploy-neutral.
* **Artifact revision:** `de6b493` — APK / EXE / ZIP, hashes in §5.
* **Migrations required:** **none.** `de6b493` changes no model, no column and no index; the
  backend diff is service/API logic only.
* **Backend compatibility:** response *shape* unchanged; `/dashboard/stats` and `/vehicles/stats`
  keep the same keys. Behaviour changes only for offset-less datetimes, which cannot occur under
  PostgreSQL `TIMESTAMPTZ` — so deploying `de6b493` should produce **identical** production numbers.
  Verified today: server `year_revenue` 81 050.00 == local canonical recompute.
* **Mobile compatibility:** the new APK is required for the W1 fix; it remains compatible with the
  currently deployed backend, so backend and APK may ship independently.
* **Desktop compatibility:** desktop application source is unchanged since `53dfed3`; the EXE/ZIP
  differ only in the bundled `shared/` package.
* **Rollback plan:** `fly releases` → `fly deploy --image <previous>`; no migration means rollback
  is a pure image swap with no data implications. Clients need no rollback.
* **Order:** rotate → scrub → push → deploy backend → distribute APK → distribute Windows build.

---

## 16. FINAL RELEASE MATRIX

| Gate | Status | Evidence |
| --- | --- | --- |
| P0 orphan protection | **PASS** | `53dfed3` guards intact at 3 layers; `test_reservation_data_integrity_forensic` green in desktop 352 |
| R1 datetime parity | **PASS** | 26 shared vectors (12 naive/offset); Backend == Desktop == reference |
| R2 Kotlin policy | **PASS** | `FleetStatus.parseUtcMillis` → `CASABLANCA`; `NaiveDatetimePolicyTest` 7/7 |
| R3 backend datetime | **PASS** | `_coerce` + predicate in Python; `shared.money_time.to_utc` single helper; 4 previously-failing vectors now green |
| R4 mobile authority | **PASS** | `fleetFromLocal` removed; `DashboardVehiclesParityTest`; `MobileLiveAuthorityTest` re-specified |
| R5 regression guards | **PASS** | Reintroducing W1 ⇒ 7 failures across 3 suites; policy guard names the offending site |
| Backend tests | **PASS** | 248 passed, exit 0 (fresh, at HEAD) |
| Desktop tests | **PASS** | 352 passed, exit 0 (fresh, at HEAD) |
| Mobile tests | **PASS** | 79 tests / 0 failed, exit 0 (fresh, `--rerun-tasks`) |
| Cross-runtime parity | **PASS** | 26/26 × 3 runtimes; live `year_revenue` 81 050.00 matches local recompute |
| Cross-window parity | **PASS** | desktop `test_cross_window_convergence` + naive-row guard; mobile `DashboardVehiclesParityTest` |
| Production contamination | **OPEN** | `SYNC_7613` live: +1 vehicle, +1 maintenance, **+34 250 DH/yr revenue**; 6 dependent reservations; whole dataset appears non-business |
| Artifact provenance | **PASS** | `de6b493..HEAD` = 1 `.md`; hashes re-verified; `to_utc` in Windows bundle; Casablanca string in `classes3.dex` |
| Git history | **OPEN** | 7 clean fast-forward commits, **but `14acb89` carries a live credential** |
| **Security / secret exposure** | **🔴 FAIL** | Production credential public since 2026-09-02 in `ca77fb0` + `b84ffe6`; third copy pending in `14acb89` |
| Deployment readiness | **OPEN** | Code ready and migration-free; blocked behind rotation |

---

## FINAL VERDICT

> # `NOT READY — CLEANUP/ACTION REQUIRED`

**The release engineering is done and verified.** All four R-gates pass, all three suites are green
on fresh runs at HEAD, cross-runtime parity is proven, P0 orphan protection is intact, and artifact
provenance is confirmed. On engineering grounds alone this would be `READY`.

It is `NOT READY` for two reasons, in priority order:

1. **🔴 A live production credential is public on GitHub and has been for ~3 days**, and this push
   would add a third copy. Rotation is required immediately — ahead of, and independent of, the
   release.
2. **🟠 `SYNC_7613` distorts production financial reporting far more than previously understood** —
   not a cosmetic +1 on a vehicle count, but **42 % of reported annual revenue**. It has 6 dependent
   reservations and an active maintenance ticket, so it cannot be deleted casually. And the wider
   finding: **all 3 vehicles and 13 of 15 clients look like non-business data**, so the right
   question may not be "purge one row" but "does this environment contain any real data at all?"

### Exact conditions required before GO

1. Rotate `berlinecar@gmail.com` and the Fly `ADMIN_PASSWORD`; review auth logs since 2026-09-02.
2. Land a `chore(security)` commit removing the credential from all three files.
3. Decide `SYNC_7613`: **MARK INACTIVE** (recommended) / archive / delete / full reseed — and
   accept the stated revenue restatement if you choose removal.
4. Confirm whether this production database is expected to hold real business data.
5. Re-run the three suites after the scrub commit (expected: unchanged).
6. Then: push (fast-forward, no rewrite) → deploy `de6b493` → distribute artifacts.

Items 4 and 6's ordering, and the `SYNC_7613` decision, are business calls — not mine to make.
**No push, no deploy, no history rewrite, no production write, and no purge was performed.**
