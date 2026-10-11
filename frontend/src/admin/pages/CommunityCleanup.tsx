import { useState } from 'react';
import { useNavigate } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { request, type SchemaOf } from '@/api/http';
import { useUpdateCommunity } from '@/api/directory';
import { ErrorNotice } from '@/components/ErrorNotice';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import type { AdminCommunity, AdminMember } from '@/api/admin';

type CleanupResult = SchemaOf<'CleanupResult'>;

export function CommunityCleanup({ community, members }: {
  readonly community: AdminCommunity; readonly members: readonly AdminMember[];
}) {
  const players = members.filter((item) => item.actor_kind === 'player');
  const [selectedPlayer, setSelectedPlayer] = useState('');
  const playerId = selectedPlayer || players[0]?.actor_id || '';
  const [preview, setPreview] = useState<CleanupResult | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const update = useUpdateCommunity();
  const cache = useQueryClient();
  const navigate = useNavigate();
  const { subject, set } = useCurrentSubject();
  const readPreview = () => request<CleanupResult>('/internal/maintenance/cleanup', {
    method: 'POST', body: { community_ids: [community.community_id], dry_run: true },
  });

  const perform = async (execute: boolean) => {
    setBusy(true); setError(null);
    try {
      if (!execute) {
        setAcknowledged(false);
        setPreview(await readPreview());
      } else {
        const result = await request<CleanupResult>('/internal/maintenance/cleanup', {
          method: 'POST', body: { community_ids: [community.community_id], dry_run: false },
        });
        if (result.deleted) {
          await cache.cancelQueries({ predicate: (query) => query.queryKey.includes(community.community_id) });
          cache.removeQueries({ predicate: (query) => query.queryKey.includes(community.community_id) });
          await cache.invalidateQueries({ queryKey: ['admin', 'communities'] });
          await cache.invalidateQueries({ queryKey: ['directory'] });
          if (subject.communityId === community.community_id) set({ communityId: null, communityName: null });
          void navigate('/admin/communities');
        }
      }
    } catch (cause) {
      setError(cause);
      setAcknowledged(false);
      if (execute) {
        setPreview(null);
        try { setPreview(await readPreview()); } catch { /* 请求失败时保留明确错误。 */ }
      }
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4 rounded-lg border border-danger/25 bg-danger/5 p-4 text-[12px]">
      <h3 className="font-semibold">清理测试社群</h3>
      <p className="text-content-muted">删除这个社群的角色、会话、消息、记忆与任务。玩家、人物草稿、图片资产和备份保留。</p>
      {community.status === 'active' ? (
        <div className="flex flex-wrap gap-3">
          <select aria-label="暂停操作玩家" value={playerId} onChange={(event) => setSelectedPlayer(event.target.value)}
            className="rounded border border-border-subtle bg-surface-sunken p-2">
            {players.map((player) => <option key={player.actor_id}>{player.actor_id}</option>)}
          </select>
          <button disabled={!playerId || update.isPending} onClick={() => {
            setPreview(null); setAcknowledged(false);
            update.mutate({ communityId: community.community_id, kind: 'status', body: {
              player_id: playerId, status: 'paused', expected_version: community.state_version,
            } });
          }} className="rounded border border-border-subtle px-3 py-2">暂停社群</button>
        </div>
      ) : <p className="text-ok">社群已暂停</p>}
      <button disabled={busy || community.status !== 'paused'} onClick={() => { void perform(false); }}
        className="rounded border border-border-subtle px-3 py-2 disabled:opacity-50">{busy ? '处理中…' : '预览清理范围'}</button>
      {preview ? (
        <div className="space-y-3">
          <dl className="grid grid-cols-2 gap-2">
            {Object.entries(preview.counts).filter(([, count]) => count > 0).map(([table, count]) => (
              <div key={table}><dt className="break-all text-content-faint">{table}</dt><dd>{count} 条</dd></div>
            ))}
          </dl>
          {preview.blockers.map((blocker) => <p key={`${blocker.kind}:${blocker.object_id}:${blocker.reason}`} className="break-all text-danger">
            {blocker.kind} · {blocker.object_id} · {blocker.reason}
          </p>)}
          {Object.entries(preview.missing).map(([kind, ids]) => ids.length ? <p key={kind}>未找到：{ids.join('、')}</p> : null)}
          <p className="text-content-faint">保留：{preview.retained_resources?.join('、')}</p>
          <label className="flex items-start gap-2"><input type="checkbox" checked={acknowledged}
            onChange={(event) => setAcknowledged(event.target.checked)} />我确认删除「{community.name}」及预览中的记录，此操作无法撤销。</label>
          <button disabled={busy || !acknowledged || preview.blockers.length > 0 || community.status !== 'paused'}
            onClick={() => { void perform(true); }} className="rounded bg-danger px-3 py-2 text-white disabled:opacity-40">确认删除社群</button>
        </div>
      ) : null}
      <ErrorNotice error={error ?? update.error} diagnostic />
    </div>
  );
}
