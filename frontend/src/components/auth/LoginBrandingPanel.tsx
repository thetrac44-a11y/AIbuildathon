import React from 'react';
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock,
  FileSpreadsheet,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

const KEY_BENEFITS = [
  {
    icon: AlertTriangle,
    title: 'Phát hiện bất thường',
    description: 'Quét 8 quy tắc R1–R8 bằng SQL xác định, giữ nguyên quyết định của HR.',
  },
  {
    icon: Sparkles,
    title: 'AI phân tích dữ liệu',
    description: 'Hỏi đáp tiếng Việt trên 4 view an toàn, kèm bảng, biểu đồ và SQL trace.',
  },
  {
    icon: FileSpreadsheet,
    title: 'Báo cáo tự động',
    description: 'Đối chiếu khớp 100% số liệu nguồn, xuất PDF tiếng Việt và Excel 4 sheet.',
  },
];

const CHART_BARS = [
  { label: 'KD', height: 76, active: false },
  { label: 'KT', height: 92, active: true },
  { label: 'NS', height: 84, active: false },
  { label: 'MKT', height: 68, active: false },
  { label: 'VH', height: 88, active: false },
];

export const MobileBrandHeader: React.FC = () => (
  <div className="lg:hidden w-full bg-gradient-to-r from-[#0B1F33] via-brand-navy to-[#173B63] px-5 py-3.5 text-white shrink-0">
    <div className="max-w-[420px] mx-auto flex items-center gap-3">
      <div className="w-8 h-8 rounded-xl bg-brand-blue flex items-center justify-center shadow-sm shrink-0">
        <ShieldCheck className="w-4 h-4 text-white" />
      </div>
      <div className="min-w-0">
        <p className="text-sm font-bold tracking-tight leading-tight truncate">
          HR Attendance Copilot
        </p>
        <p className="text-[11px] text-blue-200/90 truncate">
          Smarter Attendance. Better Workforce.
        </p>
      </div>
    </div>
  </div>
);

export const LoginBrandingPanel: React.FC = () => {
  return (
    <section
      aria-label="Giới thiệu HR Attendance Copilot"
      className="hidden lg:flex lg:w-[54%] xl:w-[55%] lg:h-full relative overflow-hidden bg-gradient-to-br from-[#0B1F33] via-brand-navy to-[#173D66] text-white flex-col justify-between px-8 py-7 xl:px-12 xl:py-9"
    >
      {/* Subtle architectural grid overlay */}
      <svg
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 h-full w-full opacity-[0.07]"
      >
        <defs>
          <pattern id="enterprise-grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="white" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#enterprise-grid)" />
      </svg>

      {/* Subtle ambient depth */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-24 -right-24 w-80 h-80 rounded-full bg-brand-blue/20 blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-28 -left-24 w-72 h-72 rounded-full bg-brand-teal/15 blur-3xl"
      />

      {/* Top Brand Lockup */}
      <div className="relative z-10 flex items-center justify-between gap-4 shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl bg-brand-blue flex items-center justify-center shadow-md shadow-blue-950/40 ring-1 ring-white/15">
            <ShieldCheck className="w-5 h-5 text-white" />
          </div>
          <div>
            <span className="block text-sm font-bold tracking-tight text-white leading-tight">
              HR Attendance Copilot
            </span>
            <span className="block text-[10px] font-medium tracking-wider text-blue-200/80 uppercase">
              Enterprise Workforce Intelligence
            </span>
          </div>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/[0.06] px-2.5 py-1 text-[11px] font-medium text-blue-100">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          SQL-Verified AI
        </span>
      </div>

      {/* Main Centered Content (fits cleanly in 1 single desktop viewport without scroll) */}
      <div className="relative z-10 my-auto space-y-5 xl:space-y-6 max-w-xl w-full mx-auto">
        <div className="space-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-blue-300">
            Smarter Attendance. Better Workforce.
          </p>
          <h1 className="text-2xl xl:text-[28px] font-bold tracking-tight leading-snug text-white">
            Trợ lý chấm công thông minh và báo cáo nhân sự tự động.
          </h1>
          <p className="text-xs xl:text-[13px] text-slate-300 leading-relaxed">
            Chuẩn hóa dữ liệu chấm công, minh bạch phê duyệt nghỉ phép và hỗ trợ HR ra quyết định dựa trên số liệu SQL được kiểm chứng.
          </p>
        </div>

        {/* Compact Enterprise SaaS Illustration Card */}
        <div
          aria-hidden="true"
          className="rounded-2xl border border-white/12 bg-[#0F2942]/90 p-4 shadow-xl shadow-slate-950/35"
        >
          <div className="flex items-center justify-between pb-2.5 mb-3 border-b border-white/10">
            <div className="flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-blue-300" />
              <span className="text-xs font-semibold text-white">
                Tổng quan Chấm công & Cảnh báo R1–R8
              </span>
            </div>
            <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-300 border border-emerald-400/20">
              <CheckCircle2 className="w-3 h-3" />
              Cross-check 100%
            </span>
          </div>

          <div className="grid grid-cols-12 gap-3 items-stretch">
            {/* Left mini KPI + bar chart */}
            <div className="col-span-7 flex flex-col justify-between gap-2.5">
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-xl bg-white/[0.05] border border-white/10 px-3 py-2">
                  <div className="flex items-center gap-1 text-[10px] text-slate-300">
                    <Clock className="w-3 h-3 text-blue-300" />
                    Tỷ lệ đúng giờ
                  </div>
                  <p className="mt-0.5 text-base font-bold text-white tracking-tight">95.4%</p>
                </div>
                <div className="rounded-xl bg-white/[0.05] border border-white/10 px-3 py-2">
                  <div className="flex items-center gap-1 text-[10px] text-slate-300">
                    <AlertTriangle className="w-3 h-3 text-amber-300" />
                    Rà soát tự động
                  </div>
                  <p className="mt-0.5 text-base font-bold text-white tracking-tight">8 quy tắc</p>
                </div>
              </div>

              <div className="rounded-xl bg-white/[0.04] border border-white/10 px-3 py-2.5">
                <div className="flex items-center justify-between text-[10px] text-slate-300 mb-2">
                  <span>Chuyên cần theo phòng ban</span>
                  <span className="text-blue-300 font-medium">SQL Live</span>
                </div>
                <div className="flex items-end justify-between gap-2 h-12 px-1">
                  {CHART_BARS.map((bar) => (
                    <div key={bar.label} className="flex-1 flex flex-col items-center gap-1 h-full justify-end">
                      <div
                        className={`w-full rounded-t ${
                          bar.active ? 'bg-brand-blue ring-1 ring-blue-300/40' : 'bg-blue-400/35'
                        }`}
                        style={{ height: `${bar.height}%` }}
                      />
                      <span className="text-[9px] text-slate-400 font-medium leading-none">{bar.label}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Right AI Copilot & Report cards */}
            <div className="col-span-5 flex flex-col justify-between gap-2.5">
              <div className="flex-1 rounded-xl bg-brand-blue/20 border border-blue-400/25 p-3 space-y-1">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold text-blue-100">
                  <Sparkles className="w-3.5 h-3.5 text-blue-300" />
                  AI Copilot Trace
                </div>
                <p className="text-[10px] text-slate-200/90 leading-relaxed">
                  Truy vấn chỉ đọc trên <span className="font-mono text-blue-200">v_attendance_daily</span>, phân quyền tự động.
                </p>
              </div>

              <div className="rounded-xl bg-white/[0.05] border border-white/10 p-3 space-y-1.5">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold text-white">
                  <FileSpreadsheet className="w-3.5 h-3.5 text-teal-300" />
                  Báo cáo kỳ tháng
                </div>
                <div className="flex items-center gap-1.5 text-[10px]">
                  <span className="rounded bg-white/10 px-1.5 py-0.5 text-slate-200 font-medium">
                    PDF Unicode
                  </span>
                  <span className="rounded bg-white/10 px-1.5 py-0.5 text-slate-200 font-medium">
                    Excel 4 Sheet
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* 3 Core Benefits (Horizontal 3-column grid to stay crisp inside 1 viewport) */}
        <div className="grid grid-cols-3 gap-2.5">
          {KEY_BENEFITS.map(({ icon: Icon, title, description }) => (
            <div
              key={title}
              className="rounded-xl bg-white/[0.05] border border-white/10 p-3 space-y-1.5"
            >
              <div className="w-7 h-7 rounded-lg bg-white/[0.08] border border-white/10 flex items-center justify-center text-blue-300">
                <Icon className="w-3.5 h-3.5" />
              </div>
              <h2 className="text-[11px] font-semibold text-white leading-tight">{title}</h2>
              <p className="text-[10px] text-slate-300/90 leading-relaxed">{description}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Footer Metadata */}
      <div className="relative z-10 flex items-center justify-between text-[11px] text-slate-400 pt-3 border-t border-white/10 shrink-0">
        <span>Phân quyền RBAC 3 vai trò: Employee · Manager · HR</span>
        <span>HR Attendance Copilot</span>
      </div>
    </section>
  );
};
