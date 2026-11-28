# BÁO CÁO KIỂM THỬ PHASE 3: HYBRID AI ORCHESTRATOR — HR ATTENDANCE COPILOT

- **Ngày kiểm thử:** 2026-11-28
- **Môi trường kiểm thử thực tế:**
  - **SQLite (Local & Isolated Pytest DBs):** Python 3.12.10, pytest 9.2.0 (`backend/hr_attendance.db` + temp DB per fixture)
  - **Live Supabase PostgreSQL:** PostgreSQL 15+ với `pgvector 0.8.2`, **29/29 bảng bật RLS** (`ai_conversations` & `ai_messages` đã `REVOKE ALL` với `anon`/`authenticated`)
  - **Frontend Regression:** Node / Vitest 2.1.9 (0 file Frontend thay đổi)

---

## 1. Tổng hợp kết quả kiểm thử tự động thực tế

| Bộ kiểm thử | Lệnh chạy thực tế | Tổng số | PASS | FAIL | Thời gian |
| --- | --- | :---: | :---: | :---: | :---: |
| **Backend Pytest toàn dự án** (Baseline + Phase 1 + Phase 2 + **36 test mới Phase 3**) | `cd backend && python -m pytest -v` | **113** | **113** | **0** | `68.01s` |
| **Đánh giá trọn bộ 35 ca `AI_TEST_CASES.md` (TC-01 → TC-35)** | Script đánh giá 35 ca (SQL + RAG + Hybrid + Multi-turn + RBAC) | **35** | **35** | **0** | `2.19s` |
| **Live Supabase PostgreSQL Phase 3 E2E** (Migration + 29/29 RLS + `pgvector` + Hybrid + Multi-turn + Isolation) | `verify_phase3_supabase.py` (kèm dọn sạch dữ liệu tạm) | **15** | **15** | **0** | `33.97s` |
| **Local SQLite Migration & E2E** (`backend/hr_attendance.db`) | `migrate_ai_phase3` + Hybrid/Multi-turn E2E | **6** | **6** | **0** | `<3s` |
| **Frontend Vitest Regression** | `cd frontend && npx vitest run --pool=forks --poolOptions.forks.minForks=1 --poolOptions.forks.maxForks=1` | **38** | **38** | **0** | `21.46s` |

---

## 2. Chi tiết 36 ca kiểm thử mới Phase 3 (`test_ai_phase3_hybrid_orchestrator.py`)

Vượt mức yêu cầu tối thiểu 30 test và bao phủ đầy đủ cả **10 hạng mục kiểm thử bắt buộc**:

| Nhóm kiểm thử | Số test | Mã test & Kịch bản thực tế đã kiểm chứng | Kết quả |
| --- | :---: | --- | :---: |
| **1. AI Query Router & `SQL_ONLY`** | **5** | `test_p3_01..05`: Phân loại `SQL_ONLY`, `GENERAL` (không chạy SQL), `CLARIFICATION` (*"Xem giúp tôi"*), phân biệt `0 lần đi muộn` (TC-04) với `insufficient_data` (TC-10), phát hành SQL citations & `column_labels` tiếng Việt. | **5/5 PASS** |
| **2. `RAG_ONLY` & Chống bịa** | **5** | `test_p3_06..10`: TC-07 (ân hạn 5 phút + `[DOC-1]`), TC-08 (quy trình tạo/hủy đơn `pending` + `/leaves`), TC-09 (đổi mật khẩu `/profile` qua RAG), từ chối câu hỏi ngoài lề (`insufficient_data`, `citations=[]`), kiểm soát `visibility = hr_only`, loại tài liệu `archived` và hết hạn `effective_to = 2024-12-31`. | **5/5 PASS** |
| **3. `HYBRID` (SQL + RAG) & Fault Isolation** | **6** | `test_p3_11..16`: Trọn bộ **TC-26** (NV007 8 lần vs ngưỡng R1 ≥5 ngày), **TC-27** (R5 Kinh doanh + quy trình xử lý), **TC-28** (NV052 R8 + quy định tính ngày lịch), **TC-29** (NV045 R7 + đối chiếu 0 đơn OT + chính sách tăng ca), **TC-30** (Executive rủi ro kỳ mới nhất `2026-11` R6 `NV023` + Cẩm nang R1–R8), và giả lập RAG lỗi nhưng SQL vẫn thành công (`test_p3_16`). | **6/6 PASS** |
| **4. Câu hỏi nhiều ý (Multi-intent)** | **4** | `test_p3_17..20`: Quỹ phép + cảnh báo (Employee), nhân sự phòng + cảnh báo (HR), đi muộn + đơn chờ duyệt (Manager), không định tuyến sai khi so sánh đa điều kiện 2 phòng ban (Executive). | **4/4 PASS** |
| **5. Hội thoại nối tiếp (Multi-turn) & Zero Duplicate Audit** | **4** | `test_p3_21..24`: **TC-35** 3 lượt (*Phòng nào cao nhất T10* → *Còn tháng 9 thì sao?* → *Top 3 của phòng đó trong tháng 10*), giải đại từ nhân viên (*"Nhân viên đó"*), xác nhận mở `GET /conversations` & `GET /conversations/{id}` tạo **0 dòng `query_audit_log` mới**, và xác nhận thu hẹp quyền HR từ `ai.ask.all` → `ai.ask.department` **chặn ngay** câu nối tiếp *"phòng đó"* (Kinh doanh). | **4/4 PASS** |
| **6. Gemini 2.5 Flash & Xử lý lỗi API** | **4** | `test_p3_25..28`: Tổng hợp Gemini thành công qua kiểm chứng (`gemini_verified`), `httpx.ReadTimeout` tự động retry 3 lần rồi fallback Deterministic, lỗi HTTP `429/500/503` retry + fallback trung thực, và chế độ thiếu `LLM_API_KEY` chạy offline mượt mà (`missing_api_key`). | **4/4 PASS** |
| **7. Numeric Fact Verification Gate** | **3** | `test_p3_29..31`: Giả lập Gemini bịa số (`8` → `42`, `99.5%`) → bị từ chối tức thì (`llm_output_rejected=true`, fallback trả về đúng `8 lần`), chặn bịa `0` khi `insufficient_data`, và chặn văn bản quy kết gian lận hoặc rò rỉ `password_hash`/`system_instruction`. | **3/3 PASS** |
| **8–10. RBAC 5 vai trò, Read-Only, Prompt Injection & Conversation Isolation** | **5** | `test_p3_32..36`: Ma trận 5 vai trò (Admin 403 trên `/ask` & `/conversations`, Employee/Manager/HR/Executive đúng phạm vi), chặn mọi yêu cầu ghi (`read_only_guard`), chặn Prompt Injection trực tiếp + lọc Prompt Injection gián tiếp trong tài liệu RAG, cách ly `conversation_id` chéo người dùng (HTTP 404 cho GET/POST/DELETE), và kiểm tra trực tiếp payload prompt gửi cho Gemini **không chứa 1 bản ghi nào ngoài phạm vi RBAC**. | **5/5 PASS** |

---

## 3. Kiểm chứng Live Supabase PostgreSQL (15/15 PASS)

Chạy trực tiếp trên instance Supabase PostgreSQL thực tế (kèm dọn sạch 100% phiên hội thoại và audit log thử nghiệm sau khi chạy):

- **Schema & RLS:** `public.ai_conversations` và `public.ai_messages` đã được tạo an toàn không phá hủy; **29/29 bảng bật `rowsecurity = true`** (`anon` & `authenticated` bị `REVOKE ALL`).
- **`pgvector 0.8.2`:** `29/29` chunks có vector `256-d` hoạt động trực tiếp trong luồng `RAG_ONLY` và `HYBRID`.
- **15 kịch bản E2E đã PASS trực tiếp trên Supabase PG (`33.97s`):**
  `TC04_zero`, `TC10_missing`, `TC07_rag`, `TC08_rag`, `UNRELATED_rag`, `GENERAL`, `TC26_hybrid`, `TC27_hybrid`, `TC28_hybrid`, `TC29_hybrid`, `TC30_hybrid`, `TC35_multiturn`, `ZERO_DUP_AUDIT`, `CONV_ISOLATION`, `ADMIN_BLOCKED`.

---

## 4. Lỗi thực tế phát hiện trong quá trình kiểm thử & Cách đã khắc phục

1. **False positive của `read_only_guard` trên câu hỏi quy trình TC-08:** Cụm *"hủy đơn"* trong *"Quy trình xin nghỉ phép năm và hủy đơn đang chờ duyệt thực hiện như thế nào?"* ban đầu bị khớp nhầm regex hành động ghi. **Đã khắc phục:** Tách rõ câu hỏi quy trình/chính sách (`POLICY_INQUIRY_EXEMPT_PATTERN`) khỏi lệnh mệnh lệnh thực thi (`EXPLICIT_IMPERATIVE_WRITE_PATTERN`) — TC-08 định tuyến sạch sang `RAG_ONLY`, trong khi mọi lệnh yêu cầu tạo/duyệt/hủy/xóa vẫn bị chặn 100%.
2. **Mất ngữ nghĩa vế sau khi tách `"và"` ở câu `RAG_ONLY`:** Hàm rút gọn câu RAG ban đầu cắt TC-08 tại `"và"` làm rơi cụm *"hủy đơn đang chờ duyệt"*. **Đã khắc phục:** Luồng `RAG_ONLY` giữ nguyên 100% câu hỏi gốc của người dùng; `Điều 4` (có `/leaves` và `pending`) lập tức lên Top kết quả.
3. **Lỗi lọc mã quy tắc với biểu thức dải `"R1-R8"` (TC-30):** Regex `\b(R[1-8])\b` trích xuất `"R1"` từ cụm *"cẩm nang kiểm soát R1-R8"*, khiến SQL lọc nhầm `rule_code = 'R1'` cho kỳ `2026-11` (kỳ có `R6`). **Đã khắc phục:** Loại trừ biểu thức dải `R[1-8] - R[1-8]` trước khi trích xuất mã quy tắc đơn lẻ.
4. **Chống đầu độc vector & stopword tiếng Việt trên tài liệu chứa injection:** Tách `VN_STOPWORDS_ACCENTED` để không xóa nhầm danh từ có dấu (như *"thẻ"* ≠ *"thế"*) và chỉ tính embedding trên phần nội dung đã được lọc sạch injection cho các chunk bị gắn cờ.

---

## 5. Tiến độ đối chiếu bộ 35 câu hỏi kiểm thử (`AI_TEST_CASES.md`)

| Mốc tiến độ | Số ca PASS trọn vẹn | Tỷ lệ PASS | Ghi chú |
| --- | :---: | :---: | --- |
| Baseline Audit (trước nâng cấp) | 7 / 35 | `20,0%` | Chỉ có SQL rule-based đơn ý, chưa có RAG/Hybrid/Multi-turn |
| Sau Phase 1 (SQL Intelligence v2 + SQL Guard v2) | 27 / 35 | `77,1%` | Đạt toàn bộ nhóm SQL_ONLY + bảo mật cơ bản |
| Sau Phase 2 (RAG Intelligence) | 27 / 35 *(+RAG độc lập)* | `77,1%` *(tầng `/api/rag/search` PASS)* | Kho tài liệu & truy xuất lai BM25 + `pgvector` sẵn sàng |
| **Sau Phase 3 (Hybrid AI Orchestrator)** | **35 / 35** | **`100,0%`** | **Vượt mục tiêu ≥ 95% của lộ trình: 22 `SQL_ONLY` + 3 `RAG_ONLY` + 5 `HYBRID` + 4 `BLOCKED` + 1 Multi-turn 3 lượt (TC-35), 0% hallucination số liệu.** |
