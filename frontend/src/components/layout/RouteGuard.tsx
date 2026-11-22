import React from 'react';
import { Link } from 'react-router-dom';
import { ShieldAlert } from 'lucide-react';
import { canAccessScreen, SITEMAP_SCREENS } from '../../config/navigation';
import { useAuth } from '../../context/AuthContext';

export interface RouteGuardProps {
  screenId: string;
  children: React.ReactNode;
}

export const RouteGuard: React.FC<RouteGuardProps> = ({ screenId, children }) => {
  const { user } = useAuth();
  const screen = SITEMAP_SCREENS.find((s) => s.id === screenId);

  if (!user || !screen || !canAccessScreen(user.role, screen)) {
    return (
      <div className="rounded-card border border-red-200 bg-white p-8 text-center max-w-lg mx-auto my-8 shadow-sm">
        <div className="w-12 h-12 rounded-full bg-red-50 text-brand-red flex items-center justify-center mx-auto mb-3">
          <ShieldAlert className="w-6 h-6" />
        </div>
        <h2 className="text-base font-bold text-slate-900">403 – Không có quyền truy cập</h2>
        <p className="mt-2 text-xs text-slate-600 leading-relaxed">
          Vai trò hiện tại (<strong>{user?.role.toUpperCase() ?? 'CHƯA ĐĂNG NHẬP'}</strong>) không được phép truy
          cập màn hình <strong>{screen?.title ?? screenId}</strong>. Quyền truy cập dữ liệu cũng được
          kiểm tra bắt buộc ở tầng Backend API.
        </p>
        <div className="mt-5">
          <Link
            to="/dashboard"
            className="inline-flex items-center px-4 py-2 rounded-lg bg-brand-blue text-white text-xs font-semibold hover:bg-blue-700"
          >
            Quay về Tổng quan
          </Link>
        </div>
      </div>
    );
  }

  return <>{children}</>;
};
