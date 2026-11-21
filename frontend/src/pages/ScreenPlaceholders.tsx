import React, { useState } from 'react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import {
  Users,
  Clock,
  AlertTriangle,
  CalendarDays,
  Sparkles,
  FileSpreadsheet,
  UploadCloud,
  ShieldCheck,
  UserCircle,
} from 'lucide-react';
import { useDevAuth } from '../context/DevAuthContext';
import { KpiCard } from '../components/ui/KpiCard';
import { FilterBar } from '../components/ui/FilterBar';
import { DataTable } from '../components/ui/DataTable';
import { StatusBadge } from '../components/ui/StatusBadge';
import { EmptyState } from '../components/ui/EmptyState';
import { LoadingSkeleton } from '../components/ui/LoadingSkeleton';
import { ErrorState } from '../components/ui/ErrorState';
import { ConfirmModal } from '../components/ui/ConfirmModal';

const StageBanner: React.FC<{
  screenCode: string;
  title: string;
  description: string;
  nextStage: string;
}> = ({ screenCode, title, description, nextStage }) => (
  <div className="rounded-card border border-blue-200 bg-blue-50/60 p-4 flex flex-wrap items-center justify-between gap-3">
    <div>
      <div className="flex items-center gap-2">
        <StatusBadge label={`Màn hình ${screenCode}`} variant="info" />
        <StatusBadge label="Giai đoạn 1: Placeholder & Design System" variant="pending" />
      </div>
      <h2 className="mt-2 text-sm font-bold text-brand-navy">{title}</h2>
      <p className="mt-0.5 text-xs text-slate-600">{description}</p>
    </div>
    <span className="text-[11px] font-medium text-brand-blue bg-white px-3 py-1.5 rounded-lg border border-blue-200">
      API thật kết nối ở: {nextStage}
    </span>
  </div>
);

const SAMPLE_CHART_STRUCTURE = [
  { dept: 'Kinh doanh', rate: 0 },
  { dept: 'Kỹ thuật', rate: 0 },
  { dept: 'Nhân sự', rate: 0 },
  { dept: 'Marketing', rate: 0 },
  { dept: 'Vận hành', rate: 0 },
];

export const DashboardPlaceholder: React.FC = () => {
  const { currentUser, selectedPeriod } = useDevAuth();
  const [previewState, setPreviewState] = useState<'normal' | 'loading' | 'error'>('normal');
  const [modalOpen, setModalOpen] = useState(false);

  const kpiCards =
    currentUser.role === 'employee'
      ? [
          { title: 'Tổng giờ công cá nhân', value: '--', subtitle: `Kỳ ${selectedPeriod}`, tone: 'blue' as const },
          { title: 'Số ngày đi làm', value: '--', subtitle: 'Chờ kết nối API', tone: 'teal' as const },
          { title: 'Số lần đi muộn', value: '--', subtitle: 'Ân hạn 5 phút', tone: 'amber' as const },
          { title: 'Phép năm còn lại', value: '--', subtitle: 'Theo quỹ phép HR', tone: 'green' as const },
        ]
      : currentUser.role === 'manager'
        ? [
            { title: `Nhân sự phòng ${currentUser.departmentName}`, value: '--', subtitle: 'Phạm vi phòng mình', tone: 'blue' as const },
            { title: 'Tỷ lệ đúng giờ phòng', value: '--%', subtitle: `Kỳ ${selectedPeriod}`, tone: 'teal' as const },
            { title: 'Đơn nghỉ phép chờ duyệt', value: '--', subtitle: 'Trong phòng', tone: 'amber' as const },
            { title: 'Cảnh báo cần xem xét', value: '--', subtitle: 'R1–R8 theo phòng', tone: 'red' as const },
          ]
        : [
            { title: 'Tổng nhân viên toàn công ty', value: '--', subtitle: '5 phòng ban', tone: 'blue' as const },
            { title: 'Tổng giờ công chuẩn', value: '--', subtitle: `Kỳ ${selectedPeriod}`, tone: 'teal' as const },
            { title: 'Tỷ lệ đi muộn toàn công ty', value: '--%', subtitle: 'Tính bằng SQL/Python', tone: 'amber' as const },
            { title: 'Cảnh báo cần xem xét', value: '--', subtitle: 'R1–R8 toàn công ty', tone: 'red' as const },
          ];

  return (
    <div className="space-y-5">
      <StageBanner
        screenCode="01"
        title="Tổng quan (Dashboard)"
        description="Hiển thị 4 thẻ KPI theo vai trò, biểu đồ Recharts và các trạng thái giao diện dùng lại."
        nextStage="Giai đoạn 2–3 (Prompt 2 & 7)"
      />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs">
          <span className="font-medium text-slate-600">Kiểm thử trạng thái UI:</span>
          {(['normal', 'loading', 'error'] as const).map((st) => (
            <button
              key={st}
              type="button"
              onClick={() => setPreviewState(st)}
              className={`px-3 py-1 rounded-lg border text-xs font-medium ${
                previewState === st
                  ? 'bg-brand-blue text-white border-brand-blue'
                  : 'bg-white text-slate-700 border-brand-border hover:bg-slate-50'
              }`}
            >
              {st === 'normal' ? 'Bình thường' : st === 'loading' ? 'Đang tải' : 'Lỗi API'}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="px-3.5 py-1.5 rounded-lg bg-brand-navy text-white text-xs font-medium hover:bg-slate-800"
        >
          Kiểm thử ConfirmModal
        </button>
      </div>

      {previewState === 'loading' && <LoadingSkeleton rows={4} />}
      {previewState === 'error' && (
        <ErrorState
          message="Đây là trạng thái lỗi mẫu dùng lại (ErrorState) khi kết nối Backend thất bại."
          onRetry={() => setPreviewState('normal')}
        />
      )}

      {previewState === 'normal' && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            {kpiCards.map((card) => (
              <KpiCard
                key={card.title}
                title={card.title}
                value={card.value}
                subtitle={card.subtitle}
                tone={card.tone}
                tooltip="Chỉ số sẽ được SQL/Python tính từ database thực ở Giai đoạn 2–3."
                icon={<Users className="w-5 h-5" />}
              />
            ))}
          </div>

          <div className="rounded-card border border-brand-border bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-sm font-bold text-slate-900">
                  Khung biểu đồ Recharts (Chờ dữ liệu thật từ Database)
                </h3>
                <p className="text-xs text-slate-500">
                  Biểu đồ cột sẵn sàng nhận dữ liệu theo phòng ban cho kỳ {selectedPeriod}.
                </p>
              </div>
              <StatusBadge label="Chưa nạp dữ liệu seed" variant="info" />
            </div>
            <div className="h-56 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={SAMPLE_CHART_STRUCTURE}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E4EAF2" />
                  <XAxis dataKey="dept" tick={{ fontSize: 11, fill: '#64748B' }} />
                  <YAxis tick={{ fontSize: 11, fill: '#64748B' }} domain={[0, 100]} />
                  <Tooltip />
                  <Bar dataKey="rate" name="Tỷ lệ (%)" fill="#2563EB" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      )}

      <ConfirmModal
        isOpen={modalOpen}
        title="Xác nhận thao tác mẫu"
        description="Hộp thoại xác nhận dùng chung cho các hành động quan trọng như duyệt/từ chối đơn nghỉ phép, xác nhận import file hoặc khóa tài khoản."
        confirmLabel="Đồng ý"
        cancelLabel="Đóng"
        onConfirm={() => setModalOpen(false)}
        onCancel={() => setModalOpen(false)}
      />
    </div>
  );
};

interface GenericPlaceholderProps {
  code: string;
  title: string;
  description: string;
  nextStage: string;
  icon: React.ReactNode;
  columns: { key: string; header: string }[];
}

const GenericWorkspacePlaceholder: React.FC<GenericPlaceholderProps> = ({
  code,
  title,
  description,
  nextStage,
  icon,
  columns,
}) => {
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');

  return (
    <div className="space-y-5">
      <StageBanner screenCode={code} title={title} description={description} nextStage={nextStage} />
      <FilterBar
        searchValue={search}
        onSearchChange={setSearch}
        selectLabel="Trạng thái"
        selectValue={status}
        onSelectChange={setStatus}
        selectOptions={[
          { value: 'all', label: 'Tất cả' },
          { value: 'open', label: 'Mở / Chờ duyệt' },
          { value: 'approved', label: 'Đã duyệt / Xác nhận' },
        ]}
        actions={
          <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
            {icon} Khung bảng sẵn sàng
          </span>
        }
      />
      <DataTable
        columns={columns}
        data={[]}
        rowKey={(_, idx) => String(idx)}
        emptyTitle={`Màn hình ${title} đang ở trạng thái khung (Giai đoạn 1)`}
        emptyDescription="Dữ liệu thật từ SQLite và các API phân quyền sẽ được nối vào bảng này ở các giai đoạn tiếp theo."
      />
    </div>
  );
};

export const AttendancePlaceholder: React.FC = () => (
  <GenericWorkspacePlaceholder
    code="02"
    title="Chấm công (Attendance)"
    description="Tra cứu lịch sử giờ vào, giờ ra, giờ công chuẩn (08:30–17:30, ân hạn 5 phút) và trạng thái theo phạm vi vai trò."
    nextStage="Giai đoạn 4 (Prompt 4)"
    icon={<Clock className="w-4 h-4 text-brand-blue" />}
    columns={[
      { key: 'employee_id', header: 'Mã NV' },
      { key: 'work_date', header: 'Ngày làm' },
      { key: 'check_in', header: 'Giờ vào' },
      { key: 'check_out', header: 'Giờ ra' },
      { key: 'work_hours', header: 'Giờ công' },
      { key: 'late_minutes', header: 'Phút muộn' },
      { key: 'status', header: 'Trạng thái' },
    ]}
  />
);

export const LeavesPlaceholder: React.FC = () => (
  <GenericWorkspacePlaceholder
    code="03"
    title="Đơn nghỉ phép (Leave Management)"
    description="Tạo đơn nghỉ phép, theo dõi trạng thái và luồng Manager/HR duyệt hoặc từ chối kèm lý do bắt buộc."
    nextStage="Giai đoạn 4 (Prompt 4)"
    icon={<CalendarDays className="w-4 h-4 text-brand-teal" />}
    columns={[
      { key: 'request_id', header: 'Mã đơn' },
      { key: 'employee_id', header: 'Nhân viên' },
      { key: 'leave_type', header: 'Loại nghỉ' },
      { key: 'date_range', header: 'Thời gian' },
      { key: 'days', header: 'Số ngày' },
      { key: 'status', header: 'Trạng thái' },
    ]}
  />
);

export const AnomaliesPlaceholder: React.FC = () => (
  <GenericWorkspacePlaceholder
    code="04"
    title="Cảnh báo bất thường (Anomaly Detection R1–R8)"
    description="Hiển thị 8 loại dấu hiệu bất thường do SQL/Python phát hiện, bằng chứng gốc và thao tác Xác nhận / Bỏ qua cho Manager/HR."
    nextStage="Giai đoạn 5 (Prompt 5)"
    icon={<AlertTriangle className="w-4 h-4 text-brand-amber" />}
    columns={[
      { key: 'anomaly_id', header: 'Mã cảnh báo' },
      { key: 'target', header: 'Nhân viên / Phòng ban' },
      { key: 'anomaly_type', header: 'Loại quy tắc (R1–R8)' },
      { key: 'severity', header: 'Mức độ' },
      { key: 'review_status', header: 'Trạng thái xử lý' },
    ]}
  />
);

export const AssistantPlaceholder: React.FC = () => (
  <div className="space-y-5">
    <StageBanner
      screenCode="05"
      title="Hỏi đáp AI (AI Assistant)"
      description="Đặt câu hỏi tiếng Việt tự nhiên qua Function Calling và Text-to-SQL chỉ đọc (SQL Guard: 3 giây, tối đa 200 dòng)."
      nextStage="Giai đoạn 6 (Prompt 6)"
    />
    <EmptyState
      title="Khung hội thoại AI Assistant đã sẵn sàng"
      description="Ở Giai đoạn 6, màn hình này sẽ hiển thị lịch sử hội thoại, gợi ý câu hỏi theo role, bảng kết quả và khung 'Truy vấn đã chạy'."
      action={
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-50 text-brand-blue text-xs font-medium">
          <Sparkles className="w-4 h-4" /> AI chỉ hỗ trợ & đề xuất, SQL tính số liệu
        </span>
      }
    />
  </div>
);

export const ReportsPlaceholder: React.FC = () => (
  <div className="space-y-5">
    <StageBanner
      screenCode="06"
      title="Báo cáo định kỳ (Reports)"
      description="Tổng hợp chỉ số theo kỳ, nhận xét AI có đối chiếu số liệu nguồn và xuất file PDF tiếng Việt / Excel (chỉ Manager & HR)."
      nextStage="Giai đoạn 8 (Prompt 8)"
    />
    <EmptyState
      title="Khu vực tạo và tải Báo cáo PDF/Excel"
      description="Chỉ vai trò Manager (phạm vi phòng mình) và HR (toàn công ty/theo phòng) được phép tạo và tải báo cáo."
      action={
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-50 text-brand-green text-xs font-medium">
          <FileSpreadsheet className="w-4 h-4" /> openpyxl + ReportLab Unicode
        </span>
      }
    />
  </div>
);

export const ProfilePlaceholder: React.FC = () => {
  const { currentUser } = useDevAuth();
  return (
    <div className="space-y-5">
      <StageBanner
        screenCode="07"
        title="Hồ sơ cá nhân (My Profile)"
        description="Xem thông tin cá nhân, vị trí công việc, số ngày phép còn lại và đổi mật khẩu an toàn."
        nextStage="Giai đoạn 3 & 7 (Prompt 3 & 7)"
      />
      <div className="rounded-card border border-brand-border bg-white p-6 shadow-sm max-w-2xl">
        <div className="flex items-center gap-3 pb-4 border-b border-brand-border">
          <UserCircle className="w-10 h-10 text-brand-blue" />
          <div>
            <h3 className="text-sm font-bold text-slate-900">{currentUser.fullName}</h3>
            <p className="text-xs text-slate-500">
              {currentUser.employeeId} · {currentUser.position}
            </p>
          </div>
        </div>
        <dl className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          <div>
            <dt className="text-slate-500">Phòng ban</dt>
            <dd className="font-semibold text-slate-800 mt-0.5">{currentUser.departmentName}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Vai trò hệ thống</dt>
            <dd className="font-semibold text-slate-800 mt-0.5 uppercase">{currentUser.role}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Quản lý trực tiếp</dt>
            <dd className="font-semibold text-slate-800 mt-0.5">{currentUser.managerName}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Quyền chỉnh sửa</dt>
            <dd className="font-medium text-slate-600 mt-0.5">
              Không được tự sửa role, phòng ban hoặc quỹ phép
            </dd>
          </div>
        </dl>
      </div>
    </div>
  );
};

export const ImportPlaceholder: React.FC = () => (
  <div className="space-y-5">
    <StageBanner
      screenCode="08"
      title="Nhập dữ liệu Excel / CSV (Data Import)"
      description="Dành riêng cho HR: tải file nhân viên/chấm công/nghỉ phép theo template, kiểm tra hợp lệ/lỗi/trùng và xem trước trước khi xác nhận."
      nextStage="Giai đoạn 4 (Prompt 4)"
    />
    <EmptyState
      title="Khu vực kéo thả file .xlsx / .csv (Chỉ HR)"
      description="Quy trình 5 bước: Chọn loại dữ liệu → Tải file → Validate → Xem trước hợp lệ/lỗi/trùng → Xác nhận nhập và lưu import_logs."
      action={
        <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-50 text-brand-blue text-xs font-medium">
          <UploadCloud className="w-4 h-4" /> Staging & Validation trước khi lưu
        </span>
      }
    />
  </div>
);

export const EmployeesPlaceholder: React.FC = () => (
  <GenericWorkspacePlaceholder
    code="09"
    title="Quản lý nhân viên (Employee Management)"
    description="HR quản lý hồ sơ nhân sự (thêm, sửa, ngừng hoạt động); Manager chỉ xem danh sách phòng mình (read-only)."
    nextStage="Giai đoạn 7 (Prompt 7)"
    icon={<Users className="w-4 h-4 text-brand-navy" />}
    columns={[
      { key: 'employee_id', header: 'Mã NV' },
      { key: 'full_name', header: 'Họ và tên' },
      { key: 'department', header: 'Phòng ban' },
      { key: 'position', header: 'Chức vụ' },
      { key: 'role', header: 'Vai trò' },
      { key: 'status', header: 'Trạng thái' },
    ]}
  />
);

export const AccountsPlaceholder: React.FC = () => (
  <GenericWorkspacePlaceholder
    code="10"
    title="Quản lý tài khoản (Account Management)"
    description="Dành riêng cho HR: tạo tài khoản, liên kết employee_id, đổi vai trò, khóa/mở và bảo vệ tài khoản HR cuối cùng."
    nextStage="Giai đoạn 3 & 7 (Prompt 3 & 7)"
    icon={<ShieldCheck className="w-4 h-4 text-brand-green" />}
    columns={[
      { key: 'username', header: 'Tài khoản / Email' },
      { key: 'employee_id', header: 'Nhân viên liên kết' },
      { key: 'role', header: 'Vai trò' },
      { key: 'is_active', header: 'Trạng thái' },
      { key: 'last_login_at', header: 'Đăng nhập gần nhất' },
    ]}
  />
);
