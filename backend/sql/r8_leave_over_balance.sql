-- R8: leave_over_balance
-- Trigger: total approved annual leave days (calendar days inclusive) exceeds annual_leave_balance
-- Severity: medium
SELECT
    e.employee_id,
    e.full_name,
    e.department_id,
    e.department_name,
    e.annual_leave_balance,
    SUM(lr.leave_days) AS approved_annual_days,
    ROUND(SUM(lr.leave_days) - e.annual_leave_balance, 2) AS excess_days,
    MAX(lr.period) AS period,
    COUNT(lr.request_id) AS request_count,
    GROUP_CONCAT(lr.from_date || '..' || lr.to_date || ' (' || lr.leave_days || 'd)', '; ') AS leave_ranges,
    'medium' AS severity
FROM v_leave_requests lr
JOIN v_employees e ON e.employee_id = lr.employee_id
WHERE lr.leave_type = 'annual'
  AND lr.status = 'approved'
GROUP BY e.employee_id, e.full_name, e.department_id, e.department_name, e.annual_leave_balance
HAVING SUM(lr.leave_days) > e.annual_leave_balance
  AND (:period IS NULL OR MAX(lr.period) = :period)
ORDER BY excess_days DESC, e.employee_id ASC;
