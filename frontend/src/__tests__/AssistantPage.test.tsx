import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider, AuthUser } from '../context/AuthContext';
import { DEFAULT_ROLE_PERMISSIONS } from '../config/navigation';
import { UserRole } from '../types/navigation';
import { AssistantPage } from '../pages/AssistantPage';
import { CitationCards } from '../components/assistant/CitationCards';
import { AssistantAnalytics } from '../components/assistant/AssistantAnalytics';
import { SafeMarkdown } from '../components/assistant/SafeMarkdown';
import { AskResponse } from '../types/assistant';

function makeUser(role: UserRole): AuthUser {
  const map: Record<UserRole, { id: string; name: string; dept: string; deptId: string }> = {
    employee: { id: 'NV007', name: 'Lê Minh Nhân Viên', dept: 'Kinh doanh', deptId: 'DEPT_SALES' },
    manager: { id: 'NV001', name: 'Nguyễn Văn Bình', dept: 'Kinh doanh', deptId: 'DEPT_SALES' },
    hr: { id: 'NV002', name: 'Trần Thị Hoa', dept: 'Nhân sự', deptId: 'DEPT_HR' },
    executive: { id: 'NV079', name: 'Trần Minh Quang', dept: 'Vận hành', deptId: 'DEPT_OPS' },
    admin: { id: 'NV080', name: 'Nguyễn Hải Đăng', dept: 'Vận hành', deptId: 'DEPT_OPS' },
  };
  const info = map[role];
  return {
    user_id: `USR-${role.toUpperCase()}`,
    username: `${role}@company.vn`,
    employee_id: info.id,
    full_name: info.name,
    role,
    department_id: info.deptId,
    department_name: info.dept,
    position: role,
    manager_id: null,
    manager_name: null,
    start_date: '2024-01-01',
    annual_leave_balance: 12,
    used_annual_leave: 0,
    remaining_annual_leave: 12,
    employment_status: 'active',
    email: `${role}@company.vn`,
    phone: '0901234567',
    must_change_password: false,
    permissions: DEFAULT_ROLE_PERMISSIONS[role],
    allowed_screens: [],
  };
}

function renderAssistant(role: UserRole) {
  return render(
    <AuthProvider initialTestUser={makeUser(role)}>
      <MemoryRouter initialEntries={['/assistant']}>
        <AssistantPage />
      </MemoryRouter>
    </AuthProvider>
  );
}

describe('Phase 4 AI Frontend UX — AssistantPage, Citations, Analytics & Conversation History', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('1. Renders distinct role-based scope headers & suggestions for Employee, Manager, HR, Executive', async () => {
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/assistant/suggestions')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ suggestions: ['Câu hỏi gợi ý kiểm thử'] }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ total: 0, limit: 15, offset: 0, has_more: false, items: [] }),
      });
    });
    vi.stubGlobal('fetch', mockFetch);

    const expected: Array<[UserRole, string, string]> = [
      ['employee', 'Trợ lý AI Cá nhân', 'Dữ liệu cá nhân · NV007'],
      ['manager', 'Trợ lý AI Phòng ban', 'Phòng Kinh doanh'],
      ['hr', 'Trợ lý AI Nghiệp vụ Nhân sự', 'Toàn công ty · HR'],
      ['executive', 'Trợ lý AI Phân tích Điều hành', 'Toàn công ty · Ban Điều hành'],
    ];

    for (const [role, heading, scope] of expected) {
      const { unmount } = renderAssistant(role);
      expect(screen.getAllByText(heading).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(scope)).toBeInTheDocument();
      expect(await screen.findByText('Câu hỏi gợi ý kiểm thử')).toBeInTheDocument();
      unmount();
    }
  });

  it('2. Renders Admin defense-in-depth governance notice without calling HR AI endpoints', () => {
    const mockFetch = vi.fn();
    vi.stubGlobal('fetch', mockFetch);

    renderAssistant('admin');
    expect(screen.getByTestId('admin-ai-governance-panel')).toBeInTheDocument();
    expect(screen.getByText(/Quản trị kỹ thuật AI & Bảo mật/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Quản lý Kho tài liệu RAG/i })).toHaveAttribute('href', '/admin/rag');
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('3. Renders separated SQL & RAG CitationCards with version, clause, page, excerpt and never fabricates empty citations', () => {
    const { rerender } = render(
      <CitationCards
        citations={{
          sql: [
            {
              type: 'sql',
              source_label: 'Thống kê lượt đi muộn',
              scope_label: 'Cá nhân (NV007)',
              period: '2026-10',
              record_count: 1,
              verified: true,
            },
          ],
          rag: [
            {
              type: 'rag',
              citation_id: 'DOC-1',
              document_id: 3,
              title: 'Cẩm nang cảnh báo R1-R8',
              original_file_name: 'cam_nang_r1_r8.pdf',
              version_label: 'v1.1',
              section_title: 'Quy tắc R1 (Đi muộn lặp lại)',
              article_ref: 'Quy tắc R1',
              page_number: 2,
              excerpt: 'Kích hoạt khi nhân viên có từ 5 ngày đi muộn quá 5 phút trở lên trong tháng.',
            },
          ],
        }}
      />
    );

    expect(screen.getByTestId('sql-citations-section')).toBeInTheDocument();
    expect(screen.getByText('Thống kê lượt đi muộn')).toBeInTheDocument();
    expect(screen.getByText(/Phạm vi: Cá nhân \(NV007\)/)).toBeInTheDocument();

    expect(screen.getByTestId('rag-citations-section')).toBeInTheDocument();
    expect(screen.getByText('Cẩm nang cảnh báo R1-R8')).toBeInTheDocument();
    expect(screen.getByText('v1.1')).toBeInTheDocument();
    expect(screen.getByText('Trang 2')).toBeInTheDocument();
    expect(screen.getByText('Quy tắc R1')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Cẩm nang cảnh báo R1-R8/i }));
    expect(screen.getByText(/từ 5 ngày đi muộn quá 5 phút/i)).toBeInTheDocument();

    // Empty citations -> renders nothing (zero fabrication!)
    rerender(<CitationCards citations={{ sql: [], rag: [] }} />);
    expect(screen.queryByTestId('citation-cards')).not.toBeInTheDocument();
  });

  it('4. Renders KPI cards, LineChart (trend), BarChart (comparison), Vietnamese column labels & hides analytics on insufficient data', () => {
    const manyRows = Array.from({ length: 12 }, (_, i) => ({
      period: `2026-${String((i % 12) + 1).padStart(2, '0')}`,
      late_days: i + 1,
      late_rate_pct: 4.5 + i * 0.2,
    }));
    const trendResp: AskResponse = {
      status: 'success',
      answer: 'Xu hướng 6 tháng',
      table: { columns: ['period', 'late_days', 'late_rate_pct'], rows: manyRows },
      column_labels: { period: 'Kỳ', late_days: 'Số lần đi muộn', late_rate_pct: 'Tỷ lệ đi muộn (%)' },
      chart: {
        type: 'line',
        xKey: 'period',
        yKey: 'late_rate_pct',
        label: 'Tỷ lệ đi muộn theo tháng (%)',
        data: manyRows.slice(0, 6),
      },
    };
    const { rerender } = render(<AssistantAnalytics response={trendResp} />);
    expect(screen.getByTestId('assistant-line-chart')).toBeInTheDocument();
    expect(screen.getByText('Số lần đi muộn')).toBeInTheDocument();
    expect(screen.getByText('Tỷ lệ đi muộn (%)')).toBeInTheDocument();
    expect(screen.queryByText('late_rate_pct')).not.toBeInTheDocument();
    expect(screen.queryByText('late_days')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Xem đầy đủ 12 dòng/i }));
    expect(screen.getByRole('button', { name: /Thu gọn/i })).toBeInTheDocument();

    const summaryResp: AskResponse = {
      status: 'success',
      answer: 'Tổng hợp chấm công',
      table: {
        columns: ['employee_count', 'total_work_hours', 'on_time_rate_pct', 'late_days'],
        rows: [{ employee_count: 16, total_work_hours: 2560, on_time_rate_pct: 95.1, late_days: 14 }],
      },
      chart: {
        type: 'bar',
        xKey: 'department_name',
        yKey: 'late_rate_pct',
        label: 'So sánh phòng ban (%)',
        data: [
          { department_name: 'Kinh doanh', late_rate_pct: 4.97 },
          { department_name: 'Kỹ thuật', late_rate_pct: 4.9 },
        ],
      },
    };
    rerender(<AssistantAnalytics response={summaryResp} />);
    expect(screen.getByTestId('assistant-kpi-cards')).toBeInTheDocument();
    expect(screen.getByTestId('assistant-bar-chart')).toBeInTheDocument();

    // Insufficient data -> hides charts & KPIs strictly!
    rerender(<AssistantAnalytics response={{ ...summaryResp, status: 'insufficient_data' }} />);
    expect(screen.queryByTestId('assistant-analytics')).not.toBeInTheDocument();
  });

  it('5. Opens saved conversation via GET without re-sending POST /ask and preserves conversation_id on follow-up', async () => {
    const askCalls: Array<Record<string, unknown>> = [];

    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
        if (url.includes('/assistant/suggestions')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ suggestions: [] }) });
        }
        if (url.includes('/assistant/conversations/conv_saved_1') && (!opts?.method || opts.method === 'GET')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              conversation_id: 'conv_saved_1',
              title: 'Phòng nào đi muộn cao nhất T10?',
              created_at: '2026-11-28 10:00:00',
              updated_at: '2026-11-28 10:01:00',
              messages: [
                {
                  message_id: 1,
                  role: 'user',
                  content: 'Phòng nào đi muộn cao nhất tháng 10/2026?',
                  created_at: '2026-11-28 10:00:00',
                },
                {
                  message_id: 2,
                  role: 'assistant',
                  content: 'Phòng **Nhân sự** có tỷ lệ đi muộn cao nhất 6.9%.',
                  created_at: '2026-11-28 10:00:01',
                  response: {
                    status: 'success',
                    answer: 'Phòng **Nhân sự** có tỷ lệ đi muộn cao nhất 6.9%.',
                    conversation_id: 'conv_saved_1',
                    route: { type: 'SQL_ONLY' },
                    table: null,
                    chart: null,
                    citations: {
                      sql: [{ type: 'sql', source_label: 'So sánh phòng ban', scope_label: 'Toàn công ty', record_count: 5, verified: true }],
                      rag: [],
                    },
                    verification: { verified: true, mode: 'deterministic' },
                    suggested_followups: ['Còn tháng 9 thì sao?'],
                  },
                },
              ],
            }),
          });
        }
        if (url.includes('/assistant/conversations')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              total: 1,
              limit: 15,
              offset: 0,
              has_more: false,
              items: [
                {
                  conversation_id: 'conv_saved_1',
                  title: 'Phòng nào đi muộn cao nhất T10?',
                  created_at: '2026-11-28 10:00:00',
                  updated_at: '2026-11-28 10:01:00',
                  message_count: 2,
                },
              ],
            }),
          });
        }
        if (url.includes('/assistant/ask') && opts?.method === 'POST') {
          askCalls.push(JSON.parse(String(opts.body)));
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              status: 'success',
              answer: 'Kỳ 2026-09, Phòng Kinh doanh đứng đầu.',
              conversation_id: 'conv_saved_1',
              route: { type: 'SQL_ONLY', used_context: true },
              table: null,
              chart: null,
              citations: { sql: [], rag: [] },
              verification: { verified: true, mode: 'deterministic' },
            }),
          });
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
      })
    );

    renderAssistant('hr');
    const savedBtn = await screen.findByText('Phòng nào đi muộn cao nhất T10?');
    fireEvent.click(savedBtn);

    expect(await screen.findByText(/tỷ lệ đi muộn cao nhất 6.9%/i)).toBeInTheDocument();
    expect(askCalls).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: 'Còn tháng 9 thì sao?' }));
    expect(await screen.findByText(/Kỳ 2026-09, Phòng Kinh doanh đứng đầu/i)).toBeInTheDocument();
    expect(askCalls).toHaveLength(1);
    expect(askCalls[0].conversation_id).toBe('conv_saved_1');
    expect(screen.getByText('Ngữ cảnh nối tiếp')).toBeInTheDocument();
  });

  it('6. Supports conversation rename (PATCH), pagination (Tải thêm), and delete with ConfirmModal (DELETE)', async () => {
    let patchCalled = false;
    let deleteCalled = false;

    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
        if (url.includes('/assistant/suggestions')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ suggestions: [] }) });
        }
        if (url.includes('/assistant/conversations/conv_1') && opts?.method === 'PATCH') {
          patchCalled = true;
          const body = JSON.parse(String(opts.body));
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ conversation_id: 'conv_1', title: body.title, updated_at: '2026-11-28 11:00:00' }),
          });
        }
        if (url.includes('/assistant/conversations/conv_1') && opts?.method === 'DELETE') {
          deleteCalled = true;
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ status: 'ok' }) });
        }
        if (url.includes('offset=1')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              total: 2,
              limit: 15,
              offset: 1,
              has_more: false,
              items: [
                {
                  conversation_id: 'conv_2',
                  title: 'Hội thoại trang 2',
                  created_at: '2026-11-27 09:00:00',
                  updated_at: '2026-11-27 09:00:00',
                  message_count: 2,
                },
              ],
            }),
          });
        }
        if (url.includes('/assistant/conversations')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              total: 2,
              limit: 15,
              offset: 0,
              has_more: true,
              items: [
                {
                  conversation_id: 'conv_1',
                  title: 'Hội thoại ban đầu',
                  created_at: '2026-11-28 09:00:00',
                  updated_at: '2026-11-28 09:00:00',
                  message_count: 4,
                },
              ],
            }),
          });
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
      })
    );

    renderAssistant('employee');
    expect(await screen.findByText('Hội thoại ban đầu')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Tải thêm hội thoại/i }));
    expect(await screen.findByText('Hội thoại trang 2')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Đổi tên hội thoại Hội thoại ban đầu/i }));
    const renameInput = screen.getByLabelText('Tên hội thoại mới');
    fireEvent.change(renameInput, { target: { value: 'Quỹ phép Q4' } });
    fireEvent.click(screen.getByRole('button', { name: 'Lưu tên hội thoại' }));
    await waitFor(() => expect(patchCalled).toBe(true));
    expect(await screen.findByText('Quỹ phép Q4')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Xóa hội thoại Quỹ phép Q4/i }));
    expect(screen.getByText('Xóa phiên hội thoại?')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Xóa hội thoại' }));
    await waitFor(() => expect(deleteCalled).toBe(true));
    expect(screen.queryByText('Quỹ phép Q4')).not.toBeInTheDocument();
  });

  it('7. Clearly differentiates blocked, insufficient_data, insufficient_evidence, clarification_needed & API error with retry', async () => {
    const responses: Array<() => Promise<unknown>> = [
      async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'blocked',
          answer: 'Bạn không có quyền xem phòng khác.',
          route: { type: 'BLOCKED' },
          table: null,
          chart: null,
          citations: { sql: [], rag: [] },
        }),
      }),
      async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'insufficient_data',
          answer: 'Không đủ dữ liệu kỳ 2025-01.',
          route: { type: 'SQL_ONLY' },
          table: null,
          chart: null,
          citations: { sql: [], rag: [] },
        }),
      }),
      async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'insufficient_evidence',
          answer: 'Không đủ căn cứ tài liệu.',
          route: { type: 'RAG_ONLY' },
          table: null,
          chart: null,
          citations: { sql: [], rag: [] },
        }),
      }),
      async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'clarification_needed',
          answer: 'Vui lòng nêu cụ thể hơn.',
          route: { type: 'CLARIFICATION' },
          table: null,
          chart: null,
          citations: { sql: [], rag: [] },
        }),
      }),
      async () => ({
        ok: false,
        status: 503,
        json: async () => ({ detail: 'Dịch vụ AI tạm quá tải' }),
      }),
      async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'success',
          answer: 'Đã khôi phục kết quả thành công.',
          route: { type: 'GENERAL' },
          table: null,
          chart: null,
          citations: { sql: [], rag: [] },
          verification: { verified: true, mode: 'deterministic' },
        }),
      }),
    ];
    let askIdx = 0;

    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
        if (url.includes('/assistant/ask') && opts?.method === 'POST') {
          const fn = responses[Math.min(askIdx, responses.length - 1)];
          askIdx += 1;
          return fn();
        }
        if (url.includes('/assistant/suggestions')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ suggestions: [] }) });
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ total: 0, limit: 15, offset: 0, has_more: false, items: [] }),
        });
      })
    );

    renderAssistant('employee');
    const composer = screen.getByLabelText('Nhập câu hỏi cho Trợ lý AI');
    const sendBtn = screen.getByRole('button', { name: /Gửi/i });

    const prompts = [
      ['Phòng Kỹ thuật?', 'Bạn không có quyền xem phòng khác.'],
      ['Tháng 01/2025?', 'Không đủ dữ liệu kỳ 2025-01.'],
      ['Chính sách sao Hỏa?', 'Không đủ căn cứ tài liệu.'],
      ['Xem giúp tôi', 'Vui lòng nêu cụ thể hơn.'],
      ['Test lỗi 503', 'Dịch vụ AI tạm quá tải'],
    ];

    for (const [q, expectedText] of prompts) {
      fireEvent.change(composer, { target: { value: q } });
      fireEvent.click(sendBtn);
      expect(await screen.findByText(expectedText)).toBeInTheDocument();
    }

    expect(screen.getByTestId('status-banner-blocked')).toBeInTheDocument();
    expect(screen.getAllByTestId('status-banner-insufficient')).toHaveLength(2);
    expect(screen.getByTestId('status-banner-clarification')).toBeInTheDocument();
    expect(screen.getByTestId('status-banner-error')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Thử lại/i }));
    expect(await screen.findByText('Đã khôi phục kết quả thành công.')).toBeInTheDocument();
  });

  it('8. SafeMarkdown renders headings, lists, bold, internal routes & clickable [DOC-1] without dangerouslySetInnerHTML', () => {
    const clicked: string[] = [];
    render(
      <MemoryRouter>
        <SafeMarkdown
          content={
            '### 1. Dữ liệu thực tế từ hệ thống (SQL)\n- Nhân viên **NV007** đi muộn 8 lần.\n### 2. Căn cứ quy định & quy trình nội bộ (RAG)\nXem [DOC-1] và truy cập (/leaves) để nộp đơn.'
          }
          onCitationClick={(id) => clicked.push(id)}
        />
      </MemoryRouter>
    );
    expect(screen.getByText('1. Dữ liệu thực tế từ hệ thống (SQL)')).toBeInTheDocument();
    expect(screen.getByText('NV007').tagName).toBe('STRONG');
    expect(screen.getByRole('link', { name: '/leaves' })).toHaveAttribute('href', '/leaves');
    fireEvent.click(screen.getByRole('button', { name: 'DOC-1' }));
    expect(clicked).toEqual(['DOC-1']);
  });

  it('9. Mobile responsive drawer opens conversation history cleanly and renders empty history state', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) => {
        if (url.includes('/assistant/suggestions')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ suggestions: [] }) });
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ total: 0, limit: 15, offset: 0, has_more: false, items: [] }),
        });
      })
    );

    renderAssistant('manager');
    fireEvent.click(screen.getByRole('button', { name: /Mở lịch sử hội thoại/i }));
    const dialog = screen.getByRole('dialog', { name: 'Lịch sử hội thoại' });
    expect(await within(dialog).findByTestId('empty-history')).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Đóng danh sách hội thoại' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('10. Clicking inline [DOC-1] opens matching RAG excerpt & UI never leaks raw JSON or DB column names', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
        if (url.includes('/assistant/ask') && opts?.method === 'POST') {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              status: 'success',
              answer: '### 1. Dữ liệu thực tế từ hệ thống (SQL)\nNV007 đi muộn 8 lần.\n### 2. Căn cứ quy định & quy trình nội bộ (RAG)\nTheo [DOC-1], ngưỡng R1 là 5 ngày.',
              conversation_id: 'conv_hyb',
              route: { type: 'HYBRID', rationale: 'Kết hợp SQL + RAG' },
              table: {
                columns: ['employee_id', 'late_days', 'review_status'],
                rows: [{ employee_id: 'NV007', late_days: 8, review_status: 'open' }],
              },
              column_labels: { employee_id: 'Mã NV', late_days: 'Số lần đi muộn', review_status: 'Trạng thái xử lý' },
              chart: null,
              citations: {
                sql: [{ type: 'sql', source_label: 'Thống kê đi muộn', scope_label: 'Cá nhân (NV007)', period: '2026-10', record_count: 1, verified: true }],
                rag: [
                  {
                    type: 'rag',
                    citation_id: 'DOC-1',
                    document_id: 3,
                    title: 'Cẩm nang R1-R8',
                    version_label: 'v1.1',
                    section_title: 'Quy tắc R1',
                    page_number: 1,
                    excerpt: 'Đoạn trích chi tiết về Quy tắc R1 đi muộn lặp lại.',
                  },
                ],
              },
              trace: { tool_name: 'get_top_late_employees+rag_hybrid_search', sql_text: 'SELECT employee_id FROM v_attendance_daily', row_count: 1, execution_ms: 21.5 },
              verification: { verified: true, mode: 'deterministic' },
              suggested_actions: [{ label: 'Mở Cảnh báo bất thường', path: '/anomalies' }],
            }),
          });
        }
        if (url.includes('/assistant/suggestions')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ suggestions: [] }) });
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ total: 0, limit: 15, offset: 0, has_more: false, items: [] }),
        });
      })
    );

    const { container } = renderAssistant('employee');
    const composer = screen.getByLabelText('Nhập câu hỏi cho Trợ lý AI');
    fireEvent.change(composer, { target: { value: 'Tháng 10 tôi đi muộn mấy lần và có chạm R1 không?' } });
    fireEvent.click(screen.getByRole('button', { name: /Gửi/i }));

    expect(await screen.findByText('Kết hợp SQL + RAG')).toBeInTheDocument();
    // Clicking inline [DOC-1] pill expands the exact RAG excerpt!
    const docPill = screen.getByRole('button', { name: 'DOC-1' });
    fireEvent.click(docPill);
    expect(await screen.findByText(/Đoạn trích chi tiết về Quy tắc R1/i)).toBeInTheDocument();

    // Open business verification footer -> STILL zero raw SQL or DB snake_case leaked!
    fireEvent.click(screen.getByRole('button', { name: /Thông tin kiểm chứng/i }));
    const textContent = container.textContent || '';
    expect(textContent).not.toContain('SELECT employee_id');
    expect(textContent).not.toContain('review_status');
    expect(textContent).not.toContain('late_days');
    expect(textContent).toContain('Trạng thái xử lý');
    expect(textContent).toContain('Đang mở');
  });
});
