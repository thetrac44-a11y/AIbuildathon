-- R3: low_hours
-- Trigger: >= 5 days in a month with work_hours < 7.0 (excluding missing punches)
-- Severity: low (5-7), medium (8-11), high (12+)
SELECT
    employee_id,
    full_name,
    department_id,
    department_name,
    period,
    COUNT(*) AS low_hour_days,
    ROUND(AVG(work_hours), 2) AS avg_work_hours,
    GROUP_CONCAT(work_date || ' (' || work_hours || 'h)', '; ') AS sample_dates,
    CASE
        WHEN COUNT(*) >= 12 THEN 'high'
        WHEN COUNT(*) >= 8 THEN 'medium'
        ELSE 'low'
    END AS severity
FROM v_attendance_daily
WHERE status = 'present'
  AND check_in IS NOT NULL
  AND check_out IS NOT NULL
  AND work_hours < 7.0
  AND (:period IS NULL OR period = :period)
GROUP BY employee_id, full_name, department_id, department_name, period
HAVING COUNT(*) >= 5
ORDER BY period DESC, low_hour_days DESC, employee_id ASC;
