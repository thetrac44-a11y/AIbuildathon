-- R2: missing_punch (PostgreSQL)
SELECT
    employee_id,
    full_name,
    department_id,
    department_name,
    period,
    COUNT(*) AS missing_days,
    STRING_AGG(
        work_date::TEXT || ' (' ||
        CASE
            WHEN check_in IS NULL AND check_out IS NULL THEN 'thiếu vào & ra'
            WHEN check_in IS NULL THEN 'thiếu giờ vào'
            ELSE 'thiếu giờ ra'
        END || ')',
        '; ' ORDER BY work_date
    ) AS sample_dates,
    CASE
        WHEN COUNT(*) >= 7 THEN 'high'
        WHEN COUNT(*) >= 4 THEN 'medium'
        ELSE 'low'
    END AS severity
FROM v_attendance_daily
WHERE status = 'present'
  AND (check_in IS NULL OR check_out IS NULL)
  AND (CAST(:period AS TEXT) IS NULL OR period = :period)
GROUP BY employee_id, full_name, department_id, department_name, period
HAVING COUNT(*) >= 2
ORDER BY period DESC, missing_days DESC, employee_id ASC;
