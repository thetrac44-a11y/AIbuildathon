import React, { useCallback, useEffect, useState } from 'react';
import { BookOpen, Plus, RefreshCw, Trash2, X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { apiFetch, ApiError } from '../lib/api';
import { ColumnDef, DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';

interface RagDocRow {
  document_id: number;
  title: string;
  original_file_name: string;
  document_type: string;
  version_label: string | null;
  status: string;
  uploaded_by_username: string | null;
  processed_at: string | null;
  chunk_count: number;
}

export const RagKnowledgePage: React.FC = () => {
  const { showToast } = useAuth();
  const [docs, setDocs] = useState<RagDocRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({
    title: '',
    original_file_name: 'quy_dinh_moi.md',
    document_type: 'policy',
    version_label: 'v1.0',
    content: '',
  });

  const loadDocs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch<{ items: RagDocRow[] }>('/rag/documents');
      setDocs(res.items || []);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể tải danh sách tài liệu RAG.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDocs();
  }, [loadDocs]);

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await apiFetch<{ document_id: number; chunk_count: number }>('/rag/documents', {
        method: 'POST',
        body: JSON.stringify(form),
      });
      showToast(`Đã tải lên & đánh chỉ mục ${res.chunk_count} đoạn tri thức RAG.`, 'success');
      setModalOpen(false);
      setForm({ title: '', original_file_name: 'quy_dinh_moi.md', document_type: 'policy', version_label: 'v1.0', content: '' });
      loadDocs();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Tải tài liệu thất bại.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleReindex = async (docId: number) => {
    try {
      await apiFetch(`/rag/documents/${docId}/reindex`, { method: 'POST' });
      showToast(`Đã re-index tài liệu #${docId} thành công.`, 'success');
      loadDocs();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Re-index thất bại.', 'error');
    }
  };

  const handleDelete = async (docId: number) => {
    try {
      await apiFetch(`/rag/documents/${docId}`, { method: 'DELETE' });
      showToast(`Đã xóa tài liệu #${docId}.`, 'info');
      loadDocs();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Xóa tài liệu thất bại.', 'error');
    }
  };

  const columns: ColumnDef<RagDocRow>[] = [
    { key: 'title', header: 'Tên tài liệu', render: (r) => <div><p className="font-semibold text-slate-900">{r.title}</p><p className="text-[11px] font-mono text-slate-500">{r.original_file_name}</p></div> },
    { key: 'document_type', header: 'Phân loại', render: (r) => <StatusBadge label={r.document_type} variant="info" /> },
    { key: 'version_label', header: 'Phiên bản', render: (r) => r.version_label || 'v1.0' },
    { key: 'chunk_count', header: 'Số đoạn (Chunks)' },
    { key: 'status', header: 'Trạng thái index', render: (r) => <StatusBadge label={r.status === 'active' ? 'Đã index' : r.status} variant={r.status === 'active' ? 'approved' : 'medium'} /> },
    { key: 'processed_at', header: 'Cập nhật gần nhất', render: (r) => r.processed_at || '—' },
    {
      key: 'actions',
      header: 'Thao tác',
      render: (r) => (
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => handleReindex(r.document_id)} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-brand-border text-[11px] font-medium hover:bg-slate-50">
            <RefreshCw className="w-3 h-3" /> Re-index
          </button>
          <button type="button" onClick={() => handleDelete(r.document_id)} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-red-200 bg-red-50 text-brand-red text-[11px] font-medium hover:bg-red-100">
            <Trash2 className="w-3 h-3" /> Xóa
          </button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-blue/10 text-brand-blue flex items-center justify-center">
            <BookOpen className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-slate-900">Kho tài liệu RAG (Nội quy &amp; Chính sách)</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Quản lý tài liệu nội bộ, tách đoạn (chunking), re-index và kiểm soát trạng thái tri thức phục vụ Trợ lý AI.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-brand-blue text-white text-xs font-semibold hover:bg-blue-700"
        >
          <Plus className="w-4 h-4" /> Thêm tài liệu RAG
        </button>
      </div>

      {loading && <LoadingSkeleton rows={4} />}
      {!loading && error && <ErrorState message={error} onRetry={loadDocs} />}
      {!loading && !error && <DataTable columns={columns} data={docs} rowKey={(r) => String(r.document_id)} emptyTitle="Chưa có tài liệu RAG nào" />}

      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <form onSubmit={handleUpload} className="w-full max-w-lg rounded-card border border-brand-border bg-white p-6 shadow-xl space-y-3.5 text-xs">
            <div className="flex items-center justify-between pb-2 border-b border-brand-border">
              <h3 className="text-sm font-bold text-slate-900">Tải lên tài liệu vào Kho RAG</h3>
              <button type="button" onClick={() => setModalOpen(false)}><X className="w-4 h-4" /></button>
            </div>
            <div>
              <label className="block font-medium text-slate-700 mb-1">Tiêu đề tài liệu *</label>
              <input required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="VD: Quy định nghỉ phép và tăng ca 2026" className="w-full px-3 py-2 rounded-lg border border-brand-border" />
            </div>
            <div className="grid grid-cols-3 gap-2.5">
              <div>
                <label className="block font-medium text-slate-700 mb-1">Tên file</label>
                <input required value={form.original_file_name} onChange={(e) => setForm({ ...form, original_file_name: e.target.value })} className="w-full px-3 py-2 rounded-lg border border-brand-border" />
              </div>
              <div>
                <label className="block font-medium text-slate-700 mb-1">Loại</label>
                <select value={form.document_type} onChange={(e) => setForm({ ...form, document_type: e.target.value })} className="w-full px-3 py-2 rounded-lg border border-brand-border bg-white">
                  <option value="policy">Nội quy</option>
                  <option value="attendance_policy">Chấm công</option>
                  <option value="anomaly_guide">Quy tắc R1–R8</option>
                </select>
              </div>
              <div>
                <label className="block font-medium text-slate-700 mb-1">Phiên bản</label>
                <input value={form.version_label} onChange={(e) => setForm({ ...form, version_label: e.target.value })} className="w-full px-3 py-2 rounded-lg border border-brand-border" />
              </div>
            </div>
            <div>
              <label className="block font-medium text-slate-700 mb-1">Nội dung văn bản / Markdown *</label>
              <textarea required minLength={10} rows={6} value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} placeholder="Dán nội dung điều khoản, quy chế cần đánh chỉ mục..." className="w-full px-3 py-2 rounded-lg border border-brand-border" />
            </div>
            <div className="flex justify-end gap-2 pt-2 border-t border-brand-border">
              <button type="button" onClick={() => setModalOpen(false)} className="px-4 py-2 rounded-lg border border-brand-border">Hủy</button>
              <button type="submit" disabled={submitting} className="px-4 py-2 rounded-lg bg-brand-blue text-white font-semibold disabled:opacity-50">{submitting ? 'Đang index...' : 'Lưu & Index'}</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};
