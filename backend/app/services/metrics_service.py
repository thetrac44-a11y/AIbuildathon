from __future__ import annotations

from typing import Dict


def compute_attendance_rates(
    present_days: int,
    late_days: int,
    leave_days: int,
    absent_days: int,
) -> Dict[str, float | int]:
    """Single source of truth for attendance KPI rates shared by Dashboard and Reports.

    - late_rate: late_days / present_days * 100 (rounded to 2 decimals)
    - on_time_rate: (present_days - late_days) / present_days * 100 (rounded to 2 decimals)
    - leave_rate: leave_days / (present_days + leave_days + absent_days) * 100 (rounded to 2 decimals)
    """
    p = max(0, int(present_days or 0))
    l = max(0, int(late_days or 0))
    lv = max(0, int(leave_days or 0))
    ab = max(0, int(absent_days or 0))

    on_time_days = max(0, p - l)
    late_rate = round((l / p) * 100.0, 2) if p > 0 else 0.0
    on_time_rate = round((on_time_days / p) * 100.0, 2) if p > 0 else 0.0
    leave_denom = p + lv + ab
    leave_rate = round((lv / leave_denom) * 100.0, 2) if leave_denom > 0 else 0.0

    return {
        "on_time_days": on_time_days,
        "on_time_rate": on_time_rate,
        "late_rate": late_rate,
        "leave_rate": leave_rate,
    }
