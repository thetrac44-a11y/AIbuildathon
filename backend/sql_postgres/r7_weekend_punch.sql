-- R7: weekend_punch (PostgreSQL)
SELECT
    a.employee_id,
    a.full_name,
    a.department_id,
    a.department_name,
    a.period,
    COUNT(*) AS weekend_holiday_days,
    STRING_AGG(
        a.work_date::TEXT || ' (' || COALESCE(TO_CHAR(a.check_in, 'HH24:MI'), '--') || '-' || COALESCE(TO_CHAR(a.check_out, 'HH24:MI'), '--') || ')',
        '; ' ORDER BY a.work_date
    ) AS sample_dates,
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
  AND (CAST(:period AS TEXT) IS NULL OR a.period = :period)
GROUP BY a.employee_id, a.full_name, a.department_id, a.department_name, a.period
HAVING COUNT(*) >= 1
ORDER BY a.period DESC, weekend_holiday_days DESC, a.employee_id ASC;
