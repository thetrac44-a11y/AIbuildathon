import React, { useEffect, useState } from 'react';
import { BookOpen, CheckCircle2, ChevronDown, ChevronRight, Database, FileText } from 'lucide-react';
import { AssistantCitations } from '../../types/assistant';

export interface CitationCardsProps {
  citations?: AssistantCitations | null;
  highlightedCitationId?: string | null;
}

/**
 * Displays verified SQL Citations (factual operational sources) and RAG Citations
 * (internal policy documents, versions, sections, pages, and excerpts) separately.
 * NEVER fabricates citations when backend does not provide them.
 */
export const CitationCards: React.FC<CitationCardsProps> = ({
  citations,
  highlightedCitationId,
}) => {
  const sqlCitations = citations?.sql ?? [];
  const ragCitations = citations?.rag ?? [];
  const [expandedDocs, setExpandedDocs] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (highlightedCitationId) {
      setExpandedDocs((prev) => ({ ...prev, [highlightedCitationId]: true }));
    }
  }, [highlightedCitationId]);

  if (sqlCitations.length === 0 && ragCitations.length === 0) {
    return null;
  }

  const toggleDoc = (key: string) => {
    setExpandedDocs((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="space-y-3 pt-2 border-t border-brand-border/80" data-testid="citation-cards">
      {/* SQL Citations Section — Operational Factual Data */}
      {sqlCitations.length > 0 && (
        <div className="space-y-1.5" data-testid="sql-citations-section">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-600 uppercase tracking-wide">
            <Database className="w-3.5 h-3.5 text-brand-blue" />
            <span>Nguồn dữ liệu thực tế (SQL)</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {sqlCitations.map((sc, idx) => (
              <div
                key={`sql-cit-${idx}-${sc.source_label}`}
                className="rounded-lg border border-blue-100 bg-blue-50/40 px-3 py-2 text-xs"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="font-semibold text-slate-800 leading-snug">{sc.source_label}</p>
                  {sc.verified && (
                    <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-brand-green bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5 shrink-0">
                      <CheckCircle2 className="w-3 h-3" /> Đã đối chiếu
                    </span>
                  )}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[11px] text-slate-600">
                  <span>Phạm vi: {sc.scope_label}</span>
                  {sc.period && <span>· Kỳ: {sc.period}</span>}
                  <span>· {sc.record_count} bản ghi</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* RAG Citations Section — Policy Documents & Clauses */}
      {ragCitations.length > 0 && (
        <div className="space-y-1.5" data-testid="rag-citations-section">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-600 uppercase tracking-wide">
            <BookOpen className="w-3.5 h-3.5 text-brand-teal" />
            <span>Trích dẫn tài liệu &amp; điều khoản (RAG)</span>
          </div>
          <div className="space-y-2">
            {ragCitations.map((rc) => {
              const cid = rc.citation_id || `DOC-${rc.document_id}`;
              const isHighlighted = highlightedCitationId === cid;
              const isOpen = Boolean(expandedDocs[cid]);
              const clauseLabel = rc.article_ref || rc.section_title;

              return (
                <div
                  key={`${cid}-${rc.chunk_id ?? rc.document_id}`}
                  className={`rounded-lg border transition-colors ${
                    isHighlighted
                      ? 'border-brand-teal bg-teal-50/60 ring-1 ring-brand-teal/30'
                      : 'border-brand-border bg-slate-50/60'
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => toggleDoc(cid)}
                    className="w-full text-left px-3 py-2 flex items-start justify-between gap-2 hover:bg-slate-100/60 rounded-lg transition-colors"
                  >
                    <div className="min-w-0 flex-1 space-y-0.5">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-teal-50 text-brand-teal border border-teal-200 text-[10px] font-bold">
                          {cid}
                        </span>
                        <span className="text-xs font-semibold text-slate-800 truncate">
                          {rc.title}
                        </span>
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-white border border-brand-border text-slate-600">
                          {rc.version_label}
                        </span>
                        {rc.page_number !== null && rc.page_number !== undefined && (
                          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-white border border-brand-border text-slate-600">
                            Trang {rc.page_number}
                          </span>
                        )}
                      </div>
                      {clauseLabel && clauseLabel !== rc.title && (
                        <p className="text-[11px] text-slate-600 flex items-center gap-1">
                          <FileText className="w-3 h-3 text-slate-400 shrink-0" />
                          <span className="truncate">{clauseLabel}</span>
                        </p>
                      )}
                    </div>
                    <span className="text-slate-400 mt-0.5 shrink-0">
                      {isOpen ? (
                        <ChevronDown className="w-4 h-4" />
                      ) : (
                        <ChevronRight className="w-4 h-4" />
                      )}
                    </span>
                  </button>

                  {isOpen && rc.excerpt && (
                    <div className="px-3 pb-2.5 pt-1 border-t border-brand-border/60">
                      <p className="text-[11.5px] leading-relaxed text-slate-700 bg-white rounded-md border border-brand-border/80 p-2.5">
                        &ldquo;{rc.excerpt}&rdquo;
                      </p>
                      {(rc.effective_from || rc.original_file_name) && (
                        <p className="mt-1.5 text-[10px] text-slate-500">
                          {rc.original_file_name ? `Tệp nguồn: ${rc.original_file_name}` : ''}
                          {rc.original_file_name && rc.effective_from ? ' · ' : ''}
                          {rc.effective_from ? `Hiệu lực từ: ${rc.effective_from}` : ''}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
