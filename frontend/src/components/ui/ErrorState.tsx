import React from 'react';
import { AlertCircle } from 'lucide-react';

export interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = 'Không thể tải dữ liệu',
  message,
  onRetry,
}) => {
  return (
    <div className="rounded-card border border-red-200 bg-red-50/70 p-4 flex items-start justify-between gap-4">
      <div className="flex items-start gap-3">
        <AlertCircle className="w-5 h-5 text-brand-red shrink-0 mt-0.5" />
        <div>
          <h4 className="text-xs font-semibold text-brand-red">{title}</h4>
          <p className="mt-0.5 text-xs text-red-800">{message}</p>
        </div>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="px-3 py-1.5 rounded-lg bg-white border border-red-200 text-xs font-medium text-brand-red hover:bg-red-50"
        >
          Thử lại
        </button>
      )}
    </div>
  );
};
