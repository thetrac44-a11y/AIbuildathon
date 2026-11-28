# Báo cáo Kiểm toán Kỹ thuật, Sửa lỗi & Đánh giá Chất lượng (Technical Audit Report)

- **Dự án**: HR Attendance Copilot
- **Ngày kiểm toán**: `28/11/2026`
- **Phạm vi**: Rà soát toàn diện mã nguồn Backend (FastAPI + Python 3.12), Database (SQLite cục bộ + Supabase PostgreSQL thực tế), AI SQL Assistant & SQL Guard, Frontend (React 18 + TypeScript + Vite + Tailwind), và đồng bộ tài liệu.
- **Nguyên tắc thực hiện**: Chỉ kiểm toán, xác minh và khắc phục lỗi trên chức năng hiện hữu — **không phát triển tính năng mới (không xây thêm RAG retrieval hoặc InsightFace/camera)**, không thiết kế lại UI, không xóa dữ liệu CSDL, không giả lập kết quả test.

---

## 1. Executive Summary

Đợt rà soát kỹ thuật trực tiếp trên mã nguồn đã phát hiện và khắc phục **13 vấn đề thực tế** (1 Critical, 6 High, 3 Medium, 3 Low) trải rộng từ lỗ hổng phân quyền RBAC (`list_employees` scope leak, stale `user_roles` union, mất hiệu lực thu hồi quyền rỗng), lưu trữ JWT revocation chỉ trên RAM, thiếu RLS trên bảng `system_settings` ở PostgreSQL, race condition khi khóa Admin/HR cuối cùng hoặc duyệt trùng đơn phép, thiếu kiểm tra dữ liệu đầu vào khi điều chỉnh chấm công, sai lệch câu hỏi AI theo ngày `"hôm nay"` và câu hỏi đếm `"bao nhiêu người đi muộn"`, cho đến bundle Frontend đơn khối `822.92 kB` và nhãn vai trò còn thiếu.

Sau khi áp dụng sửa lỗi và chạy kiểm chứng thực tế:
- **Backend (`pytest`)**: **60/60 PASS** (`0 failed`, `0 skipped`).
- **Frontend (`vitest` + `tsc -b && vite build`)**: **21/21 PASS**, build production **0 lỗi TypeScript**, **0 cảnh báo chunk > 500 kB** (chunk chính giảm từ `822.92 kB` xuống `42.89 kB`).
- **Live Supabase PostgreSQL**: Migration không phá hủy thành công; xác minh trực tiếp **27/27 bảng `public` bật RLS**, **4/4 view bật `security_invoker=true`**, toàn bộ 5 vai trò và thu hồi JWT bền vững qua bảng `revoked_tokens` hoạt động chính xác.
- **Tính trung thực phạm vi**: Các hạng mục **RAG Policy Retrieval** và **Face Recognition Check-in** hiện chỉ mới ở mức hạ tầng quản trị/schema (`PARTIAL`), chưa được nối vào luồng trả lời AI hay camera nhận diện thực tế, và được phân loại minh bạch trong báo cáo này.

---

## 2. Existing Features

| Phân hệ / Chức năng | Trạng thái | Ghi chú kiểm chứng thực tế |
|---|---|---|
| Xác thực JWT, bcrypt, đổi mật khẩu, persistent logout (`revoked_tokens`) | **PASS** | Đã kiểm chứng trên SQLite & live Supabase PostgreSQL; token sau logout vẫn bị chặn `401` khi xóa RAM cache `REVOKED_JTIS`. |
| Phân quyền RBAC 5 vai trò (`employee`, `manager`, `hr`, `executive`, `admin`) & 44 permissions | **PASS** | Tách bạch Admin (kỹ thuật) và HR (nghiệp vụ); đã vá lỗi `list_employees()`, `load_user_permissions()`, `sync_user_role_mapping()`, bảo vệ Admin/HR cuối cùng có khóa giao dịch. |
| Dashboard tổng quan & Phân tích phòng ban (`/dashboard`, `/executive/departments`) | **PASS** | Khớp 100% số liệu với `/api/reports/preview` và `/api/anomalies`; chặn Admin `403`. |
| Chấm công & Điều chỉnh chấm công HR (`GET/PATCH /api/attendance`) | **PASS** | Đã bổ sung kiểm tra chặt định dạng `YYYY-MM-DD HH:MM:SS`, `check_out >= check_in`, khớp `work_date`, cấm giờ công khi `absent/on_leave/holiday`, ghi đầy đủ `activity_logs`. |
| Quản lý đơn nghỉ phép (`GET/POST /api/leaves`, `cancel`, `review` + Executive approval) | **PASS** | Đã khóa giao dịch nguyên tử + kiểm tra `WHERE status = 'pending'` (`rowcount == 1`) chống duyệt trùng / trùng ngày đồng thời; chặn tự duyệt tuyệt đối. |
| Cảnh báo bất thường 8 quy tắc `R1–R8` (`backend/sql/` & `backend/sql_postgres/`) | **PASS** | Đủ 8/8 file SQL parity giữa SQLite và PostgreSQL; giữ nguyên trạng thái duyệt người dùng khi rescan; cô lập phạm vi phòng ban cho Manager. |
| Import Excel / CSV 5 bước (`template`, `preview`, `errors`, `confirm`, `logs`) | **PASS** | Staging lưu bền vững trong `import_logs.detail_json` (phục hồi qua `_hydrate_batch_from_db()` sau restart), chống Formula Injection, rollback nguyên tử, khóa HR ghi đè `admin`/`executive` và ẩn `batch_id` preview của HR khác. |
| Báo cáo PDF Unicode & Excel 4 sheet + Cross-check số liệu | **PASS** | `verify_narrative_numbers()` kiểm chứng 100% số liệu nhận xét khớp SQL; cô lập phòng ban cho Manager; chặn Employee/Admin `403`. |
| Trợ lý AI SQL Assistant & lớp bảo vệ `SQLGuard` | **PASS** | 4 Safe TEMP Views, chặn toàn bộ bảng gốc + `revoked_tokens`, chặn Prompt Injection / Out-of-scope / Admin; đã sửa truy vấn ngày `"hôm nay"` và câu hỏi đếm `"bao nhiêu người đi muộn"`. |
| Quản trị kỹ thuật Admin (`System Dashboard`, `RBAC`, `Audit Logs`, `System Config`) | **PASS** | Chặn mọi key nhạy cảm (`secret`/`password`/`api_key`/`token`); bảo vệ 3 quyền cốt lõi của Admin; ghi `activity_logs` và `query_audit_log`. |
| Kho tài liệu RAG (`/admin/rag`, `company_documents`, `document_chunks`) | **PARTIAL** | Có CRUD tải tài liệu, tách đoạn chunk văn bản, re-index và xóa cho Admin/HR; **chưa nối tìm kiếm/retrieval vào `ai_assistant.py`** (chưa có embedding vector hoặc BM25 retrieval). |
| Face Recognition Kiosk (`/admin/kiosk`, `kiosk_devices`, `face_*` schema) | **PARTIAL** | Có schema PostgreSQL (`kiosk_devices`, `face_profiles`, `face_consent_records`, `face_scan_logs`) và UI/API quản trị thiết bị + ngưỡng Kiosk cho Admin; **chưa có InsightFace, enrollment, liveness hay luồng camera check-in**. |
| Bảng `notifications` & `overtime_requests` | **PARTIAL** | `overtime_requests` được dùng trong quy tắc `R7` và kiểm tra cảnh báo import; chưa có API/UI cho nhân viên tự gửi đơn OT hoặc hộp thư thông báo in-app. |
| Kiểm thử trực quan trên trình duyệt thật (Playwright / Browser click-through) cho bản build sau audit | **UNVERIFIED** | Không thay đổi layout/design system trong đợt audit này; toàn bộ 21 test component/router Vitest + `tsc -b` + `vite build` đều PASS, nhưng chưa chạy lại phiên click-through trình duyệt mới sau commit này. |

---

## 3. Security Findings

| Mã lỗi | Mức độ | Vị trí mã nguồn | Mô tả vấn đề phát hiện | Khắc phục & Kiểm chứng | Trạng thái |
|---|---|---|---|---|---|
| **AUDIT-SEC-01** | **Critical** | `backend/app/api/admin.py` (`list_employees`) | Truy vấn khởi tạo `WHERE 1 = 1` và chỉ gọi `assert_department_access()`; nếu Admin cấp nhầm quyền `employee.read.*` cho `employee`, `effective_dept` trả `None` làm lộ toàn bộ danh sách 80 nhân viên kèm `email`, `phone`. | Chặn cứng `RoleEnum.employee` (`403`), bắt buộc gọi `build_scope_filter(current_user, "e.employee_id", "e.department_id")` (tự chặn cả `admin` `403` và khóa `manager` trong phòng mình), và chỉ cho phép lọc toàn công ty khi có `employee.read.all`/`employee.manage`. Kiểm chứng: `test_audit_sec01_employee_list_never_leaks_even_if_misconfigured`. | **FIXED** |
| **AUDIT-SEC-02** | **High** | `backend/app/core/security.py` (`load_user_permissions`, `sync_user_role_mapping`), `backend/app/api/system_admin.py` | (1) `load_user_permissions` dùng `WHERE r.role_code = ? OR r.role_id IN (SELECT ... FROM user_roles)` nên bản ghi cũ còn sót trong `user_roles` có thể cấp lậu quyền role cũ. (2) Nếu Admin cố ý thu hồi hết quyền của role không phải Admin (`[]`), code tự fallback về `DEFAULT_ROLE_PERMISSIONS`. (3) `sync_user_role_mapping` dùng `except Exception: pass` nuốt lỗi DB thật. | Dùng `employees.role` là nguồn thẩm quyền duy nhất tra sang `roles` → `role_permissions`; chỉ fallback mặc định khi bảng `roles` chưa khởi tạo/chưa seed; cho phép lưu `permissions: []` cho non-admin và giữ nguyên `[]`; chỉ bỏ qua lỗi thiếu bảng trên schema tối giản, còn lại log & re-raise lỗi DB thật. Kiểm chứng: `test_audit_sec02_empty_role_permissions_stay_empty_and_no_stale_user_roles_leak`. | **FIXED** |
| **AUDIT-SEC-03** | **High** | `backend/app/api/admin.py` (`update_account`, `update_employee`) | Kiểm tra đếm tài khoản Admin/HR cuối cùng bằng `SELECT COUNT(*)` không khóa giao dịch — 2 request đồng thời có thể cùng thấy count=1 và cùng khóa/hạ quyền cả 2 Admin cuối cùng. | Bọc thao tác đọc–kiểm tra–cập nhật trong `begin_write_transaction(conn)` (`BEGIN IMMEDIATE` trên SQLite) và `SELECT ... FOR UPDATE` trên PostgreSQL kèm rollback sạch khi lỗi. | **FIXED** |
| **AUDIT-SEC-04** | **High** | `backend/app/core/security.py`, `backend/app/api/auth.py`, `backend/app/db/{schema.sql,schema_postgres.sql,migrations.py}` | `REVOKED_JTIS` chỉ lưu trong RAM của tiến trình FastAPI; token đã đăng xuất có hiệu lực trở lại sau khi restart server hoặc trên worker khác. | Tạo bảng bền vững `revoked_tokens` (SQLite + PostgreSQL), ghi JTI + `expires_at` khi `/api/auth/logout`, kiểm tra DB trong `is_token_revoked()` kèm dọn token hết hạn, và thêm `revoked_tokens` vào danh sách chặn của `sql_guard.py`. Kiểm chứng: `test_audit_sec04_persistent_jwt_revocation_survives_memory_clear` + live Supabase E2E. | **FIXED** |
| **AUDIT-SEC-05** | **High** | `backend/app/db/schema_postgres.sql`, `backend/app/db/migrations.py` | Bảng `public.system_settings` được tạo trong v1.2 nhưng bị thiếu `ENABLE ROW LEVEL SECURITY` và `REVOKE ALL FROM anon, authenticated`. | Bổ sung `ENABLE ROW LEVEL SECURITY` + `REVOKE ALL` từ `anon`/`authenticated` + `GRANT ALL TO service_role` cho cả `public.system_settings` và `public.revoked_tokens` trong `schema_postgres.sql` & `migrations.py`; đã áp dụng và xác minh live `27/27` bảng bật RLS trên Supabase. | **FIXED** |
| **AUDIT-SEC-06** | **Medium** | `backend/app/api/operations.py` (`list_import_logs`), `backend/app/services/import_service.py` (`get_import_log_detail`) | Khi HR2 xem danh sách hoặc chi tiết lịch sử import của bản nháp `status = 'preview'` do HR1 tạo, trường `batch_id` vẫn lộ trong payload dù nút confirm/errors bị chặn `403`. | Ẩn `batch_id = None` trong cả `/api/imports/logs` và `/api/imports/logs/{id}` đối với bản nháp `preview` không thuộc chủ sở hữu. Kiểm chứng: `test_audit_sec06_and_sec07_import_masks_foreign_preview_and_blocks_privileged_overwrite`. | **FIXED** |
| **AUDIT-SEC-07** | **Medium** | `backend/app/services/import_service.py` (`stage_and_validate_import`, `confirm_staged_import`) | Khi HR import file `employees` trùng `NV080` (`admin`) hoặc `NV079` (`executive`) với `role='employee'` và chọn cập nhật trùng, giao dịch có thể ghi đè/hạ quyền Admin/Executive hoặc HR cuối cùng, và không gọi `sync_user_role_mapping()`. | Khóa `can_update = False` ở bước preview cho mọi nhân viên có role `admin`/`executive`, chặn cứng `PermissionError` ở bước confirm phía server, chặn hạ quyền HR hoạt động cuối cùng, và gọi `sync_user_role_mapping()` khi đổi role qua import. Kiểm chứng: `test_audit_sec06_and_sec07_import_masks_foreign_preview_and_blocks_privileged_overwrite`. | **FIXED** |

---

## 4. Business Logic Findings

| Mã lỗi | Mức độ | Vị trí mã nguồn | Mô tả vấn đề | Khắc phục & Kiểm chứng | Trạng thái |
|---|---|---|---|---|---|
| **AUDIT-BIZ-01** | **High** | `backend/app/api/operations.py` (`adjust_attendance_record`) | `PATCH /api/attendance/{record_id}` nhận chuỗi tự do cho `check_in`/`check_out`, không kiểm tra định dạng, không chặn `check_out < check_in` (có thể gây 500 trên PostgreSQL CHECK constraint hoặc làm sai lệch dữ liệu SQLite), không kiểm tra khớp `work_date` hay mâu thuẫn trạng thái `absent/on_leave`. | Thêm `_parse_attendance_timestamp()` chuẩn hóa `YYYY-MM-DD HH:MM:SS`, chặn `check_out < check_in`, xác thực ngày khớp `work_date` (cho phép `check_out` qua đêm `+1 ngày`), chặn đính kèm giờ công khi `absent/on_leave/holiday` (và tự xóa giờ nếu chỉ đổi status), bọc giao dịch nguyên tử + audit `before_obj`/`after_obj`. Kiểm chứng: `test_audit_biz01_attendance_adjust_validation_and_audit`. | **FIXED** |
| **AUDIT-BIZ-02** | **High** | `backend/app/api/operations.py` (`create_leave_request`, `cancel_leave_request`, `review_leave_request`, `_is_executive_approval_enabled`) | (1) Kiểm tra trùng ngày / quỹ phép / duyệt đơn / hủy đơn thiếu khóa giao dịch nguyên tử, dễ phát sinh duyệt trùng hoặc tạo 2 đơn chồng lấn đồng thời. (2) `_is_executive_approval_enabled` dùng `except Exception: pass` nuốt lỗi DB. | Bọc `POST /api/leaves`, `/cancel`, `/review` trong `begin_write_transaction(conn)` + `SELECT ... FOR UPDATE` trên PostgreSQL + câu `UPDATE ... WHERE request_id = ? AND status = 'pending'` kiểm tra `rowcount == 1` (trả `409 Conflict` nếu bị đổi trạng thái đồng thời); bỏ `except Exception: pass`. Kiểm chứng: `test_audit_biz02_leave_double_review_and_overlap_guard`. | **FIXED** |
| **AUDIT-BIZ-03** | **Medium** | `backend/app/services/ai_tools.py`, `backend/app/services/ai_assistant.py` | (1) Câu hỏi `"Hôm nay tôi đã chấm công chưa?"` không có nhánh tra cứu ngày thực tế, rơi về tổng hợp mặc định kỳ `2026-10`. (2) Câu hỏi `"Tháng này phòng tôi có bao nhiêu người đi muộn?"` bị giới hạn mặc định `limit=5` dù người dùng không hỏi "top 5". | Bổ sung `get_daily_attendance()` + `Route 0` tra cứu đúng ngày hôm nay (hoặc `YYYY-MM-DD`), trả `insufficient_data` trung thực nếu DB không có bản ghi ngày đó; nâng giới hạn lên `50` và trả tổng số chính xác khi câu hỏi chứa `"bao nhiêu người"` / `"mấy người"`. Kiểm chứng: `test_audit_biz03_ai_daily_no_hallucination_late_count_and_sql_guard_revoked_tokens`. | **FIXED** |

**Các quy tắc nghiệp vụ đã xác minh đạt chuẩn (không lỗi):**
- Parity 8/8 file SQL `r1..r8.sql` giữa `backend/sql/` (SQLite) và `backend/sql_postgres/` (PostgreSQL).
- `R8` và quỹ phép năm (`leave_days = to_date - from_date + 1`, tính theo ngày lịch bao gồm cả 2 đầu) nhất quán giữa `v_leave_requests`, `operations.py`, `auth.py`, `reports.py`, và `ai_tools.py`.
- Staging import (`STAGING_BATCHES`) chỉ là RAM hot cache — dữ liệu đầy đủ đã được lưu bền vững vào `import_logs.detail_json` và khôi phục tự động qua `_hydrate_batch_from_db()` sau restart (đã được kiểm chứng trong `test_import_history_detail_persists_across_restart_and_enforces_rbac`).

---

## 5. Database Findings

1. **Dual-DB Compatibility (SQLite + Supabase PostgreSQL)**:
   - Xác minh trực tiếp trên Supabase (`aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres`): **27/27 bảng `public` bật Row Level Security (`rowsecurity = true`)**, **4/4 view (`v_employees`, `v_attendance_daily`, `v_leave_requests`, `v_anomalies`) bật `security_invoker = true`**, và `anon`/`authenticated` bị `REVOKE ALL`.
   - `backend/app/db/migrations.py` chạy idempotent và không làm mất dữ liệu trên cả PostgreSQL và SQLite.
2. **Điểm khác biệt đã biết giữa SQLite & PostgreSQL (ghi nhận minh bạch)**:
   - `v_attendance_daily` trên **PostgreSQL** đọc linh hoạt khung giờ làm việc từ bảng `public.attendance_policies` (`LATERAL JOIN`), trong khi `v_attendance_daily` trên **SQLite** dùng hằng số chuẩn `08:30:00`, ân hạn `5` phút, nghỉ trưa `1.0` giờ (khớp bộ seed mặc định).
   - Hiện tại các biến cấu hình như `attendance_policies` chưa có màn hình CRUD trên UI; việc thay đổi chính sách giờ làm chỉ mới hỗ trợ ở cấp DB trên PostgreSQL.

---

## 6. Frontend Findings

| Mã lỗi | Mức độ | Vị trí mã nguồn | Mô tả vấn đề | Khắc phục & Kiểm chứng | Trạng thái |
|---|---|---|---|---|---|
| **AUDIT-FE-01** | **Low** | `frontend/src/pages/ProfilePage.tsx` | `ROLE_LABELS` chỉ định nghĩa 3 vai trò cũ (`employee`, `manager`, `hr`), khiến tài khoản `director@company.vn` và `admin@company.vn` hiển thị mã thô `executive` / `admin`. | Bổ sung đầy đủ 5 nhãn tiếng Việt chuẩn cho `employee`, `manager`, `hr`, `executive`, `admin`. | **FIXED** |
| **AUDIT-FE-02** | **Low** | `frontend/src/pages/AccountsPage.tsx` | Modal tạo tài khoản không hiển thị ô chọn vai trò (`role`) và không gửi `role` trong `POST /api/accounts`; hộp thoại xác nhận khóa tài khoản vẫn ghi cứng `"HR cuối cùng"` dù đang khóa tài khoản Admin. | Thêm dropdown vai trò theo `assignableRoles` (Admin thấy 5 role, HR chỉ thấy 3 role nghiệp vụ), gửi `role` trong `POST /api/accounts`, cập nhật wording thành `"Quản trị viên"` & `"Admin hoặc HR cuối cùng"`. | **FIXED** |
| **AUDIT-PERF-01** | **Low** | `frontend/src/App.tsx`, `frontend/vite.config.ts` | Toàn bộ 18 trang được import đồng bộ tạo thành 1 file JS duy nhất `822.92 kB` (gây cảnh báo Vite `> 500 kB`). | Chuyển 17 trang sau đăng nhập sang `React.lazy()` + `<Suspense fallback={<LoadingSkeleton rows={5} />}>` và tách `manualChunks` (`react-vendor`, `charts-vendor`, `icons-vendor`). Chunk chính giảm từ **`822.92 kB` xuống `42.89 kB` (`12.70 kB gzip`)**, **0 cảnh báo >500 kB**, giữ nguyên 100% design system và **21/21 Vitest PASS**. | **FIXED** |

---

## 7. AI Findings

- **Kiến trúc hiện tại**: AI Assistant hoạt động theo mô hình **Deterministic Intent Router + Parameterized SQL Tools + Read-Only SQL Guard** (không gọi LLM đám mây tự do sinh SQL).
- **Bảo mật AI (`SQLGuard`)**:
  - Đã kiểm chứng chặn 30/30 payload SQL Injection & bypass (comment, multi-statement, quoted identifiers, comma-join, `LIMIT` subquery bypass, bảng nhạy cảm `users`, `activity_logs`, `system_settings`, **`revoked_tokens`**).
  - Lớp `TEMP VIEW` (SQLite + PostgreSQL `BEGIN TRANSACTION READ ONLY` + `statement_timeout`) và SQLite `authorizer` cô lập tuyệt đối dữ liệu theo 5 vai trò; `admin` bị từ chối mặc định (`403` / `SQLGuardError`).
- **Độ chính xác truy vấn**:
  - Đã sửa `AUDIT-BIZ-03` để câu hỏi `"Hôm nay tôi đã chấm công chưa?"` kiểm tra đúng `work_date` ngày hôm nay và trả `insufficient_data` trung thực thay vì rơi về tháng `2026-10`.
  - Đã sửa câu hỏi `"Tháng này phòng tôi có bao nhiêu người đi muộn?"` không bị cắt ngầm còn 5 người.
- **Trạng thái trung thực về RAG (chưa triển khai retrieval)**:
  - Hệ thống mới có bảng `company_documents` & `document_chunks` cùng giao diện `/admin/rag` để Admin/HR nạp & tách đoạn tài liệu.
  - **`backend/app/services/ai_assistant.py` hiện CHƯA truy vấn `company_documents`/`document_chunks`**, chưa có vector embedding hay BM25 search, và chưa trả trích dẫn tài liệu nội quy. Do đó câu hỏi về nội quy/chính sách văn bản (VD: `"Nghỉ ốm cần giấy tờ gì?"`) chưa thể trả lời từ kho RAG ở phiên bản hiện tại.

---

## 8. Face Recognition Findings

- **Những gì ĐÃ CÓ trong mã nguồn**:
  - Schema PostgreSQL sẵn sàng: `kiosk_devices`, `face_profiles`, `face_consent_records`, `face_scan_logs` (đều đã bật RLS).
  - Các mã quyền (`attendance.face_checkin`, `face.manage`, `kiosk.manage`), khóa cấu hình trong `system_settings` (`kiosk.similarity_threshold`, `kiosk.liveness_threshold`, `kiosk.duplicate_cooldown_seconds`, `kiosk.require_liveness`), và màn hình quản trị thiết bị/cấu hình Kiosk (`/admin/kiosk`, `/admin/kiosk/config`) cho Admin.
- **Những gì CHƯA CÓ (xác minh trung thực từ `backend/requirements.txt`, `backend/app/`, `frontend/src/`)**:
  - Không có thư viện `insightface`, `onnxruntime`, `opencv-python` trong `requirements.txt`.
  - Không có API đăng ký khuôn mặt (`enroll`), so khớp vector embedding, kiểm tra liveness chống giả mạo, hay endpoint ghi nhận check-in khuôn mặt vào bảng `attendance`.
  - Không có giao diện webcam Kiosk trên Frontend cho nhân viên chấm công khuôn mặt.
- **Đánh giá**: Chỉ nên mô tả phân hệ này là **"Hạ tầng quản trị Kiosk & Schema sẵn sàng tích hợp Face Recognition"** — không tuyên bố đã có tính năng chấm công khuôn mặt hoạt động hoàn chỉnh.

---

## 9. Fixed Issues

| # | Mã | Mức độ | Tóm tắt sửa lỗi | File đã sửa |
|---|---|---|---|---|
| 1 | `AUDIT-SEC-01` | Critical | Chặn rò rỉ danh sách nhân viên trong `list_employees()` bằng defense-in-depth (`403` cho `employee`, bắt buộc `build_scope_filter`) | `backend/app/api/admin.py` |
| 2 | `AUDIT-SEC-02` | High | Sửa `load_user_permissions()` (bỏ `OR user_roles`, giữ nguyên quyền rỗng `[]`), bỏ nuốt lỗi trong `sync_user_role_mapping()`, cho phép `permissions: []` ở non-admin | `backend/app/core/security.py`, `backend/app/api/system_admin.py` |
| 3 | `AUDIT-SEC-03` | High | Khóa giao dịch nguyên tử (`BEGIN IMMEDIATE` / `FOR UPDATE`) chống race condition khóa Admin/HR cuối cùng | `backend/app/core/security.py`, `backend/app/api/admin.py` |
| 4 | `AUDIT-SEC-04` | High | Lưu bền vững JWT logout revocation trong bảng `revoked_tokens` (SQLite + PostgreSQL) + chặn `revoked_tokens` trong `sql_guard.py` | `backend/app/core/security.py`, `backend/app/api/auth.py`, `backend/app/services/sql_guard.py`, `backend/app/db/{schema.sql,schema_postgres.sql,migrations.py}` |
| 5 | `AUDIT-SEC-05` | High | Bật RLS & least-privilege lockdown cho `public.system_settings` và `public.revoked_tokens` trên PostgreSQL / Supabase | `backend/app/db/schema_postgres.sql`, `backend/app/db/migrations.py` |
| 6 | `AUDIT-SEC-06` | Medium | Ẩn `batch_id` của bản nháp import `preview` khỏi tài khoản HR không phải chủ sở hữu | `backend/app/api/operations.py`, `backend/app/services/import_service.py` |
| 7 | `AUDIT-SEC-07` | Medium | Cấm HR bulk-import ghi đè/hạ quyền `admin`/`executive` hoặc HR cuối cùng; đồng bộ `user_roles` khi import đổi role | `backend/app/services/import_service.py` |
| 8 | `AUDIT-BIZ-01` | High | Kiểm tra chặt timestamp, `check_out >= check_in`, khớp `work_date` và trạng thái mâu thuẫn trên `PATCH /api/attendance/{id}` | `backend/app/api/operations.py` |
| 9 | `AUDIT-BIZ-02` | High | Khóa giao dịch nguyên tử + `WHERE status = 'pending'` (`rowcount == 1`) chống duyệt/hủy trùng và trùng ngày đồng thời; bỏ `except Exception: pass` | `backend/app/api/operations.py` |
| 10 | `AUDIT-BIZ-03` | Medium | Thêm `get_daily_attendance()` cho câu hỏi `"hôm nay"` (không bịa dữ liệu tháng 10) và bỏ cắt ngầm `limit=5` khi hỏi `"bao nhiêu người đi muộn"` | `backend/app/services/ai_tools.py`, `backend/app/services/ai_assistant.py` |
| 11 | `AUDIT-FE-01` | Low | Thêm nhãn tiếng Việt cho vai trò `executive` và `admin` trên `ProfilePage` | `frontend/src/pages/ProfilePage.tsx` |
| 12 | `AUDIT-FE-02` | Low | Thêm chọn vai trò (`assignableRoles`) khi tạo tài khoản và sửa wording khóa Admin/HR cuối cùng trên `AccountsPage` | `frontend/src/pages/AccountsPage.tsx` |
| 13 | `AUDIT-PERF-01` | Low | Tách route bằng `React.lazy()` + `<Suspense>` và `manualChunks` giảm chunk chính từ `822.92 kB` xuống `42.89 kB` | `frontend/src/App.tsx`, `frontend/vite.config.ts`, `frontend/src/__tests__/Bugfixes.test.tsx` |

---

## 10. Remaining Issues

Các hạng mục chưa hoàn thiện hoặc nằm ngoài phạm vi đợt audit sửa lỗi này (ghi nhận rõ để lên kế hoạch giai đoạn tiếp theo):

1. **RAG Retrieval chưa nối vào AI Assistant** (Medium — backlog tính năng): Cần bổ sung truy vấn hybrid (BM25 / pgvector embedding) trên `document_chunks` và trích dẫn nguồn tài liệu nội quy trong `ai_assistant.py`.
2. **Face Recognition Check-in chưa có pipeline nhận diện** (Medium — backlog tính năng): Cần tích hợp model InsightFace, luồng thu thập đồng thuận/đăng ký khuôn mặt, chống giả mạo (liveness) và UI webcam Kiosk nếu triển khai chấm công khuôn mặt thực tế.
3. **Chưa có rate limiting ở lớp API** (Medium — production hardening): Các endpoint `/api/auth/login` và `/api/assistant/ask` chưa có giới hạn tần suất (rate limit / brute-force lockout).
4. **Cơ chế phiên chỉ dùng Access Token (chưa có Refresh Token rotation)** (Low): Hiện dùng Bearer JWT hết hạn theo `JWT_EXPIRE_MINUTES` lưu trong `localStorage` của trình duyệt; môi trường production chặt hơn nên cân nhắc HttpOnly cookie + Refresh Token.
5. **Chưa đồng bộ `attendance_policies` động trên SQLite & chưa có UI quản lý chính sách ca** (Low): PostgreSQL đọc động `attendance_policies`, SQLite dùng hằng số chuẩn `08:30–17:30`.
6. **Quy ước tính ngày phép (`leave_days`) theo ngày lịch** (Low — theo đặc tả gốc): Đang tính `to_date - from_date + 1` kể cả cuối tuần/ngày lễ; nếu áp dụng doanh nghiệp thực tế cần cho phép cấu hình trừ cuối tuần/ngày lễ.
7. **2 deprecation warnings từ thư viện bên thứ ba trong `pytest`** (Info): Cảnh báo từ `anyio` (`CallSpec2`) và `starlette.testclient` (`httpx` vs `httpx2`), không phải lỗi mã nguồn dự án.

---

## 11. Test Results

**Môi trường kiểm chứng thực tế:**
- Hệ điều hành: Windows (PowerShell 5.1)
- Backend: Python `3.12.10`, `pytest 9.2.0`, `FastAPI`, `psycopg 3`
- Frontend: Node.js `v24.16.0`, `Vitest 2.1.9`, `TypeScript 5.x`, `Vite 5.4.21`
- Cơ sở dữ liệu: SQLite 3 (isolated tmp DB trong pytest + `backend/hr_attendance.db`) và **Live Supabase PostgreSQL** (`aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres`)

| Hạng mục kiểm thử | Lệnh chạy thực tế | Passed | Failed | Skipped | Blocked | Ghi chú kết quả |
|---|---|---|---|---|---|---|
| Backend Full Test Suite (12 file test, gồm 7 test mới `test_security_audit_fixes.py`) | `cd backend; python -m pytest -v` | **60** | **0** | **0** | **0** | `60 passed, 2 warnings in 38.06s` (Exit code `0`) |
| Frontend Unit & Regression Suite (3 file test) | `cd frontend; npm test -- --run` | **21** | **0** | **0** | **0** | `3 passed (3), 21 passed (21) in 5.05s` (Exit code `0`) |
| Frontend TypeScript Check & Production Build | `cd frontend; npm run build` | **PASS** | **0** | **0** | **0** | `tsc -b && vite build` `✓ built in 5.59s`, 0 lỗi TS, 0 cảnh báo >500 kB (`index`: `42.89 kB`, `react-vendor`: `162.23 kB`, `charts-vendor`: `413.28 kB`) |
| Non-destructive DB Migration (Live Supabase + Local SQLite) | `cd backend; python -m app.db.migrations` & `python -m app.db.migrations --db hr_attendance.db` | **2** | **0** | **0** | **0** | Tạo `revoked_tokens`, bật RLS cho `system_settings` & `revoked_tokens`, giữ nguyên 100% dữ liệu |
| Live Supabase PostgreSQL RLS & 5-Role E2E Verification | `verify_supabase_e2e.py` chạy trực tiếp trên `DATABASE_URL` Supabase | **PASS** | **0** | **0** | **0** | **27/27 bảng bật RLS**, **4/4 view `security_invoker=true`**, 5 role đăng nhập & phân quyền đúng, AI đúng, logout revocation bền vững sống sót sau `REVOKED_JTIS.clear()` |
| SQLite vs PostgreSQL `R1–R8` SQL File Parity | Kiểm tra danh sách `backend/sql/*.sql` vs `backend/sql_postgres/*.sql` | **8/8** | **0** | **0** | **0** | Khớp đủ `r1` đến `r8` |

---

## 12. Production Readiness

### Kết luận tổng thể: **READY FOR STAGING / DEMO & CONTROLLED INTERNAL PILOT (Chưa nên mở Public Production ngay nếu chưa hoàn tất checklist vận hành bên dưới)**

- **Sẵn sàng vận hành ngay ở mức Staging / Demo / Pilot nội bộ** cho toàn bộ nghiệp vụ lõi: Chấm công, Nghỉ phép, Cảnh báo `R1–R8`, Import Excel/CSV an toàn, Báo cáo PDF/Excel, Trợ lý AI SQL Guard, và Phân quyền RBAC 5 vai trò trên Supabase PostgreSQL (27/27 RLS).
- **Điều kiện bắt buộc trước khi Go-Live Production thực tế**:
  1. Thiết lập `APP_ENV=production`, `JWT_SECRET_KEY` ngẫu nhiên ≥ 32 ký tự, `CORS_ORIGINS` đúng domain production, chạy sau HTTPS reverse proxy.
  2. Không chạy `seed.py` trên production; đổi/xóa toàn bộ mật khẩu mặc định (`Demo@123`) của các tài khoản demo.
  3. Bổ sung rate limiting & khóa tạm thời chống brute-force cho `/api/auth/login` và `/api/assistant/ask`.
  4. Bật sao lưu định kỳ (PITR/Backup) trên Supabase và cấu hình connection pooling phù hợp tải thực tế.
  5. Minh bạch với người dùng/khách hàng rằng **RAG hỏi đáp văn bản nội quy** và **Chấm công khuôn mặt InsightFace** đang ở giai đoạn hạ tầng quản trị/schema và sẽ hoàn thiện ở giai đoạn tiếp theo.
