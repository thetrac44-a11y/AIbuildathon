# BÁO CÁO KIỂM THỬ PHASE 4: AI FRONTEND UX — HR ATTENDANCE COPILOT

- **Ngày kiểm thử:** 2026-11-28
- **Môi trường kiểm thử thực tế:**
  - **Backend Pytest:** Python 3.12.10, pytest 9.2.0 (SQLite isolated fixtures + API FastAPI TestClient)
  - **Frontend Vitest:** Node / Vitest 2.1.9 + React Testing Library + jsdom (`--pool=forks --poolOptions.forks.minForks=1 --poolOptions.forks.maxForks=1`)
  - **Frontend Production Build:** TypeScript 5.6.3 (`tsc -b`) + Vite 5.4.21
  - **Live Browser E2E:** Built-in Webview Browser (`webview_browser`)

---

## 1. Tổng hợp kết quả kiểm thử tự động & build thực tế

| Hạng mục kiểm thử | Lệnh chạy thực tế | Tổng số | PASS | FAIL / BLOCKED | Thời gian |
| --- | --- | :---: | :---: | :---: | :---: |
| **Backend Pytest toàn dự án** (giữ nguyên 113 tests + xác minh `PATCH` đổi tên & phân trang hội thoại) | `cd backend && python -m pytest -v` | **113** | **113** | **0** | `67.20s` |
| **Frontend Vitest toàn dự án** (`38` regression + **`10` test mới Phase 4**) | `cd frontend && npx vitest run --pool=forks --poolOptions.forks.minForks=1 --poolOptions.forks.maxForks=1` | **48** | **48** | **0** | `19.25s` |
| **Frontend Production Build (TypeScript + Vite)** | `cd frontend && npm run build` | **1** | **1** | **0** | `7.24s` |
| **Live Browser E2E (5 vai trò qua Webview tích hợp)** | Kiểm thử trình duyệt tích hợp tại `http://127.0.0.1:5173` | **5 vai trò** | **0** | **BLOCKED (`OP_TIMEOUT`)** | *(xem mục 4)* |

---

## 2. Chi tiết 10 kiểm thử Vitest mới cho Phase 4 (`AssistantPage.test.tsx`)

| # | Kịch bản kiểm thử | Hạng mục xác minh | Kết quả |
| :---: | --- | --- | :---: |
| **1** | **Trải nghiệm 4 vai trò có AI (`Employee`, `Manager`, `HR`, `Executive`)** | Hiển thị đúng tiêu đề, badge phạm vi dữ liệu (*Dữ liệu cá nhân · NV007*, *Phòng Kinh doanh*, *Toàn công ty · HR*, *Toàn công ty · Ban Điều hành*) và câu hỏi gợi ý từ `/api/assistant/suggestions`. | **PASS** |
| **2** | **Vai trò `Admin` phòng thủ chiều sâu** | Khi render trực tiếp `AssistantPage` với `admin`, hiển thị bảng thông báo quản trị kỹ thuật với link tới `/admin/rag`, `/admin/config`, `/admin/audit`, `/admin/system` và **0 lần gọi** API HR AI (đồng thời `RbacCompletion.test.tsx` xác nhận truy cập `/assistant` bị `RouteGuard` chặn 403). | **PASS** |
| **3** | **Citation Cards tách biệt SQL vs RAG** | Hiển thị đầy đủ SQL Citation (nguồn, phạm vi, kỳ, số bản ghi, đã đối chiếu) và RAG Citation (tên tài liệu, phiên bản `v1.1`, điều khoản `Quy tắc R1`, `Trang 2`, mở rộng đoạn trích); trả rỗng khi backend không cung cấp (0 citation tự tạo). | **PASS** |
| **4** | **AI Analytics (`KPI Cards`, `LineChart`, `BarChart`, Bảng tiếng Việt)** | Xác minh `LineChart` xu hướng, `BarChart` so sánh phòng ban, KPI cards 1 dòng tổng hợp, 100% tiêu đề cột tiếng Việt (không lộ `late_rate_pct`/`late_days`), nút mở rộng >10 dòng và **ẩn toàn bộ biểu đồ/KPI khi `status = insufficient_data`**. | **PASS** |
| **5** | **Mở lịch sử hội thoại bằng `GET` (không re-query) & Multi-turn** | Click phiên lưu trong Sidebar gọi `GET /assistant/conversations/{id}` với **0 lần gọi `POST /assistant/ask`**; gửi câu hỏi tiếp theo từ chip `suggested_followups` giữ nguyên `conversation_id` và hiển thị badge `Ngữ cảnh nối tiếp`. | **PASS** |
| **6** | **Đổi tên (`PATCH`), Phân trang (`Tải thêm`) & Xóa (`ConfirmModal` + `DELETE`)** | Kiểm chứng tải thêm trang 2 (`offset=1`), đổi tên trực tuyến cập nhật ngay tiêu đề và xóa an toàn qua hộp thoại xác nhận `ConfirmModal`. | **PASS** |
| **7** | **Phân biệt 5 trạng thái phản hồi & Nút Thử lại khi lỗi API** | Xác minh hiển thị banner riêng biệt cho `blocked`, `insufficient_data`, `insufficient_evidence`, `clarification_needed`, và lỗi HTTP `503` kèm nút **"Thử lại"** gửi lại thành công. | **PASS** |
| **8** | **SafeMarkdown an toàn XSS** | Render heading SQL/RAG, in đậm, danh sách, link nội bộ `/leaves` và nút `[DOC-1]` tương tác hoàn toàn bằng React node (không dùng `dangerouslySetInnerHTML`). | **PASS** |
| **9** | **Responsive Mobile Drawer & Empty History State** | Xác minh nút **"Lịch sử"** mở dialog slide-over trên màn hình nhỏ, hiển thị trạng thái lịch sử rỗng (`empty-history`) và đóng drawer gọn gàng. | **PASS** |
| **10** | **Tương tác `[DOC-1]` & Không lộ JSON/SQL/tên cột DB** | Click `[DOC-1]` trong nội dung mở thẳng đoạn trích tài liệu tương ứng; kể cả khi mở khung *"Thông tin kiểm chứng"* vẫn **không chứa `SELECT employee_id`**, không lộ `review_status`/`late_days`, và dịch đúng `open` → `Đang mở`. | **PASS** |

---

## 3. Kết quả kiểm thử hồi quy (Zero Regression)

- **Backend Pytest (`113/113 PASS`):**
  - Toàn bộ regression RBAC 5 vai trò, SQL Guard v2, Phase 1 SQL Intelligence, Phase 2 RAG Intelligence, Phase 3 Hybrid Orchestrator (36 tests — bổ sung xác minh `PATCH /api/assistant/conversations/{id}` bị chặn 404 chéo người dùng và phân trang `limit/offset/has_more`) đều PASS 100%.
- **Frontend Regression (`38/38 PASS` cũ + `10/10 PASS` mới = `48/48 PASS`):**
  - `AppShell.test.tsx` (7/7), `Bugfixes.test.tsx` (8/8), `BusinessEvidence.test.tsx` (11/11), `LoginPage.test.tsx` (6/6), `RbacCompletion.test.tsx` (6/6 — bao gồm chặn 403 `admin -> /assistant`), `AssistantPage.test.tsx` (10/10).
- **Production Bundle (`npm run build` PASS trong `7.24s`):**
  - `tsc -b` không còn lỗi kiểu TypeScript nào; `AssistantPage` tách chunk lazy gọn (`45.23 kB` / gzip `13.67 kB`).

---

## 4. Ghi nhận trung thực về Live Browser E2E (Blocked bởi môi trường Webview)

- **Sự cố môi trường đã quan sát:** Đã thử chạy kiểm thử trình duyệt thực tế tại `http://127.0.0.1:5173` qua 2 phiên độc lập của tác nhân trình duyệt tích hợp (`webview_browser`), nhưng cả 2 phiên đều gặp lỗi **`webview_browser script request failed: OP_TIMEOUT`** ngay từ lệnh RPC đầu tiên (kể cả lệnh chẩn đoán `return { ok: true }` không truy cập mạng; `visited_origins: none`, `latest_screenshot: none`).
- **Lưu ý bổ sung khi chạy live local:** Trong lúc khởi chạy FastAPI trên cổng `8000`, tiến trình `uvicorn` mới báo cổng `8000` đang bị chiếm (`WinError 10048`) bởi một tiến trình cũ từ trước. Trước khi nghiệm thu trực quan trên trình duyệt máy người dùng tại `http://127.0.0.1:5173`, cần đảm bảo khởi động lại tiến trình Backend trên cổng `8000` để chắc chắn nạp mã nguồn Phase 3 & Phase 4 mới nhất (`PATCH /api/assistant/conversations/{id}`, `offset`, Hybrid Orchestrator).
- **Trạng thái trung thực:** Toàn bộ logic UI, tương tác, phân quyền 5 vai trò, Citation Cards, LineChart/BarChart, lịch sử hội thoại không re-query và responsive drawer đã được kiểm chứng tự động đạt **48/48 Vitest + 113/113 Backend Pytest + `tsc -b && vite build` PASS**; riêng bước **Live Browser E2E trực quan 5 vai trò** đang chờ chạy lại ngay khi Webview runtime ổn định hoặc người dùng kiểm tra trực tiếp trên trình duyệt tại `http://127.0.0.1:5173`.
