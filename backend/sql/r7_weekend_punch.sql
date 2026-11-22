-- R7: weekend_punch
-- Trigger: attendance status = 'present' on weekend or holiday without an approved overtime_request
-- Severity: low
SELECT
    a.employee_id,
    a.full_name,
    a.department_id,
    a.department_name,
    a.period,
    COUNT(*) AS weekend_holiday_days,
    GROUP_CONCAT(a.work_date || ' (' || COALESCE(substr(a.check_in, 12, 5), '--') || '-' || COALESCE(substr(a.check_out, 12, 5), '--') || ')', '; ') AS sample_dates,
    'low' AS severity
FROM v_attendance_daily a
WHERE a.status = 'present'
  AND (a.is_weekend = 1 OR a.is_holiday = 1)
  AND NOT EXISTS (
      SELECT 1
      FROM overtime_requests ot
      WHERE ot.employee_id = a.employee_id
        AND ot.work_date = a.work_date
        AND ot.status = 'approved'
  )
  AND (:period IS NULL OR a.period = :period)
GROUP BY a.employee_id, a.full_name, a.department_id, a.department_name, a.period
HAVING COUNT(*) >= 1
ORDER BY a.period DESC, weekend_holiday_days DESC, a.employee_id ASC;
