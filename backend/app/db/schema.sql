PRAGMA foreign_keys = ON;

-- =============================================================================
-- 1. CORE TABLES (THEO PDF GOC)
-- =============================================================================

CREATE TABLE IF NOT EXISTS departments (
    department_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS employees (
    employee_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    department_id TEXT NOT NULL,
    position TEXT NOT NULL,
    manager_id TEXT NULL,
    start_date TEXT NOT NULL,
    annual_leave_balance REAL NOT NULL DEFAULT 12.0 CHECK (annual_leave_balance >= 0),
    role TEXT NOT NULL CHECK (role IN ('employee', 'manager', 'hr', 'executive', 'admin')),
    employment_status TEXT NOT NULL DEFAULT 'active' CHECK (employment_status IN ('active', 'inactive', 'terminated')),
    email TEXT UNIQUE,
    phone TEXT NULL,
    FOREIGN KEY (department_id) REFERENCES departments(department_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (manager_id) REFERENCES employees(employee_id) ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    work_date TEXT NOT NULL, -- YYYY-MM-DD
    check_in TEXT NULL,      -- YYYY-MM-DD HH:MM:SS
    check_out TEXT NULL,     -- YYYY-MM-DD HH:MM:SS
    status TEXT NOT NULL CHECK (status IN ('present', 'absent', 'on_leave', 'holiday', 'weekend')),
    source TEXT NOT NULL DEFAULT 'biometric',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    UNIQUE (employee_id, work_date),
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS leave_requests (
    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    leave_type TEXT NOT NULL CHECK (leave_type IN ('annual', 'sick', 'personal', 'unpaid')),
    from_date TEXT NOT NULL, -- YYYY-MM-DD
    to_date TEXT NOT NULL,   -- YYYY-MM-DD
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    -- Extended approval tracking fields (Mo rong da chot)
    requires_executive_approval INTEGER NOT NULL DEFAULT 0 CHECK (requires_executive_approval IN (0, 1)),
    reviewed_by TEXT NULL,
    reviewed_at TEXT NULL,
    decision_note TEXT NULL,
    cancelled_at TEXT NULL,
    CHECK (to_date >= from_date),
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (reviewed_by) REFERENCES employees(employee_id) ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS holidays (
    holiday_date TEXT PRIMARY KEY, -- YYYY-MM-DD
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS anomalies (
    anomaly_id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NULL,
    department_id TEXT NULL,
    scope_type TEXT NOT NULL DEFAULT 'employee' CHECK (scope_type IN ('employee', 'department')),
    rule_code TEXT NOT NULL CHECK (rule_code IN ('R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8')),
    anomaly_type TEXT NOT NULL CHECK (
        anomaly_type IN (
            'late_repeated',
            'missing_punch',
            'low_hours',
            'leave_near_holiday',
            'leave_cluster',
            'identical_punch',
            'weekend_punch',
            'leave_over_balance'
        )
    ),
    severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    period TEXT NOT NULL, -- YYYY-MM
    evidence TEXT NOT NULL, -- JSON string
    explanation TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'open' CHECK (review_status IN ('open', 'confirmed', 'dismissed')),
    reviewed_by TEXT NULL,
    reviewed_at TEXT NULL,
    review_note TEXT NULL,
    detected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    dedup_key TEXT NOT NULL UNIQUE,
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (department_id) REFERENCES departments(department_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (reviewed_by) REFERENCES employees(employee_id) ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS query_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('employee', 'manager', 'hr', 'executive', 'admin')),
    question TEXT NOT NULL,
    query_type TEXT NOT NULL DEFAULT 'ai_sql',
    tool_name TEXT NULL,
    sql_text TEXT NULL,
    scope TEXT NOT NULL DEFAULT 'self',
    row_count INTEGER NOT NULL DEFAULT 0,
    success INTEGER NOT NULL DEFAULT 1 CHECK (success IN (0, 1)),
    status TEXT NOT NULL CHECK (status IN ('success', 'blocked', 'error', 'insufficient_data'))
);

-- =============================================================================
-- 2. EXTENDED TABLES (MO RONG DA CHOT)
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    employee_id TEXT NOT NULL UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    last_login_at TEXT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 0 CHECK (must_change_password IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS leave_approval_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    actor_user_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('submit', 'approve', 'reject', 'cancel', 'override')),
    note TEXT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    FOREIGN KEY (request_id) REFERENCES leave_requests(request_id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (actor_user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS import_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NULL,
    file_name TEXT NOT NULL,
    data_type TEXT NOT NULL CHECK (data_type IN ('employees', 'attendance', 'leave_requests')),
    uploaded_by TEXT NOT NULL,
    rows_total INTEGER NOT NULL DEFAULT 0,
    rows_valid INTEGER NOT NULL DEFAULT 0,
    rows_error INTEGER NOT NULL DEFAULT 0,
    rows_duplicate INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('preview', 'completed', 'failed')),
    detail_json TEXT NULL,
    result_json TEXT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    FOREIGN KEY (uploaded_by) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    before_json TEXT NULL,
    after_json TEXT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    FOREIGN KEY (actor_user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS overtime_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    work_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    approved_by TEXT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    UNIQUE (employee_id, work_date),
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (approved_by) REFERENCES employees(employee_id) ON UPDATE CASCADE ON DELETE SET NULL
);

-- =============================================================================
-- 2B. RBAC 5-ROLE & TECHNICAL ADMIN TABLES (SYNCED WITH SUPABASE POSTGRESQL)
-- =============================================================================

CREATE TABLE IF NOT EXISTS roles (
    role_id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_code TEXT NOT NULL UNIQUE CHECK (role_code IN ('employee', 'manager', 'hr', 'executive', 'admin')),
    role_name TEXT NOT NULL,
    description TEXT NULL,
    is_system_role INTEGER NOT NULL DEFAULT 1 CHECK (is_system_role IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
);

CREATE TABLE IF NOT EXISTS permissions (
    permission_id INTEGER PRIMARY KEY AUTOINCREMENT,
    permission_code TEXT NOT NULL UNIQUE,
    permission_name TEXT NOT NULL,
    description TEXT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id TEXT NOT NULL,
    role_id INTEGER NOT NULL,
    assigned_by_user_id TEXT NULL,
    assigned_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    PRIMARY KEY (user_id, role_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (role_id) REFERENCES roles(role_id) ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (assigned_by_user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id INTEGER NOT NULL,
    permission_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    PRIMARY KEY (role_id, permission_id),
    FOREIGN KEY (role_id) REFERENCES roles(role_id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (permission_id) REFERENCES permissions(permission_id) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS system_settings (
    setting_key TEXT PRIMARY KEY,
    category TEXT NOT NULL DEFAULT 'general',
    setting_value TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'string',
    description TEXT NULL,
    updated_by_user_id TEXT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    FOREIGN KEY (updated_by_user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS revoked_tokens (
    jti TEXT PRIMARY KEY,
    user_id TEXT NULL,
    revoked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    expires_at TEXT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS kiosk_devices (
    kiosk_device_id TEXT PRIMARY KEY,
    device_name TEXT NOT NULL,
    location_name TEXT NULL,
    branch_name TEXT NULL,
    assigned_user_id TEXT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    last_seen_at TEXT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    FOREIGN KEY (assigned_user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS company_documents (
    document_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    original_file_name TEXT NOT NULL,
    storage_bucket TEXT NOT NULL DEFAULT 'hr-documents',
    storage_path TEXT NOT NULL UNIQUE,
    document_type TEXT NOT NULL DEFAULT 'policy',
    version_label TEXT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('processing', 'active', 'archived', 'failed')),
    checksum_sha256 TEXT NULL,
    uploaded_by_user_id TEXT NULL,
    uploaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    processed_at TEXT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    source_content TEXT NULL,
    visibility TEXT NOT NULL DEFAULT 'all' CHECK (visibility IN ('all', 'manager_up', 'hr_exec_only', 'hr_only')),
    effective_from TEXT NULL,
    effective_to TEXT NULL,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    supersedes_document_id INTEGER NULL,
    FOREIGN KEY (uploaded_by_user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE SET NULL,
    FOREIGN KEY (supersedes_document_id) REFERENCES company_documents(document_id) ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    content TEXT NOT NULL,
    embedding_model TEXT NULL,
    embedding_json TEXT NULL,
    embedding_dim INTEGER NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    UNIQUE (document_id, chunk_index),
    FOREIGN KEY (document_id) REFERENCES company_documents(document_id) ON UPDATE CASCADE ON DELETE CASCADE
);

-- =============================================================================
-- 2C. AI CONVERSATION HISTORY TABLES (PHASE 3 — USER-ISOLATED MULTI-TURN CONTEXT)
-- =============================================================================

CREATE TABLE IF NOT EXISTS ai_conversations (
    conversation_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ai_messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    route_type TEXT NULL,
    response_json TEXT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    FOREIGN KEY (conversation_id) REFERENCES ai_conversations(conversation_id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE
);

-- =============================================================================
-- 3. INDEXES
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_employees_dept ON employees(department_id);
CREATE INDEX IF NOT EXISTS idx_employees_role ON employees(role);
CREATE INDEX IF NOT EXISTS idx_attendance_emp_date ON attendance(employee_id, work_date);
CREATE INDEX IF NOT EXISTS idx_attendance_work_date ON attendance(work_date);
CREATE INDEX IF NOT EXISTS idx_attendance_status ON attendance(status);
CREATE INDEX IF NOT EXISTS idx_leave_emp_status ON leave_requests(employee_id, status);
CREATE INDEX IF NOT EXISTS idx_leave_dates ON leave_requests(from_date, to_date);
CREATE INDEX IF NOT EXISTS idx_anomalies_period_sev ON anomalies(period, severity, review_status);
CREATE INDEX IF NOT EXISTS idx_anomalies_dept ON anomalies(department_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_emp ON anomalies(employee_id);
CREATE INDEX IF NOT EXISTS idx_users_employee ON users(employee_id);
CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_query_audit_asked ON query_audit_log(asked_at);
CREATE INDEX IF NOT EXISTS idx_revoked_tokens_expires ON revoked_tokens(expires_at);
CREATE INDEX IF NOT EXISTS idx_ai_conversations_user_updated ON ai_conversations(user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_ai_messages_conv_id ON ai_messages(conversation_id, message_id);

-- =============================================================================
-- 4. SAFE ALLOWLIST VIEWS FOR AI & REPORTING
-- =============================================================================
-- Note on leave_days: Following the original PDF specification, leave_days is
-- calculated as calendar days inclusive: julianday(to_date) - julianday(from_date) + 1.

CREATE VIEW IF NOT EXISTS v_employees AS
SELECT
    e.employee_id,
    e.full_name,
    e.department_id,
    d.name AS department_name,
    e.position,
    e.manager_id,
    m.full_name AS manager_name,
    e.start_date,
    e.annual_leave_balance,
    e.role,
    e.employment_status
FROM employees e
JOIN departments d ON d.department_id = e.department_id
LEFT JOIN employees m ON m.employee_id = e.manager_id;

CREATE VIEW IF NOT EXISTS v_attendance_daily AS
SELECT
    a.id,
    a.employee_id,
    e.full_name,
    e.department_id,
    d.name AS department_name,
    a.work_date,
    substr(a.work_date, 1, 7) AS period,
    a.check_in,
    a.check_out,
    a.status,
    a.source,
    CASE
        WHEN a.status = 'present'
             AND a.check_in IS NOT NULL
             AND (julianday(a.check_in) - julianday(a.work_date || ' 08:30:00')) * 1440.0 > 5.0
        THEN CAST(ROUND((julianday(a.check_in) - julianday(a.work_date || ' 08:30:00')) * 1440.0) AS INTEGER)
        ELSE 0
    END AS late_minutes,
    CASE
        WHEN a.status = 'present'
             AND a.check_in IS NOT NULL
             AND (julianday(a.check_in) - julianday(a.work_date || ' 08:30:00')) * 1440.0 > 5.0
        THEN 1
        ELSE 0
    END AS is_late,
    CASE
        WHEN a.status = 'present' AND a.check_in IS NOT NULL AND a.check_out IS NOT NULL THEN
            ROUND(
                MAX(
                    0.0,
                    (julianday(a.check_out) - julianday(a.check_in)) * 24.0
                    - CASE
                        WHEN (julianday(a.check_out) - julianday(a.check_in)) * 24.0 > 5.0 THEN 1.0
                        ELSE 0.0
                      END
                ),
                2
            )
        ELSE 0.0
    END AS work_hours,
    CASE
        WHEN CAST(strftime('%w', a.work_date) AS INTEGER) IN (0, 6) THEN 1
        ELSE 0
    END AS is_weekend,
    CASE
        WHEN h.holiday_date IS NOT NULL THEN 1
        ELSE 0
    END AS is_holiday
FROM attendance a
JOIN employees e ON e.employee_id = a.employee_id
JOIN departments d ON d.department_id = e.department_id
LEFT JOIN holidays h ON h.holiday_date = a.work_date;

CREATE VIEW IF NOT EXISTS v_leave_requests AS
SELECT
    lr.request_id,
    lr.employee_id,
    e.full_name,
    e.department_id,
    d.name AS department_name,
    lr.leave_type,
    lr.from_date,
    lr.to_date,
    substr(lr.from_date, 1, 7) AS period,
    CAST(julianday(lr.to_date) - julianday(lr.from_date) + 1 AS INTEGER) AS leave_days,
    lr.reason,
    lr.status,
    lr.requires_executive_approval,
    lr.reviewed_by,
    lr.reviewed_at,
    lr.decision_note,
    lr.created_at
FROM leave_requests lr
JOIN employees e ON e.employee_id = lr.employee_id
JOIN departments d ON d.department_id = e.department_id;

CREATE VIEW IF NOT EXISTS v_anomalies AS
SELECT
    an.anomaly_id,
    an.employee_id,
    e.full_name,
    COALESCE(an.department_id, e.department_id) AS department_id,
    d.name AS department_name,
    an.scope_type,
    an.rule_code,
    an.anomaly_type,
    an.severity,
    an.period,
    an.evidence,
    an.explanation,
    an.review_status,
    an.reviewed_by,
    an.reviewed_at,
    an.review_note,
    an.detected_at
FROM anomalies an
LEFT JOIN employees e ON e.employee_id = an.employee_id
LEFT JOIN departments d ON d.department_id = COALESCE(an.department_id, e.department_id);
