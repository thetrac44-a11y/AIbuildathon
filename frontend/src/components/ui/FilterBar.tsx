import React from 'react';
import { Search } from 'lucide-react';

export interface FilterOption {
  value: string;
  label: string;
}

export interface FilterBarProps {
  searchPlaceholder?: string;
  searchValue?: string;
  onSearchChange?: (val: string) => void;
  selectLabel?: string;
  selectValue?: string;
  selectOptions?: FilterOption[];
  onSelectChange?: (val: string) => void;
  actions?: React.ReactNode;
}

export const FilterBar: React.FC<FilterBarProps> = ({
  searchPlaceholder = 'Tìm theo mã hoặc họ tên...',
  searchValue = '',
  onSearchChange,
  selectLabel,
  selectValue,
  selectOptions,
  onSelectChange,
  actions,
}) => {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-brand-border bg-white p-3.5">
      <div className="flex flex-wrap items-center gap-3 flex-1 min-w-[240px]">
        {onSearchChange && (
          <div className="relative flex-1 max-w-xs">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchValue}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder={searchPlaceholder}
              className="w-full pl-9 pr-3 py-2 text-xs rounded-lg border border-brand-border bg-brand-bg/60 focus:outline-none focus:border-brand-blue"
            />
          </div>
        )}
        {selectOptions && onSelectChange && (
          <div className="flex items-center gap-2">
            {selectLabel && <span className="text-xs font-medium text-slate-600">{selectLabel}:</span>}
            <select
              value={selectValue}
              onChange={(e) => onSelectChange(e.target.value)}
              className="px-3 py-2 text-xs rounded-lg border border-brand-border bg-brand-bg/60 text-slate-700 focus:outline-none focus:border-brand-blue"
            >
              {selectOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
};
