-- R1: late_repeated (PostgreSQL)
SELECT
    employee_id,
    full_name,
    department_id,
    department_name,
    period,
    COUNT(*) AS late_days,
    MIN(late_minutes) AS min_late_minutes,
    MAX(late_minutes) AS max_late_minutes,
    STRING_AGG(
        work_date::TEXT || ' (' || TO_CHAR(check_in, 'HH24:MI') || ', +' || late_minutes::TEXT || 'p)',
        '; ' ORDER BY work_date
    ) AS sample_dates,
    CASE
        WHEN COUNT(*) >= 10 THEN 'high'
        WHEN COUNT(*) >= 7 THEN 'medium'
        ELSE 'low'
    END AS severity
FROM v_attendance_daily
WHERE is_late = 1
  AND (CAST(:period AS TEXT) IS NULL OR period = :period)
GROUP BY employee_id, full_name, department_id, department_name, period
HAVING COUNT(*) >= 5
ORDER BY period DESC, late_days DESC, employee_id ASC;
