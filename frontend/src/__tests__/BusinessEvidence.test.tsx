import React from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { BusinessEvidence } from '../components/anomalies/BusinessEvidence';
import { AnomalyEvidenceInput, buildBusinessEvidence } from '../utils/businessEvidence';
import { AuthProvider, AuthUser } from '../context/AuthContext';
import { DEFAULT_ROLE_PERMISSIONS } from '../config/navigation';
import { AppRoutes } from '../App';
import { UserRole } from '../types/navigation';

const FORBIDDEN_TECHNICAL_TOKENS = [
  'dept_headcount',
  'leave_pct',
  'leave_count',
  'employee_ids',
  'department_id',
  'work_date',
  'rule_code',
  'SQL Evidence',
  'undefined',
  'NaN',
  'Infinity',
];

function assertCleanBusinessOutput(container: HTMLElement) {
  const text = container.textContent ?? '';
  for (const token of FORBIDDEN_TECHNICAL_TOKENS) {
    expect(text).not.toContain(token);
  }
  expect(text).not.toMatch(/\bnull\b/i);
  expect(container.querySelector('pre')).toBeNull();
}

function makeUser(role: UserRole): AuthUser {
  return {
    user_id: `USR-${role.toUpperCase()}`,
    username: `${role}@company.vn`,
    employee_id: role === 'hr' ? 'NV002' : role === 'manager' ? 'NV001' : 'NV007',
    full_name: role === 'hr' ? 'Trần Thị HR' : role === 'manager' ? 'Nguyễn Văn Bình' : 'Lê Minh',
    role,
    department_id: role === 'hr' ? 'DEPT_HR' : 'DEPT_SALES',
    department_name: role === 'hr' ? 'Nhân sự' : 'Kinh doanh',
    position: role,
    manager_id: null,
    manager_name: null,
    start_date: '2024-01-01',
    annual_leave_balance: 12,
    used_annual_leave: 2,
    remaining_annual_leave: 10,
    employment_status: 'active',
    must_change_password: false,
    permissions: DEFAULT_ROLE_PERMISSIONS[role],
    allowed_screens: [],
  };
}

describe('BusinessEvidence – R1 to R8 Conversion, Edge Cases & Modal Workflow', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const ALL_8_RULE_FIXTURES: Array<{ rule: string; input: AnomalyEvidenceInput; expectedText: string }> = [
    {
      rule: 'R1',
      input: {
        rule_code: 'R1',
        anomaly_type: 'late_repeated',
        scope_type: 'employee',
        employee_id: 'NV007',
        full_name: 'Nguyễn Văn An',
        department_name: 'Kinh doanh',
        period: '2026-10',
        evidence_data: {
          rule_code: 'R1',
          employee_id: 'NV007',
          period: '2026-10',
          late_days: 8,
          threshold_days: 5,
          grace_minutes: 5,
          min_late_minutes: 12,
          max_late_minutes: 38,
          sample_dates: ['2026-10-02', '2026-10-05'],
        },
      },
      expectedText: '8 ngày',
    },
    {
      rule: 'R2',
      input: {
        rule_code: 'R2',
        anomaly_type: 'missing_punch',
        scope_type: 'employee',
        employee_id: 'NV015',
        full_name: 'Trần Minh Đức',
        department_name: 'Kinh doanh',
        period: '2026-09',
        evidence_data: {
          rule_code: 'R2',
          employee_id: 'NV015',
          period: '2026-09',
          missing_days: 4,
          threshold_days: 2,
          sample_dates: ['2026-09-10', '2026-09-11'],
        },
      },
      expectedText: '4 ngày',
    },
    {
      rule: 'R3',
      input: {
        rule_code: 'R3',
        anomaly_type: 'low_hours',
        scope_type: 'employee',
        employee_id: 'NV060',
        full_name: 'Phạm Thu Hà',
        department_name: 'Vận hành',
        period: '2026-10',
        evidence_data: {
          rule_code: 'R3',
          employee_id: 'NV060',
          period: '2026-10',
          low_hour_days: 6,
          threshold_days: 5,
          threshold_hours: 7.0,
          avg_work_hours: 5.5,
          sample_dates: ['2026-10-03'],
        },
      },
      expectedText: '5,5 giờ/ngày',
    },
    {
      rule: 'R4',
      input: {
        rule_code: 'R4',
        anomaly_type: 'leave_near_holiday',
        scope_type: 'employee',
        employee_id: 'NV031',
        full_name: 'Lê Hoàng Long',
        department_name: 'Kỹ thuật',
        period: '2026-09',
        evidence_data: {
          rule_code: 'R4',
          employee_id: 'NV031',
          holiday_date: '2026-09-02',
          holiday_name: 'Quốc khánh 2/9',
          request_count: 2,
          window_days: 3,
          leave_ranges: ['2026-08-31..2026-09-01'],
        },
      },
      expectedText: 'Quốc khánh 2/9',
    },
    {
      rule: 'R5',
      input: {
        rule_code: 'R5',
        anomaly_type: 'leave_cluster',
        scope_type: 'department',
        employee_id: null,
        full_name: null,
        department_id: 'DEPT_SALES',
        department_name: 'Kinh doanh',
        period: '2026-10',
        evidence_data: {
          rule_code: 'R5',
          scope: 'department',
          department_id: 'DEPT_SALES',
          department_name: 'Kinh doanh',
          work_date: '2026-10-16',
          leave_count: 6,
          dept_headcount: 16,
          leave_pct: 37.5,
          employee_ids: ['NV008', 'NV009', 'NV010', 'NV011', 'NV012', 'NV013'],
        },
      },
      expectedText: '37,5%',
    },
    {
      rule: 'R6',
      input: {
        rule_code: 'R6',
        anomaly_type: 'identical_punch',
        scope_type: 'employee',
        employee_id: 'NV023',
        full_name: 'Đỗ Quang Huy',
        department_name: 'Kỹ thuật',
        period: '2026-11',
        evidence_data: {
          rule_code: 'R6',
          employee_id: 'NV023',
          period: '2026-11',
          identical_days: 7,
          threshold_days: 5,
          exact_check_in: '08:30:00',
          exact_check_out: '17:30:00',
          sample_dates: ['2026-11-02', '2026-11-03'],
        },
      },
      expectedText: '08:30:00',
    },
    {
      rule: 'R7',
      input: {
        rule_code: 'R7',
        anomaly_type: 'weekend_punch',
        scope_type: 'employee',
        employee_id: 'NV041',
        full_name: 'Vũ Thị Mai',
        department_name: 'Marketing',
        period: '2026-10',
        evidence_data: {
          rule_code: 'R7',
          employee_id: 'NV041',
          period: '2026-10',
          weekend_holiday_days: 3,
          sample_dates: ['2026-10-10', '2026-10-17'],
          overtime_check: 'Đã đối chiếu bảng overtime_requests (chưa có đơn làm thêm được duyệt)',
        },
      },
      expectedText: 'Chưa có đơn OT duyệt',
    },
    {
      rule: 'R8',
      input: {
        rule_code: 'R8',
        anomaly_type: 'leave_over_balance',
        scope_type: 'employee',
        employee_id: 'NV052',
        full_name: 'Hoàng Thanh Tùng',
        department_name: 'Vận hành',
        period: '2026-10',
        evidence_data: {
          rule_code: 'R8',
          employee_id: 'NV052',
          annual_leave_balance: 12,
          approved_annual_days: 17,
          excess_days: 5,
          request_count: 4,
          leave_days_method: 'calendar_days_inclusive',
          leave_ranges: ['2026-10-05..2026-10-09'],
        },
      },
      expectedText: '+5 ngày',
    },
  ];

  it.each(ALL_8_RULE_FIXTURES)(
    'renders clean Vietnamese business evidence without raw JSON for rule $rule',
    ({ input, expectedText }) => {
      const { container } = render(<BusinessEvidence anomaly={input} />);
      expect(screen.getByText('Bằng chứng xác minh')).toBeInTheDocument();
      expect(screen.getByText('Nhận xét')).toBeInTheDocument();
      expect(container.textContent).toContain(expectedText);
      assertCleanBusinessOutput(container);
    }
  );

  it('produces exact natural Vietnamese summary for R5 department leave cluster', () => {
    const model = buildBusinessEvidence(ALL_8_RULE_FIXTURES[4].input);
    expect(model.commentary).toBe(
      'Phòng Kinh doanh có 6/16 nhân viên liên quan đến dữ liệu nghỉ phép vào ngày 16/10/2026 thuộc cảnh báo R5, tương ứng 37,5%.'
    );
    expect(model.tags).toEqual(['NV008', 'NV009', 'NV010', 'NV011', 'NV012', 'NV013']);
  });

  it('handles missing, null, empty, zero-ratio, and unknown-rule evidence safely with zero undefined/null/NaN', () => {
    const edgeCases: AnomalyEvidenceInput[] = [
      {
        rule_code: 'R5',
        scope_type: 'department',
        department_name: 'Kinh doanh',
        period: '2026-10',
        evidence_data: null,
      },
      {
        rule_code: 'R5',
        scope_type: 'department',
        department_name: 'Kinh doanh',
        period: '2026-10',
        evidence_data: {
          department_name: 'Kinh doanh',
          leave_count: 0,
          dept_headcount: 0,
          leave_pct: 0,
          work_date: '',
          employee_ids: [],
        },
      },
      {
        rule_code: 'R1',
        scope_type: 'employee',
        employee_id: 'NV007',
        full_name: null,
        department_name: null,
        period: null,
        evidence_data: {
          late_days: Number.NaN,
          min_late_minutes: undefined,
          max_late_minutes: null,
          sample_dates: [null, ''],
        },
      },
      {
        rule_code: 'R99',
        scope_type: 'employee',
        employee_id: 'NV007',
        department_name: 'Kinh doanh',
        period: '2026-10',
        evidence_data: { custom_field: 123 },
      },
    ];

    for (const anomaly of edgeCases) {
      const { container, unmount } = render(<BusinessEvidence anomaly={anomaly} />);
      expect(screen.getByText('Bằng chứng xác minh')).toBeInTheDocument();
      assertCleanBusinessOutput(container);
      unmount();
    }

    // Verify 0% explicitly renders as "0%" instead of "Chưa ghi nhận" or "NaN"
    const zeroModel = buildBusinessEvidence(edgeCases[1]);
    expect(zeroModel.metrics.find((m) => m.label === 'Tỷ lệ nghỉ cùng ngày')?.value).toBe('0%');
    expect(zeroModel.metrics.find((m) => m.label === 'Số nhân viên liên quan')?.value).toBe('0/0 nhân viên');
  });

  it('AnomaliesPage modal shows BusinessEvidence (zero JSON) and submits Manager/HR review note cleanly', async () => {
    const r5Item = {
      anomaly_id: 7,
      employee_id: null,
      full_name: null,
      department_id: 'DEPT_SALES',
      department_name: 'Kinh doanh',
      scope_type: 'department',
      rule_code: 'R5',
      anomaly_type: 'leave_cluster',
      severity: 'medium',
      period: '2026-10',
      evidence_data: {
        rule_code: 'R5',
        scope: 'department',
        department_id: 'DEPT_SALES',
        department_name: 'Kinh doanh',
        work_date: '2026-10-16',
        leave_count: 6,
        dept_headcount: 16,
        leave_pct: 37.5,
        employee_ids: ['NV008', 'NV009', 'NV010', 'NV011', 'NV012', 'NV013'],
      },
      explanation: 'Phòng Kinh doanh có 6/16 nhân sự cùng nghỉ phép.',
      review_status: 'open',
      reviewed_by: null,
      review_note: null,
      detected_at: '2026-11-28 10:00:00',
      can_review: true,
    };

    const reviewPayloadCapture: Array<Record<string, unknown>> = [];
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (String(url).includes('/anomalies/7/review') && init?.method === 'POST') {
        reviewPayloadCapture.push(JSON.parse(String(init.body)));
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ok' }),
        });
      }
      if (String(url).endsWith('/anomalies/7')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => r5Item,
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          total: 1,
          can_review: true,
          summary: { total: 1, open: 1, confirmed: 0, dismissed: 0, high: 0, medium: 1, low: 0 },
          items: [r5Item],
        }),
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { container } = render(
      <AuthProvider initialTestUser={makeUser('manager')}>
        <MemoryRouter initialEntries={['/anomalies']}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
    );

    const deptCell = await screen.findByText('Kinh doanh', {}, { timeout: 4000 });
    fireEvent.click(deptCell);

    expect(await screen.findByText('Bằng chứng xác minh', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByText('6/16 nhân viên')).toBeInTheDocument();
    expect(screen.getByText('37,5%')).toBeInTheDocument();
    expect(screen.getByText('16/10/2026')).toBeInTheDocument();
    expect(screen.getByText('NV008')).toBeInTheDocument();
    assertCleanBusinessOutput(container);

    // Fill review note & submit confirmation
    fireEvent.change(screen.getByLabelText(/Ghi chú xem xét của quản lý \/ HR/i), {
      target: { value: 'Đã xác nhận điều phối nhân sự trực thay' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Xác nhận cần xử lý/i }));

    await waitFor(() => expect(reviewPayloadCapture).toHaveLength(1));
    expect(reviewPayloadCapture[0]).toEqual({
      review_status: 'confirmed',
      review_note: 'Đã xác nhận điều phối nhân sự trực thay',
    });
  });
});
