import React, { useCallback, useEffect, useState } from 'react';
import { Save, Settings, ShieldAlert } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { apiFetch, ApiError } from '../lib/api';
import { StatusBadge } from '../components/ui/StatusBadge';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';

interface SettingItem {
  setting_key: string;
  category: string;
  setting_value: string;
  value_type: string;
  description: string | null;
  updated_at: string;
}

export const SystemConfigPage: React.FC = () => {
  const { showToast } = useAuth();
  const [items, setItems] = useState<SettingItem[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [dbEngine, setDbEngine] = useState<string>('sqlite');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch<{ items: SettingItem[]; database_engine: string }>('/system/config');
      setItems(res.items || []);
      setDbEngine(res.database_engine || 'sqlite');
      const map: Record<string, string> = {};
      for (const s of res.items || []) map[s.setting_key] = s.setting_value;
      setDraft(map);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể tải cấu hình hệ thống.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const handleSave = async () => {
    const changed = items
      .filter((s) => draft[s.setting_key] !== s.setting_value)
      .map((s) => ({ setting_key: s.setting_key, setting_value: draft[s.setting_key] ?? '' }));
    if (changed.length === 0) {
      showToast('Không có thay đổi nào cần lưu.', 'info');
      return;
    }
    setSaving(true);
    try {
      await apiFetch('/system/config', {
        method: 'PATCH',
        body: JSON.stringify({ settings: changed }),
      });
      showToast(`Đã cập nhật ${changed.length} thiết lập hệ thống.`, 'success');
      loadConfig();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Lưu cấu hình thất bại.', 'error');
    } finally {
      setSaving(false);
    }
  };

  if (loading && items.length === 0) return <LoadingSkeleton rows={5} />;
  if (error) return <ErrorState message={error} onRetry={loadConfig} />;

  return (
    <div className="space-y-5">
      <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-navy/10 text-brand-navy flex items-center justify-center">
            <Settings className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-slate-900">Cấu hình Kỹ thuật Hệ thống</h2>
              <StatusBadge label={dbEngine} variant="info" />
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Quản trị tham số AI Provider, Embedding, Face Kiosk, Workflow phê duyệt cấp cao và chính sách lưu giữ Audit.
            </p>
          </div>
        </div>
        <button
          type="button"
          disabled={saving}
          onClick={handleSave}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-brand-blue text-white text-xs font-semibold hover:bg-blue-700 disabled:opacity-50"
        >
          <Save className="w-4 h-4" />
          {saving ? 'Đang lưu...' : 'Lưu cấu hình'}
        </button>
      </div>

      <div className="rounded-lg border border-blue-200 bg-blue-50/60 px-4 py-2.5 flex items-center gap-2.5 text-xs text-brand-navy">
        <ShieldAlert className="w-4 h-4 text-brand-blue shrink-0" />
        <span>
          Bảo mật: Bảng cấu hình này chỉ quản lý tham số kỹ thuật không nhạy cảm. API Key, JWT Secret và mật khẩu DB luôn được giữ riêng trong biến môi trường server.
        </span>
      </div>

      <div className="rounded-card border border-brand-border bg-white divide-y divide-brand-border shadow-sm">
        {items.map((s) => (
          <div key={s.setting_key} className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono font-semibold text-slate-900">{s.setting_key}</span>
                <StatusBadge label={s.category} variant="dismissed" />
              </div>
              <p className="text-[11px] text-slate-500 mt-0.5">{s.description}</p>
            </div>
            <input
              type="text"
              value={draft[s.setting_key] ?? ''}
              onChange={(e) => setDraft({ ...draft, [s.setting_key]: e.target.value })}
              className="sm:w-64 px-3 py-1.5 text-xs rounded-lg border border-brand-border font-mono"
            />
          </div>
        ))}
      </div>
    </div>
  );
};
