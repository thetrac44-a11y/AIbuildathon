-- R4: leave_near_holiday
-- Trigger: >= 3 approved leave requests within +-3 days of a holiday in holidays table
-- Severity: medium
SELECT
    lr.employee_id,
    lr.full_name,
    lr.department_id,
    lr.department_name,
    h.holiday_date,
    h.name AS holiday_name,
    substr(h.holiday_date, 1, 7) AS period,
    COUNT(DISTINCT lr.request_id) AS request_count,
    GROUP_CONCAT(lr.from_date || '..' || lr.to_date, '; ') AS leave_ranges,
    'medium' AS severity
FROM v_leave_requests lr
JOIN holidays h
  ON ABS(julianday(lr.from_date) - julianday(h.holiday_date)) <= 3
  OR ABS(julianday(lr.to_date) - julianday(h.holiday_date)) <= 3
WHERE lr.status = 'approved'
  AND (:period IS NULL OR substr(h.holiday_date, 1, 7) = :period)
GROUP BY lr.employee_id, lr.full_name, lr.department_id, lr.department_name, h.holiday_date, h.name
HAVING COUNT(DISTINCT lr.request_id) >= 3
ORDER BY h.holiday_date DESC, lr.employee_id ASC;
