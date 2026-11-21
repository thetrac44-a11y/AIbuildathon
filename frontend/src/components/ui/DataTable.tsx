import React from 'react';
import { EmptyState } from './EmptyState';

export interface ColumnDef<T> {
  key: string;
  header: string;
  render?: (row: T) => React.ReactNode;
}

export interface DataTableProps<T> {
  columns: ColumnDef<T>[];
  data: T[];
  rowKey: (row: T, index: number) => string;
  emptyTitle?: string;
  emptyDescription?: string;
  onRowClick?: (row: T) => void;
}

export function DataTable<T>({
  columns,
  data,
  rowKey,
  emptyTitle = 'Không có dữ liệu phù hợp',
  emptyDescription = 'Hãy thử thay đổi bộ lọc thời gian hoặc từ khóa tìm kiếm.',
  onRowClick,
}: DataTableProps<T>) {
  if (data.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />;
  }

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
      <div className="px-4 py-2.5 bg-slate-50/60 border-t border-brand-border flex items-center justify-between text-[11px] text-slate-500">
        <span>Tổng số dòng: {data.length}</span>
        <span>Trang 1 / 1</span>
      </div>
    </div>
  );
}
