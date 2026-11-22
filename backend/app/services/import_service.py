from __future__ import annotations

import csv
import datetime
import io
import re
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Tuple
import openpyxl

from app.core.security import write_activity_log

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXTENSIONS = {".csv", ".xlsx"}
DANGEROUS_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t=", "\r=")

# In-memory staging store for preview -> confirm workflow
STAGING_BATCHES: Dict[str, Dict[str, Any]] = {}

REQUIRED_COLUMNS: Dict[str, List[str]] = {
    "employees": ["employee_id", "full_name", "department_id", "position", "start_date", "role"],
    "attendance": ["employee_id", "work_date", "check_in", "check_out", "status"],
    "leave_requests": ["employee_id", "leave_type", "from_date", "to_date", "reason", "status"],
}


def sanitize_cell_for_export(value: Any) -> Any:
    """Prevent CSV/Excel formula injection (DDE/CSV Injection) on exported text cells."""
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped and stripped[0] in ("=", "+", "-", "@"):
        return "'" + value
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
        wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
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


def stage_and_validate_import(
    conn: sqlite3.Connection,
    actor_user_id: str,
    file_name: str,
    data_type: str,
    raw_bytes: bytes,
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

    existing_depts = {r[0] for r in conn.execute("SELECT department_id FROM departments").fetchall()}
    existing_emps = {r[0] for r in conn.execute("SELECT employee_id FROM employees").fetchall()}
    existing_att = {
        (r[0], r[1]) for r in conn.execute("SELECT employee_id, work_date FROM attendance").fetchall()
    }
    existing_leaves = {
        (r[0], r[1], r[2])
        for r in conn.execute("SELECT employee_id, from_date, to_date FROM leave_requests").fetchall()
    }

    valid_rows: List[Dict[str, Any]] = []
    duplicate_rows: List[Dict[str, Any]] = []
    error_rows: List[Dict[str, Any]] = []
    seen_keys: set[Any] = set()

    for idx, raw in enumerate(rows, start=2):  # Row 1 is header
        # Reject formula injection in any string cell
        injected_cols = [k for k, v in raw.items() if has_formula_injection(v)]
        if injected_cols:
            error_rows.append(
                {
                    "row_number": idx,
                    "error": f"Phát hiện ký tự công thức nguy hiểm ở cột: {', '.join(injected_cols)}",
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
                error_rows.append({"row_number": idx, "error": "; ".join(errs), "raw": raw})
                continue

            normalized = {
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
            }
            if emp_id in existing_emps or emp_id in seen_keys:
                duplicate_rows.append({"row_number": idx, "reason": f"Trùng employee_id {emp_id}", "data": normalized})
            else:
                seen_keys.add(emp_id)
                valid_rows.append(normalized)

        elif data_type == "attendance":
            emp_id = str(raw.get("employee_id") or "").strip().upper()
            work_date = str(raw.get("work_date") or "").strip()[:10]
            status_val = str(raw.get("status") or "present").strip().lower()
            source = str(raw.get("source") or "import_file").strip() or "import_file"

            errs = []
            if emp_id not in existing_emps:
                errs.append(f"Mã nhân viên không tồn tại: {emp_id}")
            if _parse_date(work_date) is None:
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
                error_rows.append({"row_number": idx, "error": "; ".join(errs), "raw": raw})
                continue

            key = (emp_id, work_date)
            normalized = {
                "employee_id": emp_id,
                "work_date": work_date,
                "check_in": check_in_norm,
                "check_out": check_out_norm,
                "status": status_val,
                "source": source,
            }
            if key in existing_att or key in seen_keys:
                duplicate_rows.append(
                    {"row_number": idx, "reason": f"Trùng bản ghi chấm công ({emp_id}, {work_date})", "data": normalized}
                )
            else:
                seen_keys.add(key)
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
                error_rows.append({"row_number": idx, "error": "; ".join(errs), "raw": raw})
                continue

            key = (emp_id, from_date, to_date)
            normalized = {
                "employee_id": emp_id,
                "leave_type": leave_type,
                "from_date": from_date,
                "to_date": to_date,
                "reason": reason,
                "status": status_val,
            }
            if key in existing_leaves or key in seen_keys:
                duplicate_rows.append(
                    {"row_number": idx, "reason": f"Trùng đơn nghỉ phép ({emp_id}, {from_date}..{to_date})", "data": normalized}
                )
            else:
                seen_keys.add(key)
                valid_rows.append(normalized)

    batch_id = f"IMP-{uuid.uuid4().hex[:16].upper()}"
    cur = conn.execute(
        """
        INSERT INTO import_logs (
            file_name, data_type, uploaded_by, rows_total, rows_valid, rows_error, rows_duplicate, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'preview')
        """,
        (file_name, data_type, actor_user_id, len(rows), len(valid_rows), len(error_rows), len(duplicate_rows)),
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
        "confirmed": False,
    }

    return {
        "batch_id": batch_id,
        "file_name": file_name,
        "data_type": data_type,
        "summary": {
            "rows_total": len(rows),
            "rows_valid": len(valid_rows),
            "rows_error": len(error_rows),
            "rows_duplicate": len(duplicate_rows),
        },
        "preview_rows": valid_rows[:50],
        "duplicate_rows": duplicate_rows[:50],
        "error_rows": error_rows[:50],
    }


def export_batch_errors_csv(batch_id: str, actor_user_id: Optional[str] = None) -> str:
    batch = STAGING_BATCHES.get(batch_id)
    if not batch:
        raise KeyError("Không tìm thấy phiên import.")
    if actor_user_id and batch["uploaded_by"] != actor_user_id:
        raise PermissionError("Bạn không có quyền tải tệp lỗi của phiên import do tài khoản khác tạo.")
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["row_number", "error", "raw_data"])
    for err in batch["error_rows"]:
        writer.writerow(
            [
                err["row_number"],
                sanitize_cell_for_export(err["error"]),
                sanitize_cell_for_export(str(err["raw"])),
            ]
        )
    return out.getvalue()


def confirm_staged_import(
    conn: sqlite3.Connection,
    batch_id: str,
    actor_user_id: str,
    duplicate_policy: str = "skip",
    force_fail_for_test: bool = False,
) -> Dict[str, Any]:
    batch = STAGING_BATCHES.get(batch_id)
    if not batch:
        raise KeyError("Không tìm thấy phiên import hoặc phiên đã hết hạn.")
    if batch["uploaded_by"] != actor_user_id:
        raise PermissionError("Bạn không có quyền xác nhận phiên import do tài khoản khác tạo.")
    if batch["confirmed"]:
        raise ValueError("Phiên import này đã được xác nhận trước đó.")

    data_type = batch["data_type"]
    inserted = 0
    updated = 0
    skipped = len(batch["duplicate_rows"]) if duplicate_policy == "skip" else 0

    try:
        conn.execute("BEGIN")
        if data_type == "employees":
            for row in batch["valid_rows"]:
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
                inserted += 1
            if duplicate_policy == "update":
                for dup in batch["duplicate_rows"]:
                    row = dup["data"]
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
                    updated += 1

        elif data_type == "attendance":
            for row in batch["valid_rows"]:
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
                inserted += 1
            if duplicate_policy == "update":
                for dup in batch["duplicate_rows"]:
                    row = dup["data"]
                    conn.execute(
                        """
                        UPDATE attendance
                        SET check_in = ?, check_out = ?, status = ?, source = ?
                        WHERE employee_id = ? AND work_date = ?
                        """,
                        (
                            row["check_in"],
                            row["check_out"],
                            row["status"],
                            row["source"],
                            row["employee_id"],
                            row["work_date"],
                        ),
                    )
                    updated += 1

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
            if duplicate_policy == "update":
                skipped = len(batch["duplicate_rows"])  # Leave requests are never blindly overwritten

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
                "errors": len(batch["error_rows"]),
            },
        )
        conn.commit()
        batch["confirmed"] = True
        return {
            "status": "completed",
            "batch_id": batch_id,
            "data_type": data_type,
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "errors": len(batch["error_rows"]),
        }
    except Exception:
        conn.rollback()
        conn.execute("UPDATE import_logs SET status = 'failed' WHERE id = ?", (batch["log_id"],))
        conn.commit()
        raise
