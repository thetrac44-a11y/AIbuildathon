import React, { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  Eye,
  EyeOff,
  Info,
  Loader2,
  Lock,
  LogIn,
  Mail,
  ShieldCheck,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { getDefaultHomePath } from '../config/navigation';
import { ApiError } from '../lib/api';
import { LoginBrandingPanel, MobileBrandHeader } from '../components/auth/LoginBrandingPanel';
import { DemoAccountsPanel } from '../components/auth/DemoAccountsPanel';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface FieldErrors {
  email?: string;
  password?: string;
}

export const LoginPage: React.FC = () => {
  const { login } = useAuth();
  const navigate = useNavigate();
  const passwordRef = useRef<HTMLInputElement | null>(null);

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [demoNotice, setDemoNotice] = useState<string | null>(null);

  const devDemoPassword = import.meta.env.DEV
    ? ((import.meta.env.VITE_DEV_DEMO_PASSWORD as string | undefined)?.trim() || '')
    : '';

  const validateFields = (emailVal: string, passwordVal: string): FieldErrors => {
    const errors: FieldErrors = {};
    const trimmedEmail = emailVal.trim();
    if (!trimmedEmail) {
      errors.email = 'Vui lòng nhập email đăng nhập.';
    } else if (!EMAIL_PATTERN.test(trimmedEmail)) {
      errors.email = 'Định dạng email không hợp lệ (ví dụ: hr@company.vn).';
    }
    if (!passwordVal) {
      errors.password = 'Vui lòng nhập mật khẩu.';
    }
    return errors;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    setDemoNotice(null);

    const errors = validateFields(email, password);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      return;
    }

    setSubmitting(true);
    try {
      const loggedUser = await login(email.trim(), password);
      navigate(getDefaultHomePath(loggedUser), { replace: true });
    } catch (err) {
      setFormError(
        err instanceof ApiError
          ? err.message
          : 'Không thể kết nối máy chủ xác thực. Vui lòng kiểm tra kết nối và thử lại.'
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleQuickDemo = async (demoEmail: string) => {
    if (!import.meta.env.DEV) return;
    setEmail(demoEmail);
    setFormError(null);
    setFieldErrors({});

    if (!devDemoPassword) {
      setPassword('');
      setDemoNotice(
        `Đã điền email ${demoEmail}. Nhập mật khẩu seed môi trường local để đăng nhập.`
      );
      passwordRef.current?.focus();
      return;
    }

    setPassword(devDemoPassword);
    setDemoNotice(null);
    setSubmitting(true);
    try {
      const loggedUser = await login(demoEmail, devDemoPassword);
      navigate(getDefaultHomePath(loggedUser), { replace: true });
    } catch (err) {
      setFormError(
        err instanceof ApiError
          ? err.message
          : 'Không thể đăng nhập tài khoản demo. Vui lòng kiểm tra backend.'
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen lg:h-screen lg:overflow-hidden w-full overflow-x-hidden bg-[#F8FAFC] flex flex-col lg:flex-row">
      {/* Compact Brand Header on Mobile / Tablet (form stays first above the fold) */}
      <MobileBrandHeader />

      {/* LEFT Panel on Desktop (45-46%): Centered Enterprise Login Form locked cleanly inside 1 viewport */}
      <main className="flex-1 lg:w-[46%] xl:w-[45%] lg:h-full flex flex-col justify-center px-4 py-5 sm:px-8 lg:px-10 overflow-y-auto lg:overflow-hidden">
        <div className="w-full max-w-[420px] mx-auto">
          <div className="rounded-2xl border border-brand-border bg-white p-6 sm:p-7 shadow-sm shadow-slate-900/[0.04]">
            {/* Form Header */}
            <div className="mb-5">
              <div className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-brand-blue mb-1.5">
                <ShieldCheck className="w-3.5 h-3.5" />
                Cổng đăng nhập nhân sự
              </div>
              <h2 className="text-2xl font-bold tracking-tight text-slate-900 leading-tight">
                Chào mừng trở lại!
              </h2>
              <p className="mt-1 text-xs text-slate-500 leading-relaxed">
                Đăng nhập bằng email doanh nghiệp để truy cập không gian làm việc theo vai trò.
              </p>
            </div>

            {/* Server / Auth Error Alert */}
            {formError && (
              <div
                role="alert"
                className="mb-4 rounded-xl border border-red-200 bg-red-50/90 px-3 py-2.5 flex items-start gap-2 text-xs text-brand-red"
              >
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <span className="leading-snug font-medium">{formError}</span>
              </div>
            )}

            {/* Dev Demo Fill Helper Notice */}
            {demoNotice && !formError && (
              <div
                role="status"
                className="mb-4 rounded-xl border border-blue-200 bg-blue-50/70 px-3 py-2 flex items-start gap-2 text-xs text-brand-navy"
              >
                <Info className="w-4 h-4 text-brand-blue shrink-0 mt-0.5" />
                <span className="leading-snug">{demoNotice}</span>
              </div>
            )}

            {/* Login Form */}
            <form onSubmit={handleSubmit} noValidate className="space-y-3.5">
              {/* Email Input */}
              <div>
                <label
                  htmlFor="login-email"
                  className="block text-xs font-semibold text-slate-700 mb-1"
                >
                  Email doanh nghiệp <span className="text-brand-red">*</span>
                </label>
                <div className="relative">
                  <Mail className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                  <input
                    id="login-email"
                    name="email"
                    type="email"
                    autoComplete="email"
                    required
                    disabled={submitting}
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      if (fieldErrors.email) {
                        setFieldErrors((prev) => ({ ...prev, email: undefined }));
                      }
                      if (formError) setFormError(null);
                    }}
                    placeholder="name@company.vn"
                    aria-invalid={Boolean(fieldErrors.email)}
                    aria-describedby={fieldErrors.email ? 'login-email-error' : undefined}
                    className={`w-full pl-10 pr-3.5 py-2.5 text-sm rounded-xl border bg-white text-slate-900 placeholder:text-slate-400 transition-colors focus:outline-none focus:ring-2 disabled:bg-slate-50 disabled:text-slate-500 ${
                      fieldErrors.email
                        ? 'border-red-400 focus:border-brand-red focus:ring-red-200/60'
                        : 'border-slate-300/90 hover:border-slate-400 focus:border-brand-blue focus:ring-brand-blue/20'
                    }`}
                  />
                </div>
                {fieldErrors.email && (
                  <p id="login-email-error" className="mt-1 text-xs font-medium text-brand-red">
                    {fieldErrors.email}
                  </p>
                )}
              </div>

              {/* Password Input with Show / Hide toggle */}
              <div>
                <label
                  htmlFor="login-password"
                  className="block text-xs font-semibold text-slate-700 mb-1"
                >
                  Mật khẩu <span className="text-brand-red">*</span>
                </label>
                <div className="relative">
                  <Lock className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                  <input
                    ref={passwordRef}
                    id="login-password"
                    name="password"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="current-password"
                    required
                    disabled={submitting}
                    value={password}
                    onChange={(e) => {
                      setPassword(e.target.value);
                      if (fieldErrors.password) {
                        setFieldErrors((prev) => ({ ...prev, password: undefined }));
                      }
                      if (formError) setFormError(null);
                    }}
                    placeholder="Nhập mật khẩu của bạn"
                    aria-invalid={Boolean(fieldErrors.password)}
                    aria-describedby={fieldErrors.password ? 'login-password-error' : undefined}
                    className={`w-full pl-10 pr-11 py-2.5 text-sm rounded-xl border bg-white text-slate-900 placeholder:text-slate-400 transition-colors focus:outline-none focus:ring-2 disabled:bg-slate-50 disabled:text-slate-500 ${
                      fieldErrors.password
                        ? 'border-red-400 focus:border-brand-red focus:ring-red-200/60'
                        : 'border-slate-300/90 hover:border-slate-400 focus:border-brand-blue focus:ring-brand-blue/20'
                    }`}
                  />
                  <button
                    type="button"
                    disabled={submitting}
                    aria-label={showPassword ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'}
                    onClick={() => setShowPassword((prev) => !prev)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors focus:outline-none focus:ring-2 focus:ring-brand-blue/25 disabled:opacity-50"
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                {fieldErrors.password && (
                  <p id="login-password-error" className="mt-1 text-xs font-medium text-brand-red">
                    {fieldErrors.password}
                  </p>
                )}
              </div>

              {/* Submit Button */}
              <button
                type="submit"
                disabled={submitting}
                className="mt-1 w-full inline-flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl bg-brand-blue text-white text-sm font-semibold shadow-sm shadow-blue-600/20 hover:bg-blue-700 active:bg-blue-800 focus:outline-none focus:ring-2 focus:ring-brand-blue/40 focus:ring-offset-1 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
              >
                {submitting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Đang xác thực...</span>
                  </>
                ) : (
                  <>
                    <LogIn className="w-4 h-4" />
                    <span>Đăng nhập hệ thống</span>
                  </>
                )}
              </button>
            </form>

            {/* Collapsible Demo Accounts (Strictly DEV-only, zero hardcoded password) */}
            <DemoAccountsPanel
              disabled={submitting}
              selectedEmail={email}
              hasQuickLoginPassword={Boolean(devDemoPassword)}
              onSelectDemo={handleQuickDemo}
            />
          </div>

          <p className="mt-3.5 text-center text-[11px] text-slate-500">
            Cần cấp mới hoặc đặt lại mật khẩu? Vui lòng liên hệ bộ phận Nhân sự (HR).
          </p>

          {/* Compact mobile-only benefits below form */}
          <div className="lg:hidden mt-5 pt-4 border-t border-brand-border grid grid-cols-3 gap-2 text-center text-[11px] text-slate-600">
            <div className="rounded-xl bg-white border border-brand-border px-2 py-2 font-medium">
              Phát hiện bất thường
            </div>
            <div className="rounded-xl bg-white border border-brand-border px-2 py-2 font-medium">
              AI phân tích dữ liệu
            </div>
            <div className="rounded-xl bg-white border border-brand-border px-2 py-2 font-medium">
              Báo cáo tự động
            </div>
          </div>
        </div>
      </main>

      {/* RIGHT Panel on Desktop (54-55%): Enterprise Navy/Blue Branding & AI HR Illustration */}
      <LoginBrandingPanel />
    </div>
  );
};
