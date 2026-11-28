import React, { useState } from 'react';
import {
  Check,
  Clock,
  MessageSquare,
  Pencil,
  Plus,
  Trash2,
  X,
} from 'lucide-react';
import { ConversationSummary } from '../../types/assistant';
import { ConfirmModal } from '../ui/ConfirmModal';
import { ErrorState } from '../ui/ErrorState';

export interface ConversationSidebarProps {
  conversations: ConversationSummary[];
  total: number;
  hasMore: boolean;
  activeConversationId: string | null;
  loadingList: boolean;
  loadingMore: boolean;
  errorMessage: string | null;
  onRetryLoad: () => void;
  onLoadMore: () => void;
  onNewConversation: () => void;
  onSelectConversation: (conversationId: string) => void;
  onRenameConversation: (conversationId: string, newTitle: string) => Promise<void>;
  onDeleteConversation: (conversationId: string) => Promise<void>;
  onCloseMobile?: () => void;
}

export const ConversationSidebar: React.FC<ConversationSidebarProps> = ({
  conversations,
  total,
  hasMore,
  activeConversationId,
  loadingList,
  loadingMore,
  errorMessage,
  onRetryLoad,
  onLoadMore,
  onNewConversation,
  onSelectConversation,
  onRenameConversation,
  onDeleteConversation,
  onCloseMobile,
}) => {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [savingRename, setSavingRename] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ConversationSummary | null>(null);
  const [deleting, setDeleting] = useState(false);

  const startEditing = (conv: ConversationSummary, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(conv.conversation_id);
    setEditTitle(conv.title);
  };

  const cancelEditing = (e?: React.MouseEvent) => {
    e?.stopPropagation();
    setEditingId(null);
    setEditTitle('');
  };

  const commitRename = async (conversationId: string, e?: React.FormEvent | React.MouseEvent) => {
    e?.preventDefault();
    e?.stopPropagation();
    const trimmed = editTitle.trim();
    if (!trimmed || savingRename) return;
    setSavingRename(true);
    try {
      await onRenameConversation(conversationId, trimmed);
      setEditingId(null);
      setEditTitle('');
    } finally {
      setSavingRename(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    try {
      await onDeleteConversation(deleteTarget.conversation_id);
      setDeleteTarget(null);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <aside
      aria-label="Lịch sử hội thoại AI"
      className="flex flex-col h-full bg-white rounded-card border border-brand-border shadow-sm overflow-hidden"
    >
      {/* Header */}
      <div className="px-4 py-3.5 border-b border-brand-border flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-xs font-bold text-brand-navy truncate">Lịch sử hội thoại</h3>
          <p className="text-[10.5px] text-slate-500">
            {total > 0 ? `${total} phiên đã lưu` : 'Riêng tư theo tài khoản'}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => {
              onNewConversation();
              onCloseMobile?.();
            }}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-brand-blue text-white text-[11px] font-semibold hover:bg-blue-700 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" /> Mới
          </button>
          {onCloseMobile && (
            <button
              type="button"
              onClick={onCloseMobile}
              aria-label="Đóng danh sách hội thoại"
              className="lg:hidden p-1.5 rounded-lg text-slate-500 hover:bg-slate-100"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-2.5 space-y-1.5">
        {errorMessage && (
          <div className="p-1">
            <ErrorState
              title="Lỗi tải lịch sử"
              message={errorMessage}
              onRetry={onRetryLoad}
            />
          </div>
        )}

        {loadingList && conversations.length === 0 ? (
          <div className="space-y-2 p-2 animate-pulse" data-testid="history-loading">
            {[1, 2, 3, 4].map((n) => (
              <div key={n} className="h-12 rounded-lg bg-slate-100" />
            ))}
          </div>
        ) : conversations.length === 0 && !errorMessage ? (
          <div className="py-10 px-4 text-center" data-testid="empty-history">
            <div className="w-10 h-10 rounded-full bg-brand-bg text-slate-400 flex items-center justify-center mx-auto mb-2.5">
              <MessageSquare className="w-4 h-4" />
            </div>
            <p className="text-xs font-semibold text-slate-700">Chưa có hội thoại nào</p>
            <p className="mt-1 text-[11px] text-slate-500 leading-relaxed">
              Đặt câu hỏi đầu tiên ở khung bên phải để bắt đầu lưu lịch sử tra cứu.
            </p>
          </div>
        ) : (
          <>
            {conversations.map((conv) => {
              const isActive = conv.conversation_id === activeConversationId;
              const isEditing = editingId === conv.conversation_id;

              return (
                <div
                  key={conv.conversation_id}
                  className={`group rounded-xl border transition-colors ${
                    isActive
                      ? 'bg-blue-50/70 border-blue-200'
                      : 'bg-white border-transparent hover:bg-brand-bg hover:border-brand-border'
                  }`}
                >
                  {isEditing ? (
                    <form
                      onSubmit={(e) => commitRename(conv.conversation_id, e)}
                      className="p-2 flex items-center gap-1"
                    >
                      <input
                        type="text"
                        aria-label="Tên hội thoại mới"
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') cancelEditing();
                        }}
                        maxLength={120}
                        autoFocus
                        className="flex-1 min-w-0 px-2 py-1 text-xs rounded-md border border-brand-blue bg-white focus:outline-none"
                      />
                      <button
                        type="submit"
                        disabled={savingRename || !editTitle.trim()}
                        aria-label="Lưu tên hội thoại"
                        className="p-1 rounded-md text-brand-green hover:bg-emerald-50 disabled:opacity-40"
                      >
                        <Check className="w-3.5 h-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={cancelEditing}
                        aria-label="Hủy đổi tên"
                        className="p-1 rounded-md text-slate-400 hover:bg-slate-100"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </form>
                  ) : (
                    <div className="flex items-start justify-between gap-1 px-2.5 py-2">
                      <button
                        type="button"
                        onClick={() => {
                          onSelectConversation(conv.conversation_id);
                          onCloseMobile?.();
                        }}
                        className="flex-1 min-w-0 text-left"
                      >
                        <p
                          className={`text-xs font-medium line-clamp-2 leading-snug ${
                            isActive ? 'text-brand-navy font-semibold' : 'text-slate-700'
                          }`}
                        >
                          {conv.title}
                        </p>
                        <p className="mt-1 text-[10px] text-slate-400 flex items-center gap-1.5">
                          <Clock className="w-3 h-3 shrink-0" />
                          <span className="truncate">{conv.updated_at}</span>
                          <span>· {conv.message_count} tin</span>
                        </p>
                      </button>

                      <div className="flex items-center gap-0.5 shrink-0 opacity-80 lg:opacity-0 lg:group-hover:opacity-100 lg:focus-within:opacity-100 transition-opacity">
                        <button
                          type="button"
                          onClick={(e) => startEditing(conv, e)}
                          aria-label={`Đổi tên hội thoại ${conv.title}`}
                          title="Đổi tên hội thoại"
                          className="p-1 rounded-md text-slate-400 hover:text-brand-blue hover:bg-white"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeleteTarget(conv);
                          }}
                          aria-label={`Xóa hội thoại ${conv.title}`}
                          title="Xóa hội thoại"
                          className="p-1 rounded-md text-slate-400 hover:text-brand-red hover:bg-white"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}

            {hasMore && (
              <div className="pt-2 text-center">
                <button
                  type="button"
                  disabled={loadingMore}
                  onClick={onLoadMore}
                  className="w-full py-2 rounded-lg border border-brand-border bg-brand-bg/60 text-xs font-semibold text-slate-700 hover:border-brand-blue hover:text-brand-blue disabled:opacity-50 transition-colors"
                >
                  {loadingMore ? 'Đang tải thêm...' : 'Tải thêm hội thoại'}
                </button>
              </div>
            )}
          </>
        )}
      </div>

      <ConfirmModal
        isOpen={deleteTarget !== null}
        title="Xóa phiên hội thoại?"
        description={
          deleteTarget
            ? `Phiên "${deleteTarget.title}" và toàn bộ tin nhắn bên trong sẽ bị xóa vĩnh viễn khỏi lịch sử cá nhân của bạn.`
            : ''
        }
        confirmLabel="Xóa hội thoại"
        cancelLabel="Giữ lại"
        isDanger
        isLoading={deleting}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </aside>
  );
};
