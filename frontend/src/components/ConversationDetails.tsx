import { useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { useConversationOperation, type ConversationSummary } from '@/api/conversations';
import type { PublicDisplay } from '@/api/directory';
import { ErrorNotice } from './ErrorNotice';

const button = 'rounded-xl border border-border-subtle px-4 py-2 text-sm transition-colors hover:bg-accent/10 disabled:opacity-40';

export function ConversationDetails({ summary, members, playerId, onClose }: {
  summary: ConversationSummary; members: readonly PublicDisplay[]; playerId: string; onClose: () => void;
}) {
  const operation = useConversationOperation(playerId, summary.conversation_id);
  const [confirm, setConfirm] = useState<'leave' | 'archive' | null>(null);
  async function act(input: Parameters<typeof operation.mutateAsync>[0]) {
    try { await operation.mutateAsync(input); setConfirm(null); } catch { /* 错误保留在详情中，重试沿用操作编号。 */ }
  }
  return <Dialog.Root open onOpenChange={(open) => { if (!open && !operation.isPending) onClose(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm" />
      <Dialog.Content aria-describedby="conversation-detail-description" className="fixed left-1/2 top-1/2 z-[61] max-h-[85dvh] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-card border border-border-strong bg-surface p-6 text-content shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <Dialog.Title className="display-title text-xl">{summary.display_name}</Dialog.Title>
          <button type="button" aria-label="关闭会话详情" onClick={onClose} disabled={operation.isPending} className="rounded-full p-1.5 text-content-muted hover:bg-white/5"><X size={18} /></button>
        </div>
        <p id="conversation-detail-description" className="mt-2 text-sm text-content-muted">{summary.kind === 'group' ? '群聊' : '私聊'} · {summary.status === 'archived' ? '已经结束，历史可以继续阅读' : summary.self_membership_status === 'past' ? '你已退出，不接收新消息' : '正在交流'}</p>
        {summary.kind === 'group' ? <p className="mt-4 text-sm">创建者：{summary.creator_display?.display_name ?? '历史记录未保存创建者'}</p> : null}
        {summary.legacy_small_group ? <p className="mt-2 text-xs text-content-faint">按历史规则创建的群聊，人数变化不影响已有记录。</p> : null}
        <section className="my-6 rounded-xl bg-surface-sunken/60 p-4">
          <h3 className="mb-3 text-xs text-content-faint">{summary.self_membership_status === 'current' ? '当前成员' : '历史读取范围'}</h3>
          {summary.self_membership_status === 'current' ? <ul className="space-y-2 text-sm">{members.map((member) => <li key={JSON.stringify(member.actor)}>{member.display_name}</li>)}</ul>
            : <p className="text-sm text-content-muted">保留你参与期间可以阅读的消息。重新加入不会开放退出期间的消息。</p>}
        </section>
        <div className="flex flex-col gap-3">
          <button type="button" className={button} disabled={operation.isPending} onClick={() => void act({ action: 'preference', hidden: !summary.hidden })}>{summary.hidden ? '找回会话' : '从我的列表移除'}</button>
          <p className="text-xs text-content-faint">列表操作保留所有消息，不影响其他成员。</p>
          {summary.can_join ? <button type="button" className={button} disabled={operation.isPending} onClick={() => void act({ action: 'join' })}>重新加入</button> : null}
          {summary.can_leave ? <button type="button" className={button} disabled={operation.isPending} onClick={() => setConfirm('leave')}>退出{summary.kind === 'group' ? '群聊' : '私聊'}</button> : null}
          {summary.can_archive ? <button type="button" className={`${button} text-danger`} disabled={operation.isPending} onClick={() => setConfirm('archive')}>结束群聊</button> : null}
        </div>
        {confirm ? <div role="alert" className="mt-5 rounded-xl border border-warn/30 bg-warn/5 p-4">
          <p className="text-sm leading-relaxed">{confirm === 'archive' ? '结束后所有成员停止交流，无法重新启动，历史记录保留。' : summary.kind === 'group' ? '退出后不再接收新消息，历史记录保留。如果最后一名玩家退出，群聊会自动结束。' : '退出后不再接收新消息，历史记录保留。再次打开私聊会继续使用这份记录。'}</p>
          <div className="mt-4 flex gap-3"><button type="button" className={button} disabled={operation.isPending} onClick={() => void act(confirm === 'archive' ? { action: 'archive', stateVersion: summary.state_version } : { action: 'leave', membershipId: summary.self_membership_id! })}>确认{confirm === 'archive' ? '结束' : '退出'}</button><button type="button" className={button} disabled={operation.isPending} onClick={() => setConfirm(null)}>取消</button></div>
        </div> : null}
        {operation.isPending ? <p role="status" className="mt-4 text-xs text-content-muted">正在保存…</p> : null}
        {operation.error ? <div className="mt-4"><ErrorNotice error={operation.error} /></div> : null}
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
