from __future__ import annotations

from typing import Dict, List, Tuple

# Canonical 5 enterprise roles
ROLE_CATALOG: List[Tuple[str, str, str]] = [
    ("employee", "Nhân viên", "Xem và thao tác dữ liệu cá nhân"),
    ("manager", "Trưởng phòng", "Quản lý dữ liệu, duyệt phép và xử lý cảnh báo trong phòng ban"),
    ("hr", "Nhân sự", "Quản trị nghiệp vụ nhân sự toàn công ty (tách biệt quản trị hệ thống)"),
    ("executive", "Cấp lãnh đạo", "Ban điều hành: xem tổng quan, phân tích toàn công ty và phê duyệt cấp cao"),
    ("admin", "Quản trị hệ thống", "Quản trị kỹ thuật: tài khoản, phân quyền, kiểm toán, RAG và cấu hình hệ thống"),
]

# Canonical permission catalog (preserving existing schema_postgres.sql dot-notation convention)
PERMISSION_CATALOG: List[Tuple[str, str, str]] = [
    ("profile.read.self", "Xem hồ sơ cá nhân", "Xem thông tin hồ sơ của chính người dùng"),
    ("profile.update.self", "Cập nhật hồ sơ cá nhân", "Cập nhật thông tin liên hệ được phép và đổi mật khẩu"),
    ("dashboard.self", "Tổng quan cá nhân", "Xem bảng điều khiển phạm vi cá nhân"),
    ("dashboard.department", "Tổng quan phòng ban", "Xem bảng điều khiển phạm vi phòng ban"),
    ("dashboard.all", "Tổng quan toàn công ty", "Xem bảng điều khiển chấm công toàn công ty"),
    ("dashboard.executive", "Tổng quan điều hành", "Xem dashboard điều hành và phân tích so sánh phòng ban"),
    ("system.dashboard", "System Dashboard", "Xem bảng điều khiển kỹ thuật, tài khoản và trạng thái hệ thống"),
    ("attendance.read.self", "Xem chấm công cá nhân", "Xem dữ liệu chấm công của bản thân"),
    ("attendance.read.department", "Xem chấm công phòng ban", "Xem dữ liệu chấm công trong phòng được quản lý"),
    ("attendance.read.all", "Xem chấm công toàn công ty", "Xem dữ liệu chấm công toàn công ty"),
    ("attendance.adjust", "Điều chỉnh chấm công", "Điều chỉnh công nghiệp vụ có lý do và nhật ký"),
    ("attendance.face_checkin", "Chấm công khuôn mặt", "Thực hiện chấm công cá nhân qua nhận diện khuôn mặt"),
    ("leave.create.self", "Tạo đơn nghỉ phép", "Tạo và hủy đơn nghỉ phép cho bản thân"),
    ("leave.read.self", "Xem đơn nghỉ phép cá nhân", "Xem đơn nghỉ phép của bản thân"),
    ("leave.read.department", "Xem đơn nghỉ phép phòng ban", "Xem đơn nghỉ phép trong phòng"),
    ("leave.read.all", "Xem đơn nghỉ phép toàn công ty", "Xem đơn nghỉ phép toàn công ty"),
    ("leave.approve.department", "Duyệt đơn phòng ban", "Duyệt đơn nhân viên thuộc phòng ban quản lý"),
    ("leave.approve.all", "Duyệt đơn toàn công ty", "Duyệt đơn toàn công ty và xử lý ngoại lệ HR"),
    ("leave.approve.executive", "Phê duyệt cấp cao", "Phê duyệt đơn được đánh dấu requires_executive_approval = true"),
    ("anomaly.read.self", "Xem cảnh báo cá nhân", "Xem cảnh báo bất thường cấp cá nhân của bản thân"),
    ("anomaly.read.department", "Xem cảnh báo phòng ban", "Xem cảnh báo bất thường trong phòng ban"),
    ("anomaly.read.all", "Xem cảnh báo toàn công ty", "Xem toàn bộ cảnh báo R1-R8 toàn công ty"),
    ("anomaly.review", "Xử lý cảnh báo", "Xác nhận hoặc bỏ qua cảnh báo R1-R8 theo phạm vi"),
    ("employee.read.department", "Xem nhân viên phòng ban", "Xem danh sách nhân viên trong phòng ban"),
    ("employee.read.all", "Xem nhân viên toàn công ty", "Xem danh sách nhân sự toàn công ty"),
    ("employee.manage", "Quản lý nhân viên", "Thêm, sửa và ngừng hoạt động hồ sơ nhân viên"),
    ("import.manage", "Nhập dữ liệu Excel/CSV", "Nhập dữ liệu chấm công/nhân sự và xử lý trùng"),
    ("report.read.department", "Xem báo cáo phòng ban", "Xem và xuất báo cáo PDF/Excel trong phòng ban"),
    ("report.read.all", "Xem báo cáo toàn công ty", "Xem và xuất báo cáo PDF/Excel toàn công ty"),
    ("ai.ask.self", "Hỏi đáp AI cá nhân", "Hỏi đáp AI trong phạm vi dữ liệu bản thân"),
    ("ai.ask.department", "Hỏi đáp AI phòng ban", "Hỏi đáp AI trong phạm vi phòng ban"),
    ("ai.ask.all", "Hỏi đáp AI toàn công ty", "Hỏi đáp AI toàn công ty"),
    ("ai.strategy", "Hỏi đáp AI chiến lược", "Hỏi đáp AI phân tích xu hướng và so sánh điều hành toàn công ty"),
    ("account.manage", "Quản lý tài khoản hệ thống", "Tạo, khóa, mở khóa, reset và gán mọi vai trò (5 roles)"),
    ("account.manage.business", "Quản lý tài khoản nghiệp vụ HR", "Quản lý tài khoản nhóm nghiệp vụ (employee/manager/hr), cấm nâng quyền admin/executive"),
    ("role.manage", "Quản lý vai trò và phân quyền", "Xem và cấu hình ma trận vai trò - quyền RBAC"),
    ("audit.read", "Xem nhật ký kiểm toán hệ thống", "Xem toàn bộ activity logs và query audit logs"),
    ("audit.read.business", "Xem nhật ký nghiệp vụ HR", "Xem nhật ký thao tác nghiệp vụ nhân sự"),
    ("rag.manage", "Quản lý kho tài liệu RAG", "Upload, xóa, re-index và theo dõi trạng thái kho tri thức RAG"),
    ("document.manage", "Quản lý tài liệu nội bộ", "Tải lên và quản lý tài liệu nội bộ"),
    ("policy.manage", "Quản lý quy định chấm công", "Tạo và cập nhật chính sách chấm công nghiệp vụ"),
    ("face.manage", "Quản lý hồ sơ khuôn mặt", "Đăng ký, cập nhật và thu hồi hồ sơ khuôn mặt nhân viên"),
    ("kiosk.manage", "Quản lý Face Kiosk", "Quản lý thiết bị và cấu hình kỹ thuật Face Kiosk"),
    ("system.manage", "Quản trị cấu hình hệ thống", "Quản lý thiết lập hệ thống, AI provider, embedding và sức khỏe hệ thống"),
]

ALL_PERMISSION_CODES = {code for code, _, _ in PERMISSION_CATALOG}

# Default strict RBAC role -> permissions mapping.
# KEY PRINCIPLE:
# - HR = Business Administration (cannot manage admin/executive roles, RBAC matrix, system config, or query audit)
# - Executive = Executive Oversight (company-wide read-only + strategic AI + executive approval only)
# - Admin = Technical Administration (NO default HR business data read/write scope!)
DEFAULT_ROLE_PERMISSIONS: Dict[str, List[str]] = {
    "employee": [
        "profile.read.self",
        "profile.update.self",
        "dashboard.self",
        "attendance.read.self",
        "attendance.face_checkin",
        "leave.create.self",
        "leave.read.self",
        "anomaly.read.self",
        "ai.ask.self",
    ],
    "manager": [
        "profile.read.self",
        "profile.update.self",
        "dashboard.department",
        "attendance.read.self",
        "attendance.read.department",
        "attendance.face_checkin",
        "leave.create.self",
        "leave.read.self",
        "leave.read.department",
        "leave.approve.department",
        "employee.read.department",
        "anomaly.read.self",
        "anomaly.read.department",
        "anomaly.review",
        "report.read.department",
        "ai.ask.department",
    ],
    "hr": [
        "profile.read.self",
        "profile.update.self",
        "dashboard.all",
        "attendance.read.all",
        "attendance.adjust",
        "attendance.face_checkin",
        "leave.create.self",
        "leave.read.all",
        "leave.approve.all",
        "employee.read.all",
        "employee.manage",
        "import.manage",
        "anomaly.read.all",
        "anomaly.review",
        "report.read.all",
        "ai.ask.all",
        "rag.manage",
        "document.manage",
        "policy.manage",
        "face.manage",
        "account.manage.business",
        "audit.read.business",
    ],
    "executive": [
        "profile.read.self",
        "profile.update.self",
        "dashboard.all",
        "dashboard.executive",
        "attendance.read.all",
        "leave.read.all",
        "leave.approve.executive",
        "employee.read.all",
        "anomaly.read.all",
        "report.read.all",
        "ai.ask.all",
        "ai.strategy",
    ],
    "admin": [
        "profile.read.self",
        "profile.update.self",
        "system.dashboard",
        "account.manage",
        "role.manage",
        "audit.read",
        "rag.manage",
        "document.manage",
        "system.manage",
        "kiosk.manage",
    ],
}

# Permissions that HR is NEVER allowed to grant or operate on via business scope
RESTRICTED_SYSTEM_PERMISSIONS = {
    "role.manage",
    "system.manage",
    "system.dashboard",
    "kiosk.manage",
    "account.manage",
    "audit.read",
}

DEFAULT_SYSTEM_SETTINGS: List[Tuple[str, str, str, str, str]] = [
    ("ai.provider", "ai", "hybrid_sql_guard", "string", "Nhà cung cấp mô hình AI đang kích hoạt (hybrid_sql_guard / openai / gemini)"),
    ("ai.model_name", "ai", "gpt-4o-mini", "string", "Tên mô hình ngôn ngữ mặc định (không lưu API key tại bảng này)"),
    ("ai.sql_max_rows", "ai", "200", "integer", "Số dòng tối đa SQL Guard cho phép trả về"),
    ("ai.sql_timeout_seconds", "ai", "3", "integer", "Thời gian timeout tối đa cho truy vấn SQL Guard (giây)"),
    ("embedding.provider", "embedding", "local_bm25_hybrid", "string", "Cơ chế embedding/indexing cho kho tài liệu RAG"),
    ("embedding.model_name", "embedding", "text-embedding-3-small", "string", "Mô hình vector embedding cho tài liệu nội bộ"),
    ("embedding.chunk_size", "embedding", "600", "integer", "Kích thước đoạn văn bản (chunk size) khi tách tài liệu RAG"),
    ("kiosk.model_name", "kiosk", "buffalo_l", "string", "Mô hình nhận diện khuôn mặt Face Kiosk (InsightFace)"),
    ("kiosk.similarity_threshold", "kiosk", "0.62", "number", "Ngưỡng tương đồng cosine tối thiểu để xác nhận chấm công"),
    ("kiosk.liveness_required", "kiosk", "true", "boolean", "Bắt buộc kiểm tra người thật (liveness) khi chấm công khuôn mặt"),
    ("workflow.executive_approval_enabled", "workflow", "true", "boolean", "Cho phép Cấp lãnh đạo phê duyệt các đơn đánh dấu requires_executive_approval = true"),
    ("security.audit_retention_days", "security", "365", "integer", "Số ngày lưu giữ nhật ký kiểm toán activity_logs và query_audit_log"),
]

DEFAULT_KIOSK_DEVICES: List[Tuple[str, str, str, str, int]] = [
    ("KIOSK-HQ-01", "Cổng chính Tầng 1", "Sảnh lễ tân HQ", "Trụ sở chính Hà Nội", 1),
    ("KIOSK-HQ-02", "Khu Văn phòng Tầng 5", "Cửa thang máy Kỹ thuật", "Trụ sở chính Hà Nội", 1),
]

DEFAULT_RAG_DOCUMENTS: List[Tuple[str, str, str, str, str, str, str]] = [
    (
        "Nội quy lao động Công ty 2026",
        "noi_quy_lao_dong_2026.md",
        "hr-documents",
        "policies/noi_quy_lao_dong_2026.md",
        "policy",
        "v2.0",
        "active",
    ),
    (
        "Quy chế chấm công, đi muộn và nghỉ phép",
        "quy_che_cham_cong_nghi_phep.md",
        "hr-documents",
        "policies/quy_che_cham_cong_nghi_phep.md",
        "attendance_policy",
        "v1.4",
        "active",
    ),
    (
        "Cẩm nang định nghĩa và quy trình xử lý cảnh báo R1-R8",
        "cam_nang_canh_bao_r1_r8.md",
        "hr-documents",
        "policies/cam_nang_canh_bao_r1_r8.md",
        "anomaly_guide",
        "v1.1",
        "active",
    ),
]


def get_default_permissions_for_role(role_code: str) -> List[str]:
    return list(DEFAULT_ROLE_PERMISSIONS.get(role_code, []))
