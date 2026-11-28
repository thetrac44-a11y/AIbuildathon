import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertCircle,
  ArrowUpRight,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  HelpCircle,
  History,
  Info,
  Loader2,
  RefreshCw,
  Send,
  ServerCog,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Square,
} from 'lucide-react';
import { useAuth, AuthUser } from '../context/AuthContext';
import { apiFetch, ApiError } from '../lib/api';
import { StatusBadge } from '../components/ui/StatusBadge';
import { SafeMarkdown } from '../components/assistant/SafeMarkdown';
import { CitationCards } from '../components/assistant/CitationCards';
import { AssistantAnalytics } from '../components/assistant/AssistantAnalytics';
import { ConversationSidebar } from '../components/assistant/ConversationSidebar';
import {
  AskResponse,
  ChatUiMessage,
  ConversationDetailResponse,
  ConversationListResponse,
  ConversationSummary,
  getRouteBadgeMeta,
} from '../types/assistant';

const PAGE_SIZE = 15;
const MAX_INPUT_CHARS = 1000;

interface RoleExperience {
  title: string;
  scopeBadge: string;
  subtitle: string;
  placeholder: string;
  capabilities: string[];
}

function getRoleExperience(user: AuthUser | null): RoleExperience {
  if (!user) {
    return {
      title: 'HR Attendance AI Assistant',
      scopeBadge: 'Chưa xác định',
      subtitle: 'Hỗ trợ tra cứu chấm công, nghỉ phép và quy định nội bộ theo phân quyền.',
      placeholder: 'Nhập câu hỏi về chấm công, nghỉ phép, cảnh báo hoặc quy định công ty...',
      capabilities: [],
    };
  }
  switch (user.role) {
    case 'employee':
      return {
        title: 'Trợ lý AI Cá nhân',
        scopeBadge: `Dữ liệu cá nhân · ${user.employee_id}`,
        subtitle:
          'Tra cứu lịch sử đi muộn, giờ công, quỹ phép năm, đơn nghỉ phép của riêng bạn và các quy định nội bộ hiện hành.',
        placeholder:
          'Hỏi về số lần đi muộn, quỹ phép năm, đơn chờ duyệt hoặc quy định chấm công...',
        capabilities: [
          'Chấm công & đi muộn cá nhân',
          'Quỹ phép năm & đơn chờ duyệt',
          'Nội quy & quy trình công ty',
        ],
      };
    case 'manager':
      return {
        title: 'Trợ lý AI Phòng ban',
        scopeBadge: `Phòng ${user.department_name}`,
        subtitle: `Phân tích chấm công, đơn nghỉ phép chờ duyệt, cảnh báo R1–R8 trong phạm vi Phòng ${user.department_name} và hướng dẫn xử lý từ cẩm nang.`,
        placeholder: `Đặt câu hỏi về chấm công, nghỉ phép hoặc cảnh báo R1–R8 của Phòng ${user.department_name}...`,
        capabilities: [
          `Tổng hợp & so sánh kỳ Phòng ${user.department_name}`,
          'Đơn nghỉ phép chờ duyệt trong phòng',
          'Cảnh báo R1–R8 & quy trình xử lý',
        ],
      };
    case 'hr':
      return {
        title: 'Trợ lý AI Nghiệp vụ Nhân sự',
        scopeBadge: 'Toàn công ty · HR',
        subtitle:
          'Đối chiếu số liệu chấm công toàn công ty, danh bạ nhân sự, tuân thủ quỹ phép (R8), tăng ca cuối tuần (R7) kết hợp kho tài liệu chính sách.',
        placeholder:
          'Hỏi về nhân sự, so sánh phòng ban, cảnh báo R1–R8, quỹ phép hoặc quy định nội bộ...',
        capabilities: [
          'Phân tích toàn công ty & theo nhân viên',
          'Kiểm soát cảnh báo R1–R8 & OT',
          'Tra cứu chính sách & cẩm nang HR',
        ],
      };
    case 'executive':
      return {
        title: 'Trợ lý AI Phân tích Điều hành',
        scopeBadge: 'Toàn công ty · Ban Điều hành',
        subtitle:
          'Tổng hợp KPI đa phòng ban, xu hướng chuyên cần nhiều tháng, đơn nghỉ phép chờ phê duyệt cấp cao và rủi ro trọng yếu theo cẩm nang R1–R8.',
        placeholder:
          'Đặt câu hỏi về so sánh 5 phòng ban, xu hướng 6 tháng, rủi ro nổi bật hoặc đơn chờ phê duyệt...',
        capabilities: [
          'So sánh đa chỉ số 5 phòng ban',
          'Xu hướng chuyên cần theo tháng',
          'Rủi ro R1–R8 & đơn phê duyệt cấp cao',
        ],
      };
    case 'admin':
    default:
      return {
        title: 'Quản trị kỹ thuật AI & Bảo mật',
        scopeBadge: 'Quản trị hệ thống · Admin',
        subtitle:
          'Vai trò Quản trị hệ thống tập trung quản trị tài khoản, phân quyền RBAC, kho tri thức RAG và nhật ký kiểm toán — không mặc định truy vấn dữ liệu chấm công nhân sự.',
        placeholder: '',
        capabilities: [],
      };
  }
}

function getVerificationSummaryLabel(response: AskResponse): string {
  const mode = response.verification?.mode;
  if (mode === 'gemini_verified') return 'Gemini 2.5 Flash · Đã xác minh số liệu';
  if (mode === 'deterministic_fallback_after_mismatch') {
    return 'Dự phòng xác định · Đã chặn sai lệch số liệu';
  }
  if (mode === 'deterministic_fallback_llm_unavailable') {
    return 'Dự phòng xác định · Kết nối LLM tạm ngắt';
  }
  if (mode === 'security_gate') return 'Cổng bảo mật RBAC / Read-Only';
  return 'Xác minh trực tiếp từ nguồn chuẩn';
}

export const AssistantPage: React.FC = () => {
  const { user, selectedPeriod, showToast } = useAuth();
  const roleExp = getRoleExperience(user);
  const isAdmin = user?.role === 'admin';

  // Conversation list state (persisted via /api/assistant/conversations)
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [convTotal, setConvTotal] = useState(0);
  const [convHasMore, setConvHasMore] = useState(false);
  const [loadingConvList, setLoadingConvList] = useState(false);
  const [loadingMoreConvs, setLoadingMoreConvs] = useState(false);
  const [convListError, setConvListError] = useState<string | null>(null);

  // Active conversation workspace state
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatUiMessage[]>([]);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [conversationLoadError, setConversationLoadError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);

  // UI helpers
  const [mobileHistoryOpen, setMobileHistoryOpen] = useState(false);
  const [openVerifyDetails, setOpenVerifyDetails] = useState<Record<string, boolean>>({});
  const [highlightedCitationByMsg, setHighlightedCitationByMsg] = useState<Record<string, string | null>>({});

  const abortRef = useRef<AbortController | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const loadConversations = useCallback(
    async (offset = 0, append = false) => {
      if (isAdmin) return;
      if (append) {
        setLoadingMoreConvs(true);
      } else {
        setLoadingConvList(true);
      }
      setConvListError(null);
      try {
        const res = await apiFetch<ConversationListResponse>(
          `/assistant/conversations?limit=${PAGE_SIZE}&offset=${offset}`
        );
        const items = Array.isArray(res.items) ? res.items : [];
        setConversations((prev) => {
          if (!append) return items;
          const seen = new Set(prev.map((c) => c.conversation_id));
          return [...prev, ...items.filter((c) => !seen.has(c.conversation_id))];
        });
        setConvTotal(typeof res.total === 'number' ? res.total : items.length);
        setConvHasMore(Boolean(res.has_more));
      } catch (err) {
        const msg =
          err instanceof ApiError
            ? err.message
            : 'Không thể tải danh sách lịch sử hội thoại.';
        setConvListError(msg);
      } finally {
        setLoadingConvList(false);
        setLoadingMoreConvs(false);
      }
    },
    [isAdmin]
  );

  const loadSuggestions = useCallback(async () => {
    if (isAdmin) return;
    try {
      const sug = await apiFetch<{ suggestions: string[] }>('/assistant/suggestions');
      setSuggestions(Array.isArray(sug.suggestions) ? sug.suggestions : []);
    } catch {
      setSuggestions([]);
    }
  }, [isAdmin]);

  useEffect(() => {
    if (isAdmin) return;
    loadSuggestions();
    loadConversations(0, false);
  }, [isAdmin, loadSuggestions, loadConversations]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView?.({ behavior: 'smooth' });
  }, [messages.length, sending]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const handleNewConversation = () => {
    abortRef.current?.abort();
    setSending(false);
    setActiveConversationId(null);
    setMessages([]);
    setConversationLoadError(null);
  };

  /**
   * Opens a saved conversation strictly via GET /api/assistant/conversations/{id}.
   * NEVER re-sends questions via POST /ask and NEVER creates duplicate query_audit_log entries!
   */
  const handleSelectConversation = async (conversationId: string) => {
    abortRef.current?.abort();
    setSending(false);
    setActiveConversationId(conversationId);
    setLoadingConversation(true);
    setConversationLoadError(null);
    try {
      const detail = await apiFetch<ConversationDetailResponse>(
        `/assistant/conversations/${encodeURIComponent(conversationId)}`
      );
      const loaded: ChatUiMessage[] = (detail.messages || []).map((m) => ({
        id: `stored-${m.message_id}`,
        role: m.role,
        text: m.content,
        createdAt: m.created_at,
        response: m.response ?? undefined,
      }));
      setMessages(loaded);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : 'Không thể mở phiên hội thoại đã lưu.';
      setConversationLoadError(msg);
      setMessages([]);
    } finally {
      setLoadingConversation(false);
    }
  };

  const handleRenameConversation = async (conversationId: string, newTitle: string) => {
    try {
      const updated = await apiFetch<{ conversation_id: string; title: string; updated_at: string }>(
        `/assistant/conversations/${encodeURIComponent(conversationId)}`,
        {
          method: 'PATCH',
          body: JSON.stringify({ title: newTitle }),
        }
      );
      setConversations((prev) =>
        prev.map((c) =>
          c.conversation_id === conversationId
            ? { ...c, title: updated.title, updated_at: updated.updated_at || c.updated_at }
            : c
        )
      );
      showToast('Đã đổi tên phiên hội thoại.', 'success');
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Không thể đổi tên hội thoại.';
      showToast(msg, 'error');
      throw err;
    }
  };

  const handleDeleteConversation = async (conversationId: string) => {
    try {
      await apiFetch(`/assistant/conversations/${encodeURIComponent(conversationId)}`, {
        method: 'DELETE',
      });
      setConversations((prev) => prev.filter((c) => c.conversation_id !== conversationId));
      setConvTotal((prev) => Math.max(0, prev - 1));
      if (activeConversationId === conversationId) {
        setActiveConversationId(null);
        setMessages([]);
      }
      showToast('Đã xóa phiên hội thoại.', 'info');
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Không thể xóa hội thoại.';
      showToast(msg, 'error');
      throw err;
    }
  };

  const sendQuestion = async (rawQuestion: string) => {
    const trimmed = rawQuestion.trim().slice(0, MAX_INPUT_CHARS);
    if (!trimmed || sending || isAdmin) return;

    setInput('');
    setConversationLoadError(null);
    const userMsgId = `u-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    setMessages((prev) => [...prev, { id: userMsgId, role: 'user', text: trimmed }]);
    setSending(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const payload: Record<string, unknown> = {
        question: trimmed,
        active_period: selectedPeriod,
      };
      if (activeConversationId) {
        payload.conversation_id = activeConversationId;
      }

      const res = await apiFetch<AskResponse>('/assistant/ask', {
        method: 'POST',
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      if (res.conversation_id) {
        setActiveConversationId(res.conversation_id);
      }

      const assistantMsgId = `a-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      setMessages((prev) => [
        ...prev,
        {
          id: assistantMsgId,
          role: 'assistant',
          text: res.answer,
          response: res,
          retryQuestion: res.status === 'error' ? trimmed : undefined,
        },
      ]);
      // Refresh sidebar cleanly without blocking response rendering
      loadConversations(0, false);
    } catch (err) {
      if ((err as { name?: string })?.name === 'AbortError') {
        setMessages((prev) => [
          ...prev,
          {
            id: `cancel-${Date.now()}`,
            role: 'assistant',
            text: 'Bạn đã dừng yêu cầu tra cứu trước khi nhận phản hồi.',
            errorDetail: 'Yêu cầu đã được hủy theo thao tác của người dùng.',
            retryQuestion: trimmed,
          },
        ]);
      } else {
        const msg =
          err instanceof ApiError
            ? err.message
            : 'Không thể kết nối máy chủ Trợ lý AI. Vui lòng kiểm tra kết nối và thử lại.';
        setMessages((prev) => [
          ...prev,
          {
            id: `err-${Date.now()}`,
            role: 'assistant',
            text: msg,
            errorDetail: msg,
            retryQuestion: trimmed,
          },
        ]);
      }
    } finally {
      abortRef.current = null;
      setSending(false);
    }
  };

  const handleStopRequest = () => {
    abortRef.current?.abort();
  };

  // Defense-in-depth technical governance panel if Admin ever renders this component directly
  if (isAdmin) {
    return (
      <div
        className="max-w-3xl mx-auto rounded-card border border-brand-border bg-white p-6 sm:p-8 shadow-sm space-y-5"
        data-testid="admin-ai-governance-panel"
      >
        <div className="flex items-start gap-3.5">
          <div className="w-11 h-11 rounded-xl bg-blue-50 text-brand-blue flex items-center justify-center shrink-0">
            <ServerCog className="w-5 h-5" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-bold text-brand-navy">{roleExp.title}</h2>
              <StatusBadge label={roleExp.scopeBadge} variant="info" />
            </div>
            <p className="mt-1.5 text-xs text-slate-600 leading-relaxed">{roleExp.subtitle}</p>
          </div>
        </div>

        <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 text-xs text-amber-900 flex items-start gap-2.5">
          <ShieldAlert className="w-4 h-4 text-brand-amber shrink-0 mt-0.5" />
          <span>
            Chính sách tách biệt quyền hạn RBAC (Backend Enforcement): Tài khoản Quản trị hệ thống
            (Admin) không được cấp quyền truy vấn dữ liệu chấm công/nghỉ phép nghiệp vụ qua Trợ lý
            AI.
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {[
            { label: 'Quản lý Kho tài liệu RAG', desc: 'Tải lên PDF/DOCX/MD, phân quyền tài liệu và Re-index', path: '/admin/rag' },
            { label: 'Cấu hình AI & Hệ thống', desc: 'Thiết lập nhà cung cấp, chunk size và giới hạn SQL Guard', path: '/admin/config' },
            { label: 'Nhật ký kiểm toán AI', desc: 'Theo dõi lịch sử truy vấn và các yêu cầu bị chặn RBAC', path: '/admin/audit' },
            { label: 'System Dashboard', desc: 'Giám sát sức khỏe hệ thống, tài khoản và thiết bị Kiosk', path: '/admin/system' },
          ].map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className="rounded-xl border border-brand-border p-3.5 hover:border-brand-blue hover:bg-brand-bg/60 transition-colors flex items-start justify-between gap-2"
            >
              <div>
                <p className="text-xs font-semibold text-brand-navy">{item.label}</p>
                <p className="mt-0.5 text-[11px] text-slate-500">{item.desc}</p>
              </div>
              <ArrowUpRight className="w-4 h-4 text-slate-400 shrink-0" />
            </Link>
          ))}
        </div>
      </div>
    );
  }

  const lastAssistantMsg = [...messages].reverse().find((m) => m.role === 'assistant');
  const activeFollowups =
    lastAssistantMsg?.response?.suggested_followups &&
    lastAssistantMsg.response.suggested_followups.length > 0
      ? lastAssistantMsg.response.suggested_followups
      : [];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 lg:gap-5 min-h-[640px] lg:h-[calc(100vh-148px)]">
      {/* Desktop Conversation Sidebar */}
      <div className="hidden lg:block lg:col-span-3 h-full min-h-0">
        <ConversationSidebar
          conversations={conversations}
          total={convTotal}
          hasMore={convHasMore}
          activeConversationId={activeConversationId}
          loadingList={loadingConvList}
          loadingMore={loadingMoreConvs}
          errorMessage={convListError}
          onRetryLoad={() => loadConversations(0, false)}
          onLoadMore={() => loadConversations(conversations.length, true)}
          onNewConversation={handleNewConversation}
          onSelectConversation={handleSelectConversation}
          onRenameConversation={handleRenameConversation}
          onDeleteConversation={handleDeleteConversation}
        />
      </div>

      {/* Mobile / Tablet Conversation Slide-over Drawer */}
      {mobileHistoryOpen && (
        <div
          className="fixed inset-0 z-50 lg:hidden flex bg-slate-900/50"
          role="dialog"
          aria-modal="true"
          aria-label="Lịch sử hội thoại"
        >
          <div className="w-80 max-w-[85vw] h-full p-3 bg-brand-bg">
            <ConversationSidebar
              conversations={conversations}
              total={convTotal}
              hasMore={convHasMore}
              activeConversationId={activeConversationId}
              loadingList={loadingConvList}
              loadingMore={loadingMoreConvs}
              errorMessage={convListError}
              onRetryLoad={() => loadConversations(0, false)}
              onLoadMore={() => loadConversations(conversations.length, true)}
              onNewConversation={handleNewConversation}
              onSelectConversation={handleSelectConversation}
              onRenameConversation={handleRenameConversation}
              onDeleteConversation={handleDeleteConversation}
              onCloseMobile={() => setMobileHistoryOpen(false)}
            />
          </div>
          <button
            type="button"
            aria-label="Đóng nền tối"
            className="flex-1"
            onClick={() => setMobileHistoryOpen(false)}
          />
        </div>
      )}

      {/* Main Enterprise Chat Workspace */}
      <section className="lg:col-span-9 rounded-card border border-brand-border bg-white shadow-sm flex flex-col overflow-hidden min-h-[580px] h-full">
        {/* Top Workspace Header with Role Scope */}
        <header className="px-4 sm:px-5 py-3.5 border-b border-brand-border bg-white flex flex-wrap items-center justify-between gap-2.5">
          <div className="flex items-center gap-2.5 min-w-0">
            <button
              type="button"
              onClick={() => setMobileHistoryOpen(true)}
              aria-label="Mở lịch sử hội thoại"
              className="lg:hidden inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-brand-border text-xs font-medium text-slate-700 hover:bg-brand-bg"
            >
              <History className="w-3.5 h-3.5" /> Lịch sử
            </button>
            <div className="w-8 h-8 rounded-xl bg-blue-50 text-brand-blue flex items-center justify-center shrink-0">
              <Sparkles className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <h2 className="text-sm font-bold text-brand-navy truncate">{roleExp.title}</h2>
              <p className="text-[11px] text-slate-500 truncate">
                Hybrid SQL + RAG · Kỳ làm việc: {selectedPeriod}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <StatusBadge label={roleExp.scopeBadge} variant="info" />
            <StatusBadge label="Chỉ đọc · Xác minh số liệu" variant="approved" />
          </div>
        </header>

        {/* Scrollable Chat Thread */}
        <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-5 space-y-5 bg-brand-bg/40">
          {loadingConversation && (
            <div
              className="flex items-center justify-center gap-2 py-12 text-xs text-slate-500"
              data-testid="conversation-loading"
            >
              <Loader2 className="w-4 h-4 animate-spin text-brand-blue" />
              <span>Đang tải lại lịch sử hội thoại đã lưu...</span>
            </div>
          )}

          {conversationLoadError && (
            <div className="rounded-xl border border-red-200 bg-red-50/80 p-4 flex items-center justify-between gap-3">
              <div className="flex items-start gap-2.5 text-xs text-red-800">
                <AlertCircle className="w-4 h-4 text-brand-red shrink-0 mt-0.5" />
                <span>{conversationLoadError}</span>
              </div>
              {activeConversationId && (
                <button
                  type="button"
                  onClick={() => handleSelectConversation(activeConversationId)}
                  className="px-3 py-1.5 rounded-lg bg-white border border-red-200 text-xs font-semibold text-brand-red hover:bg-red-50 shrink-0"
                >
                  Thử lại
                </button>
              )}
            </div>
          )}

          {/* Welcome Empty State tailored to the active user role */}
          {!loadingConversation && !conversationLoadError && messages.length === 0 && (
            <div className="max-w-2xl mx-auto py-6 sm:py-10 space-y-6" data-testid="assistant-welcome">
              <div className="text-center space-y-2.5">
                <div className="w-12 h-12 rounded-2xl bg-brand-navy text-white flex items-center justify-center mx-auto shadow-sm">
                  <Sparkles className="w-5 h-5" />
                </div>
                <h3 className="text-base sm:text-lg font-bold text-brand-navy">
                  {roleExp.title}
                </h3>
                <p className="text-xs sm:text-[13px] text-slate-600 leading-relaxed max-w-xl mx-auto">
                  {roleExp.subtitle}
                </p>
                {roleExp.capabilities.length > 0 && (
                  <div className="flex flex-wrap justify-center gap-2 pt-1">
                    {roleExp.capabilities.map((cap) => (
                      <span
                        key={cap}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-white border border-brand-border text-[11px] font-medium text-slate-600"
                      >
                        <CheckCircle2 className="w-3 h-3 text-brand-teal" /> {cap}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {suggestions.length > 0 && (
                <div className="space-y-2.5">
                  <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide text-center">
                    Gợi ý câu hỏi phù hợp vai trò của bạn
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                    {suggestions.map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => sendQuestion(s)}
                        className="text-left p-3.5 rounded-xl bg-white border border-brand-border hover:border-brand-blue hover:shadow-sm transition-all text-xs text-slate-700 leading-relaxed group"
                      >
                        <span className="group-hover:text-brand-blue transition-colors">{s}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Chat Message Thread */}
          {!loadingConversation &&
            messages.map((m) => {
              if (m.role === 'user') {
                return (
                  <div key={m.id} className="flex justify-end">
                    <div className="max-w-[85%] sm:max-w-[75%] rounded-2xl rounded-tr-sm bg-brand-navy text-white px-4 py-3 text-[13px] leading-relaxed shadow-sm">
                      {m.text}
                    </div>
                  </div>
                );
              }

              const resp = m.response;
              const status = m.errorDetail ? 'error' : resp?.status || 'success';
              const isBlocked = status === 'blocked';
              const isInsufficient =
                status === 'insufficient_data' || status === 'insufficient_evidence';
              const isClarification = status === 'clarification_needed';
              const isError = status === 'error';

              const routeBadge = getRouteBadgeMeta(resp?.route?.type);
              const cardBorderClass = isBlocked
                ? 'border-red-200 bg-white'
                : isError
                  ? 'border-red-200 bg-red-50/30'
                  : isInsufficient
                    ? 'border-amber-200 bg-white'
                    : isClarification
                      ? 'border-blue-200 bg-white'
                      : 'border-brand-border bg-white';

              return (
                <div key={m.id} className="flex justify-start" data-testid={`assistant-msg-${status}`}>
                  <div
                    className={`w-full max-w-[96%] sm:max-w-[92%] rounded-2xl rounded-tl-sm border p-4 sm:p-5 shadow-sm space-y-3.5 ${cardBorderClass}`}
                  >
                    {/* Assistant Card Top Meta Bar */}
                    <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-brand-border/70">
                      <div className="flex flex-wrap items-center gap-1.5">
                        {resp?.route?.type && (
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10.5px] font-semibold border ${routeBadge.className}`}
                          >
                            {routeBadge.label}
                          </span>
                        )}
                        {resp?.route?.used_context && (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10.5px] font-medium bg-slate-100 text-slate-600 border border-slate-200">
                            Ngữ cảnh nối tiếp
                          </span>
                        )}
                        {resp?.verification?.verified && status === 'success' && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium bg-emerald-50 text-brand-green border border-emerald-200">
                            <ShieldCheck className="w-3 h-3" /> Đã xác minh số liệu
                          </span>
                        )}
                      </div>
                      {m.createdAt && (
                        <span className="text-[10px] text-slate-400">{m.createdAt}</span>
                      )}
                    </div>

                    {/* Semantic Status Callout Banner for non-success states */}
                    {isBlocked && (
                      <div
                        className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 flex items-center gap-2 text-xs font-medium text-brand-red"
                        data-testid="status-banner-blocked"
                      >
                        <ShieldAlert className="w-4 h-4 shrink-0" />
                        <span>Yêu cầu bị giới hạn bởi chính sách phân quyền hoặc chế độ chỉ đọc</span>
                      </div>
                    )}

                    {isInsufficient && (
                      <div
                        className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 flex items-center gap-2 text-xs font-medium text-brand-amber"
                        data-testid="status-banner-insufficient"
                      >
                        <Info className="w-4 h-4 shrink-0" />
                        <span>
                          {status === 'insufficient_evidence'
                            ? 'Chưa đủ căn cứ trong tài liệu nội bộ hiện hành'
                            : 'Chưa đủ dữ liệu xác thực trong hệ thống cho truy vấn này'}
                        </span>
                      </div>
                    )}

                    {isClarification && (
                      <div
                        className="rounded-lg bg-blue-50 border border-blue-200 px-3 py-2 flex items-center gap-2 text-xs font-medium text-brand-blue"
                        data-testid="status-banner-clarification"
                      >
                        <HelpCircle className="w-4 h-4 shrink-0" />
                        <span>Cần làm rõ thêm thông tin trước khi tra cứu</span>
                      </div>
                    )}

                    {isError && (
                      <div
                        className="rounded-lg bg-red-50 border border-red-200 px-3 py-2.5 flex items-center justify-between gap-3"
                        data-testid="status-banner-error"
                      >
                        <div className="flex items-center gap-2 text-xs font-medium text-brand-red">
                          <AlertCircle className="w-4 h-4 shrink-0" />
                          <span>Đã xảy ra lỗi khi xử lý yêu cầu</span>
                        </div>
                        {m.retryQuestion && (
                          <button
                            type="button"
                            onClick={() => sendQuestion(m.retryQuestion!)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-white border border-red-200 text-[11px] font-semibold text-brand-red hover:bg-red-50 shrink-0"
                          >
                            <RefreshCw className="w-3 h-3" /> Thử lại
                          </button>
                        )}
                      </div>
                    )}

                    {/* Markdown Answer Body */}
                    <SafeMarkdown
                      content={m.text}
                      onCitationClick={(cid) =>
                        setHighlightedCitationByMsg((prev) => ({ ...prev, [m.id]: cid }))
                      }
                    />

                    {/* Verified AI Analytics: KPI Cards + Line/Bar Charts + Vietnamese Data Table */}
                    {resp && <AssistantAnalytics response={resp} />}

                    {/* Separated Verified Citations: SQL vs RAG (NEVER fabricated) */}
                    {resp?.citations && (
                      <CitationCards
                        citations={resp.citations}
                        highlightedCitationId={highlightedCitationByMsg[m.id]}
                      />
                    )}

                    {/* Safe Read-Only Navigation Actions */}
                    {resp?.suggested_actions && resp.suggested_actions.length > 0 && (
                      <div className="flex flex-wrap items-center gap-2 pt-1">
                        {resp.suggested_actions.map((act) => (
                          <Link
                            key={`${act.path}-${act.label}`}
                            to={act.path}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-50 text-brand-blue border border-blue-200 text-xs font-semibold hover:bg-blue-100 transition-colors"
                          >
                            <span>{act.label}</span>
                            <ArrowUpRight className="w-3.5 h-3.5" />
                          </Link>
                        ))}
                      </div>
                    )}

                    {/* Business-Friendly Verification Footer (NO raw JSON, NO raw SQL, NO DB column names) */}
                    {resp && (
                      <div className="pt-2 border-t border-brand-border/70">
                        <button
                          type="button"
                          onClick={() =>
                            setOpenVerifyDetails((prev) => ({ ...prev, [m.id]: !prev[m.id] }))
                          }
                          className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-500 hover:text-brand-blue transition-colors"
                        >
                          {openVerifyDetails[m.id] ? (
                            <ChevronDown className="w-3.5 h-3.5" />
                          ) : (
                            <ChevronRight className="w-3.5 h-3.5" />
                          )}
                          <span>Thông tin kiểm chứng</span>
                          {resp.trace && (
                            <span className="text-slate-400">
                              · {resp.trace.row_count} bản ghi · {resp.trace.execution_ms}ms
                            </span>
                          )}
                        </button>

                        {openVerifyDetails[m.id] && (
                          <div className="mt-2 rounded-lg bg-slate-50 border border-brand-border px-3 py-2.5 text-[11px] text-slate-600 grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                            <div>
                              <span className="font-semibold text-slate-700">Chế độ xác minh: </span>
                              {getVerificationSummaryLabel(resp)}
                            </div>
                            <div>
                              <span className="font-semibold text-slate-700">Nguồn đối chiếu: </span>
                              {resp.citations?.sql?.length ?? 0} nguồn dữ liệu ·{' '}
                              {resp.citations?.rag?.length ?? 0} trích dẫn tài liệu
                            </div>
                            {resp.route?.rationale && (
                              <div className="sm:col-span-2">
                                <span className="font-semibold text-slate-700">Phân loại yêu cầu: </span>
                                {resp.route.rationale}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

          {/* Multi-step Loading Indicator with Cancel */}
          {sending && (
            <div className="flex justify-start" data-testid="assistant-loading">
              <div className="rounded-2xl rounded-tl-sm border border-brand-border bg-white px-4 py-3 shadow-sm flex items-center gap-3">
                <Loader2 className="w-4 h-4 animate-spin text-brand-blue shrink-0" />
                <div className="text-xs text-slate-600">
                  <p className="font-semibold text-brand-navy">
                    Đang phân tích câu hỏi &amp; đối chiếu dữ liệu an toàn...
                  </p>
                  <p className="text-[11px] text-slate-400">
                    Kiểm tra phân quyền RBAC · Truy vấn nguồn xác thực · Đối chiếu số liệu
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleStopRequest}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-brand-border text-[11px] font-semibold text-slate-600 hover:border-brand-red hover:text-brand-red transition-colors"
                >
                  <Square className="w-3 h-3 fill-current" /> Dừng
                </button>
              </div>
            </div>
          )}

          {/* Contextual Follow-up Suggestions */}
          {!sending && !loadingConversation && messages.length > 0 && activeFollowups.length > 0 && (
            <div className="pt-1 space-y-1.5" data-testid="suggested-followups">
              <p className="text-[11px] font-medium text-slate-500 flex items-center gap-1">
                <BookOpen className="w-3 h-3 text-brand-blue" /> Gợi ý hỏi tiếp:
              </p>
              <div className="flex flex-wrap gap-1.5">
                {activeFollowups.slice(0, 4).map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => sendQuestion(q)}
                    className="px-3 py-1.5 rounded-full bg-white border border-brand-border text-[11.5px] text-slate-700 hover:border-brand-blue hover:text-brand-blue transition-colors text-left"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div ref={chatEndRef} />
        </div>

        {/* Modern Multiline Composer */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            sendQuestion(input);
          }}
          className="p-3.5 sm:p-4 border-t border-brand-border bg-white"
        >
          <div className="rounded-xl border border-brand-border bg-brand-bg/40 focus-within:border-brand-blue focus-within:bg-white focus-within:ring-2 focus-within:ring-blue-100 transition-all p-2 flex items-end gap-2">
            <textarea
              rows={1}
              value={input}
              maxLength={MAX_INPUT_CHARS}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  sendQuestion(input);
                }
              }}
              placeholder={roleExp.placeholder}
              aria-label="Nhập câu hỏi cho Trợ lý AI"
              className="flex-1 resize-none bg-transparent px-2 py-1.5 text-[13px] text-slate-800 placeholder:text-slate-400 focus:outline-none max-h-32 leading-relaxed"
            />
            <button
              type="submit"
              disabled={sending || !input.trim()}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-brand-blue text-white text-xs font-semibold hover:bg-blue-700 disabled:opacity-45 transition-colors shrink-0"
            >
              <Send className="w-3.5 h-3.5" /> Gửi
            </button>
          </div>
          <div className="mt-1.5 px-1 flex items-center justify-between text-[10.5px] text-slate-400">
            <span>Enter để gửi · Shift + Enter để xuống dòng · Chế độ chỉ đọc (Read-Only)</span>
            <span>
              {input.length}/{MAX_INPUT_CHARS}
            </span>
          </div>
        </form>
      </section>
    </div>
  );
};
