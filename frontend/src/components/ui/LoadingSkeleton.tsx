import React from 'react';

export const LoadingSkeleton: React.FC<{ rows?: number }> = ({ rows = 3 }) => {
  return (
    <div
      data-testid="loading-skeleton"
      className="rounded-card border border-brand-border bg-white p-5 space-y-3 animate-pulse"
    >
      <div className="h-4 w-1/3 rounded bg-slate-200" />
      {Array.from({ length: rows }).map((_, idx) => (
        <div key={idx} className="h-9 w-full rounded bg-slate-100" />
      ))}
    </div>
  );
};
