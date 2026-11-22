import React from 'react';
import { EmptyState } from './EmptyState';

export interface ColumnDef<T> {
  key: string;
  header: string;
  render?: (row: T) => React.ReactNode;
}

export interface DataTablePagination {
  page: number;
  pageSize: number;
  totalCount: number;
  onPageChange: (nextPage: number) => void;
}

export interface DataTableProps<T> {
  columns: ColumnDef<T>[];
  data: T[];
  rowKey: (row: T, index: number) => string;
  emptyTitle?: string;
  emptyDescription?: string;
  onRowClick?: (row: T) => void;
  pagination?: DataTablePagination;
}

export function DataTable<T>({
  columns,
  data,
  rowKey,
  emptyTitle = 'Không có dữ liệu phù hợp',
  emptyDescription = 'Hãy thử thay đổi bộ lọc thời gian hoặc từ khóa tìm kiếm.',
  onRowClick,
  pagination,
}: DataTableProps<T>) {
  if (data.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />;
  }

  const totalCount = pagination ? pagination.totalCount : data.length;
  const totalPages = pagination
    ? Math.max(1, Math.ceil(pagination.totalCount / Math.max(1, pagination.pageSize)))
    : 1;
  const showPagination = Boolean(pagination && totalPages > 1);

  return (
    <div className="rounded-card border border-brand-border bg-white overflow-hidden shadow-sm">
      <div className="overflow-x-auto max-h-[480px]">
        <table className="w-full text-left border-collapse">
          <thead className="bg-slate-50 border-b border-brand-border sticky top-0 z-10">
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className="px-4 py-3 text-xs font-semibold text-slate-600 whitespace-nowrap"
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-brand-border text-xs text-slate-700">
            {data.map((row, idx) => (
              <tr
                key={rowKey(row, idx)}
                onClick={() => onRowClick?.(row)}
                className={`transition-colors ${
                  onRowClick ? 'cursor-pointer hover:bg-blue-50/40' : 'hover:bg-slate-50/70'
                }`}
              >
                {columns.map((col) => (
                  <td key={col.key} className="px-4 py-3 whitespace-nowrap">
                    {col.render ? col.render(row) : String((row as Record<string, unknown>)[col.key] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-4 py-2.5 bg-slate-50/60 border-t border-brand-border flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-600">
        <span>
          {showPagination && pagination
            ? `Hiển thị ${data.length} / ${totalCount} bản ghi`
            : `Tổng số dòng: ${totalCount}`}
        </span>
        {showPagination && pagination && (
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-700">
              Trang {pagination.page} / {totalPages}
            </span>
            <button
              type="button"
              disabled={pagination.page <= 1}
              onClick={() => pagination.onPageChange(pagination.page - 1)}
              className="px-2.5 py-1 rounded-md border border-brand-border bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            >
              ← Trang trước
            </button>
            <button
              type="button"
              disabled={pagination.page >= totalPages}
              onClick={() => pagination.onPageChange(pagination.page + 1)}
              className="px-2.5 py-1 rounded-md border border-brand-border bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            >
              Trang sau →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
