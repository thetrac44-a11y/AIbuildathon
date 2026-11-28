export interface SqlCitation {
  type: 'sql';
  source_label: string;
  scope_label: string;
  period?: string | null;
  record_count: number;
  tool_name?: string | null;
  verified: boolean;
}

export interface RagCitation {
  type: 'rag';
  citation_id: string;
  document_id: number;
  title: string;
  original_file_name?: string;
  document_type?: string;
  version_label: string;
  effective_from?: string | null;
  effective_to?: string | null;
  section_title?: string | null;
  article_ref?: string | null;
  page_number?: number | null;
  chunk_id?: number;
  chunk_index?: number;
  excerpt: string;
  retrieval_mode?: string;
  scores?: {
    bm25?: number;
    vector?: number;
    hybrid?: number;
  };
}

export interface AssistantCitations {
  sql: SqlCitation[];
  rag: RagCitation[];
}

export interface AssistantTable {
  columns: string[];
  rows: Record<string, unknown>[];
}

export interface AssistantChart {
  type: 'bar' | 'line' | string;
  xKey: string;
  yKey: string;
  label: string;
  data: Record<string, unknown>[];
}

export interface TraceInfo {
  tool_name: string | null;
  sql_text: string | null;
  row_count: number;
  execution_ms: number;
}

export interface RouteInfo {
  type: 'SQL_ONLY' | 'RAG_ONLY' | 'HYBRID' | 'GENERAL' | 'BLOCKED' | 'CLARIFICATION' | string;
  sub_queries?: Array<{ kind: string; intent: string; query_text?: string }>;
  rationale?: string;
  used_context?: boolean;
  is_multi_intent?: boolean;
}

export interface VerificationInfo {
  verified: boolean;
  mode: string;
  checked_numbers?: number;
  unverified_numbers?: string[];
  sql_fact_count?: number;
  rag_fact_count?: number;
  used_fallback?: boolean;
  llm_output_rejected?: boolean;
  flagged_unverified_numbers?: string[];
}

export interface LlmMeta {
  provider: string;
  model: string;
  used_llm: boolean;
  used_fallback: boolean;
  fallback_reason?: string | null;
  latency_ms?: number;
  attempts?: number;
}

export interface SuggestedAction {
  label: string;
  path: string;
}

export interface AskResponse {
  status: 'success' | 'blocked' | 'insufficient_data' | 'insufficient_evidence' | 'clarification_needed' | 'error' | string;
  answer: string;
  conversation_id?: string | null;
  route?: RouteInfo;
  table: AssistantTable | null;
  column_labels?: Record<string, string>;
  chart: AssistantChart | null;
  citations?: AssistantCitations;
  trace?: TraceInfo;
  verification?: VerificationInfo;
  llm?: LlmMeta;
  suggested_followups?: string[];
  suggested_actions?: SuggestedAction[];
  clarification_needed?: boolean;
}

export interface ConversationSummary {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConversationListResponse {
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  items: ConversationSummary[];
}

export interface StoredConversationMessage {
  message_id: number;
  role: 'user' | 'assistant';
  content: string;
  route_type?: string | null;
  response?: AskResponse | null;
  created_at: string;
}

export interface ConversationDetailResponse {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  context?: Record<string, unknown>;
  messages: StoredConversationMessage[];
}

export interface ChatUiMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  createdAt?: string;
  response?: AskResponse;
  errorDetail?: string;
  retryQuestion?: string;
}

/**
 * Business-friendly Vietnamese labels fallback so raw database snake_case column names
 * are NEVER rendered directly to end users.
 */
export const FALLBACK_COLUMN_LABELS_VI: Record<string, string> = {
  employee_id: 'Mã nhân viên',
  full_name: 'Họ và tên',
  department_id: 'Mã phòng ban',
  department_name: 'Phòng ban',
  position: 'Chức danh',
  manager_id: 'Mã quản lý',
  manager_name: 'Quản lý trực tiếp',
  start_date: 'Ngày vào làm',
  role: 'Vai trò',
  period: 'Kỳ',
  work_date: 'Ngày công',
  check_in: 'Giờ vào',
  check_out: 'Giờ ra',
  status: 'Trạng thái',
  late_minutes: 'Phút muộn',
  work_hours: 'Giờ công',
  employee_count: 'Số nhân sự',
  total_work_hours: 'Tổng giờ công',
  present_days: 'Ngày đi làm',
  on_time_days: 'Ngày đúng giờ',
  on_time_rate_pct: 'Tỷ lệ đúng giờ (%)',
  late_days: 'Số lần đi muộn',
  late_rate_pct: 'Tỷ lệ đi muộn (%)',
  total_late_minutes: 'Tổng phút muộn',
  avg_late_minutes: 'TB phút muộn',
  leave_days: 'Ngày nghỉ phép',
  leave_rate_pct: 'Tỷ lệ nghỉ phép (%)',
  absent_days: 'Ngày vắng',
  missing_punch_days: 'Thiếu chấm công',
  annual_leave_balance: 'Quỹ phép năm',
  used_annual_days: 'Đã sử dụng',
  remaining_annual_days: 'Còn lại',
  request_id: 'Mã đơn',
  leave_type: 'Loại nghỉ phép',
  from_date: 'Từ ngày',
  to_date: 'Đến ngày',
  reason: 'Lý do',
  decision_note: 'Ghi chú duyệt',
  requires_executive_approval: 'Duyệt cấp cao',
  total_requests: 'Tổng số đơn',
  approved_requests: 'Đã duyệt',
  pending_requests: 'Chờ duyệt',
  rejected_requests: 'Từ chối',
  approved_leave_days: 'Ngày phép đã duyệt',
  anomaly_id: 'Mã cảnh báo',
  rule_code: 'Quy tắc',
  anomaly_type: 'Loại bất thường',
  scope_type: 'Phạm vi',
  target_code: 'Đối tượng',
  target_name: 'Tên đối tượng',
  severity: 'Mức độ',
  review_status: 'Trạng thái xử lý',
  explanation: 'Mô tả nghiệp vụ',
  total_anomalies: 'Tổng cảnh báo',
  open_anomalies: 'Đang mở',
  high_anomalies: 'Mức cao',
  medium_anomalies: 'Mức trung bình',
  low_anomalies: 'Mức thấp',
  rule_breakdown: 'Phân bổ R1–R8',
  approved_by: 'Người duyệt',
  id: 'Mã bản ghi',
};

const VALUE_LABELS_VI: Record<string, string> = {
  present: 'Đi làm',
  absent: 'Vắng mặt',
  on_leave: 'Nghỉ phép',
  holiday: 'Ngày lễ',
  weekend: 'Cuối tuần',
  pending: 'Chờ duyệt',
  approved: 'Đã duyệt',
  rejected: 'Từ chối',
  cancelled: 'Đã hủy',
  open: 'Đang mở',
  confirmed: 'Đã xác nhận',
  dismissed: 'Đã bỏ qua',
  high: 'Cao',
  medium: 'Trung bình',
  low: 'Thấp',
  annual: 'Phép năm',
  sick: 'Nghỉ ốm',
  personal: 'Việc riêng',
  unpaid: 'Không lương',
  employee: 'Nhân viên',
  manager: 'Trưởng phòng',
  hr: 'Nhân sự',
  executive: 'Ban Điều hành',
  admin: 'Quản trị hệ thống',
  department: 'Phòng ban',
  late_repeated: 'Đi muộn lặp lại',
  missing_punch: 'Thiếu chấm công',
  low_hours: 'Giờ công thấp',
  leave_near_holiday: 'Nghỉ sát kỳ lễ',
  leave_cluster: 'Nghỉ tập trung cấp phòng',
  identical_punch: 'Giờ chấm trùng từng giây',
  weekend_punch: 'Chấm công cuối tuần/lễ',
  leave_over_balance: 'Vượt quỹ phép năm',
};

export function getVietnameseColumnLabel(
  colKey: string,
  backendLabels?: Record<string, string>
): string {
  if (backendLabels && backendLabels[colKey]) {
    return backendLabels[colKey];
  }
  if (FALLBACK_COLUMN_LABELS_VI[colKey]) {
    return FALLBACK_COLUMN_LABELS_VI[colKey];
  }
  return colKey
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export function formatCellValueVi(colKey: string, raw: unknown): string {
  if (raw === null || raw === undefined || raw === '') return '—';
  if (colKey === 'requires_executive_approval') {
    return Number(raw) === 1 || raw === true ? 'Có' : 'Không';
  }
  if (typeof raw === 'boolean') {
    return raw ? 'Có' : 'Không';
  }
  if (typeof raw === 'number') {
    if (colKey.endsWith('_pct')) {
      return `${raw}%`;
    }
    return raw.toLocaleString('vi-VN');
  }
  const str = String(raw).trim();
  const mapped = VALUE_LABELS_VI[str.toLowerCase()];
  if (
    mapped &&
    [
      'status',
      'leave_type',
      'severity',
      'review_status',
      'role',
      'scope_type',
      'anomaly_type',
    ].includes(colKey)
  ) {
    return mapped;
  }
  return str;
}

export function getRouteBadgeMeta(routeType?: string): {
  label: string;
  className: string;
} {
  switch (routeType) {
    case 'SQL_ONLY':
      return {
        label: 'Dữ liệu thực tế · SQL',
        className: 'bg-blue-50 text-brand-blue border-blue-200',
      };
    case 'RAG_ONLY':
      return {
        label: 'Tài liệu nội bộ · RAG',
        className: 'bg-teal-50 text-brand-teal border-teal-200',
      };
    case 'HYBRID':
      return {
        label: 'Kết hợp SQL + RAG',
        className: 'bg-indigo-50 text-indigo-700 border-indigo-200',
      };
    case 'GENERAL':
      return {
        label: 'Hướng dẫn chung',
        className: 'bg-slate-100 text-slate-600 border-slate-200',
      };
    case 'BLOCKED':
      return {
        label: 'Giới hạn bảo mật',
        className: 'bg-red-50 text-brand-red border-red-200',
      };
    case 'CLARIFICATION':
      return {
        label: 'Cần làm rõ',
        className: 'bg-amber-50 text-brand-amber border-amber-200',
      };
    default:
      return {
        label: 'Trợ lý AI',
        className: 'bg-slate-100 text-slate-600 border-slate-200',
      };
  }
}
