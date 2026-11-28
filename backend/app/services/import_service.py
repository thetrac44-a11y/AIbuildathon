from __future__ import annotations

import csv
import datetime
import io
import json
import re
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Tuple
import openpyxl

from app.core.permissions import PRIVILEGED_SYSTEM_ROLES
from app.core.security import begin_write_transaction, sync_user_role_mapping, write_activity_log
from app.db.connection import DB_INTEGRITY_ERRORS, is_postgres_connection
from app.services.anomaly_service import run_anomaly_scan

PRIVILEGED_IMPORT_ROLES = PRIVILEGED_SYSTEM_ROLES

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXTENSIONS = {".csv", ".xlsx"}
DANGEROUS_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


class ImportConflictError(Exception):
    """Raised when a target record changed concurrently in DB between preview and confirm (triggers rollback + 409)."""


# In-memory staging store (hot cache backed by import_logs.detail_json for persistence across refreshes/restarts)
STAGING_BATCHES: Dict[str, Dict[str, Any]] = {}


def _parse_json_field(val: Any) -> Optional[Dict[str, Any]]:
    """Accept both SQLite TEXT JSON strings and PostgreSQL JSONB dicts cleanly."""
    if val is None:
        return None
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        return json.loads(val)
    return None


def ensure_import_logs_columns(conn: sqlite3.Connection) -> None:
    """Safely upgrade legacy databases (SQLite or PostgreSQL) to include batch_id, detail_json and result_json."""
    if is_postgres_connection(conn):
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'import_logs'"
            ).fetchall()
        }
        col_defs = (
            ("batch_id", "TEXT"),
            ("detail_json", "JSONB"),
            ("result_json", "JSONB"),
        )
    else:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(import_logs)").fetchall()}
        col_defs = (
            ("batch_id", "TEXT NULL"),
            ("detail_json", "TEXT NULL"),
            ("result_json", "TEXT NULL"),
        )
    changed = False
    for col_name, col_def in col_defs:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE import_logs ADD COLUMN {col_name} {col_def}")
            changed = True
    if changed:
        conn.commit()


def _hydrate_batch_from_db(conn: Optional[sqlite3.Connection], batch_id: str) -> Optional[Dict[str, Any]]:
    """Restore a staged batch from import_logs.detail_json if not present in RAM (e.g. after server restart)."""
    batch = STAGING_BATCHES.get(batch_id)
    if batch is not None:
        return batch
    if conn is None:
        return None
    ensure_import_logs_columns(conn)
    row = conn.execute(
        """
        SELECT id, batch_id, file_name, data_type, uploaded_by, rows_total, status, detail_json
        FROM import_logs
        WHERE batch_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (batch_id,),
    ).fetchone()
    if not row or not row["detail_json"]:
        return None
    try:
        detail = _parse_json_field(row["detail_json"])
        if not detail:
            return None
    except Exception:
        return None

    hydrated = {
        "batch_id": row["batch_id"],
        "log_id": row["id"],
        "file_name": row["file_name"],
        "data_type": row["data_type"],
        "uploaded_by": row["uploaded_by"],
        "rows_total": row["rows_total"],
        "valid_rows": detail.get("valid_rows", detail.get("preview_rows", [])),
        "duplicate_rows": detail.get("duplicate_rows", []),
        "error_rows": detail.get("error_rows", []),
        "rows_warning": detail.get("summary", {}).get("rows_warning", 0),
        "rows_future": detail.get("summary", {}).get("rows_future", 0),
        "reference_today": detail.get("reference_today"),
        "confirmed": row["status"] == "completed",
    }
    STAGING_BATCHES[batch_id] = hydrated
    return hydrated

REQUIRED_COLUMNS: Dict[str, List[str]] = {
    "employees": ["employee_id", "full_name", "department_id", "position", "start_date", "role"],
    "attendance": ["employee_id", "work_date", "check_in", "check_out", "status"],
    "leave_requests": ["employee_id", "leave_type", "from_date", "to_date", "reason", "status"],
}


def sanitize_cell_for_export(value: Any) -> Any:
    """Prevent CSV/Excel formula injection (DDE/CSV Injection) on exported text cells.

    Neutralizes strings starting with =, +, -, @ or leading control characters (\t, \r, \n).
    """
    if not isinstance(value, str):
        return value
    if not value:
        return value
    stripped = value.lstrip(" \t\r\n")
    if value[0] in ("\t", "\r", "\n") or (stripped and stripped[0] in ("=", "+", "-", "@")):
        return "'" + value.replace("\r", " ").replace("\n", " ")
    return value


def has_formula_injection(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.lstrip(" \t\r\n")
    if not stripped:
        return False
    if stripped[0] in ("=", "+", "@"):
        return True
    # Block leading '-' formula payloads (e.g. '-1+1+cmd|...') while allowing plain negative numbers to hit numeric validation
    if stripped.startswith("-") and not re.fullmatch(r"-\d+(?:\.\d+)?", stripped):
        return True
    return False


def _parse_date(val: str) -> Optional[datetime.date]:
    try:
        return datetime.date.fromisoformat(val.strip()[:10])
    except Exception:
        return None


def _normalize_datetime(work_date: str, raw_val: Any) -> Tuple[Optional[str], Optional[str]]:
    """Normalize check_in/check_out into 'YYYY-MM-DD HH:MM:SS' or return error string."""
    if raw_val is None or str(raw_val).strip() == "":
        return None, None
    s = str(raw_val).strip()
    if len(s) == 5 and ":" in s:
        s = f"{work_date} {s}:00"
    elif len(s) == 8 and ":" in s and "-" not in s:
        s = f"{work_date} {s}"
    elif len(s) == 16 and "-" in s and ":" in s:
        s = f"{s}:00"
    try:
        dt = datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S"), None
    except ValueError:
        return None, f"Sai định dạng ngày giờ: '{raw_val}' (cần YYYY-MM-DD HH:MM:SS hoặc HH:MM:SS)"


def generate_template_xlsx(data_type: str) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = data_type

    if data_type == "employees":
        headers = ["employee_id", "full_name", "department_id", "position", "manager_id", "start_date", "annual_leave_balance", "role", "email", "phone"]
        sample = ["NV081", "Nguyễn Minh Khôi", "DEPT_TECH", "Kỹ sư Phần mềm", "NV003", "2026-10-01", 12, "employee", "nv081@company.vn", "0901000081"]
    elif data_type == "attendance":
        headers = ["employee_id", "work_date", "check_in", "check_out", "status", "source"]
        sample = ["NV007", "2026-11-20", "2026-11-20 08:25:00", "2026-11-20 17:35:00", "present", "import_excel"]
    elif data_type == "leave_requests":
        headers = ["employee_id", "leave_type", "from_date", "to_date", "reason", "status"]
        sample = ["NV007", "annual", "2026-11-25", "2026-11-26", "Nghỉ phép cá nhân", "pending"]
    else:
        raise ValueError(f"Unsupported data_type: {data_type}")

    ws.append(headers)
    ws.append(sample)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def parse_uploaded_file(file_name: str, raw_bytes: bytes) -> List[Dict[str, Any]]:
    lower = file_name.lower()
    if lower.endswith(".csv"):
        text = raw_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        return [{(k or "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()} for row in reader]

    if lower.endswith(".xlsx"):
        # Load with data_only=False so raw Excel formulas (=CMD..., =HYPERLINK...) are always caught by formula-injection validation
        wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=False)
        ws = wb.active
        rows_iter = list(ws.iter_rows(values_only=True))
        if not rows_iter:
            return []
        headers = [str(h).strip() if h is not None else "" for h in rows_iter[0]]
        result: List[Dict[str, Any]] = []
        for values in rows_iter[1:]:
            if all(v is None or str(v).strip() == "" for v in values):
                continue
            item: Dict[str, Any] = {}
            for idx, h in enumerate(headers):
                if not h:
                    continue
                val = values[idx] if idx < len(values) else None
                if isinstance(val, datetime.datetime):
                    val = val.strftime("%Y-%m-%d %H:%M:%S")
                elif isinstance(val, datetime.date):
                    val = val.isoformat()
                elif isinstance(val, str):
                    val = val.strip()
                item[h] = val
            result.append(item)
        return result

    raise ValueError("Chỉ hỗ trợ file .csv hoặc .xlsx")


def _extract_error_fields(data_type: str, raw: Dict[str, Any]) -> Dict[str, str]:
    """Extract clean structured columns for tabular Error display (without requiring horizontal JSON scroll)."""
    def _s(k: str) -> str:
        v = raw.get(k)
        return "" if v is None else str(v).strip()

    if data_type == "attendance":
        return {
            "employee_id": _s("employee_id"),
            "work_date": _s("work_date"),
            "check_in": _s("check_in"),
            "check_out": _s("check_out"),
            "status": _s("status"),
        }
    if data_type == "employees":
        return {
            "employee_id": _s("employee_id"),
            "full_name": _s("full_name"),
            "department_id": _s("department_id"),
            "position": _s("position"),
            "role": _s("role"),
        }
    return {
        "employee_id": _s("employee_id"),
        "leave_type": _s("leave_type"),
        "from_date": _s("from_date"),
        "to_date": _s("to_date"),
        "status": _s("status"),
    }


def _evaluate_attendance_warnings(
    emp_id: str,
    work_date: str,
    work_dt: datetime.date,
    check_in: Optional[str],
    check_out: Optional[str],
    status_val: str,
    today: datetime.date,
    holiday_set: set[str],
    approved_ot_set: set[Tuple[str, str]],
) -> Tuple[List[Dict[str, str]], bool, bool]:
    """Classify business warnings on structurally valid attendance rows without turning them into hard errors."""
    warnings: List[Dict[str, str]] = []
    is_future = False
    is_incomplete = False

    if status_val == "present" and (check_in is None or check_out is None):
        is_incomplete = True
        if check_in is None and check_out is None:
            label = "Thiếu cả giờ vào và giờ ra"
        elif check_in is None:
            label = "Thiếu giờ vào"
        else:
            label = "Thiếu giờ ra"
        warnings.append(
            {
                "code": "missing_punch",
                "level": "warning",
                "label": label,
                "detail": "Bản ghi ở trạng thái chấm công chưa đầy đủ; không tính giờ công hoàn chỉnh và có thể phát sinh cảnh báo R2 sau khi nhập.",
            }
        )

    if status_val == "present" and (work_dt.weekday() >= 5 or work_date in holiday_set):
        has_approved_ot = (emp_id, work_date) in approved_ot_set
        if not has_approved_ot:
            if work_date in holiday_set:
                day_label = "Chấm công ngày lễ (chưa có đơn OT)"
            elif work_dt.weekday() == 5:
                day_label = "Chấm công thứ Bảy (chưa có đơn OT)"
            else:
                day_label = "Chấm công Chủ nhật (chưa có đơn OT)"
            warnings.append(
                {
                    "code": "weekend_or_holiday",
                    "level": "warning",
                    "label": day_label,
                    "detail": "Chưa có lịch làm cuối tuần/đơn làm thêm giờ được duyệt trong overtime_requests; cần đối chiếu và có thể phát sinh cảnh báo R7.",
                }
            )

    if work_dt > today:
        is_future = True
        warnings.append(
            {
                "code": "future_date",
                "level": "high",
                "label": "Ngày trong tương lai",
                "detail": f"Ngày chấm công ({work_date}) lớn hơn ngày hiện tại ({today.isoformat()}). Mặc định bị chặn khi xác nhận trừ khi HR bật xác nhận dữ liệu mô phỏng.",
            }
        )

    return warnings, is_future, is_incomplete


def stage_and_validate_import(
    conn: sqlite3.Connection,
    actor_user_id: str,
    file_name: str,
    data_type: str,
    raw_bytes: bytes,
    reference_today: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    if data_type not in REQUIRED_COLUMNS:
        raise ValueError("Loại dữ liệu import không hợp lệ.")
    if len(raw_bytes) == 0:
        raise ValueError("File tải lên bị rỗng.")
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError("Kích thước file vượt quá giới hạn 5 MB.")

    lower = file_name.lower()
    if not any(lower.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        raise ValueError("Định dạng file không hợp lệ. Chỉ chấp nhận .csv hoặc .xlsx.")

    rows = parse_uploaded_file(file_name, raw_bytes)
    if not rows:
        raise ValueError("File không có dòng dữ liệu nào để nhập.")

    present_cols = set(rows[0].keys())
    missing_cols = [c for c in REQUIRED_COLUMNS[data_type] if c not in present_cols]
    if missing_cols:
        raise ValueError(f"Thiếu các cột bắt buộc trong file: {', '.join(missing_cols)}")

    today = reference_today or datetime.date.today()

    existing_depts = {r[0] for r in conn.execute("SELECT department_id FROM departments").fetchall()}
    existing_emp_map = {
        r["employee_id"]: dict(r)
        for r in conn.execute(
            "SELECT employee_id, full_name, department_id, position, annual_leave_balance, role, phone FROM employees"
        ).fetchall()
    }
    existing_emps = set(existing_emp_map.keys())
    existing_att_map = {
        (r["employee_id"], r["work_date"]): dict(r)
        for r in conn.execute(
            "SELECT id, employee_id, work_date, check_in, check_out, status, source FROM attendance"
        ).fetchall()
    }
    existing_leave_map = {
        (r["employee_id"], r["from_date"], r["to_date"]): dict(r)
        for r in conn.execute(
            "SELECT employee_id, leave_type, from_date, to_date, reason, status FROM leave_requests"
        ).fetchall()
    }
    holiday_set = {r[0] for r in conn.execute("SELECT holiday_date FROM holidays").fetchall()}
    approved_ot_set = {
        (r[0], r[1])
        for r in conn.execute("SELECT employee_id, work_date FROM overtime_requests WHERE status = 'approved'").fetchall()
    }

    valid_rows: List[Dict[str, Any]] = []
    duplicate_rows: List[Dict[str, Any]] = []
    error_rows: List[Dict[str, Any]] = []
    seen_keys: Dict[Any, Dict[str, Any]] = {}

    for idx, raw in enumerate(rows, start=2):  # Row 1 is header
        # Reject formula injection in any string cell
        injected_cols = [k for k, v in raw.items() if has_formula_injection(v)]
        if injected_cols:
            error_rows.append(
                {
                    "row_number": idx,
                    "error": f"Phát hiện ký tự công thức nguy hiểm ở cột: {', '.join(injected_cols)}",
                    "fields": _extract_error_fields(data_type, raw),
                    "raw": raw,
                }
            )
            continue

        if data_type == "employees":
            emp_id = str(raw.get("employee_id") or "").strip().upper()
            full_name = str(raw.get("full_name") or "").strip()
            dept_id = str(raw.get("department_id") or "").strip()
            position = str(raw.get("position") or "").strip()
            start_date = str(raw.get("start_date") or "").strip()
            role = str(raw.get("role") or "employee").strip().lower()
            manager_id = str(raw.get("manager_id") or "").strip().upper() or None
            email = str(raw.get("email") or "").strip().lower() or f"{emp_id.lower()}@company.vn"
            phone = str(raw.get("phone") or "").strip() or None
            try:
                balance = float(raw.get("annual_leave_balance") if raw.get("annual_leave_balance") not in (None, "") else 12.0)
            except Exception:
                balance = -1.0

            errs = []
            if not emp_id:
                errs.append("Thiếu employee_id")
            if not full_name:
                errs.append("Thiếu full_name")
            if dept_id not in existing_depts:
                errs.append(f"Phòng ban không tồn tại: {dept_id}")
            if not position:
                errs.append("Thiếu position")
            if _parse_date(start_date) is None:
                errs.append(f"start_date không hợp lệ: {start_date}")
            if role not in ("employee", "manager", "hr"):
                errs.append(f"role không hợp lệ: {role}")
            if balance < 0:
                errs.append("annual_leave_balance không hợp lệ")
            if errs:
                error_rows.append(
                    {
                        "row_number": idx,
                        "error": "; ".join(errs),
                        "fields": _extract_error_fields(data_type, raw),
                        "raw": raw,
                    }
                )
                continue

            normalized = {
                "row_number": idx,
                "employee_id": emp_id,
                "full_name": full_name,
                "department_id": dept_id,
                "position": position,
                "manager_id": manager_id,
                "start_date": start_date[:10],
                "annual_leave_balance": balance,
                "role": role,
                "email": email,
                "phone": phone,
                "warnings": [],
                "is_future_date": False,
            }
            if emp_id in existing_emp_map or emp_id in seen_keys:
                in_db = emp_id in existing_emp_map
                existing_rec = existing_emp_map.get(emp_id) if in_db else seen_keys.get(emp_id)
                changed_fields = []
                if existing_rec:
                    for field_key in ("full_name", "department_id", "position", "role", "annual_leave_balance", "phone"):
                        if existing_rec.get(field_key) != normalized.get(field_key):
                            changed_fields.append(field_key)
                is_identical = len(changed_fields) == 0
                is_privileged_target = bool(in_db and existing_rec and existing_rec.get("role") in PRIVILEGED_IMPORT_ROLES)
                match_type = "exact_match" if is_identical else "key_conflict"
                if is_privileged_target:
                    comparison_label = "Tài khoản đặc quyền (Admin/Executive) — bị khóa ghi đè qua Import"
                else:
                    comparison_label = (
                        "Trùng lặp trong file Excel"
                        if not in_db
                        else ("Trùng hoàn toàn" if is_identical else "Trùng khóa, khác dữ liệu")
                    )
                duplicate_rows.append(
                    {
                        "row_number": idx,
                        "reason": f"Trùng employee_id {emp_id}",
                        "data": normalized,
                        "existing": existing_rec,
                        "duplicate_source": "database" if in_db else "in_file",
                        "is_identical": is_identical,
                        "match_type": match_type,
                        "changed_fields": changed_fields,
                        "comparison_label": comparison_label,
                        "can_update": bool(in_db and not is_privileged_target),
                        "default_action": "keep_existing",
                    }
                )
            else:
                seen_keys[emp_id] = normalized
                valid_rows.append(normalized)

        elif data_type == "attendance":
            emp_id = str(raw.get("employee_id") or "").strip().upper()
            work_date = str(raw.get("work_date") or "").strip()[:10]
            status_val = str(raw.get("status") or "present").strip().lower()
            source = str(raw.get("source") or "import_file").strip() or "import_file"

            errs = []
            if emp_id not in existing_emps:
                errs.append(f"Mã nhân viên không tồn tại: {emp_id}")
            work_dt = _parse_date(work_date)
            if work_dt is None:
                errs.append(f"work_date không hợp lệ: {work_date}")
            if status_val not in ("present", "absent", "on_leave", "holiday", "weekend"):
                errs.append(f"status không hợp lệ: {status_val}")

            check_in_norm, ci_err = _normalize_datetime(work_date, raw.get("check_in"))
            check_out_norm, co_err = _normalize_datetime(work_date, raw.get("check_out"))
            if ci_err:
                errs.append(ci_err)
            if co_err:
                errs.append(co_err)
            if check_in_norm and check_out_norm and check_out_norm < check_in_norm:
                errs.append("check_out không thể nhỏ hơn check_in")

            if errs:
                error_rows.append(
                    {
                        "row_number": idx,
                        "error": "; ".join(errs),
                        "fields": _extract_error_fields(data_type, raw),
                        "raw": raw,
                    }
                )
                continue

            assert work_dt is not None
            warnings, is_future, is_incomplete = _evaluate_attendance_warnings(
                emp_id=emp_id,
                work_date=work_date,
                work_dt=work_dt,
                check_in=check_in_norm,
                check_out=check_out_norm,
                status_val=status_val,
                today=today,
                holiday_set=holiday_set,
                approved_ot_set=approved_ot_set,
            )

            key = (emp_id, work_date)
            normalized = {
                "row_number": idx,
                "employee_id": emp_id,
                "work_date": work_date,
                "check_in": check_in_norm,
                "check_out": check_out_norm,
                "status": status_val,
                "source": source,
                "warnings": warnings,
                "is_future_date": is_future,
                "is_incomplete_punch": is_incomplete,
            }
            if key in existing_att_map or key in seen_keys:
                in_db = key in existing_att_map
                existing_rec = existing_att_map.get(key) if in_db else seen_keys.get(key)
                changed_fields = []
                if existing_rec:
                    if existing_rec.get("check_in") != check_in_norm:
                        changed_fields.append("check_in")
                    if existing_rec.get("check_out") != check_out_norm:
                        changed_fields.append("check_out")
                    if existing_rec.get("status") != status_val:
                        changed_fields.append("status")
                is_identical = len(changed_fields) == 0
                match_type = "exact_match" if is_identical else "key_conflict"
                comparison_label = (
                    "Trùng lặp trong file Excel"
                    if not in_db
                    else ("Trùng hoàn toàn" if is_identical else "Trùng khóa, khác dữ liệu")
                )
                duplicate_rows.append(
                    {
                        "row_number": idx,
                        "reason": f"Trùng bản ghi chấm công ({emp_id}, {work_date})",
                        "data": normalized,
                        "existing": existing_rec,
                        "duplicate_source": "database" if in_db else "in_file",
                        "is_identical": is_identical,
                        "match_type": match_type,
                        "changed_fields": changed_fields,
                        "comparison_label": comparison_label,
                        "can_update": in_db,
                        "default_action": "keep_existing",
                    }
                )
            else:
                seen_keys[key] = normalized
                valid_rows.append(normalized)

        elif data_type == "leave_requests":
            emp_id = str(raw.get("employee_id") or "").strip().upper()
            leave_type = str(raw.get("leave_type") or "").strip().lower()
            from_date = str(raw.get("from_date") or "").strip()[:10]
            to_date = str(raw.get("to_date") or "").strip()[:10]
            reason = str(raw.get("reason") or "").strip()
            status_val = str(raw.get("status") or "pending").strip().lower()

            errs = []
            if emp_id not in existing_emps:
                errs.append(f"Mã nhân viên không tồn tại: {emp_id}")
            if leave_type not in ("annual", "sick", "personal", "unpaid"):
                errs.append(f"leave_type không hợp lệ: {leave_type}")
            f_dt = _parse_date(from_date)
            t_dt = _parse_date(to_date)
            if f_dt is None or t_dt is None:
                errs.append("from_date hoặc to_date không hợp lệ")
            elif t_dt < f_dt:
                errs.append("to_date phải >= from_date")
            if not reason:
                errs.append("Thiếu lý do nghỉ phép")
            if status_val not in ("pending", "approved", "rejected", "cancelled"):
                errs.append(f"status không hợp lệ: {status_val}")

            if errs:
                error_rows.append(
                    {
                        "row_number": idx,
                        "error": "; ".join(errs),
                        "fields": _extract_error_fields(data_type, raw),
                        "raw": raw,
                    }
                )
                continue

            key = (emp_id, from_date, to_date)
            normalized = {
                "row_number": idx,
                "employee_id": emp_id,
                "leave_type": leave_type,
                "from_date": from_date,
                "to_date": to_date,
                "reason": reason,
                "status": status_val,
                "warnings": [],
                "is_future_date": False,
            }
            if key in existing_leave_map or key in seen_keys:
                in_db = key in existing_leave_map
                existing_rec = existing_leave_map.get(key) if in_db else seen_keys.get(key)
                changed_fields = []
                if existing_rec:
                    for field_key in ("leave_type", "status", "reason"):
                        if existing_rec.get(field_key) != normalized.get(field_key):
                            changed_fields.append(field_key)
                is_identical = len(changed_fields) == 0
                match_type = "exact_match" if is_identical else "key_conflict"
                duplicate_rows.append(
                    {
                        "row_number": idx,
                        "reason": f"Trùng đơn nghỉ phép ({emp_id}, {from_date}..{to_date})",
                        "data": normalized,
                        "existing": existing_rec,
                        "duplicate_source": "database" if in_db else "in_file",
                        "is_identical": is_identical,
                        "match_type": match_type,
                        "changed_fields": changed_fields,
                        "comparison_label": "Trùng hoàn toàn" if is_identical else "Trùng khóa, khác dữ liệu",
                        "can_update": False,
                        "default_action": "keep_existing",
                    }
                )
            else:
                seen_keys[key] = normalized
                valid_rows.append(normalized)

    rows_warning = sum(1 for r in valid_rows if r.get("warnings"))
    rows_future = sum(1 for r in valid_rows if r.get("is_future_date"))

    batch_id = f"IMP-{uuid.uuid4().hex[:16].upper()}"
    summary_obj = {
        "rows_total": len(rows),
        "rows_valid": len(valid_rows),
        "rows_warning": rows_warning,
        "rows_future": rows_future,
        "rows_error": len(error_rows),
        "rows_duplicate": len(duplicate_rows),
    }
    detail_payload = {
        "batch_id": batch_id,
        "file_name": file_name,
        "data_type": data_type,
        "reference_today": today.isoformat(),
        "summary": summary_obj,
        "valid_rows": valid_rows,
        "duplicate_rows": duplicate_rows,
        "error_rows": error_rows,
    }

    ensure_import_logs_columns(conn)
    now_local = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        """
        INSERT INTO import_logs (
            batch_id, file_name, data_type, uploaded_by, rows_total, rows_valid, rows_error, rows_duplicate, status, detail_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'preview', ?, ?)
        """,
        (
            batch_id,
            file_name,
            data_type,
            actor_user_id,
            len(rows),
            len(valid_rows),
            len(error_rows),
            len(duplicate_rows),
            json.dumps(detail_payload, ensure_ascii=False),
            now_local,
        ),
    )
    log_id = cur.lastrowid
    conn.commit()

    STAGING_BATCHES[batch_id] = {
        "batch_id": batch_id,
        "log_id": log_id,
        "file_name": file_name,
        "data_type": data_type,
        "uploaded_by": actor_user_id,
        "rows_total": len(rows),
        "valid_rows": valid_rows,
        "duplicate_rows": duplicate_rows,
        "error_rows": error_rows,
        "rows_warning": rows_warning,
        "rows_future": rows_future,
        "reference_today": today.isoformat(),
        "confirmed": False,
    }

    return {
        "log_id": log_id,
        "batch_id": batch_id,
        "file_name": file_name,
        "data_type": data_type,
        "reference_today": today.isoformat(),
        "summary": summary_obj,
        "preview_rows": valid_rows[:50],
        "duplicate_rows": duplicate_rows[:50],
        "error_rows": error_rows[:50],
    }


def get_import_log_detail(
    conn: sqlite3.Connection,
    log_id: int,
    actor_user_id: str,
) -> Dict[str, Any]:
    """Return persisted audit details for a historical import log entry (preview rows, warnings, errors, confirm result)."""
    ensure_import_logs_columns(conn)
    row = conn.execute(
        """
        SELECT il.id, il.batch_id, il.file_name, il.data_type, il.uploaded_by,
               u.username AS uploaded_by_username,
               il.rows_total, il.rows_valid, il.rows_error, il.rows_duplicate,
               il.status, il.detail_json, il.result_json, il.created_at
        FROM import_logs il
        LEFT JOIN users u ON u.user_id = il.uploaded_by
        WHERE il.id = ?
        """,
        (log_id,),
    ).fetchone()
    if not row:
        raise KeyError("Không tìm thấy lịch sử nhập dữ liệu.")

    preview_snapshot: Optional[Dict[str, Any]] = None
    if row["detail_json"]:
        try:
            raw_detail = _parse_json_field(row["detail_json"]) or {}
            preview_snapshot = {
                "batch_id": raw_detail.get("batch_id") or row["batch_id"],
                "file_name": raw_detail.get("file_name") or row["file_name"],
                "data_type": raw_detail.get("data_type") or row["data_type"],
                "reference_today": raw_detail.get("reference_today"),
                "summary": raw_detail.get("summary")
                or {
                    "rows_total": row["rows_total"],
                    "rows_valid": row["rows_valid"],
                    "rows_warning": 0,
                    "rows_future": 0,
                    "rows_error": row["rows_error"],
                    "rows_duplicate": row["rows_duplicate"],
                },
                "preview_rows": raw_detail.get("preview_rows", raw_detail.get("valid_rows", []))[:100],
                "duplicate_rows": raw_detail.get("duplicate_rows", [])[:100],
                "error_rows": raw_detail.get("error_rows", [])[:100],
            }
        except Exception:
            preview_snapshot = None

    result_snapshot: Optional[Dict[str, Any]] = None
    if row["result_json"]:
        try:
            result_snapshot = _parse_json_field(row["result_json"])
        except Exception:
            result_snapshot = None

    has_snapshot = preview_snapshot is not None
    is_owner = row["uploaded_by"] == actor_user_id
    mask_staged_batch = bool(row["status"] == "preview" and not is_owner)
    exposed_batch_id = None if mask_staged_batch else row["batch_id"]
    if preview_snapshot is not None and mask_staged_batch:
        preview_snapshot["batch_id"] = None

    return {
        "log": {
            "id": row["id"],
            "batch_id": exposed_batch_id,
            "file_name": row["file_name"],
            "data_type": row["data_type"],
            "uploaded_by": row["uploaded_by"],
            "uploaded_by_username": row["uploaded_by_username"],
            "rows_total": row["rows_total"],
            "rows_valid": row["rows_valid"],
            "rows_error": row["rows_error"],
            "rows_duplicate": row["rows_duplicate"],
            "status": row["status"],
            "has_snapshot": has_snapshot,
            "created_at": row["created_at"],
        },
        "has_snapshot": has_snapshot,
        "can_resume_confirm": bool(has_snapshot and row["status"] == "preview" and is_owner and row["batch_id"]),
        "can_download_errors": bool(has_snapshot and row["rows_error"] > 0 and is_owner and row["batch_id"]),
        "preview": preview_snapshot,
        "result": result_snapshot,
    }


def export_batch_errors_csv(
    batch_id: str,
    actor_user_id: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> str:
    batch = _hydrate_batch_from_db(conn, batch_id)
    if not batch:
        raise KeyError("Không tìm thấy phiên import.")
    if actor_user_id and batch["uploaded_by"] != actor_user_id:
        raise PermissionError("Bạn không có quyền tải tệp lỗi của phiên import do tài khoản khác tạo.")

    data_type = batch["data_type"]
    out = io.StringIO()
    writer = csv.writer(out)

    if data_type == "attendance":
        cols = ["employee_id", "work_date", "check_in", "check_out", "status"]
    elif data_type == "employees":
        cols = ["employee_id", "full_name", "department_id", "position", "role"]
    else:
        cols = ["employee_id", "leave_type", "from_date", "to_date", "status"]

    writer.writerow(["row_number", *cols, "error", "raw_data"])
    for err in batch["error_rows"]:
        fields = err.get("fields") or {}
        safe_field_vals = [sanitize_cell_for_export(fields.get(c, "")) for c in cols]
        raw_sanitized = {k: sanitize_cell_for_export(v) for k, v in (err.get("raw") or {}).items()}
        writer.writerow(
            [
                err["row_number"],
                *safe_field_vals,
                sanitize_cell_for_export(err["error"]),
                sanitize_cell_for_export(str(raw_sanitized)),
            ]
        )
    return out.getvalue()


def _resolve_duplicate_action(
    dup: Dict[str, Any],
    duplicate_policy: str,
    duplicate_decisions: Optional[Dict[str, str]],
) -> str:
    """Resolve per-row action safely: defaults to 'keep_existing' and never overwrites in-file duplicates."""
    if dup.get("duplicate_source") == "in_file" or dup.get("can_update") is False:
        return "keep_existing"
    if duplicate_decisions is not None:
        raw_action = duplicate_decisions.get(str(dup["row_number"]), "keep_existing")
        return "update_from_excel" if raw_action == "update_from_excel" else "keep_existing"
    return "update_from_excel" if duplicate_policy == "update" else "keep_existing"


def confirm_staged_import(
    conn: sqlite3.Connection,
    batch_id: str,
    actor_user_id: str,
    duplicate_policy: str = "skip",
    duplicate_decisions: Optional[Dict[str, str]] = None,
    allow_future_dates: bool = False,
    force_fail_for_test: bool = False,
) -> Dict[str, Any]:
    ensure_import_logs_columns(conn)
    batch = _hydrate_batch_from_db(conn, batch_id)
    if not batch:
        raise KeyError("Không tìm thấy phiên import hoặc phiên đã hết hạn.")
    if batch["uploaded_by"] != actor_user_id:
        raise PermissionError("Bạn không có quyền xác nhận phiên import do tài khoản khác tạo.")
    if batch["confirmed"]:
        raise ValueError("Phiên import này đã được xác nhận trước đó.")

    data_type = batch["data_type"]
    inserted = 0
    updated = 0
    skipped = 0
    rejected_future = 0
    affected_periods: set[str] = set()
    updated_records: List[Dict[str, Any]] = []
    applied_decisions: Dict[str, str] = {}
    action_timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        begin_write_transaction(conn)
        if data_type == "employees":
            for row in batch["valid_rows"]:
                try:
                    conn.execute(
                        """
                        INSERT INTO employees (
                            employee_id, full_name, department_id, position, manager_id,
                            start_date, annual_leave_balance, role, employment_status, email, phone
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                        """,
                        (
                            row["employee_id"],
                            row["full_name"],
                            row["department_id"],
                            row["position"],
                            row["manager_id"],
                            row["start_date"],
                            row["annual_leave_balance"],
                            row["role"],
                            row["email"],
                            row["phone"],
                        ),
                    )
                except DB_INTEGRITY_ERRORS as exc:
                    raise ImportConflictError(
                        f"Nhân viên {row['employee_id']} đã tồn tại hoặc xung đột dữ liệu phát sinh sau bước xem trước. Giao dịch đã rollback."
                    ) from exc
                inserted += 1

            for dup in batch["duplicate_rows"]:
                row = dup["data"]
                action = _resolve_duplicate_action(dup, duplicate_policy, duplicate_decisions)
                applied_decisions[str(dup["row_number"])] = action
                if action != "update_from_excel":
                    skipped += 1
                    continue

                live = conn.execute(
                    """
                    SELECT employee_id, full_name, department_id, position, annual_leave_balance, role, phone
                    FROM employees WHERE employee_id = ?
                    """,
                    (row["employee_id"],),
                ).fetchone()
                expected = dup.get("existing") or {}
                if not live or any(
                    live[f] != expected.get(f) for f in ("full_name", "department_id", "position", "role")
                ):
                    raise ImportConflictError(
                        f"Hồ sơ nhân viên {row['employee_id']} đã bị thay đổi trong cơ sở dữ liệu sau bước xem trước. "
                        "Giao dịch đã được hủy (rollback) để tránh ghi đè ngoài ý muốn; vui lòng xem trước lại tệp."
                    )

                # Hard guard: HR bulk import must NEVER overwrite/demote Admin or Executive or last active HR
                if live["role"] in PRIVILEGED_IMPORT_ROLES:
                    raise PermissionError(
                        f"Không được phép ghi đè hoặc thay đổi hồ sơ đặc quyền ({live['role']}) của {row['employee_id']} qua Import."
                    )
                if live["role"] == "hr" and row["role"] != "hr":
                    other_hr_cnt = int(
                        conn.execute(
                            """
                            SELECT COUNT(*)
                            FROM users u
                            JOIN employees e ON e.employee_id = u.employee_id
                            WHERE e.role = 'hr' AND u.is_active = 1 AND e.employment_status = 'active'
                              AND e.employee_id != ?
                            """,
                            (row["employee_id"],),
                        ).fetchone()[0]
                    )
                    if other_hr_cnt == 0:
                        raise ValueError(
                            f"Không thể hạ quyền tài khoản HR cuối cùng còn hoạt động ({row['employee_id']}) qua Import."
                        )

                before_snapshot = dict(live)
                conn.execute(
                    """
                    UPDATE employees
                    SET full_name = ?, department_id = ?, position = ?, annual_leave_balance = ?, role = ?, phone = ?
                    WHERE employee_id = ?
                    """,
                    (
                        row["full_name"],
                        row["department_id"],
                        row["position"],
                        row["annual_leave_balance"],
                        row["role"],
                        row["phone"],
                        row["employee_id"],
                    ),
                )
                if row["role"] != live["role"]:
                    linked_user = conn.execute(
                        "SELECT user_id FROM users WHERE employee_id = ?",
                        (row["employee_id"],),
                    ).fetchone()
                    if linked_user:
                        sync_user_role_mapping(conn, linked_user["user_id"], row["role"], assigned_by_user_id=actor_user_id)
                after_snapshot = {
                    "employee_id": row["employee_id"],
                    "full_name": row["full_name"],
                    "department_id": row["department_id"],
                    "position": row["position"],
                    "annual_leave_balance": row["annual_leave_balance"],
                    "role": row["role"],
                    "phone": row["phone"],
                }
                write_activity_log(
                    conn,
                    actor_user_id=actor_user_id,
                    action="import_update_employee",
                    entity_type="employee",
                    entity_id=row["employee_id"],
                    before_obj=before_snapshot,
                    after_obj={**after_snapshot, "batch_id": batch_id, "row_number": row["row_number"]},
                )
                updated_records.append(
                    {
                        "row_number": row["row_number"],
                        "employee_id": row["employee_id"],
                        "before": before_snapshot,
                        "after": after_snapshot,
                        "updated_by": actor_user_id,
                        "updated_at": action_timestamp,
                    }
                )
                updated += 1

        elif data_type == "attendance":
            for row in batch["valid_rows"]:
                if row.get("is_future_date") and not allow_future_dates:
                    rejected_future += 1
                    continue
                try:
                    conn.execute(
                        """
                        INSERT INTO attendance (employee_id, work_date, check_in, check_out, status, source)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["employee_id"],
                            row["work_date"],
                            row["check_in"],
                            row["check_out"],
                            row["status"],
                            row["source"],
                        ),
                    )
                except DB_INTEGRITY_ERRORS as exc:
                    raise ImportConflictError(
                        f"Bản ghi chấm công ({row['employee_id']}, {row['work_date']}) vừa phát sinh trùng khóa sau bước xem trước. "
                        "Giao dịch đã được hủy (rollback) để bảo toàn dữ liệu; vui lòng kiểm tra và xem trước lại."
                    ) from exc
                inserted += 1
                affected_periods.add(row["work_date"][:7])

            for dup in batch["duplicate_rows"]:
                row = dup["data"]
                action = _resolve_duplicate_action(dup, duplicate_policy, duplicate_decisions)
                applied_decisions[str(dup["row_number"])] = action
                if action != "update_from_excel":
                    skipped += 1
                    continue

                if row.get("is_future_date") and not allow_future_dates:
                    rejected_future += 1
                    continue

                # Optimistic concurrency guard: verify live DB record has not changed since preview
                live = conn.execute(
                    """
                    SELECT id, employee_id, work_date, check_in, check_out, status, source
                    FROM attendance
                    WHERE employee_id = ? AND work_date = ?
                    """,
                    (row["employee_id"], row["work_date"]),
                ).fetchone()
                expected = dup.get("existing") or {}
                if (
                    not live
                    or live["check_in"] != expected.get("check_in")
                    or live["check_out"] != expected.get("check_out")
                    or live["status"] != expected.get("status")
                ):
                    raise ImportConflictError(
                        f"Dữ liệu chấm công của {row['employee_id']} ngày {row['work_date']} đã bị thay đổi trong cơ sở dữ liệu sau bước xem trước. "
                        "Giao dịch đã được hủy (rollback) để tránh ghi đè ngoài ý muốn; vui lòng tải lại xem trước."
                    )

                before_snapshot = {
                    "employee_id": live["employee_id"],
                    "work_date": live["work_date"],
                    "check_in": live["check_in"],
                    "check_out": live["check_out"],
                    "status": live["status"],
                    "source": live["source"],
                }
                # Update permitted attendance fields only (in-place by PK/key — never inserts a duplicate row)
                conn.execute(
                    """
                    UPDATE attendance
                    SET check_in = ?, check_out = ?, status = ?, source = ?
                    WHERE id = ?
                    """,
                    (
                        row["check_in"],
                        row["check_out"],
                        row["status"],
                        row["source"],
                        live["id"],
                    ),
                )
                after_snapshot = {
                    "employee_id": row["employee_id"],
                    "work_date": row["work_date"],
                    "check_in": row["check_in"],
                    "check_out": row["check_out"],
                    "status": row["status"],
                    "source": row["source"],
                }
                write_activity_log(
                    conn,
                    actor_user_id=actor_user_id,
                    action="import_update_attendance",
                    entity_type="attendance",
                    entity_id=f"{row['employee_id']}:{row['work_date']}",
                    before_obj=before_snapshot,
                    after_obj={**after_snapshot, "batch_id": batch_id, "row_number": row["row_number"]},
                )
                updated_records.append(
                    {
                        "row_number": row["row_number"],
                        "employee_id": row["employee_id"],
                        "work_date": row["work_date"],
                        "before": before_snapshot,
                        "after": after_snapshot,
                        "updated_by": actor_user_id,
                        "updated_at": action_timestamp,
                    }
                )
                updated += 1
                affected_periods.add(row["work_date"][:7])

        elif data_type == "leave_requests":
            for row in batch["valid_rows"]:
                conn.execute(
                    """
                    INSERT INTO leave_requests (employee_id, leave_type, from_date, to_date, reason, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["employee_id"],
                        row["leave_type"],
                        row["from_date"],
                        row["to_date"],
                        row["reason"],
                        row["status"],
                    ),
                )
                inserted += 1
                affected_periods.add(row["from_date"][:7])
            for dup in batch["duplicate_rows"]:
                applied_decisions[str(dup["row_number"])] = "keep_existing"
                skipped += 1

        if force_fail_for_test:
            raise RuntimeError("Simulated mid-transaction failure for rollback verification")

        conn.execute(
            "UPDATE import_logs SET status = 'completed' WHERE id = ?",
            (batch["log_id"],),
        )
        write_activity_log(
            conn,
            actor_user_id=actor_user_id,
            action="confirm_import",
            entity_type="import",
            entity_id=batch_id,
            after_obj={
                "data_type": data_type,
                "file_name": batch["file_name"],
                "inserted": inserted,
                "updated": updated,
                "skipped": skipped,
                "rejected_future": rejected_future,
                "errors": len(batch["error_rows"]),
                "allow_future_dates": allow_future_dates,
                "duplicate_decisions": applied_decisions,
            },
        )
        conn.commit()
        batch["confirmed"] = True

        # Automatically re-run R1-R8 anomaly scan on ALL affected periods (both inserted & updated records!)
        anomaly_scan_summary: Optional[Dict[str, Any]] = None
        if data_type in ("attendance", "leave_requests") and affected_periods:
            agg_inserted = 0
            agg_updated = 0
            agg_by_rule: Dict[str, int] = {}
            sorted_periods = sorted(affected_periods)
            for p in sorted_periods:
                scan_res = run_anomaly_scan(conn, period=p)
                agg_inserted += scan_res["inserted"]
                agg_updated += scan_res["updated"]
                for rule_k, cnt in scan_res["by_rule"].items():
                    agg_by_rule[rule_k] = agg_by_rule.get(rule_k, 0) + cnt
            anomaly_scan_summary = {
                "periods": sorted_periods,
                "inserted": agg_inserted,
                "updated": agg_updated,
                "by_rule": agg_by_rule,
            }

        result_payload = {
            "status": "completed",
            "batch_id": batch_id,
            "data_type": data_type,
            "duplicate_policy": duplicate_policy,
            "duplicate_decisions": applied_decisions,
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "rejected_future": rejected_future,
            "errors": len(batch["error_rows"]),
            "rejected_total": rejected_future + len(batch["error_rows"]),
            "allow_future_dates": allow_future_dates,
            "confirmed_at": action_timestamp,
            "updated_records": updated_records,
            "anomaly_scan": anomaly_scan_summary,
        }
        conn.execute(
            "UPDATE import_logs SET result_json = ? WHERE id = ?",
            (json.dumps(result_payload, ensure_ascii=False), batch["log_id"]),
        )
        conn.commit()
        return result_payload
    except Exception as exc:
        conn.rollback()
        fail_payload = {
            "status": "failed",
            "error": str(exc),
            "failed_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        conn.execute(
            "UPDATE import_logs SET status = 'failed', result_json = ? WHERE id = ?",
            (json.dumps(fail_payload, ensure_ascii=False), batch["log_id"]),
        )
        conn.commit()
        raise
