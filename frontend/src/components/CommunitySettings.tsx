import { useCommunity, useUpdateCommunity } from '@/api/directory';
import { PRESET_COVERS } from '@/lib/coverPresets';
import { ErrorNotice } from './ErrorNotice';

export function CommunitySettings({ playerId, communityId }: {
  readonly playerId: string; readonly communityId: string;
}) {
  const community = useCommunity(playerId, communityId);
  const update = useUpdateCommunity();
  const data = community.data;
  if (!data) return <ErrorNotice error={community.error} />;
  const disabled = update.isPending;
  return (
    <div className="glass-soft space-y-4 rounded-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[14px] font-semibold">{data.name}</p>
          <p className="mt-1 text-[12px] text-content-muted">
            {data.status === 'active' ? '正在运行，角色会准备记忆并回应消息。' : '已暂停，启动后角色会准备记忆并回应消息。'}
          </p>
        </div>
        <button disabled={disabled} className="rounded-full border border-accent/40 px-4 py-2 text-[13px] text-accent disabled:opacity-50"
          onClick={() => update.mutate({ communityId, kind: 'status', body: {
            player_id: playerId, expected_version: data.state_version,
            status: data.status === 'active' ? 'paused' : 'active',
          } })}>
          {disabled ? '保存中…' : data.status === 'active' ? '暂停社群' : '启动社群'}
        </button>
      </div>
      <label className="flex flex-col gap-2 text-[12px] text-content-muted">
        官方封面
        <select aria-label="官方封面" value={data.cover_kind === 'preset' ? data.cover_ref ?? '' : ''} disabled={disabled}
          className="rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2 text-content"
          onChange={(event) => update.mutate({ communityId, kind: 'appearance', body: {
            player_id: playerId, expected_version: data.state_version,
            cover_kind: event.target.value ? 'preset' : null, cover_ref: event.target.value || null,
          } })}>
          <option value="">默认渐变</option>
          {PRESET_COVERS.map((cover) => <option key={cover.id} value={cover.id}>{cover.matchNames[0]}</option>)}
        </select>
      </label>
      <ErrorNotice error={update.error} />
    </div>
  );
}
