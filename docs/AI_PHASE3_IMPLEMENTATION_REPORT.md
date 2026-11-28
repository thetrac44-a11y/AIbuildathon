# BÁO CÁO TRIỂN KHAI PHASE 3: HYBRID AI ORCHESTRATOR — HR ATTENDANCE COPILOT

- **Ngày hoàn thành:** 2026-11-28
- **Phạm vi thực hiện:** Hợp nhất SQL Intelligence (Phase 1) và RAG Intelligence (Phase 2) thành **Hybrid AI Assistant** thống nhất gồm: AI Query Router (`SQL_ONLY` / `RAG_ONLY` / `HYBRID` / `GENERAL` / `CLARIFICATION` + Multi-intent), Hybrid Orchestrator, tích hợp Google Gemini 2.5 Flash kèm Deterministic Fallback, Numeric Fact Verification Gate và Conversation Context Manager có cách ly người dùng.
- **Tuân thủ giới hạn phạm vi:** **0 file Frontend bị sửa**, không tạo bảng trùng lặp, giữ nguyên 100% tương thích ngược trên cả **SQLite** và **Supabase PostgreSQL (29/29 bảng bật RLS)**, dừng đúng điểm nghiệm thu Phase 3 (chưa chuyển Phase 4).

---

## 1. Danh sách file tạo mới & chỉnh sửa

### 1.1. File tạo mới (Backend & Tài liệu)

| File | Vai trò kỹ thuật |
| --- | --- |
| [ai_router.py](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/services/ai_router.py) | **AI Query Router**: phân loại `SQL_ONLY`, `RAG_ONLY`, `HYBRID`, `GENERAL`, `CLARIFICATION`; hỗ trợ câu hỏi nhiều ý (tối đa 4 `SubQuery` trực giao) và tránh định tuyến sai các câu hỏi đa điều kiện/quy trình. |
| [ai_llm_client.py](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/services/ai_llm_client.py) | **Gemini 2.5 Flash Client**: provider abstraction (`BaseLLMProvider` / `GeminiLLMProvider`), đọc API key qua biến môi trường (`x-goog-api-key`), timeout + retry exponential backoff cho lỗi tạm thời, prompt tối giản chỉ chứa dữ liệu đã qua RBAC + khung `DATA-ONLY`, báo trung thực khi fallback. |
| [ai_fact_verifier.py](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/services/ai_fact_verifier.py) | **Numeric Fact Verification Gate**: đối chiếu 100% số liệu trong câu trả lời LLM với kết quả SQL + chunk RAG xác thực (hỗ trợ cả dấu thập phân `,` tiếng Việt & `350.000`), phân biệt `0` với `insufficient_data`, chặn rò rỉ prompt và tự động fallback nếu phát hiện số lạ. |
| [ai_context_manager.py](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/services/ai_context_manager.py) | **Conversation Context Manager**: quản lý `ai_conversations` & `ai_messages` cô lập tuyệt đối theo `user_id` (HTTP 404 anti-enumeration), giải đại từ/kỳ nối tiếp (`top_department_by_period`, `last_top_employee_id`, `last_sql_intent`) trước bước tái kiểm RBAC, và đọc lịch sử không tạo lại query hay audit log trùng. |
| [ai_orchestrator.py](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/services/ai_orchestrator.py) | **Hybrid Orchestrator**: điều phối toàn trình RBAC Pre-Gate → Security/Read-Only Guards → Entity & Context Resolution → Live RBAC Re-Check → Router → SQL Intelligence v2 + Fault-Isolated RAG → Gemini 2.5 Flash + Fact Verifier → Audit Log & Persistence. |
| [test_ai_phase3_hybrid_orchestrator.py](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/tests/test_ai_phase3_hybrid_orchestrator.py) | **36 test case chuyên biệt Phase 3** (vượt mức tối thiểu 30 test) phủ trọn 10 nhóm yêu cầu bắt buộc. |
| [AI_HYBRID_ARCHITECTURE.md](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/docs/AI_HYBRID_ARCHITECTURE.md) | Tài liệu kiến trúc Hybrid AI Core kèm sơ đồ Mermaid end-to-end, sequence multi-turn và hợp đồng JSON cho Phase 4. |
| [AI_PHASE3_TEST_REPORT.md](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/docs/AI_PHASE3_TEST_REPORT.md) | Báo cáo kết quả kiểm thử tự động thực tế (SQLite, Live Supabase PostgreSQL, Frontend Regression) và tỷ lệ PASS 35/35 trên `AI_TEST_CASES.md`. |

### 1.2. File chỉnh sửa (Backend — 0 file Frontend)

| File | Nội dung thay đổi |
| --- | --- |
| [ai_assistant.py](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/services/ai_assistant.py) | Chuyển `answer_question()` sang gọi `answer_question_hybrid()` của `HybridOrchestrator`, giữ nguyên 100% signature và export tương thích ngược. |
| [assistant.py](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/api/assistant.py) | Mở rộng `POST /api/assistant/ask` hỗ trợ `conversation_id` & `active_period` (optional); thêm `GET /api/assistant/conversations`, `GET /api/assistant/conversations/{conversation_id}`, `DELETE /api/assistant/conversations/{conversation_id}` (chỉ đọc lịch sử đã lưu, không tạo audit log trùng); giữ nguyên `GET /api/assistant/history`. |
| [config.py](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/core/config.py) | Bổ sung cấu hình non-secret cho LLM (`llm_provider`, `llm_model`, `llm_timeout_seconds`, `llm_max_retries`). |
| [schema.sql](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/db/schema.sql) & [schema_postgres.sql](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/db/schema_postgres.sql) | Bổ sung 2 bảng nhẹ `ai_conversations` & `ai_messages` kèm index và chính sách bật RLS (`29/29` bảng trên Supabase PostgreSQL). |
| [migrations.py](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/db/migrations.py) & [connection.py](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/db/connection.py) | Thêm `ensure_ai_phase3_schema()` & `migrate_ai_phase3()` idempotent cho SQLite & PostgreSQL (kèm `REVOKE ALL` với `anon`/`authenticated`); đăng ký `"ai_messages": "message_id"` trong `_AUTO_PK_BY_TABLE`. |
| [ai_rag_service.py](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/services/ai_rag_service.py) & [rag_embeddings.py](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/services/rag_embeddings.py) | Gia cố chống đầu độc vector embedding (chỉ embed nội dung đã làm sạch với chunk bị gắn cờ injection) và tách stopword tiếng Việt có dấu (`VN_STOPWORDS_ACCENTED`) để không xóa nhầm danh từ như *"thẻ"*. |

---

## 2. Database Migration, Bảo mật RLS & Khả năng Rollback

- **Không tạo bảng trùng:** Tận dụng nguyên vẹn `query_audit_log`, `company_documents`, `document_chunks`, `system_settings` và 4 view `v_*`; chỉ thêm đúng 2 bảng hội thoại theo lộ trình đã duyệt:
  - `ai_conversations (conversation_id, user_id, title, context_json, created_at, updated_at)`
  - `ai_messages (message_id, conversation_id, user_id, role, content, route_type, response_json, created_at)`
- **Trạng thái áp dụng thực tế:**
  - **SQLite (`backend/hr_attendance.db`):** Migration thành công, giữ nguyên toàn bộ dữ liệu hiện có.
  - **Live Supabase PostgreSQL:** Migration thành công; xác minh trực tiếp trên `pg_tables` có **29/29 bảng bật `rowsecurity = true`** (`ai_conversations` và `ai_messages` đã `REVOKE ALL` khỏi `anon`/`authenticated`), `29/29` chunks có vector `pgvector 0.8.2` (`256-d`).
- **Kịch bản Rollback an toàn (PostgreSQL):**
  ```sql
  BEGIN;
  DROP TABLE IF EXISTS public.ai_messages;
  DROP TABLE IF EXISTS public.ai_conversations;
  COMMIT;
  ```

---

## 3. Bảo đảm bảo mật 5 vai trò & Chống rủi ro AI

1. **RBAC 5 vai trò tuyệt đối (không giao cho LLM):**
   - `Admin` bị chặn ở 3 tầng (API `require_permissions` 403, `EffectiveScopeResolver = none`, `SQLGuardError`) trên cả `/ask`, `/conversations` và RAG retrieval.
   - `Employee` (`self`), `Manager` (`department`), `HR` (`all`), `Executive` (`all` + strategic) được kiểm tra lại **quyền sống trong DB** ngay cả sau khi giải đại từ từ lịch sử hội thoại cũ (`test_p3_24`).
2. **Không bao giờ để LLM tự thực thi SQL hoặc nhìn thấy dữ liệu ngoài quyền:**
   - 100% số liệu do 16 tool tham số hóa + `SQL Guard v2` thực thi; prompt gửi cho Gemini chỉ chứa bằng chứng đã lọc theo đúng phạm vi người hỏi (`test_p3_36`).
3. **Read-Only tuyệt đối:**
   - Chặn toàn bộ yêu cầu tạo/duyệt/từ chối/hủy đơn hoặc sửa/xóa chấm công/cảnh báo/nhân sự (`read_only_guard`) và chỉ cung cấp đường dẫn điều hướng an toàn (`suggested_actions`), đồng thời phân biệt chính xác với câu hỏi quy trình như *"Quy trình hủy đơn đang chờ duyệt thế nào?"* (`test_p3_07`).
4. **Chống Prompt Injection 2 chiều:**
   - Tiêm lệnh trực tiếp trong câu hỏi → chặn trước khi gọi SQL/RAG/LLM (`security_guard`).
   - Tiêm lệnh gián tiếp trong tài liệu RAG → lọc sạch/cách ly khi index & retrieve + bọc khung `DATA-ONLY` (`test_p3_34`).

---

## 4. Hạn chế & Điểm bàn giao cho Phase 4

1. **Chế độ mặc định khi chưa cấu hình `LLM_API_KEY`:** Hệ thống chạy 100% ở chế độ `Deterministic + BM25/Vector Hybrid Fallback` trung thực (`used_llm = false`, `fallback_reason = missing_api_key`). Khi triển khai có `LLM_API_KEY` (Google AI Studio / Gemini 2.5 Flash), bộ tổng hợp tự động kích hoạt kèm bắt buộc qua `Numeric Fact Verification Gate`.
2. **Hội thoại dài & giới hạn ngữ cảnh:** `context_json` lưu các thực thể có cấu trúc (`top_department_by_period`, `last_sql_intent`, `last_employee_id`, `last_rule_code`) giúp nhẹ và xác định, phù hợp nối tiếp 3–6 lượt; khi cần tóm tắt hội thoại rất dài (>20 lượt) có thể mở rộng thêm cửa sổ tóm tắt.
3. **Điểm nối sang Phase 4 (Frontend UX):** Backend đã trả đầy đủ `conversation_id`, `route`, `citations` (`sql` + `rag`), `column_labels`, `verification`, `llm`, `suggested_actions` và các endpoint `/api/assistant/conversations*` để Phase 4 nâng cấp giao diện `AssistantPage.tsx` (Sidebar hội thoại thật không re-query, thẻ Citation, nhãn cột tiếng Việt, `LineChart` xu hướng và badge phạm vi theo 5 vai trò) mà không cần chỉnh lại API.

> Xem chi tiết kết quả chạy toàn bộ 113 Backend tests, Live Supabase PostgreSQL E2E và 38 Frontend tests tại [AI_PHASE3_TEST_REPORT.md](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/docs/AI_PHASE3_TEST_REPORT.md).
