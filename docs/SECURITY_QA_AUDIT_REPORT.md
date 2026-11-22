# Báo cáo Rà soát Bảo mật & Nghiệm thu QA (Prompt 9)

- **Dự án**: HR Attendance Copilot
- **Ngày rà soát**: `21/11/2026`
- **Phạm vi**: Toàn bộ mã nguồn Backend (`backend/app/`, `backend/sql/`, `backend/tests/`), Frontend (`frontend/src/`, `frontend/dist/`), cấu hình môi trường (`.gitignore`, `.env.example`) và tài liệu bàn giao (`README.md`, `docs/`).

---

## 1. Bảng phân loại lỗ hổng phát hiện & Trạng thái khắc phục

| Mã | Mức độ | Vị trí | Mô tả phát hiện trong đợt rà soát | Hành động khắc phục & Kiểm chứng | Trạng thái |
|---|---|---|---|---|---|
| **SEC-01** | **Critical** | `backend/app/services/sql_guard.py` | Truy vấn dùng định danh bọc ngoặc (`"employees"`, `` `employees` ``, `[attendance]`) hoặc comma-join (`FROM v_employees, employees`) có thể lách regex `FROM/JOIN` để đọc trực tiếp bảng gốc, vượt qua `TEMP VIEW` phân quyền RBAC và lộ PII (`email`, `phone`). Ngoài ra, `LIMIT` bên trong subquery khiến câu lệnh không bị gắn `LIMIT 200` ở lớp ngoài cùng. | Chặn hoàn toàn ký tự `"`, `` ` ``, `[`, `]`; chặn cú pháp comma-join trong `FROM`; đưa toàn bộ tên bảng gốc (`employees`, `attendance`, `leave_requests`, `anomalies`, `departments`, `holidays`, `overtime_requests`, `temp`) và cột `email`/`phone` vào `FORBIDDEN_IDENTIFIERS`; bắt buộc kiểm tra `LIMIT` ở cuối truy vấn ngoài cùng. Kiểm chứng bởi `test_sec01_sql_guard_blocks_advanced_bypass_vectors` (13 vector bypass mới + 17 payload cũ = **30/30 bị chặn**). | **ĐÃ SỬA & PASS** |
| **SEC-02** | **High** | `backend/app/services/import_service.py` | Hàm `has_formula_injection()` chỉ kiểm tra ký tự đầu `=`, `+`, `@`, bỏ sót payload Excel Formula Injection bắt đầu bằng dấu `-` (ví dụ `-1+1+cmd|' /C calc'!A0`) hoặc ký tự điều khiển `\t`, `\r`, `\n`. | Mở rộng `has_formula_injection()` xử lý strip ` \t\r\n` và chặn mọi chuỗi bắt đầu bằng `-` không phải số âm thuần (`-\d+(?:\.\d+)?`). Kiểm chứng bởi `test_sec02_formula_injection_blocks_leading_minus_and_control_chars`. | **ĐÃ SỬA & PASS** |
| **SEC-03** | **High** | `backend/app/core/config.py`, `backend/app/main.py`, `backend/app/db/seed.py` | Ứng dụng có thể khởi động ở `APP_ENV=production` với `JWT_SECRET_KEY` mặc định của môi trường dev hoặc ngắn hơn 32 ký tự; script `seed.py` chưa có chốt chặn nếu vô tình chạy trong production. | Thêm `settings.validate_runtime_security()` gọi trong `create_app()` (ném `RuntimeError` nếu `APP_ENV=production` dùng khóa mặc định/ngắn `< 32` ký tự); thêm chốt chặn `APP_ENV=production` trong `seed_database()`. Kiểm chứng bởi `test_sec03_production_runtime_rejects_default_or_short_jwt_secret`. | **ĐÃ SỬA & PASS** |
| **SEC-04** | **High** | `backend/app/api/anomalies.py`, `backend/app/services/anomaly_service.py` | Khi Manager gọi `POST /api/anomalies/scan`, API trả về `total_detected` và `by_rule` của **toàn công ty**, làm rò rỉ metadata bất thường của các phòng ban khác. | Thêm tham số `department_id` cho `run_anomaly_scan()`: khi Manager gọi scan, hệ thống chỉ quét, cập nhật và trả thống kê đúng trong phòng ban của Manager đó. Kiểm chứng bởi `test_sec04_manager_anomaly_scan_does_not_leak_other_departments`. | **ĐÃ SỬA & PASS** |
| **SEC-05** | **Medium** | `backend/app/api/admin.py` | Truy vấn `open_anomalies` và `top_alerts` trên Dashboard chỉ dựa ngầm vào `employee_id = ?` (loại `NULL` của `R5`), thiếu điều kiện tường minh `scope_type = 'employee'` cho Employee. | Bổ sung tường minh `scope_type = 'employee' AND employee_id = ?` cho Employee trên `/api/dashboard/summary`. Kiểm chứng bởi `test_sec05_sec07_security_headers_and_strict_scope_isolation`. | **ĐÃ SỬA & PASS** |
| **SEC-06** | **Medium** | `frontend/src/pages/LoginPage.tsx` | Chuỗi mật khẩu dev `'Demo@123'` nằm trực tiếp trong mã nguồn `LoginPage.tsx` (dù bị Vite loại khi build prod). | Gỡ bỏ hoàn toàn chuỗi mật khẩu khỏi `LoginPage.tsx`; nút demo nhanh ở `DEV` chỉ đọc `import.meta.env.VITE_DEV_DEMO_PASSWORD` (nếu dev tự cấu hình local), nếu không thì chỉ điền sẵn username và focus vào ô mật khẩu. | **ĐÃ SỬA & PASS** |
| **SEC-07** | **Medium** | `backend/app/main.py` | CORS dùng `allow_methods=["*"]`, `allow_headers=["*"]` kết hợp `allow_credentials=True`; thiếu các HTTP security headers. | Siết CORS về đúng method (`GET, POST, PATCH, DELETE, OPTIONS`) và header (`Authorization, Content-Type`); bổ sung middleware gắn `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Cache-Control: no-store` cho mọi đường dẫn `/api/`. Kiểm chứng bởi `test_sec05_sec07_security_headers_and_strict_scope_isolation`. | **ĐÃ SỬA & PASS** |
| **SEC-08** | **Medium** | `backend/app/services/import_service.py`, `backend/app/api/operations.py` | Phiên import tạm (`batch_id`) không kiểm tra chủ sở hữu (`uploaded_by`), cho phép một HR khác tải file lỗi hoặc xác nhận nhầm batch đang staging của người khác. | Tăng độ dài ngẫu nhiên `batch_id` (16 ký tự hex) và kiểm tra `batch["uploaded_by"] == actor_user_id` (trả `403` nếu khác chủ sở hữu). Kiểm chứng bởi `test_sec08_import_batch_ownership_enforced`. | **ĐÃ SỬA & PASS** |
| **SEC-09** | **Medium** | `backend/app/services/ai_assistant.py` | Khi Manager hỏi về mã NV ngoài phòng, phản hồi cho mã tồn tại khác với mã không tồn tại (existence oracle); thiếu từ khóa `"phòng khác"` trong bộ lọc phạm vi Manager. | Thống nhất câu từ chối trung lập cho mọi mã NV không thuộc phòng Manager quản lý và bổ sung chặn `"phòng khác"`. Kiểm chứng bởi `test_sec09_manager_ai_no_employee_existence_oracle`. | **ĐÃ SỬA & PASS** |
| **SEC-10** | **Low** | `backend/app/core/security.py`, `backend/app/services/import_service.py` | `REVOKED_JTIS` và `STAGING_BATCHES` lưu trong RAM của tiến trình FastAPI (phù hợp MVP đơn tiến trình, nhưng sẽ mất khi restart hoặc không chia sẻ được giữa nhiều worker). | Ghi nhận rõ trong mục Giới hạn của `README.md` để nâng cấp sang Redis/PostgreSQL trước khi triển khai production đa worker. | **ĐÃ GHI NHẬN (MVP)** |

---

## 2. Kết quả kiểm tra 10 hạng mục nghiệm thu (Prompt 9 Checklist)

| # | Hạng mục kiểm tra | Trạng thái | Bằng chứng kiểm chứng |
|---|---|---|---|
| 1 | SQL Injection, Text-to-SQL bypass, Prompt Injection | **PASS** | `test_ai_and_sql_guard.py` (17 payload) + `test_security_review.py` (13 bypass vector nâng cao) = **30/30 bị chặn**; prompt injection bị chặn và ghi `query_audit_log`. |
| 2 | Rò rỉ giữa `employee` / `manager` / `hr` (API, export, chat history, charts, logs, download) | **PASS** | `test_auth_rbac.py`, `test_reports.py`, `test_anomalies.py`, `test_security_review.py` xác nhận cô lập hoàn toàn theo vai trò, phòng ban, user chat history và import batch ownership. |
| 3 | Quyền bị thay đổi bằng request client hoặc URL | **PASS** | `PATCH /api/profile` (`extra="forbid"`) trả `422` khi chèn `"role": "hr"`; `get_current_user` tải lại vai trò & trạng thái khóa từ DB ở mỗi request; `AppShell.test.tsx` xác nhận `403 RouteGuard`. |
| 4 | Password/secrets, API key, upload, formula injection | **PASS** | Mật khẩu băm `bcrypt`, zero password plaintext trong `activity_logs` và `frontend/src`, `.env` & `*.db` trong `.gitignore`, upload giới hạn `5 MB` + `.csv/.xlsx`, chặn đầy đủ `=`, `+`, `-`, `@`, `\t`, `\r`. |
| 5 | LLM tự tính số hoặc bịa số không có trong nguồn | **PASS** | 100% KPI & bảng tính bằng SQL; `verify_narrative_numbers()` quét từng con số trong nhận xét báo cáo và tự fallback về mẫu chuẩn SQL nếu phát hiện số lạ (`test_reports.py`). |
| 6 | Audit đầy đủ cho leave approve/reject & anomaly review | **PASS** | Mọi thao tác nghỉ phép ghi cả `leave_approval_logs` và `activity_logs`; mọi thao tác duyệt bất thường, import, sửa nhân viên/tài khoản, xuất báo cáo đều ghi `activity_logs` trước/sau JSON. |
| 7 | Empty/loading/error states & transaction rollback | **PASS** | Toàn bộ 10 màn hình sử dụng `LoadingSkeleton`, `EmptyState`, `ErrorState` (kèm nút Thử lại) và `ConfirmModal`; rollback giao dịch import được kiểm chứng bằng `force_fail_for_test=True` trong `test_operations_import.py`. |
| 8 | Mọi button/action đều nối API thật | **PASS** | Đã xóa `DevAuthContext.tsx` và `ScreenPlaceholders.tsx`; quét toàn bộ `frontend/src` không còn TODO/FIXME/mock page hay từ ngữ quy chụp. |
| 9 | Test `R1–R8`, seed `S1–S7`, 24 câu hỏi AI, 15+ SQL độc hại | **PASS** | Đủ 8/8 rule `R1–R8`, 7/7 kịch bản `S1–S7` (+ `R3`), **24/24 câu hỏi AI (100%)**, **30/30 SQL độc hại bị chặn**. |
| 10 | Tài liệu `README.md` & bàn giao | **PASS** | Hoàn thiện `README.md` và `docs/HANDOVER_AND_DEMO_GUIDE.md` khớp 100% với mã nguồn thực tế. |

---

## 3. Lệnh kiểm chứng thực tế & Kết quả cuối cùng

1. **Backend Test Suite**:
   - Lệnh: `cd backend && python -m pytest -v`
   - Kết quả: **`30 passed, 2 warnings in 18.04s`** (Exit code `0` — 0 lỗi; 2 deprecation warning đến từ thư viện bên thứ ba `anyio`/`starlette.testclient`).
   - Kiểm chứng lệnh seed & scan trong `README.md`: `departments=5, employees=80, users=80, attendance=10483, leave_requests=20`, `total_detected=11` phủ đủ `R1–R8` (`R1:3, R2:1, R3:1, R4:1, R5:1, R6:2, R7:1, R8:1`).
2. **Frontend Unit Test**:
   - Lệnh: `cd frontend && npm test`
   - Kết quả: **`5 passed (1 test file) in 4.49s`** (Exit code `0`).
3. **Frontend TypeScript Check & Production Build**:
   - Lệnh: `cd frontend && npm run build` (`tsc -b && vite build`)
   - Kết quả: **`✓ built in 7.17s` (`2193 modules transformed`, 0 lỗi TypeScript)** (Exit code `0`).
4. **Kiểm tra không lộ mật khẩu demo trong mã nguồn & bản build Frontend**:
   - Đã loại bỏ chuỗi `'Demo@123'` khỏi `frontend/src/pages/LoginPage.tsx` và xác nhận bản build `frontend/dist/assets/*.js` không chứa chuỗi này.
