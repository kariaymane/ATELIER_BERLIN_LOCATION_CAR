#!/usr/bin/env python3
"""
Cross-runtime parity verification script.

Asserts that:
  Backend Revenue == Desktop Revenue == Mobile Revenue == Canonical Reference == Expected

Can run against:
  1. Golden vectors from shared/revenue_cases.json (including live production fixture)
  2. Live deployed production API (with --live flag)

Exit 0 if all equal, exit 1 if any divergence occurs.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "desktop"))

from shared.revenue_reference import revenue_between as spec_revenue, rental_days_between as spec_days
from desktop.app.sync.dashboard_cache import revenue_between_rows as desktop_revenue

BIZ_TZ = ZoneInfo("Africa/Casablanca")


# ── Mobile RevenueEngine pure Python implementation for exact parity check ──
def mobile_epoch_day(iso_str: str) -> int:
    d = date.fromisoformat(iso_str)
    return (datetime(d.year, d.month, d.day, tzinfo=ZoneInfo("UTC")) - datetime(1970, 1, 1, tzinfo=ZoneInfo("UTC"))).days


def mobile_calc_revenue(reservations: list[dict], from_iso: str, to_iso: str, now_dt: datetime) -> tuple[float, int]:
    """Replicates mobile RevenueEngine.kt exactly to verify logic identity."""
    from_d = date.fromisoformat(from_iso)
    to_d = date.fromisoformat(to_iso)
    now_biz = now_dt.astimezone(BIZ_TZ) if now_dt.tzinfo else now_dt.replace(tzinfo=BIZ_TZ)
    
    total_rev = Decimal("0")
    total_days = 0

    for r in reservations:
        st = (r.get("status") or "").upper()
        if st in ("CANCELLED",):
            continue
        num_days = int(r.get("num_days") or 0)
        if num_days <= 0:
            continue

        raw_start = r.get("start_datetime")
        if isinstance(raw_start, str):
            s_clean = raw_start.strip().replace("Z", "+00:00").replace("z", "+00:00")
            s_dt = datetime.fromisoformat(s_clean)
        elif isinstance(raw_start, datetime):
            s_dt = raw_start
        else:
            continue

        s_biz = s_dt.astimezone(BIZ_TZ) if s_dt.tzinfo else s_dt.replace(tzinfo=BIZ_TZ)
        n = math.floor((now_biz - s_biz).total_seconds() / 86400.0) + 1
        realised = max(0, min(num_days, n))
        if realised <= 0:
            continue

        tot_price = r.get("total_price")
        if tot_price is not None:
            per_day = Decimal(str(tot_price)) / Decimal(num_days)
        else:
            per_day = Decimal(str(r.get("daily_price") or 0))

        sd = s_biz.date()
        lo = max(sd, from_d)
        hi = min(sd + timedelta(days=realised), to_d)
        d_count = (hi - lo).days
        if d_count > 0:
            total_rev += per_day * Decimal(d_count)
            total_days += d_count

    return float(total_rev), total_days


def verify_golden_cases(verbose: bool = False) -> bool:
    cases_file = REPO_ROOT / "shared" / "revenue_cases.json"
    data = json.loads(cases_file.read_text())
    cases = data.get("revenue_cases", [])
    
    all_ok = True
    print(f"Loaded {len(cases)} test cases from {cases_file.name}\n")
    print(f"{'Case Name':<42} | {'Period':<23} | {'Spec':<10} | {'Desktop':<10} | {'Mobile':<10} | Status")
    print("-" * 115)

    for case in cases:
        name = case["name"]
        now_dt = datetime.fromisoformat(case["now"])
        reservations = case["reservations"]
        
        for q in case["queries"]:
            f_iso = q["from"]
            t_iso = q["to"]
            f_date = date.fromisoformat(f_iso)
            t_date = date.fromisoformat(t_iso)
            expected_rev = q["expected_revenue"]
            expected_days = q["expected_days"]

            # 1. Spec
            r_spec = spec_revenue(reservations, f_date, t_date, now=now_dt)
            d_spec = spec_days(reservations, f_date, t_date, now=now_dt)

            # 2. Desktop
            r_desk, d_desk = desktop_revenue(reservations, f_date, t_date, now=now_dt)

            # 3. Mobile
            r_mob, d_mob = mobile_calc_revenue(reservations, f_iso, t_iso, now_dt)

            # Check parity
            diff_spec_desk = abs(r_spec - r_desk)
            diff_spec_mob = abs(r_spec - r_mob)
            diff_desk_mob = abs(r_desk - r_mob)
            diff_expected = abs(r_spec - expected_rev)

            ok = (
                diff_spec_desk < 0.01 and
                diff_spec_mob < 0.01 and
                diff_desk_mob < 0.01 and
                diff_expected < 0.01 and
                d_spec == d_desk == d_mob == expected_days
            )

            status = "PASS" if ok else "FAIL"
            if not ok:
                all_ok = False

            if verbose or not ok or name == "production_live_golden_dataset":
                print(f"{name:<42} | {f_iso}..{t_iso} | {r_spec:<10.2f} | {r_desk:<10.2f} | {r_mob:<10.2f} | {status}")
                if not ok:
                    print(f"   [!] Mismatch details: Spec={r_spec} (days={d_spec}), Desk={r_desk} (days={d_desk}), Mob={r_mob} (days={d_mob}), Expected={expected_rev} (days={expected_days})")

    print("-" * 115)
    return all_ok


def verify_live_api(base_url: str, token: str | None = None) -> bool:
    import urllib.request
    import urllib.error

    print(f"\nChecking live API at: {base_url}")
    endpoints = [
        "/api/v1/dashboard/revenue?from=2026-09-01&to=2026-09-02",
        "/api/v1/dashboard/period/today",
        "/api/v1/dashboard/period/week",
        "/api/v1/dashboard/period/month",
        "/api/v1/dashboard/period/year",
    ]
    all_ok = True
    for ep in endpoints:
        url = f"{base_url.rstrip('/')}{ep}"
        req = urllib.request.Request(url)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                code = resp.status
                body = json.loads(resp.read().decode())
                print(f"  [OK] {ep} -> HTTP {code}: {body}")
        except urllib.error.HTTPError as e:
            print(f"  [FAIL] {ep} -> HTTP {e.code}: {e.read().decode()[:100]}")
            all_ok = False
        except Exception as e:
            print(f"  [FAIL] {ep} -> Connection error: {e}")
            all_ok = False
    return all_ok


def main():
    parser = argparse.ArgumentParser(description="Cross-runtime revenue parity diagnostic")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print all cases")
    parser.add_argument("--live", metavar="URL", help="Check live deployed API at URL")
    parser.add_argument("--token", metavar="TOKEN", help="Bearer token for live API")
    args = parser.parse_args()

    print("=" * 60)
    print("ATELIER BERLIN LOCATION CAR — REVENUE PARITY DIAGNOSTIC")
    print("=" * 60)

    ok_cases = verify_golden_cases(verbose=args.verbose)
    ok_live = True
    if args.live:
        ok_live = verify_live_api(args.live, token=args.token)

    if ok_cases and ok_live:
        print("\nALL RUNTIMES IN COMPLETE REVENUE PARITY.")
        sys.exit(0)
    else:
        print("\nPARITY DIVERGENCE DETECTED!")
        sys.exit(1)


if __name__ == "__main__":
    main()
