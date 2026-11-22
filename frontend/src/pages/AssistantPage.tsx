import React, { useEffect, useState } from 'react';
import { Send, Sparkles, ChevronDown, ChevronRight, PlusCircle, Clock } from 'lucide-react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import { apiFetch, ApiError } from '../lib/api';
import { StatusBadge } from '../components/ui/StatusBadge';

interface TraceInfo {
  tool_name: string | null;
  sql_text: string | null;
  row_count: number;
  execution_ms: number;
}

interface AskResponse {
  status: string;
  answer: string;
  table: { columns: string[]; rows: Record<string, unknown>[] } | null;
  chart: { type: string; xKey: string; yKey: string; label: string; data: Record<string, unknown>[] } | null;
  trace: TraceInfo;
  suggested_followups: string[];
}

interface ChatMessage {
  id: number;
  role: 'user' | 'assistant';
  text: string;
  response?: AskResponse;
}

interface HistoryItem {
  id: number;
  asked_at: string;
  question: string;
  tool_name: string | null;
  row_count: number;
  status: string;
}

export const AssistantPage: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [openTraces, setOpenTraces] = useState<Record<number, boolean>>({});

  const loadMeta = async () => {
    try {
      const [sug, hist] = await Promise.all([
        apiFetch<{ suggestions: string[] }>('/assistant/suggestions'),
        apiFetch<{ items: HistoryItem[] }>('/assistant/history?limit=20'),
      ]);
      setSuggestions(sug.suggestions);
      setHistory(hist.items);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    loadMeta();
  }, []);

  const sendQuestion = async (q: string) => {
    const trimmed = q.trim();
    if (!trimmed || loading) return;
    setInput('');
    const userMsg: ChatMessage = { id: Date.now(), role: 'user', text: trimmed };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);
    try {
      const res = await apiFetch<AskResponse>('/assistant/ask', {
        method: 'POST',
        body: JSON.stringify({ question: trimmed }),
      });
      setMessages((prev) => [
        ...prev,
        { id: Date.now() + 1, role: 'assistant', text: res.answer, response: res },
      ]);
      loadMeta();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Không thể kết nối trợ lý AI.';
      setMessages((prev) => [...prev, { id: Date.now() + 1, role: 'assistant', text: msg }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-5 min-h-[600px]">
      {/* Left History Column */}
      <div className="rounded-card border border-brand-border bg-white p-4 shadow-sm flex flex-col">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-bold text-slate-900">Lịch sử hội thoại</h3>
          <button
            type="button"
            onClick={() => setMessages([])}
            className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-blue hover:underline"
          >
            <PlusCircle className="w-3.5 h-3.5" /> Mới
          </button>
        </div>
        <div className="space-y-1.5 overflow-y-auto max-h-[520px] flex-1">
          {history.length === 0 ? (
            <p className="text-xs text-slate-400">Chưa có lịch sử hỏi đáp.</p>
          ) : (
            history.map((h) => (
              <button
                key={h.id}
                type="button"
                onClick={() => sendQuestion(h.question)}
                className="w-full text-left px-2.5 py-2 rounded-lg hover:bg-brand-bg border border-transparent hover:border-brand-border transition-colors"
              >
                <p className="text-xs font-medium text-slate-700 line-clamp-2">{h.question}</p>
                <p className="text-[10px] text-slate-400 mt-0.5 flex items-center gap-1">
                  <Clock className="w-3 h-3" /> {h.asked_at} · {h.tool_name || h.status}
                </p>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Main Chat Panel */}
      <div className="lg:col-span-3 rounded-card border border-brand-border bg-white shadow-sm flex flex-col overflow-hidden">
        <div className="px-5 py-3.5 border-b border-brand-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-brand-blue" />
            <h3 className="text-sm font-bold text-slate-900">HR Attendance Assistant</h3>
          </div>
          <StatusBadge label="Function Calling + SQL Guard" variant="approved" />
        </div>

        <div className="flex-1 p-5 space-y-4 overflow-y-auto max-h-[520px] bg-brand-bg/40">
          {messages.length === 0 && (
            <div className="text-center py-8 space-y-4">
              <p className="text-sm font-semibold text-slate-800">
                Đặt câu hỏi tiếng Việt về chấm công, nghỉ phép hoặc cảnh báo bất thường
              </p>
              <p className="text-xs text-slate-500 max-w-lg mx-auto">
                Mọi số liệu đều do SQL tính trực tiếp theo đúng quyền vai trò của bạn. Bạn có thể
                mở khung &ldquo;Truy vấn đã chạy&rdquo; dưới mỗi câu trả lời để kiểm chứng.
              </p>
              <div className="flex flex-wrap justify-center gap-2 pt-2">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => sendQuestion(s)}
                    className="px-3 py-1.5 rounded-full bg-white border border-brand-border text-xs text-slate-700 hover:border-brand-blue hover:text-brand-blue transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => (
            <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[90%] rounded-2xl px-4 py-3 text-xs space-y-3 ${
                  m.role === 'user'
                    ? 'bg-brand-blue text-white'
                    : 'bg-white border border-brand-border text-slate-800 shadow-sm'
                }`}
              >
                <div className="whitespace-pre-line leading-relaxed">{m.text}</div>

                {/* Result Table */}
                {m.response?.table && m.response.table.rows.length > 0 && (
                  <div className="overflow-x-auto rounded-lg border border-brand-border">
                    <table className="w-full text-[11px] text-left">
                      <thead className="bg-slate-50 border-b border-brand-border">
                        <tr>
                          {m.response.table.columns.slice(0, 7).map((col) => (
                            <th key={col} className="px-2.5 py-1.5 font-semibold text-slate-600">
                              {col}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-brand-border">
                        {m.response.table.rows.slice(0, 10).map((row, idx) => (
                          <tr key={idx}>
                            {m.response!.table!.columns.slice(0, 7).map((col) => (
                              <td key={col} className="px-2.5 py-1.5 whitespace-nowrap">
                                {String(row[col] ?? '')}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Result Chart */}
                {m.response?.chart && (
                  <div className="h-44 w-full pt-2">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={m.response.chart.data}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#E4EAF2" />
                        <XAxis dataKey={m.response.chart.xKey} tick={{ fontSize: 10 }} />
                        <YAxis tick={{ fontSize: 10 }} />
                        <Tooltip />
                        <Bar
                          dataKey={m.response.chart.yKey}
                          name={m.response.chart.label}
                          fill="#2563EB"
                          radius={[4, 4, 0, 0]}
                        />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}

                {/* Collapsible SQL / Tool Trace */}
                {m.response?.trace && (
                  <div className="pt-1 border-t border-brand-border">
                    <button
                      type="button"
                      onClick={() =>
                        setOpenTraces((prev) => ({ ...prev, [m.id]: !prev[m.id] }))
                      }
                      className="inline-flex items-center gap-1 text-[11px] font-semibold text-slate-500 hover:text-brand-blue"
                    >
                      {openTraces[m.id] ? (
                        <ChevronDown className="w-3.5 h-3.5" />
                      ) : (
                        <ChevronRight className="w-3.5 h-3.5" />
                      )}
                      Truy vấn đã chạy ({m.response.trace.tool_name} · {m.response.trace.row_count} dòng ·{' '}
                      {m.response.trace.execution_ms}ms)
                    </button>
                    {openTraces[m.id] && (
                      <pre className="mt-2 rounded-lg bg-slate-900 text-slate-100 p-3 text-[11px] overflow-x-auto whitespace-pre-wrap">
                        {m.response.trace.sql_text || 'Không thực thi SQL (Guard / Làm rõ câu hỏi)'}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="text-xs text-slate-500 italic">Đang truy vấn dữ liệu an toàn...</div>
          )}
        </div>

        {/* Input Form */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            sendQuestion(input);
          }}
          className="p-3.5 border-t border-brand-border bg-white flex items-center gap-2"
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Nhập câu hỏi về chấm công, nghỉ phép, cảnh báo bất thường..."
            className="flex-1 px-3.5 py-2.5 text-xs rounded-xl border border-brand-border bg-brand-bg/50 focus:outline-none focus:border-brand-blue"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-brand-blue text-white text-xs font-semibold hover:bg-blue-700 disabled:opacity-50"
          >
            <Send className="w-3.5 h-3.5" /> Gửi
          </button>
        </form>
      </div>
    </div>
  );
};
