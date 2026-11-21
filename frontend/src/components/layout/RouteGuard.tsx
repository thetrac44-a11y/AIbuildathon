import React from 'react';
import { Link } from 'react-router-dom';
import { ShieldAlert } from 'lucide-react';
import { canAccessScreen, SITEMAP_SCREENS } from '../../config/navigation';
import { useDevAuth } from '../../context/DevAuthContext';

export interface RouteGuardProps {
  screenId: string;
  children: React.ReactNode;
}

export const RouteGuard: React.FC<RouteGuardProps> = ({ screenId, children }) => {
  const { currentUser } = useDevAuth();
  const screen = SITEMAP_SCREENS.find((s) => s.id === screenId);

  if (!screen || !canAccessScreen(currentUser.role, screen)) {
    return (
      <div className="rounded-card border border-red-200 bg-white p-8 text-center max-w-lg mx-auto my-8 shadow-sm">
        <div className="w-12 h-12 rounded-full bg-red-50 text-brand-red flex items-center justify-center mx-auto mb-3">
          <ShieldAlert className="w-6 h-6" />
        </div>
        <h2 className="text-base font-bold text-slate-900">403 – Không có quyền truy cập</h2>
        <p className="mt-2 text-xs text-slate-600 leading-relaxed">
          Vai trò hiện tại (<strong>{currentUser.role.toUpperCase()}</strong>) không được phép truy
          cập màn hình <strong>{screen?.title ?? screenId}</strong>. Lưu ý: quyền truy cập dữ liệu
          cũng sẽ được cưỡng chế bắt buộc ở tầng Backend API và Database.
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
