"""
Comprehensive tests for overlap-safe vehicle utilization rate calculation.
Covers Cases A through H specified in the audit requirements.
"""
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import pytest

from shared.utilization_reference import calculate_vehicle_utilization

BIZ_TZ = ZoneInfo("Africa/Casablanca")


class TestUtilizationIntervalUnion:
    def test_case_a_non_overlapping_intervals(self):
        """Case A: [day1, day3) and [day3, day5) -> Expected union: 4 days."""
        now = datetime(2026, 9, 10, 12, 0, 0, tzinfo=BIZ_TZ)
        created_at = datetime(2026, 9, 1, 0, 0, 0, tzinfo=BIZ_TZ)

        res = [
            {"status": "COMPLETED", "start_datetime": "2026-09-01T08:00:00+01:00", "num_days": 2},
            {"status": "COMPLETED", "start_datetime": "2026-09-03T08:00:00+01:00", "num_days": 2},
        ]
        op_d, occ_d, raw_pct, fin_pct = calculate_vehicle_utilization(created_at, res, now)
        assert op_d == 10  # Sep 1 to Sep 10 = 10 days
        assert occ_d == 4   # 2 + 2 = 4 distinct days (Sep 1, 2, 3, 4)
        assert fin_pct == 40.0

    def test_case_b_fully_overlapping_intervals(self):
        """Case B: [day1, day5) and [day1, day5) -> Expected union: 4 days, NOT 8."""
        now = datetime(2026, 9, 10, 12, 0, 0, tzinfo=BIZ_TZ)
        created_at = datetime(2026, 9, 1, 0, 0, 0, tzinfo=BIZ_TZ)

        res = [
            {"status": "COMPLETED", "start_datetime": "2026-09-01T08:00:00+01:00", "num_days": 4},
            {"status": "COMPLETED", "start_datetime": "2026-09-01T08:00:00+01:00", "num_days": 4},
        ]
        op_d, occ_d, raw_pct, fin_pct = calculate_vehicle_utilization(created_at, res, now)
        assert op_d == 10
        assert occ_d == 4  # Merged union is 4 days, NOT 8
        assert fin_pct == 40.0

    def test_case_c_partially_overlapping_intervals(self):
        """Case C: [day1, day5) and [day3, day7) -> Expected union: 6 days, NOT 8."""
        now = datetime(2026, 9, 10, 12, 0, 0, tzinfo=BIZ_TZ)
        created_at = datetime(2026, 9, 1, 0, 0, 0, tzinfo=BIZ_TZ)

        res = [
            {"status": "COMPLETED", "start_datetime": "2026-09-01T08:00:00+01:00", "num_days": 4},
            {"status": "COMPLETED", "start_datetime": "2026-09-03T08:00:00+01:00", "num_days": 4},
        ]
        op_d, occ_d, raw_pct, fin_pct = calculate_vehicle_utilization(created_at, res, now)
        assert op_d == 10
        # Days occupied: Sep 1, 2, 3, 4, 5, 6 -> 6 distinct days
        assert occ_d == 6
        assert fin_pct == 60.0

    def test_case_d_three_overlapping_rentals_proofmodel(self):
        """Case D: Exact ProofModel pattern from production.
        Created Aug 21, now Sep 3 (14 op days).
        Rentals: 8 days (Aug 27), 6 days (Aug 27), 3 days (Aug 31).
        Expected union: 8 days, NOT 17.
        Expected utilization: 57.1%, NOT 100.0%.
        """
        now = datetime(2026, 9, 3, 3, 36, 0, tzinfo=BIZ_TZ)
        created_at = datetime(2026, 8, 21, 4, 43, 25, tzinfo=BIZ_TZ)

        res = [
            {"id": "7c665b6d", "status": "COMPLETED", "start_datetime": "2026-08-27T08:00:00+00:00", "num_days": 8},
            {"id": "90f87394", "status": "COMPLETED", "start_datetime": "2026-08-27T08:00:00+00:00", "num_days": 6},
            {"id": "833ab76f", "status": "ACTIVE", "start_datetime": "2026-08-31T08:00:00+00:00", "num_days": 185},
        ]
        op_d, occ_d, raw_pct, fin_pct = calculate_vehicle_utilization(created_at, res, now)
        assert op_d == 14
        assert occ_d == 8
        assert abs(raw_pct - 57.1429) < 0.01
        assert fin_pct == 57.1

    def test_case_e_future_reservation_excluded(self):
        """Case E: Future reservations starting after now must not count."""
        now = datetime(2026, 9, 3, 3, 36, 0, tzinfo=BIZ_TZ)
        created_at = datetime(2026, 9, 1, 0, 0, 0, tzinfo=BIZ_TZ)

        res = [
            {"status": "RESERVED", "start_datetime": "2026-09-04T09:00:00+01:00", "num_days": 5},
        ]
        op_d, occ_d, raw_pct, fin_pct = calculate_vehicle_utilization(created_at, res, now)
        assert occ_d == 0
        assert fin_pct == 0.0

    def test_case_f_cancelled_reservation_excluded(self):
        """Case F: Cancelled reservations must not increase utilization."""
        now = datetime(2026, 9, 10, 12, 0, 0, tzinfo=BIZ_TZ)
        created_at = datetime(2026, 9, 1, 0, 0, 0, tzinfo=BIZ_TZ)

        res = [
            {"status": "CANCELLED", "start_datetime": "2026-09-02T09:00:00+01:00", "num_days": 5},
        ]
        op_d, occ_d, raw_pct, fin_pct = calculate_vehicle_utilization(created_at, res, now)
        assert occ_d == 0
        assert fin_pct == 0.0

    def test_case_g_completed_reservation_occupancy(self):
        """Case G: Completed reservation historical occupied interval."""
        now = datetime(2026, 9, 10, 12, 0, 0, tzinfo=BIZ_TZ)
        created_at = datetime(2026, 9, 1, 0, 0, 0, tzinfo=BIZ_TZ)

        res = [
            {"status": "COMPLETED", "start_datetime": "2026-09-02T09:00:00+01:00", "num_days": 3},
        ]
        op_d, occ_d, raw_pct, fin_pct = calculate_vehicle_utilization(created_at, res, now)
        assert occ_d == 3  # Sep 2, 3, 4
        assert fin_pct == 30.0

    def test_case_h_boundary_clipping(self):
        """Case H: Boundary clipping:
        1) Rental begins before vehicle creation (clipped to created_at).
        2) Rental extends past now (clipped to now).
        """
        now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=BIZ_TZ)
        created_at = datetime(2026, 9, 3, 0, 0, 0, tzinfo=BIZ_TZ)

        res = [
            # Starts on Sep 1 (before creation date Sep 3)
            # Duration 7 days: Sep 1..Sep 7
            {"status": "COMPLETED", "start_datetime": "2026-09-01T09:00:00+01:00", "num_days": 7},
        ]
        op_d, occ_d, raw_pct, fin_pct = calculate_vehicle_utilization(created_at, res, now)
        assert op_d == 3  # Sep 3, 4, 5 = 3 operational days
        assert occ_d == 3  # Only Sep 3, 4, 5 are within [created_at, now]
        assert fin_pct == 100.0
