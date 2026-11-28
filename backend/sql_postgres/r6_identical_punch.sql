-- R6: identical_punch (PostgreSQL)
SELECT
    employee_id,
    full_name,
    department_id,
    department_name,
    period,
    TO_CHAR(check_in, 'HH24:MI:SS') AS exact_check_in,
    TO_CHAR(check_out, 'HH24:MI:SS') AS exact_check_out,
    COUNT(*) AS identical_days,
    STRING_AGG(work_date::TEXT, '; ' ORDER BY work_date) AS sample_dates,
    'high' AS severity
FROM v_attendance_daily
WHERE status = 'present'
  AND check_in IS NOT NULL
  AND check_out IS NOT NULL
  AND (CAST(:period AS TEXT) IS NULL OR period = :period)
GROUP BY
    employee_id,
    full_name,
    department_id,
    department_name,
    period,
    TO_CHAR(check_in, 'HH24:MI:SS'),
    TO_CHAR(check_out, 'HH24:MI:SS')
HAVING COUNT(*) >= 5
ORDER BY period DESC, identical_days DESC, employee_id ASC;
