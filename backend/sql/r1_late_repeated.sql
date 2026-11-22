-- R1: late_repeated
-- Trigger: >= 5 late days (is_late = 1, > 5 mins after 08:30:00) in a calendar month
-- Severity: low (5-6), medium (7-9), high (10+)
SELECT
    employee_id,
    full_name,
    department_id,
    department_name,
    period,
    COUNT(*) AS late_days,
    MIN(late_minutes) AS min_late_minutes,
    MAX(late_minutes) AS max_late_minutes,
    GROUP_CONCAT(work_date || ' (' || substr(check_in, 12, 5) || ', +' || late_minutes || 'p)', '; ') AS sample_dates,
    CASE
        WHEN COUNT(*) >= 10 THEN 'high'
        WHEN COUNT(*) >= 7 THEN 'medium'
        ELSE 'low'
    END AS severity
FROM v_attendance_daily
WHERE is_late = 1
  AND (:period IS NULL OR period = :period)
GROUP BY employee_id, full_name, department_id, department_name, period
HAVING COUNT(*) >= 5
ORDER BY period DESC, late_days DESC, employee_id ASC;
