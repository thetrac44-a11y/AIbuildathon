import React, { useCallback, useEffect, useState } from 'react';
import { Camera, Plus, Power, Save, SlidersHorizontal, X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { apiFetch, ApiError } from '../lib/api';
import { ColumnDef, DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';

interface KioskDeviceRow {
  kiosk_device_id: string;
  device_name: string;
  location_name: string | null;
  branch_name: string | null;
  is_active: boolean;
  last_seen_at: string | null;
}

interface KioskSettingItem {
  setting_key: string;
  setting_value: string;
  description: string | null;
}

export const KioskDevicesPage: React.FC<{ initialTab?: 'devices' | 'config' }> = ({ initialTab = 'devices' }) => {
  const { showToast } = useAuth();
  const [tab, setTab] = useState<'devices' | 'config'>(initialTab);
  const [devices, setDevices] = useState<KioskDeviceRow[]>([]);
  const [settings, setSettings] = useState<KioskSettingItem[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState({ kiosk_device_id: '', device_name: '', location_name: '', branch_name: '' });

  useEffect(() => {
    setTab(initialTab);
  }, [initialTab]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [devRes, cfgRes] = await Promise.all([
        apiFetch<{ items: KioskDeviceRow[] }>('/kiosk/devices'),
        apiFetch<{ items: KioskSettingItem[] }>('/system/config?category=kiosk'),
      ]);
      setDevices(devRes.items || []);
      setSettings(cfgRes.items || []);
      const map: Record<string, string> = {};
      for (const s of cfgRes.items || []) map[s.setting_key] = s.setting_value;
      setDraft(map);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể tải dữ liệu Face Kiosk.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleAddDevice = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await apiFetch('/kiosk/devices', { method: 'POST', body: JSON.stringify(form) });
      showToast(`Đã đăng ký thiết bị ${form.kiosk_device_id.toUpperCase()}.`, 'success');
      setModalOpen(false);
      setForm({ kiosk_device_id: '', device_name: '', location_name: '', branch_name: '' });
      loadData();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Thêm thiết bị thất bại.', 'error');
    }
  };

  const handleToggle = async (dev: KioskDeviceRow) => {
    try {
      await apiFetch(`/kiosk/devices/${dev.kiosk_device_id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: !dev.is_active }),
      });
      showToast(`Đã ${dev.is_active ? 'tạm ngưng' : 'kích hoạt'} thiết bị ${dev.kiosk_device_id}.`, 'success');
      loadData();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Cập nhật thất bại.', 'error');
    }
  };

  const handleSaveConfig = async () => {
    try {
      await apiFetch('/system/config', {
        method: 'PATCH',
        body: JSON.stringify({
          settings: settings.map((s) => ({ setting_key: s.setting_key, setting_value: draft[s.setting_key] ?? '' })),
        }),
      });
      showToast('Đã lưu cấu hình Face Kiosk.', 'success');
      loadData();
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Lưu cấu hình thất bại.', 'error');
    }
  };

  const columns: ColumnDef<KioskDeviceRow>[] = [
    { key: 'kiosk_device_id', header: 'Mã thiết bị', render: (r) => <span className="font-mono font-semibold text-brand-navy">{r.kiosk_device_id}</span> },
    { key: 'device_name', header: 'Tên thiết bị' },
    { key: 'location_name', header: 'Vị trí', render: (r) => r.location_name || '—' },
    { key: 'branch_name', header: 'Chi nhánh', render: (r) => r.branch_name || '—' },
    { key: 'is_active', header: 'Trạng thái', render: (r) => <StatusBadge label={r.is_active ? 'Hoạt động' : 'Tạm ngưng'} variant={r.is_active ? 'approved' : 'rejected'} /> },
    {
      key: 'actions',
      header: 'Thao tác',
      render: (r) => (
        <button type="button" onClick={() => handleToggle(r)} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-brand-border text-[11px] font-medium hover:bg-slate-50">
          <Power className="w-3 h-3" /> {r.is_active ? 'Tạm ngưng' : 'Kích hoạt'}
        </button>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-navy/10 text-brand-navy flex items-center justify-center">
            <Camera className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-slate-900">Face Kiosk – Thiết bị &amp; Cấu hình kỹ thuật</h2>
            <p className="text-xs text-slate-500 mt-0.5">Quản lý danh sách thiết bị chấm công khuôn mặt và ngưỡng nhận diện InsightFace / Liveness.</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setTab('devices')} className={`inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold ${tab === 'devices' ? 'bg-brand-navy text-white' : 'bg-slate-100 text-slate-600'}`}>
            <Camera className="w-3.5 h-3.5" /> Thiết bị ({devices.length})
          </button>
          <button type="button" onClick={() => setTab('config')} className={`inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold ${tab === 'config' ? 'bg-brand-navy text-white' : 'bg-slate-100 text-slate-600'}`}>
            <SlidersHorizontal className="w-3.5 h-3.5" /> Cấu hình Kiosk
          </button>
          {tab === 'devices' ? (
            <button type="button" onClick={() => setModalOpen(true)} className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-brand-blue text-white text-xs font-semibold hover:bg-blue-700">
              <Plus className="w-4 h-4" /> Thêm thiết bị
            </button>
          ) : (
            <button type="button" onClick={handleSaveConfig} className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-brand-blue text-white text-xs font-semibold hover:bg-blue-700">
              <Save className="w-4 h-4" /> Lưu cấu hình
            </button>
          )}
        </div>
      </div>

      {loading && <LoadingSkeleton rows={4} />}
      {!loading && error && <ErrorState message={error} onRetry={loadData} />}
      {!loading && !error && tab === 'devices' && <DataTable columns={columns} data={devices} rowKey={(r) => r.kiosk_device_id} emptyTitle="Chưa có thiết bị Kiosk" />}
      {!loading && !error && tab === 'config' && (
        <div className="rounded-card border border-brand-border bg-white divide-y divide-brand-border shadow-sm">
          {settings.map((s) => (
            <div key={s.setting_key} className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <p className="text-xs font-mono font-semibold text-slate-900">{s.setting_key}</p>
                <p className="text-[11px] text-slate-500 mt-0.5">{s.description}</p>
              </div>
              <input value={draft[s.setting_key] ?? ''} onChange={(e) => setDraft({ ...draft, [s.setting_key]: e.target.value })} className="sm:w-64 px-3 py-1.5 text-xs rounded-lg border border-brand-border font-mono" />
            </div>
          ))}
        </div>
      )}

      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <form onSubmit={handleAddDevice} className="w-full max-w-md rounded-card border border-brand-border bg-white p-6 shadow-xl space-y-3.5 text-xs">
            <div className="flex items-center justify-between pb-2 border-b border-brand-border">
              <h3 className="text-sm font-bold text-slate-900">Đăng ký thiết bị Face Kiosk</h3>
              <button type="button" onClick={() => setModalOpen(false)}><X className="w-4 h-4" /></button>
            </div>
            <div>
              <label className="block font-medium text-slate-700 mb-1">Mã thiết bị *</label>
              <input required value={form.kiosk_device_id} onChange={(e) => setForm({ ...form, kiosk_device_id: e.target.value })} placeholder="VD: KIOSK-HQ-03" className="w-full px-3 py-2 rounded-lg border border-brand-border" />
            </div>
            <div>
              <label className="block font-medium text-slate-700 mb-1">Tên thiết bị *</label>
              <input required value={form.device_name} onChange={(e) => setForm({ ...form, device_name: e.target.value })} placeholder="Cổng khu B" className="w-full px-3 py-2 rounded-lg border border-brand-border" />
            </div>
            <div>
              <label className="block font-medium text-slate-700 mb-1">Vị trí đặt</label>
              <input value={form.location_name} onChange={(e) => setForm({ ...form, location_name: e.target.value })} placeholder="Sảnh tầng 3" className="w-full px-3 py-2 rounded-lg border border-brand-border" />
            </div>
            <div>
              <label className="block font-medium text-slate-700 mb-1">Chi nhánh</label>
              <input value={form.branch_name} onChange={(e) => setForm({ ...form, branch_name: e.target.value })} placeholder="Trụ sở chính Hà Nội" className="w-full px-3 py-2 rounded-lg border border-brand-border" />
            </div>
            <div className="flex justify-end gap-2 pt-2 border-t border-brand-border">
              <button type="button" onClick={() => setModalOpen(false)} className="px-4 py-2 rounded-lg border border-brand-border">Hủy</button>
              <button type="submit" className="px-4 py-2 rounded-lg bg-brand-blue text-white font-semibold">Đăng ký</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};
