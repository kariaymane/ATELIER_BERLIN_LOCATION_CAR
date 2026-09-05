# Secret Exposure Audit

**Repository:** `/home/ayman/car-rental-system`
**Remote:** `https://github.com/kariaymane/ATELIER_BERLIN_LOCATION_CAR.git` — **PUBLIC**
**Audit date:** 2026-09-05
**Scope:** current working tree + every commit in `origin/main..HEAD` + the full history of each
file found to carry a credential.

> **No secret value appears in this document.** Findings are reported as location, class, and value
> *shape* only. The scanner used (`redact()`) emits `<N chars>`, never the value.

---

## 1. Headline

A **live production administrator credential** was committed and reached the public remote on
**2026-09-02**. It remained public for **3 days** before the pre-push audit found it. A third copy
was staged to be published by the pending push.

**The credential must be treated as compromised and rotated.** Rotation is the owner's action,
performed outside this repository. History rewriting is **not** a substitute — see §5.

---

## 2. Exposure table

| Secret Type | First Commit | Public? | Current Tree? | Rotation Required | Code Remediation |
| --- | --- | --- | --- | --- | --- |
| Production admin password + email (`FORENSIC_ROOT_CAUSE_ANALYSIS.md:67`) | `ca77fb0` (2026-09-02 19:36) | **YES — public 3 days** | **No — redacted** | **YES — mandatory** | ✅ Done: value → `<REDACTED>`, address → `<PROD_ADMIN_EMAIL>` |
| Production admin password + email (`desktop/tests/test_auth_client.py:54`) | `b84ffe6` (2026-09-02 19:48) | **YES — public 3 days** | **No — replaced** | **YES — mandatory** | ✅ Done: synthetic `operator@example.test` / `dummy-password`; transport is mocked so the value was decorative |
| Production admin email only (`desktop/tests/test_auth_client.py:64,71`) | `b84ffe6` | **YES** | **No — replaced** | n/a (identifier, not a secret) | ✅ Done: synthetic address |
| Production admin password + email (`scripts/reconcile_data.py:53`) | `14acb89` (2026-09-04 17:11) | **No — unpushed** | **No — env-based** | **YES** (same value) | ✅ Done: `RECONCILE_EMAIL` / `RECONCILE_PASSWORD`, aborts if unset |
| Real DB URLs w/ credentials (`.env`, `.env.backup.*`, `backend/.env`, `backend/.env.local`) | — | **No — never tracked** | Yes (local only) | Recommended (same infra) | ⚪ None needed: `.gitignore` covers `.env` / `.env.*`; `test_env_files_are_never_tracked` now pins this |
| CI PostgreSQL service password (`.github/workflows/backend.yml:67-69`) | pre-existing | Yes | Yes | **No** | ⚪ Accepted: ephemeral GitHub Actions service container on `localhost`, destroyed with the runner, unreachable externally |
| Android **debug** keystore password (`mobile/app/build.gradle.kts:38,40`) | pre-existing | Yes | Yes | **No** | ⚪ Accepted: the universal public Android debug password, by design. The **release** config correctly uses `System.getenv("STORE_PASSWORD"/"KEY_PASSWORD")` |
| `docker-compose.prod.yml:29,30` | pre-existing | Yes | Yes | **No** | ⚪ False positive: `${POSTGRES_USER}` / `${POSTGRES_PASSWORD}` interpolation, no literal |
| Test fixtures at `@test.com` / `@test.local` / `@int.local` / `@rec.local` (`backend/tests/test_auth.py`, `test_rbac.py`, `scripts/{acceptance_chain,final_reconciliation,integration_chain_check,reconciliation_check,vehicle_isolation_matrix}.py`) | pre-existing | Yes | Yes | **No** | ⚪ Accepted: synthetic accounts against `localhost:800x` throwaway servers; verified by fingerprint **not** to be the compromised value |
| `backend/app/schemas/user.py:20` | pre-existing | Yes | Yes | **No** | ⚪ False positive: Pydantic `json_schema_extra` documentation example |
| `mobile/.../AuthScreenPasswordLifecycleTest.kt:59` | pre-existing | Yes | Yes | **No** | ⚪ Accepted: synthetic test constant; verified by fingerprint **not** to be the compromised value |

**Verified absent:** AWS keys (`AKIA…`), GitHub tokens (`ghp_`/`gho_`/…), Fly.io tokens (`FlyV1 …`),
private-key blocks (`-----BEGIN … PRIVATE KEY-----`), hardcoded bearer JWTs. Zero hits across the
tracked tree and all seven unpushed commits.

---

## 3. Per-commit scan of `origin/main..HEAD`

Every commit that a push would publish was scanned by extracting each blob at that revision.

| Commit | Subject | Result |
| --- | --- | --- |
| `14acb89` | fix(forensics): reservation/vehicle/dashboard integrity | ⚠ **2 findings** — `scripts/reconcile_data.py:53` (email+password pair, password literal) |
| `a860c86` | docs(release): v1.1.2 manifest | clean |
| `e0a3b93` | fix(ui): table overflow / mnemonic / headers | clean |
| `1781f90` | docs(release): manifest refresh | clean |
| `53dfed3` | fix(data-integrity): orphan fleet inflation | clean |
| `de6b493` | fix(consistency): naive-datetime policy | clean |
| `99d705c` | docs: final consistency report | clean |

**Only `14acb89` carries a real credential.** The six other unpushed commits are clean.

---

## 4. Identification method (no value printed)

To determine which files held the *specific* compromised value without ever printing or retyping
it, the value was read from the untracked local `.env` and compared by **SHA-256 fingerprint**
(prefix `395bb348c282…`) against every literal found. This proved:

* `AuthScreenPasswordLifecycleTest.kt`, `backend/app/schemas/user.py`, `backend/tests/test_rbac.py`
  → **do not** contain the compromised value (distinct fixtures).
* `FORENSIC_ROOT_CAUSE_ANALYSIS.md`, `scripts/reconcile_data.py`,
  `desktop/tests/test_auth_client.py` → **did** contain it. All three are now remediated.

**Post-remediation verification:** zero tracked files contain the compromised value; zero tracked
files contain the production admin email.

---

## 5. Git-history decision

| Question | Answer |
| --- | --- |
| A) Which commits contain secrets? | `ca77fb0`, `b84ffe6` (public); `14acb89` (unpushed) |
| B) Already public? | `ca77fb0` and `b84ffe6` — **yes, 3 days**. `14acb89` — not yet. |
| C) Would a push expose more? | **Yes** — `14acb89` would publish a third copy. Remediated in the working tree; the *commit* still contains it. |

**Recommendation: rotate; do NOT rewrite history.**

* **For reducing future accidental exposure** — history rewriting adds nothing that the new
  `test_no_hardcoded_secrets.py` guard does not already provide, permanently and automatically.
* **For removing credentials from existing clones** — rewriting cannot achieve this. Public GitHub
  content is cloned, cached, and indexed within minutes; forks and the GitHub API retain unreachable
  objects. Three days of public exposure must be assumed scraped.
* **For compliance** — if a formal record is required, rewriting *after* rotation is defensible, but
  it must be understood as hygiene, not containment.

**Cost of rewriting, for completeness:** rewriting from `14acb89` forward changes every subsequent
SHA, including `de6b493` — the revision the current APK/EXE/ZIP were built from and are named after.
Artifacts would need renaming and every shipped report's SHA references would become wrong. The
benefit is removing one copy of an already-public value. **Not worth it.**

**What to do instead:** land the remediation as a normal forward commit (done in the working tree),
then push. The compromised value stays in `ca77fb0`/`b84ffe6` history but is **dead** after rotation.

---

## 6. Remediation applied to the working tree

| File | Change |
| --- | --- |
| `scripts/reconcile_data.py` | New `_credentials()` reads `RECONCILE_EMAIL` / `RECONCILE_PASSWORD`; **raises `SystemExit` when unset** — no default, no fallback. Matches the file's existing `os.environ.get("API_BASE_URL", …)` idiom; no new secret-management system introduced. |
| `desktop/tests/test_auth_client.py` | All three real-address logins → `operator@example.test` / `dummy-password`, with a comment explaining that the transport is mocked so a real credential adds nothing. |
| `FORENSIC_ROOT_CAUSE_ANALYSIS.md` | Credential → `<REDACTED>`; admin address → `<PROD_ADMIN_EMAIL>`. |
| `backend/tests/test_no_hardcoded_secrets.py` | **New** permanent guard (§7). |

### Testing-strategy compliance (§5 of the brief)

`scripts/reconcile_data.py` now **fails safely**: absent environment configuration it aborts with a
clear message rather than falling back to any credential. `desktop/tests/test_auth_client.py` uses a
mocked transport and synthetic values, so it never depends on a real account. No test in the
repository authenticates against production.

---

## 7. Permanent guard — `backend/tests/test_no_hardcoded_secrets.py`

Runs inside the backend suite, therefore in CI, and **fails the build** on reintroduction. It scans
`git ls-files` — precisely what a push would publish — so gitignored `.env` files are correctly out
of scope.

| Check | Rule |
| --- | --- |
| `test_no_real_credentials_in_tracked_files` | An email/password literal pair fails **unless** the email domain is in `SYNTHETIC_DOMAINS` (RFC 2606 reserved + this project's `*.local` fixtures). Catches "a real address next to a password" — the exact shape of this incident — **without hardcoding the compromised value**. |
| `test_no_inline_database_credentials_in_tracked_files` | DB URLs must interpolate (`${VAR}`). Literal passwords fail — except for loopback hosts, since a credential reaching only the CI runner's own loopback is not publishable. |
| `test_no_provider_tokens_or_private_keys` | AWS / GitHub / Fly.io tokens, private-key blocks, hardcoded bearer JWTs. |
| `test_env_files_are_never_tracked` | `.env` / `.env.*` must not be tracked (`.env.example` permitted). |
| `test_guard_actually_detects_a_planted_credential` | Self-test: the detector must match a planted real credential and must **not** match synthetic fixtures — a guard that cannot fail is decoration. |

**Verified by planting a probe file** (`scripts/_guard_probe.py`, since removed):

```
E  HARDCODED PRODUCTION CREDENTIAL DETECTED — do not commit this.
E    scripts/_guard_probe.py:2 — credential literal for a real domain 'realbusiness.com' (18-char password)
E  INLINE DATABASE CREDENTIAL DETECTED — use ${VAR} interpolation.
E    scripts/_guard_probe.py:3 — inline DB password (14 chars) for reachable host 'db.production.example-corp.net'
```

Location, domain and length only — **never the value**. On the clean tree: **9 passed**.

---

## 8. Required owner actions (outside this repository)

1. **Rotate** the production admin password and the Fly `ADMIN_PASSWORD` secret.
2. Rotate the PostgreSQL credentials in `.env` / `backend/.env` if that infrastructure is reachable
   from outside the Fly private network.
3. Review the production audit log for unexpected authentications since **2026-09-02 19:36 UTC+1**.
4. Consider enabling GitHub **secret scanning + push protection** on the repository.
5. Do **not** paste the new credential into this repository, any report, or this session.
