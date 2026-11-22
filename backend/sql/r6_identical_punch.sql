-- R6: identical_punch
-- Trigger: >= 5 days in a month with identical check_in and check_out times down to the exact second
-- Severity: high
SELECT
    employee_id,
    full_name,
    department_id,
    department_name,
    period,
    substr(check_in, 12, 8) AS exact_check_in,
    substr(check_out, 12, 8) AS exact_check_out,
    COUNT(*) AS identical_days,
    GROUP_CONCAT(work_date, '; ') AS sample_dates,
    'high' AS severity
FROM v_attendance_daily
WHERE status = 'present'
  AND check_in IS NOT NULL
  AND check_out IS NOT NULL
  AND (:period IS NULL OR period = :period)
GROUP BY
    employee_id,
    full_name,
    department_id,
    department_name,
    period,
    substr(check_in, 12, 8),
    substr(check_out, 12, 8)
HAVING COUNT(*) >= 5
ORDER BY period DESC, identical_days DESC, employee_id ASC;
