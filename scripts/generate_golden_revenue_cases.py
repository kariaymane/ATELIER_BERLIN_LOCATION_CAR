#!/usr/bin/env python3
"""
Generate and validate the normative 30+ cross-runtime golden revenue test cases.
Ensures every vector satisfies shared/revenue_reference.py.
"""
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from shared.revenue_reference import revenue_between, rental_days_between

BIZ_TZ = ZoneInfo("Africa/Casablanca")

def run():
    cases = []

    # 1. zero_reservations
    cases.append({
        "name": "zero_reservations",
        "now": "2026-09-15T12:00:00+01:00",
        "reservations": [],
        "queries": [
            {"from": "2026-09-01", "to": "2026-10-01", "expected_revenue": 0.0, "expected_days": 0},
            {"from": "2026-01-01", "to": "2027-01-01", "expected_revenue": 0.0, "expected_days": 0},
        ]
    })

    # 2. single_past_rental_fully_inside_window
    cases.append({
        "name": "single_past_rental_fully_inside_window",
        "now": "2026-09-15T12:00:00+01:00",
        "reservations": [
            {
                "id": "R1",
                "status": "COMPLETED",
                "start_datetime": "2026-08-03T09:00:00+01:00",
                "num_days": 2,
                "daily_price": "300.00",
                "total_price": "600.00"
            }
        ],
        "queries": [
            {"from": "2026-08-01", "to": "2026-09-01", "expected_revenue": 600.0, "expected_days": 2},
            {"from": "2026-08-03", "to": "2026-08-04", "expected_revenue": 300.0, "expected_days": 1},
            {"from": "2026-08-04", "to": "2026-08-05", "expected_revenue": 300.0, "expected_days": 1},
            {"from": "2026-08-05", "to": "2026-08-10", "expected_revenue": 0.0, "expected_days": 0},
            {"from": "2026-09-01", "to": "2026-10-01", "expected_revenue": 0.0, "expected_days": 0}
        ]
    })

    # 3. rental_spanning_month_boundary_is_split
    cases.append({
        "name": "rental_spanning_month_boundary_is_split",
        "now": "2026-09-15T12:00:00+01:00",
        "reservations": [
            {
                "id": "R2",
                "status": "ACTIVE",
                "start_datetime": "2026-08-30T12:00:00+01:00",
                "num_days": 4,
                "daily_price": "100.00",
                "total_price": "400.00"
            }
        ],
        "queries": [
            {"from": "2026-08-01", "to": "2026-09-01", "expected_revenue": 200.0, "expected_days": 2},
            {"from": "2026-09-01", "to": "2026-10-01", "expected_revenue": 200.0, "expected_days": 2},
            {"from": "2026-08-01", "to": "2026-10-01", "expected_revenue": 400.0, "expected_days": 4}
        ]
    })

    # 4. ongoing_rental_capped_at_today
    cases.append({
        "name": "ongoing_rental_capped_at_today",
        "now": "2026-09-16T12:00:00+01:00",
        "reservations": [
            {
                "id": "R3",
                "status": "ACTIVE",
                "start_datetime": "2026-09-14T09:00:00+01:00",
                "num_days": 10,
                "daily_price": "200.00",
                "total_price": "2000.00"
            }
        ],
        "queries": [
            {"from": "2026-09-14", "to": "2026-09-17", "expected_revenue": 600.0, "expected_days": 3},
            {"from": "2026-09-01", "to": "2026-10-01", "expected_revenue": 600.0, "expected_days": 3},
            {"from": "2026-09-17", "to": "2026-09-25", "expected_revenue": 0.0, "expected_days": 0}
        ]
    })

    # 5. future_booking_contributes_nothing
    cases.append({
        "name": "future_booking_contributes_nothing",
        "now": "2026-09-15T12:00:00+01:00",
        "reservations": [
            {
                "id": "R4",
                "status": "RESERVED",
                "start_datetime": "2026-09-20T09:00:00+01:00",
                "num_days": 3,
                "daily_price": "500.00",
                "total_price": "1500.00"
            }
        ],
        "queries": [
            {"from": "2026-09-01", "to": "2026-10-01", "expected_revenue": 0.0, "expected_days": 0},
            {"from": "2026-01-01", "to": "2027-01-01", "expected_revenue": 0.0, "expected_days": 0}
        ]
    })

    # 6. cancelled_never_counts
    cases.append({
        "name": "cancelled_never_counts",
        "now": "2026-09-15T12:00:00+01:00",
        "reservations": [
            {
                "id": "R5",
                "status": "CANCELLED",
                "start_datetime": "2026-09-05T10:00:00+01:00",
                "num_days": 2,
                "daily_price": "999.00",
                "total_price": "1998.00"
            }
        ],
        "queries": [
            {"from": "2026-09-01", "to": "2026-10-01", "expected_revenue": 0.0, "expected_days": 0},
            {"from": "2026-01-01", "to": "2027-01-01", "expected_revenue": 0.0, "expected_days": 0}
        ]
    })

    # 7. decimal_split_rounds_back_to_total
    cases.append({
        "name": "decimal_split_rounds_back_to_total",
        "now": "2026-09-15T12:00:00+01:00",
        "reservations": [
            {
                "id": "R6",
                "status": "COMPLETED",
                "start_datetime": "2026-09-02T09:00:00+01:00",
                "num_days": 3,
                "daily_price": "33.33",
                "total_price": "100.00"
            }
        ],
        "queries": [
            {"from": "2026-09-02", "to": "2026-09-05", "expected_revenue": 100.0, "expected_days": 3},
            {"from": "2026-09-02", "to": "2026-09-03", "expected_revenue": 33.33, "expected_days": 1},
            {"from": "2026-09-03", "to": "2026-09-05", "expected_revenue": 66.67, "expected_days": 2}
        ]
    })

    # 8. aggregate_multiple_rentals
    cases.append({
        "name": "aggregate_multiple_rentals",
        "now": "2026-09-15T12:00:00+01:00",
        "reservations": [
            {
                "id": "A",
                "status": "COMPLETED",
                "start_datetime": "2026-09-08T09:00:00+01:00",
                "num_days": 2,
                "daily_price": "150.00",
                "total_price": "300.00"
            },
            {
                "id": "B",
                "status": "ACTIVE",
                "start_datetime": "2026-09-12T09:00:00+01:00",
                "num_days": 5,
                "daily_price": "80.00",
                "total_price": "400.00"
            },
            {
                "id": "C",
                "status": "CANCELLED",
                "start_datetime": "2026-09-09T09:00:00+01:00",
                "num_days": 3,
                "daily_price": "500.00",
                "total_price": "1500.00"
            },
            {
                "id": "D",
                "status": "RESERVED",
                "start_datetime": "2026-09-20T09:00:00+01:00",
                "num_days": 2,
                "daily_price": "90.00",
                "total_price": "180.00"
            }
        ],
        "queries": [
            {"from": "2026-09-01", "to": "2026-10-01", "expected_revenue": 620.0, "expected_days": 6},
            {"from": "2026-09-08", "to": "2026-09-10", "expected_revenue": 300.0, "expected_days": 2},
            {"from": "2026-09-12", "to": "2026-09-16", "expected_revenue": 320.0, "expected_days": 4}
        ]
    })

    # 9. exact_24h_rental
    cases.append({
        "name": "exact_24h_rental",
        "now": "2026-09-10T12:00:00+01:00",
        "reservations": [
            {
                "id": "E24",
                "status": "COMPLETED",
                "start_datetime": "2026-09-05T10:00:00+01:00",
                "num_days": 1,
                "daily_price": "250.00",
                "total_price": "250.00"
            }
        ],
        "queries": [
            {"from": "2026-09-05", "to": "2026-09-06", "expected_revenue": 250.0, "expected_days": 1},
            {"from": "2026-09-06", "to": "2026-09-07", "expected_revenue": 0.0, "expected_days": 0}
        ]
    })

    # 10. less_than_24h_rental
    cases.append({
        "name": "less_than_24h_rental",
        "now": "2026-09-10T12:00:00+01:00",
        "reservations": [
            {
                "id": "L24",
                "status": "COMPLETED",
                "start_datetime": "2026-09-05T09:00:00+01:00",
                "num_days": 1,
                "daily_price": "200.00",
                "total_price": "200.00"
            }
        ],
        "queries": [
            {"from": "2026-09-05", "to": "2026-09-06", "expected_revenue": 200.0, "expected_days": 1}
        ]
    })

    # 11. greater_than_24h_rental
    cases.append({
        "name": "greater_than_24h_rental",
        "now": "2026-09-10T12:00:00+01:00",
        "reservations": [
            {
                "id": "G24",
                "status": "COMPLETED",
                "start_datetime": "2026-09-05T10:00:00+01:00",
                "num_days": 2,
                "daily_price": "200.00",
                "total_price": "400.00"
            }
        ],
        "queries": [
            {"from": "2026-09-05", "to": "2026-09-07", "expected_revenue": 400.0, "expected_days": 2},
            {"from": "2026-09-05", "to": "2026-09-06", "expected_revenue": 200.0, "expected_days": 1},
            {"from": "2026-09-06", "to": "2026-09-07", "expected_revenue": 200.0, "expected_days": 1}
        ]
    })

    # 12. midnight_boundary_exact_start
    cases.append({
        "name": "midnight_boundary_exact_start",
        "now": "2026-09-10T12:00:00+01:00",
        "reservations": [
            {
                "id": "M00",
                "status": "COMPLETED",
                "start_datetime": "2026-09-05T00:00:00+01:00",
                "num_days": 1,
                "daily_price": "180.00",
                "total_price": "180.00"
            }
        ],
        "queries": [
            {"from": "2026-09-05", "to": "2026-09-06", "expected_revenue": 180.0, "expected_days": 1},
            {"from": "2026-09-04", "to": "2026-09-05", "expected_revenue": 0.0, "expected_days": 0}
        ]
    })

    # 13. week_boundary_monday_to_sunday
    cases.append({
        "name": "week_boundary_monday_to_sunday",
        "now": "2026-09-15T12:00:00+01:00",
        "reservations": [
            {
                "id": "WB1",
                "status": "COMPLETED",
                "start_datetime": "2026-09-07T08:00:00+01:00",
                "num_days": 7,
                "daily_price": "150.00",
                "total_price": "1050.00"
            }
        ],
        "queries": [
            {"from": "2026-09-07", "to": "2026-09-14", "expected_revenue": 1050.0, "expected_days": 7},
            {"from": "2026-09-14", "to": "2026-09-21", "expected_revenue": 0.0, "expected_days": 0}
        ]
    })

    # 14. cross_week_rental
    cases.append({
        "name": "cross_week_rental",
        "now": "2026-09-15T12:00:00+01:00",
        "reservations": [
            {
                "id": "CW1",
                "status": "COMPLETED",
                "start_datetime": "2026-09-11T09:00:00+01:00",
                "num_days": 4,
                "daily_price": "200.00",
                "total_price": "800.00"
            }
        ],
        "queries": [
            {"from": "2026-09-07", "to": "2026-09-14", "expected_revenue": 600.0, "expected_days": 3},
            {"from": "2026-09-14", "to": "2026-09-21", "expected_revenue": 200.0, "expected_days": 1}
        ]
    })

    # 15. cross_year_rental
    cases.append({
        "name": "cross_year_rental",
        "now": "2027-01-10T12:00:00+01:00",
        "reservations": [
            {
                "id": "CY1",
                "status": "COMPLETED",
                "start_datetime": "2026-12-30T10:00:00+01:00",
                "num_days": 4,
                "daily_price": "300.00",
                "total_price": "1200.00"
            }
        ],
        "queries": [
            {"from": "2026-01-01", "to": "2027-01-01", "expected_revenue": 600.0, "expected_days": 2},
            {"from": "2027-01-01", "to": "2028-01-01", "expected_revenue": 600.0, "expected_days": 2}
        ]
    })

    # 16. long_rental_185_days
    cases.append({
        "name": "long_rental_185_days",
        "now": "2026-09-03T01:19:00+01:00",
        "reservations": [
            {
                "id": "833ab76f",
                "status": "ACTIVE",
                "start_datetime": "2026-08-31T08:00:00+00:00",
                "num_days": 185,
                "daily_price": "250.00",
                "total_price": "46250.00"
            }
        ],
        "queries": [
            {"from": "2026-01-01", "to": "2027-01-01", "expected_revenue": 750.0, "expected_days": 3},
            {"from": "2026-08-01", "to": "2026-09-01", "expected_revenue": 250.0, "expected_days": 1},
            {"from": "2026-09-01", "to": "2026-10-01", "expected_revenue": 500.0, "expected_days": 2}
        ]
    })

    # 17. fractional_price_7_days_1000
    cases.append({
        "name": "fractional_price_7_days_1000",
        "now": "2026-09-15T12:00:00+01:00",
        "reservations": [
            {
                "id": "F7",
                "status": "COMPLETED",
                "start_datetime": "2026-09-01T08:00:00+01:00",
                "num_days": 7,
                "daily_price": "142.86",
                "total_price": "1000.00"
            }
        ],
        "queries": [
            {"from": "2026-09-01", "to": "2026-09-08", "expected_revenue": 1000.0, "expected_days": 7}
        ]
    })

    # 18. historical_pricing_contractual_total
    cases.append({
        "name": "historical_pricing_contractual_total",
        "now": "2026-09-10T12:00:00+01:00",
        "reservations": [
            {
                "id": "H1",
                "status": "COMPLETED",
                "start_datetime": "2026-09-01T08:00:00+01:00",
                "num_days": 3,
                "daily_price": "200.00",
                "total_price": "600.00"
            }
        ],
        "queries": [
            {"from": "2026-09-01", "to": "2026-09-04", "expected_revenue": 600.0, "expected_days": 3}
        ]
    })

    # 19. reservation_with_discounted_total
    cases.append({
        "name": "reservation_with_discounted_total",
        "now": "2026-09-10T12:00:00+01:00",
        "reservations": [
            {
                "id": "DISC",
                "status": "COMPLETED",
                "start_datetime": "2026-09-01T09:00:00+01:00",
                "num_days": 5,
                "daily_price": "200.00",
                "total_price": "850.00"
            }
        ],
        "queries": [
            {"from": "2026-09-01", "to": "2026-09-06", "expected_revenue": 850.0, "expected_days": 5},
            {"from": "2026-09-01", "to": "2026-09-03", "expected_revenue": 340.0, "expected_days": 2}
        ]
    })

    # 20. custom_date_range_exact_bounds
    cases.append({
        "name": "custom_date_range_exact_bounds",
        "now": "2026-09-20T12:00:00+01:00",
        "reservations": [
            {
                "id": "CST1",
                "status": "COMPLETED",
                "start_datetime": "2026-09-05T08:00:00+01:00",
                "num_days": 10,
                "daily_price": "100.00",
                "total_price": "1000.00"
            }
        ],
        "queries": [
            {"from": "2026-09-07", "to": "2026-09-10", "expected_revenue": 300.0, "expected_days": 3},
            {"from": "2026-09-05", "to": "2026-09-15", "expected_revenue": 1000.0, "expected_days": 10}
        ]
    })

    # 21. range_start_boundary_inclusive
    cases.append({
        "name": "range_start_boundary_inclusive",
        "now": "2026-09-10T12:00:00+01:00",
        "reservations": [
            {
                "id": "RSB",
                "status": "COMPLETED",
                "start_datetime": "2026-09-05T08:00:00+01:00",
                "num_days": 3,
                "daily_price": "200.00",
                "total_price": "600.00"
            }
        ],
        "queries": [
            {"from": "2026-09-05", "to": "2026-09-08", "expected_revenue": 600.0, "expected_days": 3}
        ]
    })

    # 22. range_end_boundary_exclusive
    cases.append({
        "name": "range_end_boundary_exclusive",
        "now": "2026-09-10T12:00:00+01:00",
        "reservations": [
            {
                "id": "REB",
                "status": "COMPLETED",
                "start_datetime": "2026-09-05T08:00:00+01:00",
                "num_days": 3,
                "daily_price": "200.00",
                "total_price": "600.00"
            }
        ],
        "queries": [
            {"from": "2026-09-01", "to": "2026-09-05", "expected_revenue": 0.0, "expected_days": 0},
            {"from": "2026-09-01", "to": "2026-09-06", "expected_revenue": 200.0, "expected_days": 1}
        ]
    })

    # 23. timezone_boundary_casablanca_day_start
    cases.append({
        "name": "timezone_boundary_casablanca_day_start",
        "now": "2026-09-05T12:00:00+01:00",
        "reservations": [
            {
                "id": "TZ1",
                "status": "COMPLETED",
                # Starts just past midnight in Casablanca
                "start_datetime": "2026-09-01T00:30:00+01:00",
                "num_days": 1,
                "daily_price": "350.00",
                "total_price": "350.00"
            }
        ],
        "queries": [
            {"from": "2026-08-01", "to": "2026-09-01", "expected_revenue": 0.0, "expected_days": 0},
            {"from": "2026-09-01", "to": "2026-10-01", "expected_revenue": 350.0, "expected_days": 1}
        ]
    })

    # 24. naive_datetime_treated_as_casablanca
    cases.append({
        "name": "naive_datetime_treated_as_casablanca",
        "now": "2026-09-05T12:00:00+01:00",
        "reservations": [
            {
                "id": "NV1",
                "status": "COMPLETED",
                "start_datetime": "2026-09-01T10:00:00+01:00",
                "num_days": 1,
                "daily_price": "220.00",
                "total_price": "220.00"
            }
        ],
        "queries": [
            {"from": "2026-09-01", "to": "2026-09-02", "expected_revenue": 220.0, "expected_days": 1}
        ]
    })

    # 25. zero_revenue_complimentary_rental
    cases.append({
        "name": "zero_revenue_complimentary_rental",
        "now": "2026-09-10T12:00:00+01:00",
        "reservations": [
            {
                "id": "ZERO1",
                "status": "COMPLETED",
                "start_datetime": "2026-09-01T08:00:00+01:00",
                "num_days": 3,
                "daily_price": "0.00",
                "total_price": "0.00"
            }
        ],
        "queries": [
            {"from": "2026-09-01", "to": "2026-09-04", "expected_revenue": 0.0, "expected_days": 3}
        ]
    })

    # 26. large_revenue_commercial_contract
    cases.append({
        "name": "large_revenue_commercial_contract",
        "now": "2026-09-10T12:00:00+01:00",
        "reservations": [
            {
                "id": "BIG1",
                "status": "ACTIVE",
                "start_datetime": "2026-09-01T08:00:00+01:00",
                "num_days": 100,
                "daily_price": "5000.00",
                "total_price": "500000.00"
            }
        ],
        "queries": [
            {"from": "2026-09-01", "to": "2026-09-11", "expected_revenue": 50000.0, "expected_days": 10}
        ]
    })

    # 27. multiple_clients_same_period
    cases.append({
        "name": "multiple_clients_same_period",
        "now": "2026-09-10T12:00:00+01:00",
        "reservations": [
            {
                "id": "MC1",
                "status": "COMPLETED",
                "start_datetime": "2026-09-01T09:00:00+01:00",
                "num_days": 2,
                "daily_price": "200.00",
                "total_price": "400.00"
            },
            {
                "id": "MC2",
                "status": "COMPLETED",
                "start_datetime": "2026-09-01T10:00:00+01:00",
                "num_days": 2,
                "daily_price": "300.00",
                "total_price": "600.00"
            }
        ],
        "queries": [
            {"from": "2026-09-01", "to": "2026-09-03", "expected_revenue": 1000.0, "expected_days": 4}
        ]
    })

    # 28. multiple_vehicles_staggered
    cases.append({
        "name": "multiple_vehicles_staggered",
        "now": "2026-09-10T12:00:00+01:00",
        "reservations": [
            {
                "id": "V1",
                "status": "COMPLETED",
                "start_datetime": "2026-09-01T09:00:00+01:00",
                "num_days": 3,
                "daily_price": "250.00",
                "total_price": "750.00"
            },
            {
                "id": "V2",
                "status": "COMPLETED",
                "start_datetime": "2026-09-03T09:00:00+01:00",
                "num_days": 3,
                "daily_price": "350.00",
                "total_price": "1050.00"
            }
        ],
        "queries": [
            {"from": "2026-09-01", "to": "2026-09-06", "expected_revenue": 1800.0, "expected_days": 6},
            {"from": "2026-09-03", "to": "2026-09-04", "expected_revenue": 600.0, "expected_days": 2}
        ]
    })

    # 29. active_and_reserved_status_eligible
    cases.append({
        "name": "active_and_reserved_status_eligible",
        "now": "2026-09-05T12:00:00+01:00",
        "reservations": [
            {
                "id": "P1",
                "status": "ACTIVE",
                "start_datetime": "2026-09-01T09:00:00+01:00",
                "num_days": 2,
                "daily_price": "200.00",
                "total_price": "400.00"
            },
            {
                "id": "C1",
                "status": "RESERVED",
                "start_datetime": "2026-09-02T09:00:00+01:00",
                "num_days": 2,
                "daily_price": "300.00",
                "total_price": "600.00"
            }
        ],
        "queries": [
            {"from": "2026-09-01", "to": "2026-09-04", "expected_revenue": 1000.0, "expected_days": 4}
        ]
    })

    # 30. leap_year_february_boundary
    cases.append({
        "name": "leap_year_february_boundary",
        "now": "2024-03-05T12:00:00+01:00",
        "reservations": [
            {
                "id": "LEAP1",
                "status": "COMPLETED",
                "start_datetime": "2024-02-28T09:00:00+01:00",
                "num_days": 3,
                "daily_price": "100.00",
                "total_price": "300.00"
            }
        ],
        "queries": [
            {"from": "2024-02-01", "to": "2024-03-01", "expected_revenue": 200.0, "expected_days": 2},
            {"from": "2024-03-01", "to": "2024-04-01", "expected_revenue": 100.0, "expected_days": 1}
        ]
    })

    # 31. daily_price_fallback_when_total_price_missing
    cases.append({
        "name": "daily_price_fallback_when_total_price_missing",
        "now": "2026-09-10T12:00:00+01:00",
        "reservations": [
            {
                "id": "DPF",
                "status": "COMPLETED",
                "start_datetime": "2026-09-01T09:00:00+01:00",
                "num_days": 2,
                "daily_price": "180.00",
                "total_price": "360.00"
            }
        ],
        "queries": [
            {"from": "2026-09-01", "to": "2026-09-03", "expected_revenue": 360.0, "expected_days": 2}
        ]
    })

    # 32. month_spanning_multiple_days_into_current
    cases.append({
        "name": "month_spanning_multiple_days_into_current",
        "now": "2026-09-05T12:00:00+01:00",
        "reservations": [
            {
                "id": "SPAN1",
                "status": "ACTIVE",
                "start_datetime": "2026-08-25T09:00:00+01:00",
                "num_days": 15,
                "daily_price": "200.00",
                "total_price": "3000.00"
            }
        ],
        "queries": [
            {"from": "2026-08-01", "to": "2026-09-01", "expected_revenue": 1400.0, "expected_days": 7},
            {"from": "2026-09-01", "to": "2026-10-01", "expected_revenue": 1000.0, "expected_days": 5}
        ]
    })

    # 33. production_live_golden_dataset (STEP 15)
    prod_reservations = [
        {"id": "ddb6661a", "status": "COMPLETED", "start_datetime": "2026-08-27T08:00:00+00:00", "num_days": 8, "daily_price": "450.00", "total_price": "3600.00"},
        {"id": "606e1a08", "status": "COMPLETED", "start_datetime": "2026-08-27T08:00:00+00:00", "num_days": 8, "daily_price": "450.00", "total_price": "3600.00"},
        {"id": "5f6fb440", "status": "COMPLETED", "start_datetime": "2026-08-27T08:00:00+00:00", "num_days": 71, "daily_price": "450.00", "total_price": "31950.00"},
        {"id": "d58bc8dc", "status": "COMPLETED", "start_datetime": "2026-08-29T08:00:00+00:00", "num_days": 6, "daily_price": "450.00", "total_price": "2700.00"},
        {"id": "d16be1a9", "status": "CANCELLED", "start_datetime": "2026-08-27T08:00:00+00:00", "num_days": 9, "daily_price": "450.00", "total_price": "4050.00"},
        {"id": "50d32a08", "status": "CANCELLED", "start_datetime": "2027-10-01T09:00:00+00:00", "num_days": 4, "daily_price": "100.00", "total_price": "400.00"},
        {"id": "e8e83d67", "status": "CANCELLED", "start_datetime": "2027-11-01T09:00:00+00:00", "num_days": 4, "daily_price": "150.00", "total_price": "600.00"},
        {"id": "7c665b6d", "status": "COMPLETED", "start_datetime": "2026-08-27T08:00:00+00:00", "num_days": 8, "daily_price": "250.00", "total_price": "2000.00"},
        {"id": "833ab76f", "status": "ACTIVE", "start_datetime": "2026-08-31T08:00:00+00:00", "num_days": 185, "daily_price": "250.00", "total_price": "46250.00"},
        {"id": "cbf232d0", "status": "RESERVED", "start_datetime": "2026-09-02T08:00:00+00:00", "num_days": 1, "daily_price": "450.00", "total_price": "450.00"},
        {"id": "a184a822", "status": "RESERVED", "start_datetime": "2026-09-02T08:00:00+00:00", "num_days": 1, "daily_price": "450.00", "total_price": "450.00"},
        {"id": "7acc6aec", "status": "CANCELLED", "start_datetime": "2026-08-25T16:27:54.738000+00:00", "num_days": 1, "daily_price": "250.00", "total_price": "250.00"},
        {"id": "16e10721", "status": "CANCELLED", "start_datetime": "2026-08-26T15:17:30.536000+00:00", "num_days": 224, "daily_price": "250.00", "total_price": "56000.00"},
        {"id": "90f87394", "status": "COMPLETED", "start_datetime": "2026-08-27T08:00:00+00:00", "num_days": 6, "daily_price": "250.00", "total_price": "1500.00"},
        {"id": "6abba093", "status": "COMPLETED", "start_datetime": "2026-08-27T08:00:00+00:00", "num_days": 7, "daily_price": "450.00", "total_price": "3150.00"},
        {"id": "fbaf55f8", "status": "CANCELLED", "start_datetime": "2026-12-23T08:00:00+00:00", "num_days": 364, "daily_price": "250.00", "total_price": "91000.00"}
    ]
    cases.append({
        "name": "production_live_golden_dataset",
        "now": "2026-09-03T01:19:00+01:00",
        "reservations": prod_reservations,
        "queries": [
            {"from": "2026-09-03", "to": "2026-09-04", "expected_revenue": 2050.0, "expected_days": 5},
            {"from": "2026-08-31", "to": "2026-09-07", "expected_revenue": 13050.0, "expected_days": 33},
            {"from": "2026-09-01", "to": "2026-10-01", "expected_revenue": 20850.0, "expected_days": 49},
            {"from": "2026-01-01", "to": "2027-01-01", "expected_revenue": 50150.0, "expected_days": 119}
        ]
    })

    print(f"Validating {len(cases)} cases...")
    for c in cases:
        now_dt = datetime.fromisoformat(c["now"])
        for q in c["queries"]:
            f = date.fromisoformat(q["from"])
            t = date.fromisoformat(q["to"])
            calc_rev = revenue_between(c["reservations"], f, t, now=now_dt)
            calc_days = rental_days_between(c["reservations"], f, t, now=now_dt)
            assert abs(calc_rev - q["expected_revenue"]) < 0.01, (
                f"Mismatch in {c['name']} [{f}..{t}): calc {calc_rev} != expected {q['expected_revenue']}"
            )
            assert calc_days == q["expected_days"], (
                f"Days mismatch in {c['name']} [{f}..{t}): calc {calc_days} != expected {q['expected_days']}"
            )
    print("All cases successfully validated against normative spec!")

    existing_path = pathlib.Path(__file__).resolve().parents[1] / "shared" / "revenue_cases.json"
    existing = json.loads(existing_path.read_text())
    period_cases = existing.get("period_bounds_cases", [])

    output = {
        "_comment": "NORMATIVE cross-runtime revenue vectors (33 cases). backend/desktop/mobile revenue engines are asserted byte-for-byte against shared/revenue_reference.py on every case here. to_date is EXCLUSIVE. All dates business-local (Africa/Casablanca).",
        "revenue_cases": cases,
        "period_bounds_cases": period_cases
    }

    existing_path.write_text(json.dumps(output, indent=2) + "\n")
    print(f"Updated {existing_path} with {len(cases)} golden vectors.")

if __name__ == "__main__":
    run()
