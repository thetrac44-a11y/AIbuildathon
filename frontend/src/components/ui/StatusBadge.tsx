import React from 'react';

export type BadgeVariant =
  | 'approved'
  | 'pending'
  | 'rejected'
  | 'open'
  | 'confirmed'
  | 'dismissed'
  | 'high'
  | 'medium'
  | 'low'
  | 'info';

export interface StatusBadgeProps {
  label: string;
  variant?: BadgeVariant;
}

const variantStyles: Record<BadgeVariant, string> = {
  approved: 'bg-emerald-50 text-brand-green border-emerald-200',
  confirmed: 'bg-emerald-50 text-brand-green border-emerald-200',
  low: 'bg-emerald-50 text-brand-green border-emerald-200',
  pending: 'bg-amber-50 text-brand-amber border-amber-200',
  medium: 'bg-amber-50 text-brand-amber border-amber-200',
  open: 'bg-amber-50 text-brand-amber border-amber-200',
  rejected: 'bg-red-50 text-brand-red border-red-200',
  high: 'bg-red-50 text-brand-red border-red-200',
  dismissed: 'bg-slate-100 text-slate-600 border-slate-200',
  info: 'bg-blue-50 text-brand-blue border-blue-200',
};

export const StatusBadge: React.FC<StatusBadgeProps> = ({ label, variant = 'info' }) => {
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${variantStyles[variant]}`}
    >
      {label}
    </span>
  );
};
