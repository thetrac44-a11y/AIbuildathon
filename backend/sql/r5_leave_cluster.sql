-- R5: leave_cluster (DEPARTMENT-SCOPED ANOMALY)
-- Trigger: >= 4 employees AND >= 25% of active department headcount on approved leave on the same date
-- Severity: medium (25%..39.99%), high (>= 40%)
WITH dept_sizes AS (
    SELECT department_id, COUNT(*) AS dept_headcount
    FROM employees
    WHERE employment_status = 'active'
    GROUP BY department_id
),
leave_day_clusters AS (
    SELECT
        a.department_id,
        a.department_name,
        a.work_date,
        a.period,
        COUNT(DISTINCT a.employee_id) AS leave_count,
        GROUP_CONCAT(DISTINCT a.employee_id) AS employee_ids
    FROM v_attendance_daily a
    WHERE a.status = 'on_leave'
      AND EXISTS (
          SELECT 1
          FROM leave_requests lr
          WHERE lr.employee_id = a.employee_id
            AND lr.status = 'approved'
            AND a.work_date BETWEEN lr.from_date AND lr.to_date
      )
      AND (:period IS NULL OR a.period = :period)
    GROUP BY a.department_id, a.department_name, a.work_date, a.period
)
SELECT
    c.department_id,
    c.department_name,
    c.work_date,
    c.period,
    c.leave_count,
    ds.dept_headcount,
    ROUND((c.leave_count * 100.0) / ds.dept_headcount, 2) AS leave_pct,
    c.employee_ids,
    CASE
        WHEN (c.leave_count * 100.0) / ds.dept_headcount >= 40.0 THEN 'high'
        ELSE 'medium'
    END AS severity
FROM leave_day_clusters c
JOIN dept_sizes ds ON ds.department_id = c.department_id
WHERE c.leave_count >= 4
  AND (c.leave_count * 100.0) / ds.dept_headcount >= 25.0
ORDER BY c.work_date DESC, c.department_id ASC;
