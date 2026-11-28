# Tài liệu Phân quyền RBAC 5 Vai trò & Bảo mật API — HR Attendance Copilot

Tài liệu này mô tả kiến trúc phân quyền **5 vai trò chuẩn doanh nghiệp** (`employee`, `manager`, `hr`, `executive`, `admin`), ma trận quyền chi tiết (`permissions`), kiểm soát truy cập API phía Backend, lớp bảo vệ `AI SQL Guard`, và quy trình migration an toàn không mất dữ liệu.

---

## 1. Nguyên tắc kiến trúc tách bạch vai trò

```text
Employee  = Dữ liệu cá nhân (self-service)
Manager   = Quản lý nghiệp vụ trong phòng ban phụ trách (department scope)
HR        = Quản trị nghiệp vụ nhân sự toàn công ty (Business Administration)
Executive = Ban điều hành: phân tích toàn công ty & phê duyệt cấp cao (Executive Oversight)
Admin     = Quản trị kỹ thuật hệ thống: tài khoản, RBAC, audit, RAG, Kiosk (Technical Administration)
```

**Chốt chặn bảo mật cốt lõi:**
1. **Admin ≠ HR**: Vai trò `admin` không mặc định được cấp quyền đọc/sửa dữ liệu chấm công, đơn nghỉ phép, hồ sơ nhân sự nghiệp vụ, báo cáo HR hay truy vấn AI nghiệp vụ (`403 Forbidden` + `SQLGuardError`).
2. **HR ≠ System Admin**: Vai trò `hr` không được phép nâng quyền lên `admin`/`executive`, không được sửa hoặc khóa tài khoản `admin`/`executive`, không được truy cập ma trận RBAC (`/api/rbac/*`), cấu hình hệ thống (`/api/system/config`), thiết bị Kiosk (`/api/kiosk/*`), hay nhật ký truy vấn kỹ thuật (`/api/audit/queries`).
3. **Executive ≠ HR/Admin**: Vai trò `executive` có quyền xem phân tích & báo cáo toàn công ty, hỏi AI chiến lược và phê duyệt các đơn được đánh dấu `requires_executive_approval = true`; bị chặn `403` khi cố sửa chấm công, import Excel, duyệt đơn thường, xử lý cảnh báo R1–R8 hay quản trị tài khoản/hệ thống.
4. **Chống tự khóa quản trị cuối cùng**: Backend chặn tuyệt đối thao tác khóa hoặc hạ quyền tài khoản `admin` hoạt động cuối cùng (kể cả tự khóa chính mình), tài khoản `hr` hoạt động cuối cùng, và chặn gỡ 3 quyền cốt lõi (`role.manage`, `account.manage`, `system.dashboard`) khỏi vai trò `admin`.
5. **Tải quyền tươi từ CSDL ở mỗi request**: JWT chỉ lưu danh tính (`sub`, `emp`, `jti`); mỗi API request đều tải lại `role`, trạng thái `is_active` và danh sách `permissions` trực tiếp từ CSDL (`load_authenticated_user`).

---

## 2. Ma trận 5 Vai trò & Phạm vi Dữ liệu

| Vai trò (`role_code`) | Tên hiển thị | Phạm vi dữ liệu (`Data Scope Indicator`) | Quyền chính | Giới hạn / Bảo vệ |
|---|---|---|---|---|
| `employee` | Nhân viên | `Dữ liệu cá nhân` | Xem công cá nhân, chấm công khuôn mặt, tạo/hủy đơn phép cá nhân, xem cảnh báo cá nhân (`scope_type='employee'`), hỏi AI cá nhân, xem/cập nhật hồ sơ cá nhân | Không xem người khác/phòng khác, không xem báo cáo, không duyệt đơn, không truy cập quản trị |
| `manager` | Trưởng phòng | `Phòng ban của tôi` | Dashboard phòng, chấm công & nhân sự phòng (chỉ xem), duyệt đơn nhân viên phòng mình, quét & xử lý cảnh báo R1–R8 phòng, báo cáo & AI phòng mình | Không xem phòng ban khác (kể cả REST/Report/Export/AI), không tự duyệt đơn mình, không duyệt đơn cấp quản lý, không quản trị tài khoản/hệ thống |
| `hr` | Nhân sự | `Toàn công ty` | Quản lý hồ sơ NV, xem & điều chỉnh chấm công (`PATCH /api/attendance/{id}`), Import Excel/CSV, quản lý & duyệt đơn phép, xử lý R1–R8, báo cáo PDF/Excel & AI toàn công ty, quản lý tài liệu RAG nghiệp vụ, quản lý tài khoản nhóm nghiệp vụ (`employee`/`manager`/`hr`), xem audit nghiệp vụ | Không quản trị `admin`/`executive`, không nâng quyền lên `admin`/`executive`, không truy cập `/api/rbac/*`, `/api/system/*`, `/api/kiosk/*`, `/api/audit/queries` |
| `executive` | Cấp lãnh đạo | `Toàn công ty` | Dashboard điều hành, Phân tích & so sánh phòng ban, xem toàn bộ cảnh báo R1–R8 (chỉ đọc), xuất báo cáo PDF/Excel toàn công ty/theo phòng, hỏi đáp AI chiến lược (xu hướng 3 tháng, so sánh phòng, rủi ro nổi bật), phê duyệt đơn đánh dấu `requires_executive_approval = true` | Không sửa chấm công, không duyệt đơn thường, không quét/xử lý R1–R8, không import Excel, không quản lý nhân sự/tài khoản/RBAC/cấu hình hệ thống |
| `admin` | Quản trị hệ thống | `Quản trị hệ thống` | System Dashboard, quản lý toàn bộ tài khoản 5 vai trò (bảo vệ Admin cuối cùng), quản lý ma trận vai trò & quyền RBAC (`/api/rbac/*`), xem toàn bộ Activity Logs & Query Audit Logs, quản lý kho tài liệu RAG, quản lý cấu hình hệ thống (phi-secret) & thiết bị/cấu hình Face Kiosk | Không mặc định đọc/sửa chấm công, không duyệt phép, không xử lý R1–R8, không xem báo cáo HR, không truy vấn AI nghiệp vụ HR |

---

## 3. Danh mục Quyền (Permissions) chuẩn hóa

Danh mục đầy đủ được định nghĩa tại [`backend/app/core/permissions.py`](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/core/permissions.py) và lưu trong bảng `permissions` + `role_permissions`:

- **Hồ sơ**: `profile.read.self`, `profile.update.self`
- **Dashboard**: `dashboard.self`, `dashboard.department`, `dashboard.all`, `dashboard.executive`, `system.dashboard`
- **Chấm công**: `attendance.read.self`, `attendance.read.department`, `attendance.read.all`, `attendance.adjust`, `attendance.face_checkin`
- **Nghỉ phép**: `leave.create.self`, `leave.read.self`, `leave.read.department`, `leave.read.all`, `leave.approve.department`, `leave.approve.all`, `leave.approve.executive`
- **Cảnh báo R1–R8**: `anomaly.read.self`, `anomaly.read.department`, `anomaly.read.all`, `anomaly.review`
- **Nhân sự & Import**: `employee.read.department`, `employee.read.all`, `employee.manage`, `import.manage`
- **Báo cáo**: `report.read.department`, `report.read.all`
- **AI Assistant**: `ai.ask.self`, `ai.ask.department`, `ai.ask.all`, `ai.strategy`
- **Quản trị & Kiểm toán & Kỹ thuật**: `account.manage`, `account.manage.business`, `role.manage`, `audit.read`, `audit.read.business`, `rag.manage`, `document.manage`, `policy.manage`, `face.manage`, `kiosk.manage`, `system.manage`

---

## 4. Ma trận Bảo mật API (`/api`)

| Endpoint | Phương thức | Permission yêu cầu (Backend) | Vai trò mặc định được phép |
|---|---|---|---|
| `/api/dashboard/summary` | `GET` | `dashboard.self` \| `dashboard.department` \| `dashboard.all` \| `dashboard.executive` | `employee`, `manager`, `hr`, `executive` (**Admin → 403**) |
| `/api/attendance` & `/api/attendance/{id}` | `GET` | `attendance.read.self` \| `.department` \| `.all` | `employee`, `manager`, `hr`, `executive` (**Admin → 403**) |
| `/api/attendance/{id}` | `PATCH` | `attendance.adjust` | Chỉ `hr` (**Executive/Admin/Manager/Employee → 403**) |
| `/api/leaves` & `/api/leaves/{id}` | `GET` | `leave.read.self` \| `.department` \| `.all` | `employee`, `manager`, `hr`, `executive` (**Admin → 403**) |
| `/api/leaves` & `/api/leaves/{id}/cancel` | `POST` | `leave.create.self` | `employee`, `manager`, `hr` |
| `/api/leaves/{id}/review` | `POST` | `leave.approve.department` \| `.all` \| `.executive` | `manager` (NV phòng), `hr` (toàn công ty), `executive` (chỉ đơn `requires_executive_approval=true`) |
| `/api/anomalies` & `/api/anomalies/{id}` | `GET` | `anomaly.read.self` \| `.department` \| `.all` | `employee` (cá nhân), `manager` (phòng), `hr`, `executive` (**Admin → 403**) |
| `/api/anomalies/scan` & `/api/anomalies/{id}/review` | `POST` | `anomaly.review` | `manager` (phòng mình), `hr` (**Executive/Admin/Employee → 403**) |
| `/api/reports/preview`, `/export/excel`, `/export/pdf` | `GET` | `report.read.department` \| `report.read.all` | `manager` (phòng mình), `hr`, `executive` (**Employee/Admin → 403**) |
| `/api/employees` | `GET` | `employee.read.department` \| `.all` \| `.manage` | `manager` (phòng), `hr`, `executive` (**Employee/Admin → 403**) |
| `/api/employees` & `/api/employees/{id}` | `POST`/`PATCH` | `employee.manage` | Chỉ `hr` (cấm gán/sửa vai trò `admin`/`executive`) |
| `/api/imports/*` | `GET`/`POST` | `import.manage` | Chỉ `hr` (**Executive/Admin/Manager/Employee → 403**) |
| `/api/assistant/ask`, `/suggestions`, `/history` | `POST`/`GET` | `ai.ask.self` \| `.department` \| `.all` \| `ai.strategy` | `employee`, `manager`, `hr`, `executive` (**Admin → 403**) |
| `/api/admin/system-dashboard` | `GET` | `system.dashboard` | Chỉ `admin` |
| `/api/accounts`, `/api/accounts/unlinked-employees`, `/api/accounts/{id}` | `GET`/`POST`/`PATCH` | `account.manage` \| `account.manage.business` | `admin` (đủ 5 vai trò + bảo vệ Admin cuối); `hr` (chỉ `employee`/`manager`/`hr`, cấm `admin`/`executive`) |
| `/api/rbac/roles`, `/api/rbac/permissions`, `/api/rbac/roles/{code}/permissions` | `GET`/`PATCH` | `role.manage` | Chỉ `admin` |
| `/api/audit/activity` | `GET` | `audit.read` \| `audit.read.business` | `admin` (toàn hệ thống), `hr` (chỉ nghiệp vụ HR) |
| `/api/audit/queries` | `GET` | `audit.read` | Chỉ `admin` |
| `/api/rag/documents`, `/{id}/reindex`, `/{id}` | `GET`/`POST`/`DELETE` | `rag.manage` | `admin`, `hr` |
| `/api/system/config` | `GET`/`PATCH` | `system.manage` | Chỉ `admin` (từ chối mọi key chứa `secret`/`password`/`api_key`/`token`) |
| `/api/kiosk/devices` & `/api/kiosk/devices/{id}` | `GET`/`POST`/`PATCH` | `kiosk.manage` | Chỉ `admin` |

---

## 5. Kiến trúc AI SQL Guard (5 Vai trò)

Luồng thực thi bắt buộc cho mọi câu hỏi AI (tuyệt đối không để LLM tự chạy SQL tự do):

```text
User -> /api/assistant/ask (require_permissions)
  -> AI Assistant (Prompt Injection + Out-of-scope + 5-Role RBAC Guard)
  -> Intent Router (Employee / Manager / HR / Executive Strategic)
  -> Parameterized SQL Tool (build_scope_filter)
  -> SQL Guard (Allowlist 4 TEMP Views + Read-Only + Timeout + Max 200 rows; Admin DENIED)
  -> Database (SQLite / Supabase PostgreSQL)
  -> query_audit_log (user_id, role, question, query_type, tool_name, sql_text, scope, row_count, success, status)
  -> AI Response
```

---

## 6. Migration An toàn (Không xóa dữ liệu)

Để nâng cấp một CSDL hiện có (SQLite 3-role cũ hoặc Supabase PostgreSQL) lên RBAC 5 vai trò mà **không mất dữ liệu**:

```powershell
cd backend
python -m app.db.migrations
```

Script [`backend/app/db/migrations.py`](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/db/migrations.py) kiểm tra schema hiện tại và chỉ chạy `ALTER TABLE` / `CREATE TABLE IF NOT EXISTS` / copy an toàn giữ nguyên 100% bản ghi hiện hữu.
