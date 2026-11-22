import React, { useState } from 'react';
import { ChevronDown, ChevronUp, ShieldCheck, UserCheck } from 'lucide-react';

export interface DemoAccountOption {
  roleLabel: 'HR Admin' | 'Manager' | 'Employee';
  badgeClass: string;
  username: string;
  employeeId: string;
  scopeDescription: string;
}

export const DEV_DEMO_ACCOUNTS: DemoAccountOption[] = [
  {
    roleLabel: 'HR Admin',
    badgeClass: 'bg-blue-50 text-brand-blue border-blue-200',
    username: 'hr@company.vn',
    employeeId: 'NV002',
    scopeDescription: 'Toàn công ty (80 NV · Đủ 10 màn hình)',
  },
  {
    roleLabel: 'Manager',
    badgeClass: 'bg-teal-50 text-brand-teal border-teal-200',
    username: 'manager.sales@company.vn',
    employeeId: 'NV001',
    scopeDescription: 'Phòng Kinh doanh (16 NV · Duyệt & Báo cáo)',
  },
  {
    roleLabel: 'Employee',
    badgeClass: 'bg-slate-100 text-slate-700 border-slate-200',
    username: 'nv007@company.vn',
    employeeId: 'NV007',
    scopeDescription: 'Phạm vi cá nhân (Kịch bản S1 · 6 màn hình)',
  },
];

interface DemoAccountsPanelProps {
  disabled?: boolean;
  selectedEmail: string;
  hasQuickLoginPassword: boolean;
  onSelectDemo: (username: string) => void;
}

export const DemoAccountsPanel: React.FC<DemoAccountsPanelProps> = ({
  disabled = false,
  selectedEmail,
  hasQuickLoginPassword,
  onSelectDemo,
}) => {
  const [isOpen, setIsOpen] = useState(false);

  if (!import.meta.env.DEV) {
    return null;
  }

  return (
    <div className="mt-4 pt-3.5 border-t border-brand-border">
      <button
        type="button"
        aria-expanded={isOpen}
        aria-controls="demo-accounts-list"
        onClick={() => setIsOpen((prev) => !prev)}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-xl bg-slate-50 hover:bg-slate-100/90 border border-brand-border text-left transition-colors focus:outline-none focus:ring-2 focus:ring-brand-blue/25"
      >
        <span className="flex items-center gap-2 text-xs font-semibold text-slate-700">
          <ShieldCheck className="w-3.5 h-3.5 text-brand-blue shrink-0" />
          <span>Trải nghiệm tài khoản demo</span>
          <span className="rounded bg-amber-50 border border-amber-200 px-1.5 py-0.5 text-[10px] font-semibold text-brand-amber leading-none">
            DEV
          </span>
        </span>
        {isOpen ? (
          <ChevronUp className="w-4 h-4 text-slate-500 shrink-0" />
        ) : (
          <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" />
        )}
      </button>

      {isOpen && (
        <div id="demo-accounts-list" className="mt-2 space-y-1.5">
          <p className="text-[11px] text-slate-500 leading-snug px-0.5">
            {hasQuickLoginPassword
              ? 'Nhấp vào vai trò để đăng nhập qua API thật (Development).'
              : 'Nhấp để điền email vai trò, sau đó nhập mật khẩu seed local.'}
          </p>

          {DEV_DEMO_ACCOUNTS.map((acc) => {
            const isSelected = selectedEmail.trim().toLowerCase() === acc.username;
            return (
              <button
                key={acc.username}
                type="button"
                disabled={disabled}
                onClick={() => onSelectDemo(acc.username)}
                className={`w-full text-left px-2.5 py-2 rounded-xl border transition-all disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-brand-blue/25 ${
                  isSelected
                    ? 'border-brand-blue bg-blue-50/50 shadow-sm'
                    : 'border-brand-border bg-white hover:border-blue-300 hover:bg-slate-50/70'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border shrink-0 leading-none ${acc.badgeClass}`}
                    >
                      {acc.roleLabel}
                    </span>
                    <span className="text-[11px] font-mono font-medium text-slate-800 truncate">
                      {acc.username}
                    </span>
                  </div>
                  <span className="inline-flex items-center gap-1 text-[10px] font-medium text-brand-blue shrink-0">
                    <UserCheck className="w-3 h-3" />
                    {acc.employeeId}
                  </span>
                </div>
                <p className="mt-1 text-[10px] text-slate-500 truncate">
                  {acc.scopeDescription}
                </p>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};
