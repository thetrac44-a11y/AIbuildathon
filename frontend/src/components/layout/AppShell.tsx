import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Clock,
  CalendarDays,
  AlertTriangle,
  Sparkles,
  FileSpreadsheet,
  UserCircle,
  UploadCloud,
  Users,
  ShieldCheck,
  Menu,
  X,
  Bell,
  ChevronLeft,
  ChevronRight,
  LogOut,
  CheckCircle2,
  AlertCircle,
  Info,
} from 'lucide-react';
import { getVisibleNavGroups, SITEMAP_SCREENS } from '../../config/navigation';
import { AVAILABLE_PERIODS, useAuth } from '../../context/AuthContext';
import { NavItem } from '../../types/navigation';

const iconMap: Record<NavItem['iconName'], React.ReactNode> = {
  LayoutDashboard: <LayoutDashboard className="w-4 h-4 shrink-0" />,
  Clock: <Clock className="w-4 h-4 shrink-0" />,
  CalendarDays: <CalendarDays className="w-4 h-4 shrink-0" />,
  AlertTriangle: <AlertTriangle className="w-4 h-4 shrink-0" />,
  Sparkles: <Sparkles className="w-4 h-4 shrink-0" />,
  FileSpreadsheet: <FileSpreadsheet className="w-4 h-4 shrink-0" />,
  UserCircle: <UserCircle className="w-4 h-4 shrink-0" />,
  UploadCloud: <UploadCloud className="w-4 h-4 shrink-0" />,
  Users: <Users className="w-4 h-4 shrink-0" />,
  ShieldCheck: <ShieldCheck className="w-4 h-4 shrink-0" />,
};

export const AppShell: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, logout, selectedPeriod, setSelectedPeriod, toasts, dismissToast } = useAuth();
  const location = useLocation();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);

  if (!user) return null;

  const visibleGroups = getVisibleNavGroups(user.role);
  const currentScreen = SITEMAP_SCREENS.find((s) => location.pathname.startsWith(s.path));
  const pageTitle = currentScreen?.title ?? 'Tổng quan';
  const showPeriodFilter = currentScreen?.syncPeriodFilter ?? true;

  const renderSidebarContent = (isMobile = false) => (
    <div className="flex flex-col h-full bg-brand-navy text-white">
      <div className="flex items-center justify-between px-4 py-4 border-b border-white/10">
        <div className="flex items-center gap-2.5 overflow-hidden">
          <div className="w-8 h-8 rounded-lg bg-brand-blue flex items-center justify-center font-bold text-sm shrink-0">
            H
          </div>
          {(!sidebarCollapsed || isMobile) && (
            <div className="truncate">
              <p className="text-sm font-bold leading-tight truncate">HR Attendance</p>
              <p className="text-[10px] tracking-wider uppercase text-blue-300 font-semibold">
                COPILOT
              </p>
            </div>
          )}
        </div>
        {isMobile ? (
          <button
            type="button"
            aria-label="Đóng menu"
            onClick={() => setMobileDrawerOpen(false)}
            className="p-1.5 rounded-lg text-slate-300 hover:bg-white/10"
          >
            <X className="w-4 h-4" />
          </button>
        ) : (
          <button
            type="button"
            aria-label={sidebarCollapsed ? 'Mở rộng sidebar' : 'Thu gọn sidebar'}
            onClick={() => setSidebarCollapsed((prev) => !prev)}
            className="hidden lg:inline-flex p-1.5 rounded-lg text-slate-300 hover:bg-white/10"
          >
            {sidebarCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>
        )}
      </div>

      <nav aria-label="Điều hướng chính" className="flex-1 overflow-y-auto px-3 py-4 space-y-5">
        {visibleGroups.map(({ group, items }) => (
          <div key={group}>
            {(!sidebarCollapsed || isMobile) && (
              <p className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                {group}
              </p>
            )}
            <ul className="space-y-1">
              {items.map((item) => {
                const isActive = location.pathname === item.path;
                return (
                  <li key={item.id}>
                    <Link
                      to={item.path}
                      onClick={() => setMobileDrawerOpen(false)}
                      title={sidebarCollapsed && !isMobile ? item.title : undefined}
                      className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-medium transition-colors ${
                        isActive
                          ? 'bg-brand-blue text-white shadow-sm'
                          : 'text-slate-300 hover:bg-white/10 hover:text-white'
                      }`}
                    >
                      {iconMap[item.iconName]}
                      {(!sidebarCollapsed || isMobile) && <span className="truncate">{item.title}</span>}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="p-3 border-t border-white/10 space-y-2">
        <div className="flex items-center gap-2.5 rounded-xl bg-white/5 p-2.5">
          <div className="w-8 h-8 rounded-full bg-brand-blue/30 text-blue-200 flex items-center justify-center text-xs font-bold shrink-0">
            {user.employee_id.slice(-2)}
          </div>
          {(!sidebarCollapsed || isMobile) && (
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold text-white truncate">{user.full_name}</p>
              <p className="text-[11px] text-slate-300 truncate">
                {user.employee_id} · {user.role.toUpperCase()}
              </p>
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={logout}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-xl text-xs font-medium text-slate-300 hover:bg-white/10 hover:text-white transition-colors"
        >
          <LogOut className="w-3.5 h-3.5 shrink-0" />
          {(!sidebarCollapsed || isMobile) && <span>Đăng xuất</span>}
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen flex bg-brand-bg text-slate-900">
      <aside
        className={`hidden lg:block shrink-0 transition-all duration-200 ${
          sidebarCollapsed ? 'w-[76px]' : 'w-[256px]'
        }`}
      >
        <div className="sticky top-0 h-screen">{renderSidebarContent(false)}</div>
      </aside>

      {mobileDrawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden flex">
          <div
            className="fixed inset-0 bg-slate-900/50"
            onClick={() => setMobileDrawerOpen(false)}
          />
          <div className="relative z-50 w-64 max-w-[80vw] h-full">{renderSidebarContent(true)}</div>
        </div>
      )}

      <div className="flex-1 flex flex-col min-w-0">
        <header className="sticky top-0 z-20 bg-white/95 backdrop-blur border-b border-brand-border px-4 lg:px-7 py-3.5 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <button
              type="button"
              aria-label="Mở menu điều hướng"
              onClick={() => setMobileDrawerOpen(true)}
              className="lg:hidden p-2 rounded-lg border border-brand-border text-slate-700 hover:bg-brand-bg"
            >
              <Menu className="w-4 h-4" />
            </button>
            <div className="min-w-0">
              <h1 className="text-lg font-bold text-slate-900 truncate">{pageTitle}</h1>
              <p className="text-[11px] text-slate-500 truncate">
                Phạm vi dữ liệu:{' '}
                <strong className="text-slate-700">
                  {user.role === 'hr'
                    ? 'Toàn công ty'
                    : user.role === 'manager'
                      ? `Phòng ${user.department_name}`
                      : `Cá nhân (${user.employee_id})`}
                </strong>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            {showPeriodFilter && (
              <select
                aria-label="Chọn kỳ tháng"
                value={selectedPeriod}
                onChange={(e) => setSelectedPeriod(e.target.value)}
                className="px-3 py-1.5 rounded-lg border border-brand-border bg-brand-bg/70 text-xs font-medium text-slate-700 focus:outline-none focus:border-brand-blue"
              >
                {AVAILABLE_PERIODS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            )}
            <Link
              to="/anomalies"
              aria-label="Cảnh báo bất thường"
              className="p-2 rounded-lg border border-brand-border bg-white text-slate-600 hover:bg-brand-bg relative"
            >
              <Bell className="w-4 h-4" />
            </Link>
            <Link
              to="/profile"
              className="w-8 h-8 rounded-full bg-brand-blue/15 text-brand-blue font-bold text-xs flex items-center justify-center hover:bg-brand-blue/25"
              title="Hồ sơ cá nhân"
            >
              {user.full_name.charAt(0)}
            </Link>
          </div>
        </header>

        <main className="flex-1 p-4 lg:p-7 max-w-[1440px] w-full mx-auto">{children}</main>
      </div>

      {/* Toast Notifications */}
      <div className="fixed bottom-4 right-4 z-50 space-y-2 max-w-sm w-full pointer-events-none">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto flex items-start gap-2.5 px-4 py-3 rounded-xl border shadow-lg text-xs font-medium bg-white ${
              t.type === 'error'
                ? 'border-red-200 text-brand-red'
                : t.type === 'info'
                  ? 'border-blue-200 text-brand-blue'
                  : 'border-emerald-200 text-brand-green'
            }`}
          >
            {t.type === 'error' ? (
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            ) : t.type === 'info' ? (
              <Info className="w-4 h-4 shrink-0 mt-0.5" />
            ) : (
              <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
            )}
            <span className="flex-1 text-slate-800">{t.text}</span>
            <button
              type="button"
              onClick={() => dismissToast(t.id)}
              className="text-slate-400 hover:text-slate-600"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
};
