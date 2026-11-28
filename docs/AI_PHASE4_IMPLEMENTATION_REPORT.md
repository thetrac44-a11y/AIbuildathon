# BÁO CÁO TRIỂN KHAI PHASE 4: AI FRONTEND UX — HR ATTENDANCE COPILOT

- **Ngày hoàn thành:** 2026-11-28
- **Mục tiêu:** Hoàn thiện giao diện AI Assistant theo chuẩn SaaS Enterprise hiện đại, an toàn, thân thiện với người dùng nghiệp vụ và phù hợp chặt chẽ mô hình phân quyền RBAC 5 vai trò (`employee`, `manager`, `hr`, `executive`, `admin`), kế thừa trọn vẹn design system hiện có (`#102A43`, `#2563EB`, `#0F9D9A`, `#F4F7FB`, `#E4EAF2`, `rounded-card`) và các shared UI components (`StatusBadge`, `ConfirmModal`, `ErrorState`).
- **Tuân thủ phạm vi:** Chỉ triển khai Phase 4 (AI Frontend UX + bổ sung nhỏ API đổi tên/phân trang hội thoại ở Backend giữ 100% tương thích ngược), không tự ý mở rộng sang chức năng khác, không thay đổi phân quyền Backend hay phá vỡ 113 Backend tests & 38 Frontend regression tests.

---

## 1. Kết quả Audit trước khi sửa

Trước khi chỉnh sửa, đã rà soát toàn bộ:
- [AssistantPage.tsx](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/frontend/src/pages/AssistantPage.tsx) (bản cũ 286 dòng): chỉ dùng `GET /assistant/history` (từ `query_audit_log`), click lịch sử bị **gửi lại `POST /assistant/ask`** gây lặp audit log, không giữ `conversation_id`, không render Markdown/Citations, lộ tên cột database `snake_case` và câu SQL thô `<pre>`, chỉ có `BarChart`, chưa có phân biệt trạng thái `blocked` / `insufficient_data` / `insufficient_evidence` / `error` và chưa có trải nghiệm riêng theo vai trò.
- [AuthContext.tsx](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/frontend/src/context/AuthContext.tsx), [navigation.ts](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/frontend/src/config/navigation.ts), [RouteGuard.tsx](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/frontend/src/components/layout/RouteGuard.tsx): đã có sẵn `useAuth()` (`user`, `selectedPeriod`, `showToast`), phân quyền động 5 vai trò và chặn trực tiếp URL `/assistant` (403) đối với vai trò `admin`.
- Shared UI components: tái sử dụng trực tiếp [StatusBadge.tsx](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/frontend/src/components/ui/StatusBadge.tsx), [ConfirmModal.tsx](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/frontend/src/components/ui/ConfirmModal.tsx), [ErrorState.tsx](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/frontend/src/components/ui/ErrorState.tsx).

---

## 2. Danh sách file tạo mới & chỉnh sửa

### 2.1. Frontend — Tạo mới (5 files)

| File | Vai trò kỹ thuật |
| --- | --- |
| [assistant.ts](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/frontend/src/types/assistant.ts) | Định nghĩa đầy đủ TypeScript contract Phase 3/4 (`AskResponse`, `SqlCitation`, `RagCitation`, `ConversationSummary`, `ConversationDetailResponse`, `ChatUiMessage`), từ điển nhãn cột tiếng Việt `FALLBACK_COLUMN_LABELS_VI` và hàm định dạng giá trị nghiệp vụ `formatCellValueVi()` (triệt tiêu hoàn toàn tên cột `snake_case` và mã trạng thái tiếng Anh thô). |
| [SafeMarkdown.tsx](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/frontend/src/components/assistant/SafeMarkdown.tsx) | Bộ render Markdown thuần React an toàn XSS (**0 `dangerouslySetInnerHTML`**), hỗ trợ heading (`##`/`###` có chấm màu phân tách phần SQL vs RAG), danh sách có/không thứ tự, in đậm/nghiêng, link nội bộ an toàn (`/leaves`, `/anomalies`, `/profile`, `/attendance`) và nút trích dẫn `[DOC-N]` có thể click để mở thẳng thẻ tài liệu tương ứng. |
| [CitationCards.tsx](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/frontend/src/components/assistant/CitationCards.tsx) | Tách biệt rõ 2 nhóm: **Nguồn dữ liệu thực tế (SQL)** (nguồn nghiệp vụ, phạm vi RBAC, kỳ, số bản ghi, nhãn đã đối chiếu) và **Trích dẫn tài liệu & điều khoản (RAG)** (tên tài liệu, phiên bản, điều khoản/mục, số trang, đoạn trích đóng/mở). Tuyệt đối không tự tạo citation khi backend trả rỗng. |
| [AssistantAnalytics.tsx](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/frontend/src/components/assistant/AssistantAnalytics.tsx) | Hiển thị **KPI Cards** (chỉ rút từ dòng tổng hợp SQL xác thực), **`LineChart`** (xu hướng nhiều tháng), **`BarChart`** (so sánh phòng ban/kỳ) và **Bảng dữ liệu tiếng Việt** (tự ẩn cột ID kỹ thuật dư thừa, hỗ trợ mở rộng khi >10 dòng). Chỉ hiển thị khi `status === 'success'` và dữ liệu đủ căn cứ; tuyệt đối không suy diễn số liệu từ văn bản LLM. |
| [ConversationSidebar.tsx](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/frontend/src/components/assistant/ConversationSidebar.tsx) | Sidebar lịch sử hội thoại đầy đủ: tạo hội thoại mới, mở lại hội thoại cũ qua `GET /api/assistant/conversations/{id}` (không gửi lại câu hỏi), đổi tên trực tuyến (`PATCH`), xóa hội thoại kèm `ConfirmModal`, phân trang **"Tải thêm hội thoại"** (`offset`, `has_more`), trạng thái rỗng/loading/lỗi và hỗ trợ drawer trượt trên Mobile/Tablet. |
| [AssistantPage.test.tsx](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/frontend/src/__tests__/AssistantPage.test.tsx) | Bộ 10 kiểm thử Vitest chuyên biệt bao phủ toàn bộ component mới, trải nghiệm 5 vai trò, Citations, Analytics, History GET/PATCH/DELETE/Pagination, phân biệt 5 trạng thái phản hồi, Mobile Drawer và kiểm chứng không lộ JSON/tên cột DB. |

### 2.2. Frontend & Backend — Chỉnh sửa (3 files)

| File | Nội dung thay đổi |
| --- | --- |
| [AssistantPage.tsx](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/frontend/src/pages/AssistantPage.tsx) | Nâng cấp thành Enterprise SaaS Chat Workspace: header nhận diện vai trò & phạm vi RBAC 5 vai trò (kèm lớp phòng thủ chiều sâu cho `admin`), đồng bộ `selectedPeriod`, giữ `conversation_id` qua nhiều lượt, phân biệt rõ `blocked` / `insufficient_data` / `insufficient_evidence` / `clarification_needed` / `error` (kèm nút **Thử lại**), nút **Dừng** (`AbortController`), chip `suggested_followups`, link `suggested_actions`, và khung **"Thông tin kiểm chứng"** thân thiện nghiệp vụ (không hiện JSON hay SQL thô). |
| [ai_context_manager.py](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/services/ai_context_manager.py) | Nâng cấp `list_user_conversations()` hỗ trợ phân trang (`limit`, `offset`, `total`, `has_more`) và thêm `rename_user_conversation()` khóa cứng `WHERE conversation_id = ? AND user_id = ?` (HTTP 404 chống truy cập chéo, 0 audit log trùng). |
| [assistant.py](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/backend/app/api/assistant.py) | Bổ sung query `offset` cho `GET /api/assistant/conversations` và endpoint `PATCH /api/assistant/conversations/{conversation_id}` (bảo vệ bằng `require_permissions` giống các endpoint AI khác). |

---

## 3. Đảm bảo Bảo mật & Trải nghiệm 5 Vai trò RBAC

- **Không chỉ ẩn nút ở Frontend:** Toàn bộ kiểm soát quyền vẫn do Backend (`require_permissions`, `EffectiveScopeResolver`, `SQL Guard v2`, `rag_security`, khóa `user_id` tại `ai_conversations`) thực thi độc lập.
- **Admin:** Bị chặn ở `RouteGuard` (`/assistant` → 403) và Backend API (`403`), đồng thời có màn hình phòng thủ chiều sâu bên trong `AssistantPage` chỉ dẫn tới các màn hình quản trị kỹ thuật (`/admin/rag`, `/admin/config`, `/admin/audit`, `/admin/system`) mà không gọi API dữ liệu nhân sự.
- **Không lộ cấu trúc nội bộ:** Loại bỏ hoàn toàn `<pre>` SQL thô và JSON thô khỏi UI người dùng nghiệp vụ; mọi tiêu đề cột và giá trị trạng thái đều được chuẩn hóa tiếng Việt.

> Chi tiết hướng dẫn trải nghiệm giao diện & chuẩn thiết kế xem tại [AI_UI_UX_GUIDE.md](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/docs/AI_UI_UX_GUIDE.md); kết quả kiểm thử đầy đủ xem tại [AI_PHASE4_TEST_REPORT.md](file:///c:/Users/DEll/OneDrive/Dokumen/code/AI%20buildathon/docs/AI_PHASE4_TEST_REPORT.md).
