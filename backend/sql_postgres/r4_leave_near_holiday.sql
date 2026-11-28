-- R4: leave_near_holiday (PostgreSQL)
SELECT
    lr.employee_id,
    lr.full_name,
    lr.department_id,
    lr.department_name,
    h.holiday_date,
    h.name AS holiday_name,
    TO_CHAR(h.holiday_date, 'YYYY-MM') AS period,
    COUNT(DISTINCT lr.request_id) AS request_count,
    STRING_AGG(lr.from_date::TEXT || '..' || lr.to_date::TEXT, '; ' ORDER BY lr.from_date) AS leave_ranges,
    'medium' AS severity
FROM v_leave_requests lr
JOIN holidays h
  ON ABS(lr.from_date - h.holiday_date) <= 3
  OR ABS(lr.to_date - h.holiday_date) <= 3
WHERE lr.status = 'approved'
  AND (CAST(:period AS TEXT) IS NULL OR TO_CHAR(h.holiday_date, 'YYYY-MM') = :period)
GROUP BY lr.employee_id, lr.full_name, lr.department_id, lr.department_name, h.holiday_date, h.name
HAVING COUNT(DISTINCT lr.request_id) >= 3
ORDER BY h.holiday_date DESC, lr.employee_id ASC;
