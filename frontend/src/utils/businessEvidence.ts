export interface AnomalyEvidenceInput {
  rule_code: string;
  anomaly_type?: string | null;
  scope_type?: 'employee' | 'department' | string | null;
  employee_id?: string | null;
  full_name?: string | null;
  department_id?: string | null;
  department_name?: string | null;
  period?: string | null;
  explanation?: string | null;
  evidence_data?: Record<string, unknown> | null;
}

export interface EvidenceMetricCard {
  label: string;
  value: string;
  sublabel?: string;
  tone?: 'default' | 'blue' | 'amber' | 'red' | 'teal';
}

export interface BusinessEvidenceModel {
  title: string;
  subtitle: string;
  metrics: EvidenceMetricCard[];
  tagsTitle?: string;
  tags: string[];
  commentary: string;
  disclaimer: string;
  isPartialOrEmpty: boolean;
  fallbackNote?: string;
}

export const NEUTRAL_DISCLAIMER =
  'Đây là dấu hiệu cần xác minh từ dữ liệu chấm công/nghỉ phép, chưa phải kết luận vi phạm.';

export function toFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function formatNumberVN(value: number | null | undefined, maxFractionDigits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return 'Chưa ghi nhận';
  }
  const rounded = Number(value.toFixed(maxFractionDigits));
  return new Intl.NumberFormat('vi-VN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: maxFractionDigits,
  }).format(rounded);
}

export function formatPercentVN(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return 'Chưa ghi nhận';
  }
  return `${formatNumberVN(value, 1)}%`;
}

export function formatDateVN(raw: unknown): string {
  if (typeof raw !== 'string') return 'Chưa ghi nhận';
  const trimmed = raw.trim();
  if (!trimmed) return 'Chưa ghi nhận';

  // Range format: YYYY-MM-DD..YYYY-MM-DD or YYYY-MM-DD -> YYYY-MM-DD or YYYY-MM-DD to YYYY-MM-DD
  const rangeMatch = trimmed.match(
    /^(\d{4})-(\d{2})-(\d{2})\s*(?:\.\.|->|→|~|to|-)\s*(\d{4})-(\d{2})-(\d{2})$/i
  );
  if (rangeMatch) {
    const start = `${rangeMatch[3]}/${rangeMatch[2]}/${rangeMatch[1]}`;
    const end = `${rangeMatch[6]}/${rangeMatch[5]}/${rangeMatch[4]}`;
    return start === end ? start : `${start} – ${end}`;
  }

  // Datetime format: YYYY-MM-DD HH:MM:SS
  const dtMatch = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)$/);
  if (dtMatch) {
    return `${dtMatch[4]} (${dtMatch[3]}/${dtMatch[2]}/${dtMatch[1]})`;
  }

  // ISO date format: YYYY-MM-DD
  const dateMatch = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateMatch) {
    return `${dateMatch[3]}/${dateMatch[2]}/${dateMatch[1]}`;
  }

  return trimmed;
}

export function formatPeriodVN(period: unknown): string {
  if (typeof period !== 'string') return 'Chưa ghi nhận';
  const m = period.trim().match(/^(\d{4})-(\d{2})$/);
  if (!m) return period.trim() || 'Chưa ghi nhận';
  return `Tháng ${m[2]}/${m[1]}`;
}

export function toCleanString(value: unknown, fallback = 'Chưa ghi nhận'): string {
  if (typeof value !== 'string') return fallback;
  const trimmed = value.trim();
  if (!trimmed || trimmed.toLowerCase() === 'null' || trimmed.toLowerCase() === 'undefined') {
    return fallback;
  }
  return trimmed;
}

export function toStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => (typeof item === 'string' ? item.trim() : typeof item === 'number' && Number.isFinite(item) ? String(item) : ''))
      .filter((s) => s.length > 0 && s.toLowerCase() !== 'null' && s.toLowerCase() !== 'undefined');
  }
  if (typeof value === 'string' && value.trim()) {
    return value
      .split(/[;,]/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0 && s.toLowerCase() !== 'null' && s.toLowerCase() !== 'undefined');
  }
  return [];
}

function getSafeRecord(raw: unknown): Record<string, unknown> {
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    return raw as Record<string, unknown>;
  }
  return {};
}

function subjectLabel(anomaly: AnomalyEvidenceInput): string {
  const empId = toCleanString(anomaly.employee_id, '');
  const name = toCleanString(anomaly.full_name, '');
  if (name && empId) return `${name} (${empId})`;
  if (name) return name;
  if (empId) return empId;
  return 'Nhân sự liên quan';
}

function departmentLabel(anomaly: AnomalyEvidenceInput, ev: Record<string, unknown>): string {
  return toCleanString(ev.department_name ?? anomaly.department_name, 'Chưa xác định phòng ban');
}

function buildFallbackModel(
  anomaly: AnomalyEvidenceInput,
  ev: Record<string, unknown>,
  title: string
): BusinessEvidenceModel {
  const dept = departmentLabel(anomaly, ev);
  const periodLabel = formatPeriodVN(ev.period ?? anomaly.period);
  const scopeLabel = anomaly.scope_type === 'department' ? 'Cấp phòng ban' : 'Cấp cá nhân';
  const cleanExplanation = toCleanString(anomaly.explanation, '');

  return {
    title,
    subtitle: `${dept} · ${periodLabel}`,
    metrics: [
      { label: 'Phòng ban liên quan', value: dept, tone: 'blue' },
      { label: 'Phạm vi áp dụng', value: scopeLabel },
      { label: 'Kỳ ghi nhận', value: periodLabel },
    ],
    tags: [],
    commentary:
      cleanExplanation ||
      `Hệ thống ghi nhận dấu hiệu cần đối chiếu thuộc quy tắc ${toCleanString(anomaly.rule_code, 'cảnh báo')} trong ${periodLabel.toLowerCase()}.`,
    disclaimer: NEUTRAL_DISCLAIMER,
    isPartialOrEmpty: true,
    fallbackNote:
      'Dữ liệu chi tiết đi kèm cảnh báo chưa đầy đủ để hiển thị đầy đủ chỉ số. Vui lòng đối chiếu trực tiếp lịch sử chấm công hoặc đơn nghỉ phép liên quan.',
  };
}

/**
 * Convert raw SQL evidence payload from backend (R1–R8) into human-readable Vietnamese
 * business metrics & neutral commentary. Strictly grounded in existing SQL definitions
 * (`backend/app/services/anomaly_service.py`) without altering detection rules or inventing facts.
 */
export function buildBusinessEvidence(anomaly: AnomalyEvidenceInput): BusinessEvidenceModel {
  const rule = toCleanString(anomaly.rule_code, '').toUpperCase();
  const ev = getSafeRecord(anomaly.evidence_data);
  const hasAnyKeys = Object.keys(ev).length > 0;
  const dept = departmentLabel(anomaly, ev);
  const periodLabel = formatPeriodVN(ev.period ?? anomaly.period);
  const subj = subjectLabel(anomaly);

  if (!hasAnyKeys) {
    return buildFallbackModel(anomaly, ev, 'Thông tin bằng chứng xác minh');
  }

  switch (rule) {
    case 'R1': {
      // R1 (late_repeated): late_days, threshold_days, grace_minutes, min_late_minutes, max_late_minutes, sample_dates
      const lateDays = toFiniteNumber(ev.late_days);
      const thresholdDays = toFiniteNumber(ev.threshold_days);
      const graceMinutes = toFiniteNumber(ev.grace_minutes);
      const minLate = toFiniteNumber(ev.min_late_minutes);
      const maxLate = toFiniteNumber(ev.max_late_minutes);
      const sampleDates = toStringList(ev.sample_dates).map(formatDateVN);

      let lateRangeValue = 'Chưa ghi nhận';
      if (minLate !== null && maxLate !== null) {
        lateRangeValue =
          minLate === maxLate
            ? `${formatNumberVN(minLate)} phút`
            : `${formatNumberVN(minLate)} – ${formatNumberVN(maxLate)} phút`;
      } else if (maxLate !== null) {
        lateRangeValue = `Tối đa ${formatNumberVN(maxLate)} phút`;
      } else if (minLate !== null) {
        lateRangeValue = `Từ ${formatNumberVN(minLate)} phút`;
      }

      const commentaryParts: string[] = [];
      if (lateDays !== null) {
        commentaryParts.push(
          `${subj} (Phòng ${dept}) ghi nhận ${formatNumberVN(lateDays)} ngày vào làm muộn trong ${periodLabel.toLowerCase()}`
        );
        if (graceMinutes !== null) {
          commentaryParts[0] += ` (sau mốc ân hạn ${formatNumberVN(graceMinutes)} phút)`;
        }
        if (minLate !== null && maxLate !== null) {
          commentaryParts[0] += `, mức trễ dao động từ ${formatNumberVN(minLate)} đến ${formatNumberVN(maxLate)} phút`;
        }
        if (thresholdDays !== null && lateDays >= thresholdDays) {
          commentaryParts[0] += `, chạm/vượt ngưỡng theo dõi ${formatNumberVN(thresholdDays)} ngày/tháng`;
        }
        commentaryParts[0] += '.';
      } else {
        commentaryParts.push(
          toCleanString(
            anomaly.explanation,
            `${subj} có dấu hiệu đi muộn lặp lại nhiều lần trong ${periodLabel.toLowerCase()}.`
          )
        );
      }

      return {
        title: 'Bằng chứng bất thường giờ vào làm (Đi muộn lặp lại)',
        subtitle: `${subj} · Phòng ${dept} · ${periodLabel}`,
        metrics: [
          {
            label: 'Số ngày đi muộn',
            value: lateDays !== null ? `${formatNumberVN(lateDays)} ngày` : 'Chưa ghi nhận',
            sublabel: thresholdDays !== null ? `Ngưỡng cảnh báo: ≥ ${formatNumberVN(thresholdDays)} ngày` : undefined,
            tone: lateDays !== null && lateDays > 0 ? 'amber' : 'default',
          },
          {
            label: 'Biên độ trễ ghi nhận',
            value: lateRangeValue,
            sublabel: graceMinutes !== null ? `Ân hạn chuẩn: ${formatNumberVN(graceMinutes)} phút` : undefined,
            tone: 'blue',
          },
          {
            label: 'Phòng ban',
            value: dept,
            sublabel: periodLabel,
          },
        ],
        tagsTitle: sampleDates.length > 0 ? `Các ngày đi muộn tiêu biểu (${sampleDates.length})` : undefined,
        tags: sampleDates,
        commentary: commentaryParts.join(' '),
        disclaimer: NEUTRAL_DISCLAIMER,
        isPartialOrEmpty: lateDays === null,
      };
    }

    case 'R2': {
      // R2 (missing_punch): missing_days, threshold_days, sample_dates
      const missingDays = toFiniteNumber(ev.missing_days);
      const thresholdDays = toFiniteNumber(ev.threshold_days);
      const sampleDates = toStringList(ev.sample_dates).map(formatDateVN);

      const commentary =
        missingDays !== null
          ? `${subj} (Phòng ${dept}) có ${formatNumberVN(missingDays)} ngày trong ${periodLabel.toLowerCase()} bị thiếu dữ liệu giờ vào hoặc giờ ra${
              thresholdDays !== null ? ` (ngưỡng theo dõi từ ${formatNumberVN(thresholdDays)} ngày)` : ''
            }. Cần rà soát đối chiếu dữ liệu chấm công để đảm bảo tính đủ ngày công.`
          : toCleanString(
              anomaly.explanation,
              `${subj} có ngày công thiếu dữ liệu giờ vào hoặc giờ ra trong ${periodLabel.toLowerCase()}.`
            );

      return {
        title: 'Bằng chứng thiếu dữ liệu chấm công (Giờ vào / Giờ ra)',
        subtitle: `${subj} · Phòng ${dept} · ${periodLabel}`,
        metrics: [
          {
            label: 'Số ngày thiếu giờ vào/ra',
            value: missingDays !== null ? `${formatNumberVN(missingDays)} ngày` : 'Chưa ghi nhận',
            sublabel: thresholdDays !== null ? `Ngưỡng cảnh báo: ≥ ${formatNumberVN(thresholdDays)} ngày` : undefined,
            tone: missingDays !== null && missingDays > 0 ? 'amber' : 'default',
          },
          {
            label: 'Phòng ban liên quan',
            value: dept,
          },
          {
            label: 'Kỳ ghi nhận',
            value: periodLabel,
            tone: 'blue',
          },
        ],
        tagsTitle: sampleDates.length > 0 ? `Các ngày thiếu dữ liệu chấm công (${sampleDates.length})` : undefined,
        tags: sampleDates,
        commentary,
        disclaimer: NEUTRAL_DISCLAIMER,
        isPartialOrEmpty: missingDays === null,
      };
    }

    case 'R3': {
      // R3 (low_hours): low_hour_days, threshold_days, threshold_hours, avg_work_hours, sample_dates
      const lowDays = toFiniteNumber(ev.low_hour_days);
      const thresholdDays = toFiniteNumber(ev.threshold_days);
      const thresholdHours = toFiniteNumber(ev.threshold_hours);
      const avgHours = toFiniteNumber(ev.avg_work_hours);
      const sampleDates = toStringList(ev.sample_dates).map(formatDateVN);

      const commentary =
        lowDays !== null
          ? `${subj} (Phòng ${dept}) ghi nhận ${formatNumberVN(lowDays)} ngày có tổng thời lượng làm việc dưới ${
              thresholdHours !== null ? `${formatNumberVN(thresholdHours)} giờ` : 'mức chuẩn'
            } trong ${periodLabel.toLowerCase()}${
              avgHours !== null ? `, đạt trung bình ${formatNumberVN(avgHours)} giờ/ngày ở các ngày này` : ''
            }.`
          : toCleanString(
              anomaly.explanation,
              `${subj} ghi nhận nhiều ngày làm việc có số giờ công thấp hơn định mức trong ${periodLabel.toLowerCase()}.`
            );

      return {
        title: 'Bằng chứng tổng giờ làm việc thấp hơn định mức',
        subtitle: `${subj} · Phòng ${dept} · ${periodLabel}`,
        metrics: [
          {
            label: 'Số ngày thiếu giờ chuẩn',
            value: lowDays !== null ? `${formatNumberVN(lowDays)} ngày` : 'Chưa ghi nhận',
            sublabel: thresholdDays !== null ? `Ngưỡng cảnh báo: ≥ ${formatNumberVN(thresholdDays)} ngày` : undefined,
            tone: lowDays !== null && lowDays > 0 ? 'amber' : 'default',
          },
          {
            label: 'Giờ công trung bình',
            value: avgHours !== null ? `${formatNumberVN(avgHours)} giờ/ngày` : 'Chưa ghi nhận',
            sublabel: thresholdHours !== null ? `Định mức đối chiếu: < ${formatNumberVN(thresholdHours)} giờ` : undefined,
            tone: 'blue',
          },
          {
            label: 'Phòng ban',
            value: dept,
            sublabel: periodLabel,
          },
        ],
        tagsTitle: sampleDates.length > 0 ? `Các ngày có số giờ làm việc thấp (${sampleDates.length})` : undefined,
        tags: sampleDates,
        commentary,
        disclaimer: NEUTRAL_DISCLAIMER,
        isPartialOrEmpty: lowDays === null && avgHours === null,
      };
    }

    case 'R4': {
      // R4 (leave_near_holiday): holiday_date, holiday_name, request_count, window_days, leave_ranges
      const holidayName = toCleanString(ev.holiday_name, 'Kỳ nghỉ lễ');
      const holidayDate = formatDateVN(ev.holiday_date);
      const requestCount = toFiniteNumber(ev.request_count);
      const windowDays = toFiniteNumber(ev.window_days);
      const leaveRanges = toStringList(ev.leave_ranges).map(formatDateVN);

      const commentary =
        requestCount !== null
          ? `${subj} (Phòng ${dept}) có ${formatNumberVN(requestCount)} đơn nghỉ phép đã phê duyệt nằm trong khoảng ±${
              windowDays !== null ? formatNumberVN(windowDays) : '3'
            } ngày liền kề dịp ${holidayName}${holidayDate !== 'Chưa ghi nhận' ? ` (${holidayDate})` : ''}.`
          : toCleanString(
              anomaly.explanation,
              `${subj} có đơn nghỉ phép nằm sát ngày lễ ${holidayName}.`
            );

      return {
        title: 'Bằng chứng nghỉ phép liền kề ngày lễ',
        subtitle: `${subj} · Phòng ${dept} · ${periodLabel}`,
        metrics: [
          {
            label: 'Dịp nghỉ lễ liên quan',
            value: holidayName,
            sublabel: holidayDate !== 'Chưa ghi nhận' ? `Ngày lễ: ${holidayDate}` : undefined,
            tone: 'blue',
          },
          {
            label: 'Số đơn nghỉ phép',
            value: requestCount !== null ? `${formatNumberVN(requestCount)} đơn` : 'Chưa ghi nhận',
            sublabel: windowDays !== null ? `Khoảng theo dõi: ±${formatNumberVN(windowDays)} ngày` : undefined,
            tone: 'amber',
          },
          {
            label: 'Phòng ban',
            value: dept,
            sublabel: periodLabel,
          },
        ],
        tagsTitle: leaveRanges.length > 0 ? `Khoảng thời gian nghỉ phép đã duyệt (${leaveRanges.length})` : undefined,
        tags: leaveRanges,
        commentary,
        disclaimer: NEUTRAL_DISCLAIMER,
        isPartialOrEmpty: requestCount === null && holidayDate === 'Chưa ghi nhận',
      };
    }

    case 'R5': {
      // R5 (leave_cluster): department_name, work_date, leave_count, dept_headcount, leave_pct, employee_ids
      const leaveCount = toFiniteNumber(ev.leave_count);
      const headcount = toFiniteNumber(ev.dept_headcount);
      let leavePct = toFiniteNumber(ev.leave_pct);
      if (leavePct === null && leaveCount !== null && headcount !== null) {
        leavePct = headcount > 0 ? (leaveCount / headcount) * 100 : 0;
      }
      const workDate = formatDateVN(ev.work_date);
      const employeeIds = toStringList(ev.employee_ids);

      const ratioText =
        leaveCount !== null && headcount !== null
          ? `${formatNumberVN(leaveCount)}/${formatNumberVN(headcount)} nhân viên`
          : leaveCount !== null
            ? `${formatNumberVN(leaveCount)} nhân viên`
            : 'Chưa ghi nhận';

      let commentary: string;
      if (leaveCount !== null && headcount !== null) {
        commentary = `Phòng ${dept} có ${formatNumberVN(leaveCount)}/${formatNumberVN(headcount)} nhân viên liên quan đến dữ liệu nghỉ phép${
          workDate !== 'Chưa ghi nhận' ? ` vào ngày ${workDate}` : ''
        } thuộc cảnh báo R5${leavePct !== null ? `, tương ứng ${formatPercentVN(leavePct)}` : ''}.`;
      } else if (leaveCount !== null) {
        commentary = `Phòng ${dept} ghi nhận ${formatNumberVN(leaveCount)} nhân viên nghỉ phép cùng ngày${
          workDate !== 'Chưa ghi nhận' ? ` (${workDate})` : ''
        } thuộc cảnh báo R5.`;
      } else {
        commentary = toCleanString(
          anomaly.explanation,
          `Phòng ${dept} ghi nhận nhiều nhân sự nghỉ phép trùng ngày trong ${periodLabel.toLowerCase()}.`
        );
      }

      return {
        title: 'Bằng chứng nghỉ phép trùng phạm vi phòng ban',
        subtitle: `Phòng ${dept} · Phạm vi cấp phòng ban`,
        metrics: [
          {
            label: 'Phòng ban liên quan',
            value: dept,
            sublabel: headcount !== null ? `Tổng quy mô: ${formatNumberVN(headcount)} nhân viên` : undefined,
            tone: 'blue',
          },
          {
            label: 'Số nhân viên liên quan',
            value: ratioText,
            tone: leaveCount !== null && leaveCount > 0 ? 'amber' : 'default',
          },
          {
            label: 'Tỷ lệ nghỉ cùng ngày',
            value: formatPercentVN(leavePct),
            tone: leavePct !== null && leavePct >= 30 ? 'red' : 'teal',
          },
          {
            label: 'Ngày ghi nhận',
            value: workDate,
          },
        ],
        tagsTitle: employeeIds.length > 0 ? `Mã nhân viên liên quan (${employeeIds.length})` : undefined,
        tags: employeeIds,
        commentary,
        disclaimer: NEUTRAL_DISCLAIMER,
        isPartialOrEmpty: leaveCount === null && headcount === null && workDate === 'Chưa ghi nhận',
      };
    }

    case 'R6': {
      // R6 (identical_punch): identical_days, threshold_days, exact_check_in, exact_check_out, sample_dates
      const identicalDays = toFiniteNumber(ev.identical_days);
      const thresholdDays = toFiniteNumber(ev.threshold_days);
      const exactIn = toCleanString(ev.exact_check_in, 'Chưa ghi nhận');
      const exactOut = toCleanString(ev.exact_check_out, 'Chưa ghi nhận');
      const sampleDates = toStringList(ev.sample_dates).map(formatDateVN);

      const commentary =
        identicalDays !== null
          ? `${subj} (Phòng ${dept}) có ${formatNumberVN(identicalDays)} ngày trong ${periodLabel.toLowerCase()} ghi nhận giờ vào (${exactIn}) và giờ ra (${exactOut}) trùng khớp đến từng giây. Cần kiểm tra thiết bị chấm công hoặc nguồn đồng bộ dữ liệu.`
          : toCleanString(
              anomaly.explanation,
              `${subj} ghi nhận nhiều ngày có mốc giờ chấm công trùng khớp từng giây trong ${periodLabel.toLowerCase()}.`
            );

      return {
        title: 'Bằng chứng giờ chấm công trùng khớp từng giây',
        subtitle: `${subj} · Phòng ${dept} · ${periodLabel}`,
        metrics: [
          {
            label: 'Số ngày trùng mốc giờ',
            value: identicalDays !== null ? `${formatNumberVN(identicalDays)} ngày` : 'Chưa ghi nhận',
            sublabel: thresholdDays !== null ? `Ngưỡng cảnh báo: ≥ ${formatNumberVN(thresholdDays)} ngày` : undefined,
            tone: identicalDays !== null && identicalDays > 0 ? 'red' : 'default',
          },
          {
            label: 'Mốc giờ vào lặp lại',
            value: exactIn,
            tone: 'blue',
          },
          {
            label: 'Mốc giờ ra lặp lại',
            value: exactOut,
            tone: 'blue',
          },
        ],
        tagsTitle: sampleDates.length > 0 ? `Các ngày ghi nhận trùng mốc giờ (${sampleDates.length})` : undefined,
        tags: sampleDates,
        commentary,
        disclaimer: NEUTRAL_DISCLAIMER,
        isPartialOrEmpty: identicalDays === null,
      };
    }

    case 'R7': {
      // R7 (weekend_punch): weekend_holiday_days, sample_dates, overtime_check
      const whDays = toFiniteNumber(ev.weekend_holiday_days);
      const sampleDates = toStringList(ev.sample_dates).map(formatDateVN);
      const otCheckText = toCleanString(
        ev.overtime_check,
        'Chưa ghi nhận đơn làm thêm giờ (OT) được phê duyệt'
      );

      const commentary =
        whDays !== null
          ? `${subj} (Phòng ${dept}) có ${formatNumberVN(whDays)} ngày chấm công vào cuối tuần hoặc ngày lễ trong ${periodLabel.toLowerCase()} khi chưa có đơn làm thêm giờ được phê duyệt.`
          : toCleanString(
              anomaly.explanation,
              `${subj} phát sinh dữ liệu chấm công vào ngày nghỉ cuối tuần hoặc ngày lễ.`
            );

      return {
        title: 'Bằng chứng chấm công ngày nghỉ / cuối tuần chưa có đơn OT',
        subtitle: `${subj} · Phòng ${dept} · ${periodLabel}`,
        metrics: [
          {
            label: 'Số ngày cuối tuần / lễ',
            value: whDays !== null ? `${formatNumberVN(whDays)} ngày` : 'Chưa ghi nhận',
            tone: whDays !== null && whDays > 0 ? 'amber' : 'default',
          },
          {
            label: 'Trạng thái đơn tăng ca',
            value: 'Chưa có đơn OT duyệt',
            sublabel: otCheckText,
            tone: 'blue',
          },
          {
            label: 'Phòng ban',
            value: dept,
            sublabel: periodLabel,
          },
        ],
        tagsTitle: sampleDates.length > 0 ? `Các ngày cuối tuần / ngày lễ ghi nhận (${sampleDates.length})` : undefined,
        tags: sampleDates,
        commentary,
        disclaimer: NEUTRAL_DISCLAIMER,
        isPartialOrEmpty: whDays === null,
      };
    }

    case 'R8': {
      // R8 (leave_over_balance): annual_leave_balance, approved_annual_days, excess_days, request_count, leave_ranges
      const balance = toFiniteNumber(ev.annual_leave_balance);
      const approved = toFiniteNumber(ev.approved_annual_days);
      let excess = toFiniteNumber(ev.excess_days);
      if (excess === null && approved !== null && balance !== null) {
        excess = Math.max(0, approved - balance);
      }
      const reqCount = toFiniteNumber(ev.request_count);
      const leaveRanges = toStringList(ev.leave_ranges).map(formatDateVN);

      const commentary =
        approved !== null && balance !== null
          ? `${subj} (Phòng ${dept}) có tổng ${formatNumberVN(approved)} ngày phép năm đã được phê duyệt (tính theo ngày lịch), vượt định mức ${formatNumberVN(balance)} ngày là ${formatNumberVN(excess ?? Math.max(0, approved - balance))} ngày.`
          : toCleanString(
              anomaly.explanation,
              `${subj} có tổng số ngày phép năm đã duyệt vượt quá định mức phép năm hiện hành.`
            );

      return {
        title: 'Bằng chứng sử dụng phép năm vượt định mức',
        subtitle: `${subj} · Phòng ${dept}`,
        metrics: [
          {
            label: 'Định mức phép năm',
            value: balance !== null ? `${formatNumberVN(balance)} ngày` : 'Chưa ghi nhận',
            tone: 'blue',
          },
          {
            label: 'Tổng phép đã duyệt',
            value: approved !== null ? `${formatNumberVN(approved)} ngày` : 'Chưa ghi nhận',
            sublabel: reqCount !== null ? `${formatNumberVN(reqCount)} đơn phép năm` : undefined,
            tone: 'amber',
          },
          {
            label: 'Số ngày vượt quỹ phép',
            value: excess !== null ? `+${formatNumberVN(excess)} ngày` : 'Chưa ghi nhận',
            sublabel: 'Tính theo ngày lịch',
            tone: excess !== null && excess > 0 ? 'red' : 'default',
          },
        ],
        tagsTitle: leaveRanges.length > 0 ? `Các kỳ nghỉ phép năm đã duyệt (${leaveRanges.length})` : undefined,
        tags: leaveRanges,
        commentary,
        disclaimer: NEUTRAL_DISCLAIMER,
        isPartialOrEmpty: balance === null && approved === null,
      };
    }

    default:
      return buildFallbackModel(anomaly, ev, 'Thông tin bằng chứng xác minh');
  }
}
