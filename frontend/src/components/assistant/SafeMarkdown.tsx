import React from 'react';
import { Link } from 'react-router-dom';

export interface SafeMarkdownProps {
  content: string;
  onCitationClick?: (citationId: string) => void;
}

const ALLOWED_APP_ROUTES = new Set([
  '/dashboard',
  '/attendance',
  '/leaves',
  '/anomalies',
  '/reports',
  '/profile',
  '/assistant',
  '/executive/departments',
  '/admin/rag',
  '/admin/audit',
  '/admin/config',
  '/admin/system',
]);

function renderInline(
  text: string,
  keyPrefix: string,
  onCitationClick?: (citationId: string) => void
): React.ReactNode[] {
  // Tokenize **bold**, *italic*, `code`, [DOC-N], and safe internal route paths like (/leaves)
  const tokenRegex =
    /(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`]+`|\[DOC-\d+\]|(?:\(\/[a-zA-Z0-9/_-]+\)))/g;
  const parts = text.split(tokenRegex);

  return parts.map((part, idx) => {
    const key = `${keyPrefix}-${idx}`;
    if (!part) return null;

    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return (
        <strong key={key} className="font-semibold text-slate-900">
          {part.slice(2, -2)}
        </strong>
      );
    }

    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      return (
        <em key={key} className="italic text-slate-600">
          {part.slice(1, -1)}
        </em>
      );
    }

    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      const inner = part.slice(1, -1);
      if (ALLOWED_APP_ROUTES.has(inner)) {
        return (
          <Link
            key={key}
            to={inner}
            className="inline-flex items-center px-1.5 py-0.5 rounded bg-blue-50 text-brand-blue font-medium text-[12px] hover:underline"
          >
            {inner}
          </Link>
        );
      }
      return (
        <code
          key={key}
          className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-800 font-mono text-[11.5px]"
        >
          {inner}
        </code>
      );
    }

    if (/^\[DOC-\d+\]$/.test(part)) {
      const cid = part.slice(1, -1);
      return (
        <button
          key={key}
          type="button"
          onClick={() => onCitationClick?.(cid)}
          className="inline-flex items-center px-1.5 py-0.5 mx-0.5 rounded-md bg-teal-50 text-brand-teal border border-teal-200 text-[11px] font-semibold hover:bg-teal-100 transition-colors"
          title={`Xem nguồn trích dẫn ${cid}`}
        >
          {cid}
        </button>
      );
    }

    if (part.startsWith('(/') && part.endsWith(')')) {
      const route = part.slice(1, -1);
      if (ALLOWED_APP_ROUTES.has(route)) {
        return (
          <React.Fragment key={key}>
            (
            <Link to={route} className="text-brand-blue font-medium hover:underline">
              {route}
            </Link>
            )
          </React.Fragment>
        );
      }
    }

    return <React.Fragment key={key}>{part}</React.Fragment>;
  });
}

/**
 * XSS-safe Enterprise Markdown renderer (ZERO dangerouslySetInnerHTML).
 * Optimized for clean readability of long Hybrid SQL + RAG responses.
 */
export const SafeMarkdown: React.FC<SafeMarkdownProps> = ({ content, onCitationClick }) => {
  const rawLines = (content || '').replace(/\r\n/g, '\n').split('\n');
  const blocks: React.ReactNode[] = [];
  let i = 0;

  while (i < rawLines.length) {
    const line = rawLines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i += 1;
      continue;
    }

    // Heading ### or ##
    const headingMatch = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const headingText = headingMatch[2];
      const isSqlSec = headingText.includes('(SQL)') || headingText.includes('Dữ liệu thực tế');
      const isRagSec = headingText.includes('(RAG)') || headingText.includes('Căn cứ quy định');

      blocks.push(
        <div
          key={`h-${i}`}
          className={`flex items-center gap-2 pt-2 pb-1 ${
            blocks.length > 0 ? 'mt-2 border-t border-brand-border/80' : ''
          }`}
        >
          {isSqlSec && (
            <span className="w-2 h-2 rounded-full bg-brand-blue shrink-0" aria-hidden="true" />
          )}
          {isRagSec && (
            <span className="w-2 h-2 rounded-full bg-brand-teal shrink-0" aria-hidden="true" />
          )}
          <h4
            className={`${
              level <= 2 ? 'text-sm' : 'text-[13px]'
            } font-bold text-brand-navy tracking-tight`}
          >
            {renderInline(headingText, `hi-${i}`, onCitationClick)}
          </h4>
        </div>
      );
      i += 1;
      continue;
    }

    // Bullet list (- or *)
    if (/^[-*•]\s+/.test(trimmed)) {
      const items: string[] = [];
      const startIdx = i;
      while (i < rawLines.length && /^[-*•]\s+/.test(rawLines[i].trim())) {
        items.push(rawLines[i].trim().replace(/^[-*•]\s+/, ''));
        i += 1;
      }
      blocks.push(
        <ul key={`ul-${startIdx}`} className="space-y-1.5 pl-4 list-disc marker:text-slate-400">
          {items.map((itemText, liIdx) => (
            <li key={`li-${startIdx}-${liIdx}`} className="text-[13px] leading-6 text-slate-700">
              {renderInline(itemText, `uli-${startIdx}-${liIdx}`, onCitationClick)}
            </li>
          ))}
        </ul>
      );
      continue;
    }

    // Ordered list (1. 2. 3.)
    if (/^\d+\.\s+/.test(trimmed)) {
      const items: string[] = [];
      const startIdx = i;
      while (i < rawLines.length && /^\d+\.\s+/.test(rawLines[i].trim())) {
        items.push(rawLines[i].trim().replace(/^\d+\.\s+/, ''));
        i += 1;
      }
      blocks.push(
        <ol
          key={`ol-${startIdx}`}
          className="space-y-1.5 pl-5 list-decimal marker:text-slate-500 marker:font-semibold"
        >
          {items.map((itemText, liIdx) => (
            <li key={`oli-${startIdx}-${liIdx}`} className="text-[13px] leading-6 text-slate-700">
              {renderInline(itemText, `oli-${startIdx}-${liIdx}`, onCitationClick)}
            </li>
          ))}
        </ol>
      );
      continue;
    }

    // Regular paragraph (group adjacent plain lines)
    const paraLines: string[] = [];
    const startIdx = i;
    while (
      i < rawLines.length &&
      rawLines[i].trim() &&
      !/^(#{1,3})\s+/.test(rawLines[i].trim()) &&
      !/^[-*•]\s+/.test(rawLines[i].trim()) &&
      !/^\d+\.\s+/.test(rawLines[i].trim())
    ) {
      paraLines.push(rawLines[i].trim());
      i += 1;
    }
    const paraText = paraLines.join(' ');
    blocks.push(
      <p key={`p-${startIdx}`} className="text-[13px] leading-6 text-slate-700">
        {renderInline(paraText, `pi-${startIdx}`, onCitationClick)}
      </p>
    );
  }

  return <div className="space-y-2">{blocks}</div>;
};
