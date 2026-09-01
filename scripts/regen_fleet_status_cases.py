"""Regenerate expected_* fields in shared/fleet_status_cases.json from the
NORMATIVE reference (shared/fleet_status_reference.py).

Run after a deliberate, reviewed change to the reference rule:

    python scripts/regen_fleet_status_cases.py

Case *inputs* (vehicles / reservations / maintenances / now) and *names* are
authored by hand; only expected_effective / expected_counts /
expected_next_boundary are recomputed here.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))

import fleet_status_reference as ref  # noqa: E402

CASES = ROOT / "shared" / "fleet_status_cases.json"


def main() -> None:
    data = json.loads(CASES.read_text())
    now = data["now"]
    for case in data["cases"]:
        vehicles = case["vehicles"]
        reservations = case["reservations"]
        maintenances = case["maintenances"]
        eff = ref.effective_statuses(vehicles, reservations, maintenances, now)
        counts = ref.fleet_counts(vehicles, reservations, maintenances, now)
        nb = ref.next_boundary(reservations, maintenances, now)
        case["expected_effective"] = eff
        case["expected_counts"] = counts
        case["expected_next_boundary"] = nb.isoformat().replace("+00:00", "Z") if nb else None
    CASES.write_text(json.dumps(data, indent=2) + "\n")
    print(f"regenerated {len(data['cases'])} cases -> {CASES}")


if __name__ == "__main__":
    main()
