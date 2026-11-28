from __future__ import annotations

import argparse
import json
import os
import pathlib
import tempfile
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

from app.db.connection import get_connection
from app.db.seed import seed_database
from app.services.anomaly_service import run_anomaly_scan


class SupabaseRestMigrator:
    def __init__(self, supabase_url: str, secret_key: str) -> None:
        self.base_url = supabase_url.rstrip("/") + "/rest/v1"
        self.headers = {
            "apikey": secret_key,
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
        }
        self.client = httpx.Client(timeout=60.0)

    def close(self) -> None:
        self.client.close()

    def _raise_if_failed(self, resp: httpx.Response, label: str) -> None:
        if resp.status_code >= 400:
            raise RuntimeError(f"Supabase error on {label}: HTTP {resp.status_code} - {resp.text[:500]}")

    def get_all(self, table: str, select: str = "*") -> List[Dict[str, Any]]:
        r = self.client.get(f"{self.base_url}/{table}", params={"select": select}, headers=self.headers)
        self._raise_if_failed(r, f"GET {table}")
        return r.json()

    def count(self, table: str) -> int:
        hdrs = {**self.headers, "Prefer": "count=exact"}
        r = self.client.get(f"{self.base_url}/{table}", params={"select": "*", "limit": "1"}, headers=hdrs)
        self._raise_if_failed(r, f"COUNT {table}")
        cr = r.headers.get("content-range", "*/0")
        return int(cr.split("/")[-1])

    def upsert_batches(
        self,
        table: str,
        rows: List[Dict[str, Any]],
        on_conflict: str,
        batch_size: int = 500,
        return_rows: bool = False,
    ) -> List[Dict[str, Any]]:
        if not rows:
            return []
        prefer = "resolution=merge-duplicates,return=representation" if return_rows else "resolution=merge-duplicates,return=minimal"
        hdrs = {**self.headers, "Prefer": prefer}
        collected: List[Dict[str, Any]] = []
        for i in range(0, len(rows), batch_size):
            chunk = rows[i : i + batch_size]
            r = self.client.post(
                f"{self.base_url}/{table}",
                params={"on_conflict": on_conflict},
                headers=hdrs,
                json=chunk,
            )
            self._raise_if_failed(r, f"UPSERT {table} [{i}:{i + len(chunk)}]")
            if return_rows:
                collected.extend(r.json())
        return collected

    def insert_rows(
        self,
        table: str,
        rows: List[Dict[str, Any]],
        batch_size: int = 200,
        return_rows: bool = False,
    ) -> List[Dict[str, Any]]:
        if not rows:
            return []
        prefer = "return=representation" if return_rows else "return=minimal"
        hdrs = {**self.headers, "Prefer": prefer}
        collected: List[Dict[str, Any]] = []
        for i in range(0, len(rows), batch_size):
            chunk = rows[i : i + batch_size]
            r = self.client.post(f"{self.base_url}/{table}", headers=hdrs, json=chunk)
            self._raise_if_failed(r, f"INSERT {table} [{i}:{i + len(chunk)}]")
            if return_rows:
                collected.extend(r.json())
        return collected

    def patch_eq(self, table: str, key_col: str, key_val: str, payload: Dict[str, Any]) -> None:
        hdrs = {**self.headers, "Prefer": "return=minimal"}
        r = self.client.patch(
            f"{self.base_url}/{table}",
            params={key_col: f"eq.{key_val}"},
            headers=hdrs,
            json=payload,
        )
        self._raise_if_failed(r, f"PATCH {table} ({key_col}={key_val})")


def migrate_sqlite_to_supabase(
    supabase_url: str,
    secret_key: str,
    sqlite_path: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    tmp_ctx = None
    if sqlite_path is None:
        tmp_ctx = tempfile.TemporaryDirectory()
        sqlite_path = pathlib.Path(tmp_ctx.name) / "clean_seed.db"
        seed_database(db_path=sqlite_path, reset=True)
        scan_conn = get_connection(sqlite_path, readonly=False)
        try:
            run_anomaly_scan(scan_conn)
        finally:
            scan_conn.close()

    conn = get_connection(sqlite_path, readonly=True)
    sb = SupabaseRestMigrator(supabase_url, secret_key)
    try:
        # 1. Departments
        depts = [dict(r) for r in conn.execute("SELECT department_id, name FROM departments").fetchall()]
        sb.upsert_batches("departments", depts, on_conflict="department_id")

        # 2. Positions (normalized master table derived from employees.position)
        emp_rows = [dict(r) for r in conn.execute("SELECT * FROM employees").fetchall()]
        unique_positions = sorted({e["position"] for e in emp_rows if e.get("position")})
        sb.upsert_batches("positions", [{"name": p} for p in unique_positions], on_conflict="name")
        pos_map = {p["name"]: p["position_id"] for p in sb.get_all("positions", "position_id,name")}

        # 3. Employees (2-pass upsert so self-referencing manager_id FK always succeeds)
        emp_pass1 = [
            {
                "employee_id": e["employee_id"],
                "full_name": e["full_name"],
                "department_id": e["department_id"],
                "position": e["position"],
                "position_id": pos_map.get(e["position"]),
                "manager_id": None,
                "start_date": e["start_date"],
                "annual_leave_balance": float(e["annual_leave_balance"]),
                "role": e["role"],
                "employment_status": e["employment_status"],
                "email": e["email"],
                "phone": e["phone"],
            }
            for e in emp_rows
        ]
        sb.upsert_batches("employees", emp_pass1, on_conflict="employee_id")

        # Pass 2: link manager_id cleanly
        emp_pass2 = [
            {
                **row,
                "manager_id": next((e["manager_id"] for e in emp_rows if e["employee_id"] == row["employee_id"]), None),
            }
            for row in emp_pass1
        ]
        sb.upsert_batches("employees", emp_pass2, on_conflict="employee_id")

        # 4. Users
        user_rows = [
            {
                "user_id": u["user_id"],
                "username": u["username"],
                "password_hash": u["password_hash"],
                "employee_id": u["employee_id"],
                "is_active": int(u["is_active"]),
                "last_login_at": u["last_login_at"],
                "must_change_password": int(u["must_change_password"]),
            }
            for u in conn.execute("SELECT * FROM users").fetchall()
        ]
        sb.upsert_batches("users", user_rows, on_conflict="user_id")

        # 5. User Roles (link each user to roles table based on employees.role)
        role_map = {r["role_code"]: r["role_id"] for r in sb.get_all("roles", "role_id,role_code")}
        emp_role_by_id = {e["employee_id"]: e["role"] for e in emp_rows}
        user_role_rows = [
            {
                "user_id": u["user_id"],
                "role_id": role_map[emp_role_by_id[u["employee_id"]]],
            }
            for u in user_rows
            if emp_role_by_id.get(u["employee_id"]) in role_map
        ]
        sb.upsert_batches("user_roles", user_role_rows, on_conflict="user_id,role_id")

        # 6. Holidays
        holidays = [dict(r) for r in conn.execute("SELECT holiday_date, name FROM holidays").fetchall()]
        sb.upsert_batches("holidays", holidays, on_conflict="holiday_date")

        # 7. Attendance (batch size 500)
        att_rows = [
            {
                "employee_id": a["employee_id"],
                "work_date": a["work_date"],
                "check_in": a["check_in"],
                "check_out": a["check_out"],
                "status": a["status"],
                "source": a["source"],
            }
            for a in conn.execute("SELECT employee_id, work_date, check_in, check_out, status, source FROM attendance").fetchall()
        ]
        sb.upsert_batches("attendance", att_rows, on_conflict="employee_id,work_date", batch_size=500)

        # 8. Overtime requests
        ot_rows = [
            {
                "employee_id": o["employee_id"],
                "work_date": o["work_date"],
                "status": o["status"],
                "approved_by": o["approved_by"],
            }
            for o in conn.execute("SELECT employee_id, work_date, status, approved_by FROM overtime_requests").fetchall()
        ]
        sb.upsert_batches("overtime_requests", ot_rows, on_conflict="employee_id,work_date")

        # 9. Leave requests & approval logs (preserve PG identity sequence by omitting explicit request_id)
        existing_leave_count = sb.count("leave_requests")
        if existing_leave_count == 0:
            lr_src = [dict(r) for r in conn.execute("SELECT * FROM leave_requests ORDER BY request_id ASC").fetchall()]
            id_map: Dict[int, int] = {}
            lr_payloads = [
                {
                    "employee_id": lr["employee_id"],
                    "leave_type": lr["leave_type"],
                    "from_date": lr["from_date"],
                    "to_date": lr["to_date"],
                    "reason": lr["reason"],
                    "status": lr["status"],
                    "reviewed_by": lr["reviewed_by"],
                    "reviewed_at": lr["reviewed_at"],
                    "decision_note": lr["decision_note"],
                    "cancelled_at": lr["cancelled_at"],
                }
                for lr in lr_src
            ]
            inserted_leaves = sb.insert_rows("leave_requests", lr_payloads, return_rows=True)
            for src_lr, pg_lr in zip(lr_src, inserted_leaves):
                id_map[int(src_lr["request_id"])] = int(pg_lr["request_id"])

            log_src = [dict(r) for r in conn.execute("SELECT * FROM leave_approval_logs ORDER BY id ASC").fetchall()]
            log_payloads = [
                {
                    "request_id": id_map[int(lg["request_id"])],
                    "actor_user_id": lg["actor_user_id"],
                    "action": lg["action"],
                    "note": lg["note"],
                }
                for lg in log_src
                if int(lg["request_id"]) in id_map
            ]
            sb.insert_rows("leave_approval_logs", log_payloads)

        # 10. Anomalies (parse evidence JSON string -> JSONB object)
        anom_rows = []
        for an in conn.execute("SELECT * FROM anomalies").fetchall():
            ev = an["evidence"]
            if isinstance(ev, str):
                try:
                    ev = json.loads(ev)
                except Exception:
                    ev = {"raw": ev}
            anom_rows.append(
                {
                    "employee_id": an["employee_id"],
                    "department_id": an["department_id"],
                    "scope_type": an["scope_type"],
                    "rule_code": an["rule_code"],
                    "anomaly_type": an["anomaly_type"],
                    "severity": an["severity"],
                    "period": an["period"],
                    "evidence": ev,
                    "explanation": an["explanation"],
                    "review_status": an["review_status"],
                    "reviewed_by": an["reviewed_by"],
                    "reviewed_at": an["reviewed_at"],
                    "review_note": an["review_note"],
                    "dedup_key": an["dedup_key"],
                }
            )
        sb.upsert_batches("anomalies", anom_rows, on_conflict="dedup_key")

        # Verify live counts on Supabase (tables + reporting views)
        tables_to_verify = [
            "departments",
            "positions",
            "employees",
            "users",
            "user_roles",
            "holidays",
            "attendance",
            "overtime_requests",
            "leave_requests",
            "leave_approval_logs",
            "anomalies",
            "v_employees",
            "v_attendance_daily",
            "v_leave_requests",
            "v_anomalies",
        ]
        summary = {tbl: sb.count(tbl) for tbl in tables_to_verify}
        return summary
    finally:
        conn.close()
        sb.close()
        if tmp_ctx is not None:
            tmp_ctx.cleanup()


def main() -> None:
    load_dotenv(pathlib.Path(__file__).resolve().parents[2] / ".env")
    parser = argparse.ArgumentParser(description="Migrate HR Attendance Copilot clean seed/SQLite data to Supabase.")
    parser.add_argument("--sqlite-path", type=str, default=None, help="Optional path to existing SQLite .db file (default: fresh clean seed)")
    args = parser.parse_args()

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not url or not key:
        raise SystemExit("Thiếu SUPABASE_URL hoặc SUPABASE_SECRET_KEY trong backend/.env")

    path = pathlib.Path(args.sqlite_path).resolve() if args.sqlite_path else None
    summary = migrate_sqlite_to_supabase(url, key, sqlite_path=path)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
