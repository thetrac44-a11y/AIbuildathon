import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertCircle,
  Briefcase,
  CalendarDays,
  KeyRound,
  Lock,
  Phone,
  Save,
  Shield,
  UserCheck,
} from 'lucide-react';
import { AuthUser, useAuth } from '../context/AuthContext';
import { apiFetch, ApiError } from '../lib/api';
import { StatusBadge } from '../components/ui/StatusBadge';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';

const ROLE_LABELS: Record<string, string> = {
  employee: 'Nhân viên (Employee)',
  manager: 'Trưởng phòng (Manager)',
  hr: 'Nhân sự / Quản trị (HR)',
};

export const ProfilePage: React.FC = () => {
  const { refreshProfile, showToast } = useAuth();
  const [profile, setProfile] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Contact form (phone only)
  const [phone, setPhone] = useState<string>('');
  const [savingPhone, setSavingPhone] = useState<boolean>(false);

  // Change password form
  const [currentPassword, setCurrentPassword] = useState<string>('');
  const [newPassword, setNewPassword] = useState<string>('');
  const [confirmPassword, setConfirmPassword] = useState<string>('');
  const [savingPwd, setSavingPwd] = useState<boolean>(false);
  const [pwdError, setPwdError] = useState<string | null>(null);

  const loadProfile = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<AuthUser>('/profile');
      setProfile(data);
      setPhone(data.phone || '');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể tải hồ sơ cá nhân.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  const handleSavePhone = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingPhone(true);
    try {
      const updated = await apiFetch<AuthUser>('/profile', {
        method: 'PATCH',
        body: JSON.stringify({ phone: phone.trim() || null }),
      });
      setProfile(updated);
      await refreshProfile();
      showToast('Đã cập nhật số điện thoại liên hệ.', 'success');
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Không thể cập nhật thông tin.', 'error');
    } finally {
      setSavingPhone(false);
    }
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwdError(null);
    if (newPassword.length < 6) {
      setPwdError('Mật khẩu mới phải có ít nhất 6 ký tự.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setPwdError('Mật khẩu xác nhận không khớp với mật khẩu mới.');
      return;
    }

    setSavingPwd(true);
    try {
      await apiFetch('/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      await refreshProfile();
      await loadProfile();
      showToast('Đổi mật khẩu thành công!', 'success');
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Đổi mật khẩu thất bại.';
      setPwdError(msg);
      showToast(msg, 'error');
    } finally {
      setSavingPwd(false);
    }
  };

  if (loading) return <LoadingSkeleton rows={4} />;
  if (error || !profile) return <ErrorState message={error || 'Không tìm thấy hồ sơ.'} onRetry={loadProfile} />;

  const usedPct =
    profile.annual_leave_balance > 0
      ? Math.min(100, Math.round((profile.used_annual_leave / profile.annual_leave_balance) * 100))
      : 0;

  return (
    <div className="space-y-6">
      {profile.must_change_password && (
        <div className="rounded-card border border-amber-300 bg-amber-50 p-4 flex items-start gap-3 text-xs text-amber-900">
          <AlertCircle className="w-5 h-5 text-brand-amber shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold">Khuyến nghị đổi mật khẩu lần đầu</p>
            <p className="mt-0.5">
              Tài khoản của bạn đang được đánh dấu cần thay đổi mật khẩu mặc định. Vui lòng cập nhật mật khẩu mới ở bên dưới.
            </p>
          </div>
        </div>
      )}

      {/* Top identity summary */}
      <div className="rounded-card border border-brand-border bg-white p-6 shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4 min-w-0">
          <div
            data-testid="profile-avatar"
            className="w-14 h-14 shrink-0 rounded-2xl bg-brand-navy text-white flex items-center justify-center text-lg font-bold"
          >
            {profile.full_name
              .split(' ')
              .slice(-2)
              .map((w) => w[0])
              .join('')
              .toUpperCase()}
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-bold text-slate-900">{profile.full_name}</h2>
              <StatusBadge label={profile.employee_id} variant="info" />
              <StatusBadge
                label={profile.employment_status === 'active' ? 'Đang làm việc' : 'Ngừng hoạt động'}
                variant={profile.employment_status === 'active' ? 'approved' : 'dismissed'}
              />
            </div>
            <p className="mt-1 text-xs text-slate-500">
              {profile.position} • Phòng {profile.department_name} • Tài khoản:{' '}
              <span className="font-mono text-slate-700">{profile.username}</span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-100 border border-brand-border text-xs text-slate-700">
          <Shield className="w-4 h-4 text-brand-blue" />
          <span>{ROLE_LABELS[profile.role] || profile.role}</span>
        </div>
      </div>

      {/* Main 2-column grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Read-only Work Info + Annual Leave Quota */}
        <div className="lg:col-span-2 space-y-6">
          <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between gap-2 pb-3 border-b border-brand-border">
              <div className="flex items-center gap-2">
                <Briefcase className="w-4 h-4 text-brand-blue" />
                <h3 className="text-sm font-bold text-slate-900">Thông tin công việc (Chỉ xem)</h3>
              </div>
              <span className="inline-flex items-center gap-1 text-[11px] text-slate-500">
                <Lock className="w-3 h-3" /> Do bộ phận HR quản lý
              </span>
            </div>

            <dl className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
              <div className="p-3 rounded-lg bg-brand-bg/60 border border-brand-border/60">
                <dt className="text-slate-500">Mã nhân viên</dt>
                <dd className="mt-1 font-mono font-semibold text-slate-900">{profile.employee_id}</dd>
              </div>
              <div className="p-3 rounded-lg bg-brand-bg/60 border border-brand-border/60">
                <dt className="text-slate-500">Email công ty</dt>
                <dd className="mt-1 font-medium text-slate-900">{profile.email || '—'}</dd>
              </div>
              <div className="p-3 rounded-lg bg-brand-bg/60 border border-brand-border/60">
                <dt className="text-slate-500">Phòng ban</dt>
                <dd className="mt-1 font-medium text-slate-900">
                  {profile.department_name} ({profile.department_id})
                </dd>
              </div>
              <div className="p-3 rounded-lg bg-brand-bg/60 border border-brand-border/60">
                <dt className="text-slate-500">Chức danh</dt>
                <dd className="mt-1 font-medium text-slate-900">{profile.position}</dd>
              </div>
              <div className="p-3 rounded-lg bg-brand-bg/60 border border-brand-border/60">
                <dt className="text-slate-500">Quản lý trực tiếp</dt>
                <dd className="mt-1 font-medium text-slate-900">
                  {profile.manager_name ? `${profile.manager_name} (${profile.manager_id})` : 'Cấp lãnh đạo / Không áp dụng'}
                </dd>
              </div>
              <div className="p-3 rounded-lg bg-brand-bg/60 border border-brand-border/60">
                <dt className="text-slate-500">Ngày bắt đầu làm việc</dt>
                <dd className="mt-1 font-medium text-slate-900">{profile.start_date}</dd>
              </div>
            </dl>
          </div>

          {/* Leave Balance */}
          <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm">
            <div className="flex items-center gap-2 pb-3 border-b border-brand-border">
              <CalendarDays className="w-4 h-4 text-brand-teal" />
              <h3 className="text-sm font-bold text-slate-900">Quỹ nghỉ phép năm 2026</h3>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-3 text-center">
              <div className="rounded-lg border border-brand-border bg-slate-50 p-3.5">
                <p className="text-[11px] text-slate-500">Định mức cả năm</p>
                <p className="mt-1 text-xl font-bold text-slate-900">{profile.annual_leave_balance}</p>
                <p className="text-[11px] text-slate-400">ngày</p>
              </div>
              <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3.5">
                <p className="text-[11px] text-amber-800">Đã duyệt sử dụng</p>
                <p className="mt-1 text-xl font-bold text-brand-amber">{profile.used_annual_leave}</p>
                <p className="text-[11px] text-amber-700">ngày</p>
              </div>
              <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-3.5">
                <p className="text-[11px] text-emerald-800">Còn lại khả dụng</p>
                <p className="mt-1 text-xl font-bold text-brand-green">{profile.remaining_annual_leave}</p>
                <p className="text-[11px] text-emerald-700">ngày</p>
              </div>
            </div>
            <div className="mt-4">
              <div className="flex justify-between text-[11px] text-slate-500 mb-1">
                <span>Tiến độ sử dụng phép năm</span>
                <span>{usedPct}%</span>
              </div>
              <div className="h-2.5 w-full rounded-full bg-slate-100 overflow-hidden">
                <div
                  className="h-full rounded-full bg-brand-teal transition-all"
                  style={{ width: `${usedPct}%` }}
                />
              </div>
            </div>
          </div>
        </div>

        {/* Right: Editable Phone + Change Password */}
        <div className="space-y-6">
          <form onSubmit={handleSavePhone} className="rounded-card border border-brand-border bg-white p-5 shadow-sm space-y-4">
            <div className="flex items-center gap-2 pb-3 border-b border-brand-border">
              <Phone className="w-4 h-4 text-brand-blue" />
              <h3 className="text-sm font-bold text-slate-900">Thông tin liên hệ</h3>
            </div>
            <div>
              <label htmlFor="profile-phone" className="block text-xs font-medium text-slate-700 mb-1.5">
                Số điện thoại cá nhân
              </label>
              <input
                id="profile-phone"
                type="text"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="VD: 0901234567"
                maxLength={30}
                className="w-full px-3 py-2 text-xs rounded-lg border border-brand-border focus:outline-none focus:border-brand-blue"
              />
              <p className="mt-1.5 text-[11px] text-slate-500">
                Vì lý do bảo mật, bạn chỉ có thể tự cập nhật số điện thoại. Để thay đổi vai trò, phòng ban hoặc quỹ phép, vui lòng liên hệ HR.
              </p>
            </div>
            <button
              type="submit"
              disabled={savingPhone}
              className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-brand-blue text-white text-xs font-semibold hover:bg-blue-700 disabled:opacity-50"
            >
              <Save className="w-4 h-4" />
              {savingPhone ? 'Đang lưu...' : 'Lưu số điện thoại'}
            </button>
          </form>

          <form onSubmit={handleChangePassword} className="rounded-card border border-brand-border bg-white p-5 shadow-sm space-y-3.5">
            <div className="flex items-center gap-2 pb-3 border-b border-brand-border">
              <KeyRound className="w-4 h-4 text-brand-navy" />
              <h3 className="text-sm font-bold text-slate-900">Đổi mật khẩu</h3>
            </div>

            {pwdError && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-brand-red">
                {pwdError}
              </div>
            )}

            <div>
              <label htmlFor="cur-pwd" className="block text-xs font-medium text-slate-700 mb-1">
                Mật khẩu hiện tại
              </label>
              <input
                id="cur-pwd"
                type="password"
                required
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                className="w-full px-3 py-2 text-xs rounded-lg border border-brand-border focus:outline-none focus:border-brand-blue"
              />
            </div>

            <div>
              <label htmlFor="new-pwd" className="block text-xs font-medium text-slate-700 mb-1">
                Mật khẩu mới (tối thiểu 6 ký tự)
              </label>
              <input
                id="new-pwd"
                type="password"
                required
                minLength={6}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="w-full px-3 py-2 text-xs rounded-lg border border-brand-border focus:outline-none focus:border-brand-blue"
              />
            </div>

            <div>
              <label htmlFor="confirm-pwd" className="block text-xs font-medium text-slate-700 mb-1">
                Nhập lại mật khẩu mới
              </label>
              <input
                id="confirm-pwd"
                type="password"
                required
                minLength={6}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full px-3 py-2 text-xs rounded-lg border border-brand-border focus:outline-none focus:border-brand-blue"
              />
            </div>

            <button
              type="submit"
              disabled={savingPwd}
              className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-brand-navy text-white text-xs font-semibold hover:bg-slate-800 disabled:opacity-50"
            >
              <UserCheck className="w-4 h-4" />
              {savingPwd ? 'Đang cập nhật...' : 'Cập nhật mật khẩu'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};
