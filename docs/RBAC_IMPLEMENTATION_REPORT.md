# Báo cáo Hoàn thiện Hệ thống Phân quyền RBAC 5 Vai trò (RBAC Implementation Report)

- **Dự án**: HR Attendance Copilot
- **Ngày hoàn thiện**: `28/11/2026`
- **Phạm vi**: Hoàn thiện & đồng bộ phân quyền RBAC 5 vai trò (`employee`, `manager`, `hr`, `executive`, `admin`) trên Backend (FastAPI), Frontend (React/TypeScript), và CSDL kép (SQLite cục bộ + Live Supabase PostgreSQL), bảo toàn toàn bộ 81 bài kiểm thử cũ và bổ sung 11 bài kiểm thử RBAC mới (**tổng 92/92 PASS**).

---

## 1. Hiện trạng trước khi sửa

Trước đợt hoàn thiện này (sau đợt kiểm toán kỹ thuật trước đó), hệ thống đã có:
- 5 vai trò (`employee`, `manager`, `hr`, `executive`, `admin`) và 44 mã quyền (`permissions`) trong `backend/app/core/permissions.py` cùng bảng `roles`, `permissions`, `role_permissions`, `user_roles`, `revoked_tokens`.
- Cơ chế JWT chỉ lưu định danh (`sub`, `emp`, `jti`), mỗi request tải lại tươi `role`, `department_id`, `is_active`, `permissions` từ DB.
- 60/60 backend pytest và 21/21 frontend Vitest đang PASS; 27/27 bảng PostgreSQL trên Supabase đã bật RLS.
- Tuy nhiên, khi đối chiếu chi tiết theo ma trận 5 vai trò chuẩn doanh nghiệp (Giai đoạn 1 – Audit), vẫn còn **7 lỗ hổng/điểm lệch RBAC** giữa Backend, Frontend và các nhánh phòng thủ chiều sâu (defense-in-depth).

---

## 2. Các lỗi phát hiện (Giai đoạn 1 – Audit)

| Mã | Mức độ | Lớp | Mô tả lỗi / khoảng trống thực tế | Trạng thái |
|---|---|---|---|---|
| **RBAC-GAP-01** | **High** | Frontend (`navigation.ts`) | `resolvePermissions()` kiểm tra `subject.permissions.length > 0`; khi Admin thu hồi **toàn bộ** quyền của một vai trò (`permissions: []` từ `/api/auth/me`), Frontend tự fallback về `DEFAULT_ROLE_PERMISSIONS` thay vì ẩn toàn bộ menu & chặn `403`. `getDataScopeLabel()` thiếu nhánh `default` cho role không hợp lệ. | **PASS (Đã sửa)** |
| **RBAC-GAP-02** | **High** | Backend (`anomalies.py`) | `GET /api/anomalies/{id}` chỉ kiểm nhánh `employee` và `manager` rồi rơi thẳng ra trả dữ liệu; `POST /api/anomalies/scan` và `POST /api/anomalies/{id}/review` chưa chặn tường minh `admin`/`executive`/`employee` theo defense-in-depth nếu quyền bị cấu hình nhầm. | **PASS (Đã sửa)** |
| **RBAC-GAP-03** | **High** | Backend (`report_service.py`) | `collect_metrics()` chưa chặn tường minh `employee`/`admin` và chưa thu hẹp phạm vi về phòng ban cá nhân khi `hr`/`executive` bị thu hồi `report.read.all` (chỉ còn `report.read.department`). | **PASS (Đã sửa)** |
| **RBAC-GAP-04** | **Medium** | Backend/Frontend (`routes.py`) | `build_screens()` trả `attendance` và `employees` trong `allowed_screens` của `executive`, không đồng nhất với sidebar thực tế của Executive trên `navigation.ts`. | **PASS (Đã sửa)** |
| **RBAC-GAP-05** | **Medium** | Frontend (`PermissionGuard`, `EmployeesPage`, `AttendancePage`) | Thiếu component `<PermissionGuard>` dùng chung; `EmployeesPage` dùng `user?.role === 'hr'` thay vì `hasPermission()`, kiểu `role` thiếu `executive`/`admin` và vẫn hiện nút `Sửa`/`Ngừng HĐ` trên dòng `admin`/`executive` cho HR; `AttendancePage` chưa nối form điều chỉnh chấm công bọc `<PermissionGuard permission="attendance.adjust" roles={['hr']}>`. | **PASS (Đã sửa)** |
| **RBAC-GAP-06** | **Medium** | Backend (`permissions.py`, `operations.py`, `admin.py`, `import_service.py`, `system_admin.py`) | Hằng số vai trò đặc quyền (`PRIVILEGED_SYSTEM_ROLES`, `PROTECTED_ADMIN_PERMISSIONS`) bị lặp ở 3 file; `PATCH /api/attendance/{id}` chưa chặn tự điều chỉnh bản ghi chấm công của chính mình (`employee_id == current_user.employee_id`). | **PASS (Đã sửa)** |
| **RBAC-GAP-07** | **Low** | Database (`seed.py`) | Lệnh `seed_database(reset=True)` trên SQLite chưa xóa sạch bảng `revoked_tokens` khi reset môi trường test/demo. | **PASS (Đã sửa)** |

---

## 3. Những file đã thay đổi

### Backend
- `backend/app/core/permissions.py`: Chuẩn hóa hằng số duy nhất `ALL_ROLE_CODES`, `PRIVILEGED_SYSTEM_ROLES`, `HR_MANAGED_ROLES`, `PROTECTED_ADMIN_PERMISSIONS`.
- `backend/app/api/admin.py`: Dùng `PRIVILEGED_SYSTEM_ROLES` chuẩn từ `permissions.py`; siết phạm vi `get_dashboard_summary` khi bị thu hồi `dashboard.all`/`dashboard.executive`.
- `backend/app/api/system_admin.py`: Dùng `PROTECTED_ADMIN_PERMISSIONS` chuẩn từ `permissions.py`.
- `backend/app/services/import_service.py`: Dùng `PRIVILEGED_SYSTEM_ROLES` chuẩn từ `permissions.py`.
- `backend/app/api/anomalies.py`: Khóa phòng thủ chiều sâu cho 5 vai trò trên `GET /api/anomalies/{id}`, `POST /api/anomalies/scan`, `POST /api/anomalies/{id}/review`.
- `backend/app/services/report_service.py`: Chặn tường minh `employee`/`admin` (`403`) và hạ phạm vi phòng ban khi mất `report.read.all`.
- `backend/app/api/operations.py`: Chặn cứng non-HR và chặn **tự điều chỉnh ngày công bản thân** (`403`) trên `PATCH /api/attendance/{record_id}`.
- `backend/app/api/routes.py`: Đồng bộ `allowed_screens` (`attendance`, `employees`) với `navigation.ts`.
- `backend/app/db/seed.py`: Bổ sung `revoked_tokens` vào danh sách bảng dọn khi `reset=True`.
- `backend/tests/test_rbac_completion.py` *(mới)*: 5 kịch bản kiểm thử nâng cao (thu hồi role live trên JWT cũ, đổi phòng ban live trên JWT cũ, tự sửa công bị chặn, phòng thủ chiều sâu `anomalies`/`reports`, tự phục vụ cá nhân của Manager, đồng bộ `allowed_screens`).

### Frontend
- `frontend/src/config/navigation.ts`: Sửa `resolvePermissions()` tôn trọng mảng rỗng `[]`, thêm `VALID_ROLES`/`isValidRole()`, nhánh `default` cho `getDataScopeLabel()`, và cải thiện `getDefaultHomePath()`.
- `frontend/src/components/layout/PermissionGuard.tsx` *(mới)*: Component kiểm soát hiển thị nút/khối UI theo `permission`, `anyPermissions`, `roles`, và `fallback`.
- `frontend/src/components/layout/RouteGuard.tsx`: Xử lý an toàn role không hợp lệ / mất toàn bộ quyền, hiển thị trang `403 – Không có quyền truy cập` thân thiện.
- `frontend/src/pages/EmployeesPage.tsx`: Chuyển kiểm tra quyền sang `hasPermission()` / `<PermissionGuard>`, cập nhật kiểu `UserRole`, hiển thị nhãn `Được bảo vệ` (ẩn nút sửa/ngừng HĐ) đối với dòng `admin`/`executive` khi HR xem.
- `frontend/src/pages/AttendancePage.tsx`: Thêm khu vực điều chỉnh chấm công nghiệp vụ bọc `<PermissionGuard permission="attendance.adjust" roles={['hr']}>` trong Drawer chi tiết (ẩn hoàn toàn với 4 vai trò khác và chặn tự sửa bản ghi của chính mình).
- `frontend/src/__tests__/RbacCompletion.test.tsx` *(mới)*: 6 kịch bản kiểm thử Frontend (`PermissionGuard`, thu hồi quyền rỗng `[]`, nhập URL trái phép trên cả 5 role, role không hợp lệ không trắng màn hình, chuyển đổi giữa 5 role, ẩn nút thao tác trên `EmployeesPage`).

---

## 4. Những API đã cập nhật

| Endpoint | Thay đổi bảo mật / phân quyền |
|---|---|
| `GET /api/dashboard/summary` | Thu hẹp về phòng ban cá nhân nếu `hr`/`executive` bị thu hồi `dashboard.all` & `dashboard.executive`. |
| `PATCH /api/attendance/{record_id}` | Bắt buộc vai trò `hr` + quyền `attendance.adjust`; chặn `403` nếu tự điều chỉnh bản ghi chấm công của chính mình. |
| `GET /api/anomalies/{anomaly_id}` | Kiểm tra tường minh đủ 5 vai trò (`employee` chỉ `scope_type='employee'` của mình; `manager` chỉ phòng mình; `hr`/`executive` cần `anomaly.read.all` cho toàn công ty; `admin` → `403`). |
| `POST /api/anomalies/scan` & `POST /api/anomalies/{id}/review` | Phòng thủ chiều sâu: chỉ `manager` (phòng mình) hoặc `hr` được phép; `admin`/`executive`/`employee` → `403`. |
| `GET /api/reports/preview`, `/export/pdf`, `/export/excel` | Chặn cứng `employee`/`admin` (`403`); nếu `hr`/`executive` chỉ còn `report.read.department` thì chặn lọc phòng khác (`403`) và chỉ xuất phòng của mình. |
| `GET /api/meta/sitemap` & `GET /api/auth/me` (`allowed_screens`) | Đồng bộ chính xác `allowed_screens` cho `executive` (không trả `attendance`, `employees`) và `admin`. |

---

## 5. Ma trận phân quyền cuối cùng

| Vai trò | Phạm vi dữ liệu | Số quyền mặc định | Chức năng được phép (đã kiểm chứng) | Chặn tuyệt đối (`403` / `400`) | Trạng thái |
|---|---|---|---|---|---|
| **employee** | Cá nhân (`employee_id`) | `9` | Dashboard cá nhân, lịch sử chấm công cá nhân, tạo/hủy đơn phép cá nhân (`pending`), cảnh báo cá nhân (`scope_type='employee'`), AI cá nhân, hồ sơ cá nhân & đổi mật khẩu | Mọi dữ liệu người khác/phòng khác, duyệt đơn, sửa công, báo cáo, import, nhân sự, tài khoản, RBAC, hệ thống | **PASS** |
| **manager** | Phòng ban (`department_id`) | `16` | Dashboard phòng, danh sách NV phòng (chỉ xem), chấm công phòng, duyệt đơn NV phòng mình, quét/xử lý R1–R8 phòng, báo cáo PDF/Excel phòng, AI phòng mình, hồ sơ & tạo/hủy đơn phép cá nhân độc lập | Phòng ban khác (REST/Report/Export/AI), tự duyệt đơn mình, duyệt đơn quản lý, sửa chấm công, import, quản lý tài khoản/hệ thống | **PASS** |
| **hr** | Toàn công ty (nghiệp vụ HR) | `22` | Dashboard toàn công ty, quản lý NV (trừ vai trò/trạng thái `admin`/`executive`), điều chỉnh công NV khác có lý do & audit, duyệt đơn phép toàn công ty/cấp quản lý, xử lý R1–R8, import Excel/CSV an toàn, báo cáo PDF/Excel & AI công ty, quản lý tài liệu RAG, quản lý tài khoản nhóm nghiệp vụ (`employee`/`manager`/`hr`), audit nghiệp vụ | Quản trị/khóa/sửa `admin`/`executive`, nâng quyền lên `admin`/`executive`, tự sửa công bản thân, System Dashboard, RBAC, System Config, Kiosk, Query Audit | **PASS** |
| **executive** | Toàn công ty (điều hành – chỉ xem & duyệt cấp cao) | `12` | Tổng quan điều hành, Phân tích & so sánh phòng ban, xem toàn bộ cảnh báo R1–R8 (chỉ đọc), báo cáo PDF/Excel toàn công ty/lọc phòng, AI phân tích điều hành chiến lược, phê duyệt đơn có `requires_executive_approval = true`, hồ sơ cá nhân | Sửa chấm công, duyệt đơn thường, quét/đóng R1–R8, import Excel, thêm/sửa NV, quản lý tài khoản/RBAC/cấu hình hệ thống | **PASS** |
| **admin** | Toàn hệ thống (kỹ thuật & bảo mật) | `10` | System Dashboard, quản lý tài khoản toàn bộ 5 vai trò (chống khóa/hạ quyền Admin cuối cùng), quản lý ma trận 5 role × 44 permission (bảo vệ 3 quyền cốt lõi), Activity Logs & Query Audit Logs, quản lý kho tài liệu RAG, Cấu hình hệ thống phi-secret, quản lý thiết bị & cấu hình Kiosk, hồ sơ cá nhân | Không mặc định truy cập/sửa dữ liệu nghiệp vụ HR (Dashboard HR, Chấm công, Nghỉ phép, R1–R8, Nhân sự, Import, Báo cáo, AI HR đều trả `403` / `SQLGuardError`) | **PASS** |

---

## 6. Sidebar từng role (Chỉ hiển thị chức năng thực tế có trong source)

Tuân thủ nguyên tắc **không tạo menu giả / màn hình trang trí** cho các module chưa triển khai:

- **Employee (6 mục)**: `Tổng quan` (`/dashboard`), `Chấm công` (`/attendance`), `Cảnh báo bất thường` (`/anomalies`), `Hỏi đáp AI` (`/assistant`), `Đơn nghỉ phép` (`/leaves`), `Hồ sơ cá nhân` (`/profile`).
- **Manager (8 mục)**: `Tổng quan`, `Chấm công`, `Cảnh báo bất thường`, `Báo cáo` (`/reports`), `Hỏi đáp AI`, `Đơn nghỉ phép`, `Quản lý nhân viên` (`/admin/employees` – chỉ xem phòng mình), `Hồ sơ cá nhân`.
- **HR (12 mục)**: `Tổng quan`, `Chấm công`, `Cảnh báo bất thường`, `Báo cáo`, `Hỏi đáp AI`, `Đơn nghỉ phép`, `Nhập dữ liệu` (`/admin/import`), `Quản lý nhân viên`, `Quản lý tài khoản` (`/admin/accounts` – phạm vi nghiệp vụ), `Nhật ký kiểm toán` (`/admin/audit` – nghiệp vụ), `Kho tài liệu RAG` (`/admin/rag`), `Hồ sơ cá nhân`.
- **Executive (7 mục)**: `Tổng quan điều hành` (`/dashboard`), `Phân tích phòng ban` (`/executive/departments`), `Cảnh báo R1-R8` (`/anomalies` – chỉ đọc), `Báo cáo` (`/reports`), `Hỏi đáp AI` (`/assistant`), `Đơn cần phê duyệt` (`/leaves` – lọc mặc định `requires_executive_approval=true`), `Hồ sơ cá nhân`.
- **Admin (9 mục)**: `System Dashboard` (`/admin/system`), `Quản lý tài khoản` (`/admin/accounts` – 5 vai trò), `Phân quyền` (`/admin/rbac`), `Nhật ký kiểm toán` (`/admin/audit` – Activity + Query Audit), `Cấu hình hệ thống` (`/admin/config`), `Kho tài liệu RAG` (`/admin/rag`), `Thiết bị` (`/admin/kiosk`), `Cấu hình` (`/admin/kiosk/config`), `Hồ sơ cá nhân`.

---

## 7. Database và migration đã thay đổi

- **Schema & Migration (`schema.sql`, `schema_postgres.sql`, `migrations.py`, `seed.py`)**:
  - Giữ nguyên cấu trúc 21 bảng SQLite và 27 bảng Supabase PostgreSQL (không tạo bảng trùng, không xóa dữ liệu hiện hữu).
  - Bổ sung `revoked_tokens` vào danh sách dọn bảng của `seed_database(reset=True)`.
  - Xác minh trực tiếp trên **SQLite (`backend/hr_attendance.db`)**: `roles=5`, `permissions=44`, `user_roles` khớp 1:1 với `employees.role` (`drift=0`, `dup_ur=0`).
  - Xác minh trực tiếp trên **Live Supabase PostgreSQL**: `roles=5`, `permissions=44`, `drift=0`, `dup_ur=0`, **27/27 bảng `public` bật RLS**, **4/4 view bật `security_invoker=true`**, bảo toàn nguyên vẹn tài khoản `admin@company.vn` và `director@company.vn`.

---

## 8. Kết quả kiểm thử thực tế

| Hạng mục | Lệnh thực thi | Trạng thái | Kết quả đo thực tế |
|---|---|---|---|
| Backend Full Pytest Suite | `cd backend; python -m pytest -v` | **PASS** | **65 passed, 0 failed, 0 skipped** (`48.48s`) — gồm 60 test cũ + 5 test mới trong `test_rbac_completion.py` |
| Frontend Vitest Suite | `cd frontend; npm test -- --run` | **PASS** | **27 passed, 0 failed, 0 skipped** (`4/4` files, `6.38s`) — gồm 21 test cũ + 6 test mới trong `RbacCompletion.test.tsx` |
| Frontend TypeScript & Production Build | `cd frontend; npm run build` | **PASS** | `tsc -b && vite build` thành công trong `6.99s`, **0 lỗi TS**, **0 cảnh báo chunk > 500 kB** (`index`: `43.14 kB`) |
| Dual-DB RBAC Integrity & Live Supabase E2E | `verify_rbac_dual_db.py` (SQLite + Live Supabase PostgreSQL) | **PASS** | SQLite & Live Supabase đều `roles=5, perms=44, drift=0, dup_ur=0`; Supabase `RLS=27/27`; cả 3 lỗi cấm tuyệt đối bị chặn `403` trực tiếp trên Supabase |

---

## 9. Các chức năng còn thiếu (Phân loại trung thực)

| Hạng mục | Phân loại | Ghi chú thực tế |
|---|---|---|
| Hệ thống RBAC 5 vai trò (Backend + Frontend + SQLite + Supabase RLS) | **PASS** | Hoàn thiện & kiểm chứng đầy đủ 92/92 test + live Supabase. |
| Kho tài liệu RAG (`/admin/rag`) | **PARTIAL** | Đã có CRUD/chunk/re-index; **chưa nối bước tìm kiếm (retrieval/embedding) vào `ai_assistant.py`**. |
| Face Recognition Kiosk (`/admin/kiosk`, `face_*` tables) | **PARTIAL** | Đã có schema PostgreSQL + màn hình quản trị thiết bị/ngưỡng Kiosk cho Admin; **chưa có InsightFace, đăng ký khuôn mặt hay webcam check-in**. |
| Giao diện CRUD Phòng ban & Ca làm việc (`attendance_policies`) | **NOT IMPLEMENTED** | Hiện mới có API đọc phòng ban (`/api/departments`) và bảng `attendance_policies` ở PostgreSQL; chưa có màn hình CRUD riêng nên không tạo menu giả. |
| Luồng tự gửi đơn tăng ca (`overtime_requests`) & Hộp thư thông báo (`notifications`) | **NOT IMPLEMENTED** | Bảng đã có ở schema (và `overtime_requests` được dùng trong `R7`/Import), chưa có API/UI người dùng cuối. |

---

## 10. Các rủi ro chưa xử lý

1. **Chưa có Rate Limiting / Brute-force Lockout** trên `/api/auth/login` và `/api/assistant/ask` (nên bổ sung ở reverse proxy hoặc middleware Redis khi lên production).
2. **Access Token lưu tại `localStorage`** (chưa áp dụng Refresh Token rotation với `HttpOnly` cookie).
3. **Kiểm thử click-through trực quan trên trình duyệt thật sau bản build mới** (`BLOCKED / NOT RE-RUN IN THIS BATCH`): Toàn bộ 27 component/router test Vitest + `tsc -b` + `vite build` đều PASS và không đổi design system, nhưng khuyến nghị QA chạy thêm 1 lượt kiểm tra trực quan 5 vai trò trên trình duyệt trước khi go-live.

---

## 11. Hướng dẫn đăng nhập và kiểm tra từng role

> **Lưu ý bảo mật:** Không lưu mật khẩu trong tài liệu công khai. Mật khẩu tài khoản seed local được cấu hình qua biến môi trường `DEV_SEED_PASSWORD` trong `backend/.env` (chỉ dùng cho môi trường phát triển/demo; khi lên production bắt buộc đặt `APP_ENV=production` và đổi toàn bộ mật khẩu).

| Vai trò | Email đăng nhập (Local/Dev) | Trang mặc định sau đăng nhập | Kịch bản kiểm tra nhanh |
|---|---|---|---|
| **Employee** | `nv007@company.vn` | `/dashboard` | Kiểm tra phạm vi `Dữ liệu cá nhân`; thử mở trực tiếp `/admin/employees`, `/reports`, `/admin/accounts` → thấy `403` và API trả `403`. |
| **Manager** | `manager.sales@company.vn` | `/dashboard` | Kiểm tra phạm vi `Phòng ban của tôi`; xem `Quản lý nhân viên` không có nút `Thêm nhân viên`; tạo đơn phép cá nhân và thử tự duyệt → bị chặn `403`; thử lọc `DEPT_TECH` → `403`. |
| **HR** | `hr@company.vn` | `/dashboard` | Kiểm tra `Quản lý nhân viên` thấy nhãn `Được bảo vệ` trên `NV079`/`NV080`; mở Drawer một bản ghi chấm công của `NV007` thấy form `Điều chỉnh chấm công nghiệp vụ (HR)` (không thấy trên dòng của `NV002`); thử mở `/admin/rbac`, `/admin/config` → `403`. |
| **Executive** | `director@company.vn` | `/dashboard` (`Tổng quan điều hành`) | Kiểm tra Sidebar có 7 mục (không có `Chấm công`, `Nhập dữ liệu`, `Quản lý nhân viên`, `Tài khoản`, `Phân quyền`); mở `Đơn cần phê duyệt` chỉ duyệt được đơn gắn `Cấp BGĐ`; thử `PATCH /api/attendance/*` → `403`. |
| **Admin** | `admin@company.vn` | `/admin/system` (`System Dashboard`) | Kiểm tra Sidebar chỉ có các mục quản trị kỹ thuật & `Hồ sơ cá nhân` (không có menu nghiệp vụ HR); vào `Phân quyền` kiểm tra 5 role × 44 quyền; thử tự khóa `USR080` → bị chặn `400`; thử mở `/attendance`, `/leaves`, `/reports` → `403`. |
