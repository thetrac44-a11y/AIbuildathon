# HƯỚNG DẪN THIẾT KẾ & SỬ DỤNG AI ASSISTANT UI/UX — HR ATTENDANCE COPILOT

- **Đối tượng:** Người dùng nghiệp vụ (Employee, Manager, HR, Executive), Quản trị hệ thống (Admin) và đội ngũ bảo trì Frontend.
- **Hệ thống thiết kế (Design System):** Kế thừa nhất quán bảng màu SaaS Enterprise hiện hành (`brand-navy #102A43`, `brand-blue #2563EB`, `brand-teal #0F9D9A`, `brand-green #15803D`, `brand-amber #B45309`, `brand-red #B91C1C`, nền `brand-bg #F4F7FB`, viền `brand-border #E4EAF2`, bo góc `rounded-card 12px`).

---

## 1. Bố cục Không gian làm việc (Chat Workspace)

- **Desktop (`>= 1024px`):** Bố cục 2 cột tỉ lệ `3 : 9` (`ConversationSidebar` bên trái cố định chiều cao khung nhìn + `Chat Workspace` bên phải cuộn độc lập).
- **Tablet & Mobile (`< 1024px`):** Tự động chuyển về 1 cột rộng tối ưu; nút **"Lịch sử"** ngay trên thanh tiêu đề mở ngăn kéo trượt (slide-over drawer) để quản lý hội thoại mà không chiếm diện tích đọc.
- **Thanh tiêu đề theo vai trò (Role Scope Header):** Luôn hiển thị tên Trợ lý theo vai trò, badge phạm vi dữ liệu thực tế, kỳ làm việc đang chọn (`selectedPeriod`) và badge **"Chỉ đọc · Xác minh số liệu"**.

---

## 2. Trải nghiệm chuyên biệt theo 5 Vai trò RBAC

| Vai trò | Tiêu đề Workspace | Badge Phạm vi dữ liệu | Trọng tâm hỗ trợ AI |
| --- | --- | --- | --- |
| **Employee** | Trợ lý AI Cá nhân | `Dữ liệu cá nhân · NVxxx` | Lịch sử đi muộn, giờ công, quỹ phép năm, đơn chờ duyệt của cá nhân và quy định công ty |
| **Manager** | Trợ lý AI Phòng ban | `Phòng <Tên phòng>` | Tổng hợp & so sánh kỳ trong phòng, đơn phép chờ duyệt, cảnh báo R1–R8 phòng ban & quy trình xử lý |
| **HR** | Trợ lý AI Nghiệp vụ Nhân sự | `Toàn công ty · HR` | Tra cứu nhân sự/phòng ban toàn công ty, tuân thủ R8/R7/OT, đối soát quy chế & cẩm nang |
| **Executive** | Trợ lý AI Phân tích Điều hành | `Toàn công ty · Ban Điều hành` | So sánh đa chỉ số 5 phòng ban (`BarChart`), xu hướng 6 tháng (`LineChart`), đơn phê duyệt cấp cao & rủi ro R1–R8 |
| **Admin** | Quản trị kỹ thuật (chặn `/assistant` 403) | `Quản trị hệ thống · Admin` | Quản trị kỹ thuật AI qua `/admin/rag`, `/admin/config`, `/admin/audit`, `/admin/system`; không mặc định truy vấn dữ liệu nhân sự |

---

## 3. Phân biệt Trạng thái Phản hồi (Semantic Message States)

Mỗi phản hồi của Trợ lý AI hiển thị rõ tuyến xử lý (`Dữ liệu thực tế · SQL`, `Tài liệu nội bộ · RAG`, `Kết hợp SQL + RAG`, `Hướng dẫn chung`) và phân biệt trực quan 5 trạng thái:

1. **Thành công (`success`):** Khung trắng sạch, badge **"Đã xác minh số liệu"** (xanh lục) và badge **"Ngữ cảnh nối tiếp"** khi câu hỏi kế thừa ngữ cảnh từ lượt trước.
2. **Bị giới hạn (`blocked`):** Khung viền đỏ nhạt + banner cảnh báo bảo mật RBAC hoặc chế độ chỉ đọc (`Read-Only`) kèm nút điều hướng an toàn (ví dụ: *Mở Đơn nghỉ phép*).
3. **Thiếu dữ liệu / Thiếu căn cứ (`insufficient_data` / `insufficient_evidence`):** Khung viền hổ phách nhạt + banner thông báo trung thực chưa đủ dữ liệu/tài liệu xác thực; **không vẽ biểu đồ và không tạo citation giả**.
4. **Cần làm rõ (`clarification_needed`):** Khung xanh dương nhạt hướng dẫn người dùng bổ sung chỉ số hoặc kỳ thời gian.
5. **Lỗi kết nối / API (`error`):** Banner lỗi rõ ràng kèm nút **"Thử lại"** để gửi lại ngay câu hỏi bị lỗi.

---

## 4. Quy chuẩn Hiển thị Citation Cards & AI Analytics

### 4.1. Citation Cards (`CitationCards.tsx`)
- **Nguồn dữ liệu thực tế (SQL):** Hiển thị tên nguồn nghiệp vụ tiếng Việt, phạm vi RBAC, kỳ dữ liệu, số bản ghi và nhãn **"Đã đối chiếu"**.
- **Trích dẫn tài liệu & điều khoản (RAG):** Hiển thị mã `[DOC-1..N]`, tên tài liệu, phiên bản (`v1.1`, `v1.4`, `v2.0`), điều khoản/mục, số trang (nếu có) và đoạn trích đóng/mở. Click vào badge `[DOC-1]` ngay trong nội dung câu trả lời sẽ tự động mở rộng thẻ tài liệu tương ứng.

### 4.2. AI Analytics (`AssistantAnalytics.tsx`)
- **KPI Cards:** Tự động hiển thị 2–4 thẻ chỉ số chính khi kết quả SQL trả về 1 bản ghi tổng hợp (nhân sự, giờ công, tỷ lệ đúng giờ, phép còn lại...).
- **Biểu đồ xác thực:** Tự động dùng **`LineChart`** cho dữ liệu xu hướng theo thời gian (`chart.type = 'line'`) và **`BarChart`** cho so sánh phòng ban/kỳ (`chart.type = 'bar'`); chỉ hiển thị khi `status === 'success'` và có tối thiểu 2 điểm dữ liệu số từ SQL.
- **Bảng dữ liệu nghiệp vụ:** 100% tiêu đề cột bằng tiếng Việt (không lộ `snake_case` của database), giá trị trạng thái được dịch sẵn (*Chờ duyệt*, *Đã duyệt*, *Cao*, *Đang mở*...) và tự động gập bảng với nút **"Xem đầy đủ N dòng"** khi vượt quá 10 dòng.

---

## 5. Quản lý Lịch sử Hội thoại (`ConversationSidebar.tsx`)

- **Tạo mới:** Nhấn **"+ Mới"** để mở phiên trống mới (`conversation_id = null`).
- **Mở lại phiên cũ:** Click vào bất kỳ hội thoại nào trong danh sách để tải ngay tin nhắn đã lưu qua `GET /api/assistant/conversations/{id}` — **không gọi lại `POST /ask` và không sinh thêm `query_audit_log`**.
- **Hỏi nối tiếp:** Khi đang mở một phiên hội thoại, mọi câu hỏi tiếp theo tự động đính kèm `conversation_id` hiện hành để AI hiểu đại từ (*"Còn tháng 9 thì sao?"*, *"phòng đó"*).
- **Đổi tên & Xóa:** Nhấn biểu tượng bút chì để đổi tên trực tiếp (`Enter` lưu, `Esc` hủy) hoặc biểu tượng thùng rác để xóa sau khi xác nhận trên hộp thoại `ConfirmModal`.
- **Phân trang:** Nhấn **"Tải thêm hội thoại"** ở cuối danh sách khi lịch sử vượt quá 15 phiên.
- **Phím tắt nhập liệu:** `Enter` để gửi câu hỏi, `Shift + Enter` để xuống dòng (tối đa 1.000 ký tự), nhấn **"Dừng"** trong lúc đang tải để hủy yêu cầu đang chạy.
