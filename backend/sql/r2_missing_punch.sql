-- R2: missing_punch
-- Trigger: >= 2 days in a month with status = 'present' and missing check_in or check_out
-- Severity: low (2-3), medium (4-6), high (7+)
SELECT
    employee_id,
    full_name,
    department_id,
    department_name,
    period,
    COUNT(*) AS missing_days,
    GROUP_CONCAT(
        work_date || ' (' ||
        CASE
            WHEN check_in IS NULL AND check_out IS NULL THEN 'thiếu vào & ra'
            WHEN check_in IS NULL THEN 'thiếu giờ vào'
            ELSE 'thiếu giờ ra'
        END || ')',
        '; '
    ) AS sample_dates,
    CASE
        WHEN COUNT(*) >= 7 THEN 'high'
        WHEN COUNT(*) >= 4 THEN 'medium'
        ELSE 'low'
    END AS severity
FROM v_attendance_daily
WHERE status = 'present'
  AND (check_in IS NULL OR check_out IS NULL)
  AND (:period IS NULL OR period = :period)
GROUP BY employee_id, full_name, department_id, department_name, period
HAVING COUNT(*) >= 2
ORDER BY period DESC, missing_days DESC, employee_id ASC;
