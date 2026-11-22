# Báo cáo Nghiệm thu Người dùng (UAT – User Acceptance Testing)

- **Dự án**: HR Attendance Copilot
- **Ngày kiểm thử UAT**: `21/11/2026`
- **Môi trường kiểm thử**: Frontend Vite (`http://127.0.0.1:5173`), Backend FastAPI (`http://127.0.0.1:8000`), Database SQLite (`backend/hr_attendance.db` seed `2026`).
- **Kết luận tổng quan**: **CONDITIONAL PASS (Đạt nghiệm thu, 0 Critical / 0 High / 0 Medium; 2 lỗi nhỏ mức Low mới phát hiện: `BUG-11`, `BUG-12`)**.

## 1. Tóm tắt kết quả 8 hạng mục UAT

| # | Hạng mục UAT | Kết quả | Chi tiết xác thực |
|---|---|---|---|
| 1 | Giao diện 3 tài khoản (`Employee`, `Manager`, `HR`) | **PASS** | Menu 10/8/6 màn hình đúng RBAC; Login split-screen 1 khung hình desktop (`scrollHeight=900`). |
| 2 | Luồng nghiệp vụ E2E từ đầu đến cuối | **PASS (6/6)** | Leave create/cancel/reject(400+200)/approve+sync `attendance`, Anomaly review+rescan, Profile+change password, Employee soft-deactivate, Account last-HR protection (`400`). |
| 3 | Kiểm thử 24 câu hỏi AI | **23/24 PASS** | 10/10 HR, 5/5 Manager, 4/4 Employee, 4/5 Guard/Edge — Q21 (`"Chấm công"`) phát hiện **`BUG-11` (Low)**. |
| 4 | Kiểm thử SQL Guard (≥ 15 SQL độc hại) | **PASS (30/30)** | 30/30 truy vấn độc hại bị chặn hoàn toàn bởi `SQLGuardError`. |
| 5 | Kiểm thử Upload CSV / XLSX | **PASS** | Tải mẫu `.xlsx`, preview CSV thật trên trình duyệt (`4` dòng: `1` hợp lệ, `1` trùng, `2` lỗi gồm `NV999` & Formula Injection `=CMD\|...`), xác nhận `.csv`/`.xlsx` và rollback giao dịch. |
| 6 | Kiểm thử Xuất PDF / Excel | **PASS** | `Cross-check khớp 17 số liệu SQL`, tải thật `bao_cao_cham_cong_2026-10.pdf` (`87.3 KB`) & `.xlsx` 4 sheet (`9.9 KB`), Manager chỉ 1 phòng, Employee chặn `403`. |
| 7 | Kiểm thử 3 màn hình: Hồ sơ (`07`), Nhập dữ liệu (`08`), Quản lý tài khoản (`10`) | **PASS** *(có `BUG-12` Low)* | Đủ chức năng cập nhật SĐT, preview CSV lỗi, danh sách 80 tài khoản + tab `Nhật ký hoạt động` xem JSON trước/sau. |
| 8 | Kiểm thử Responsive (`390×844`) & Lỗi trình duyệt | **PASS** | 0 phần tử tràn ngang trên Login/Dashboard/Profile Mobile, mở/đóng Drawer mượt, 0 lỗi JS console ứng dụng. |

## 2. Lỗi mới phát hiện trong UAT

1. **`BUG-11` (Low)** – `backend/app/services/ai_assistant.py#L312`: Câu hỏi quá ngắn/mơ hồ 2 từ như `"Chấm công"` (9 ký tự có dấu) vượt qua ngưỡng `len(q_clean) < 8` nên chạy mặc định kỳ `2026-10` thay vì trả `clarification_needed`.
2. **`BUG-12` (Low)** – `frontend/src/pages/ProfilePage.tsx#L126`: Khối avatar chữ cái `w-14 h-14` thiếu `shrink-0`, bị co hẹp chiều ngang ở màn hình Mobile `390×844`.
