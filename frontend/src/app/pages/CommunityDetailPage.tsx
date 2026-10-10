import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { Users } from 'lucide-react';
import { useCommunity, useCommunityMembers, useUpdateCommunity } from '@/api/directory';
import { isConflict } from '@/api/http';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { CommunityDetailLayout } from '@/components/CommunityDetailLayout';
import { CommunityCoverPicker } from '@/components/CommunityCoverPicker';
import { PrimaryButton, SecondaryButton } from '@/components/Page';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { ErrorNotice } from '@/components/ErrorNotice';
import { resolveCover } from '@/lib/coverPresets';
import { resolveOfficialAvatar } from '@/lib/officialCharacters';

export function CommunityDetailPage() {
  const { communityId = '' } = useParams();
  return <CommunityDetails key={communityId} communityId={communityId} />;
}

function CommunityDetails({ communityId }: { readonly communityId: string }) {
  const { subject, set } = useCurrentSubject();
  const navigate = useNavigate();
  const community = useCommunity(subject.playerId, communityId);
  const members = useCommunityMembers(subject.playerId, communityId);
  const update = useUpdateCommunity();
  const [selection, setSelection] = useState<string | null>(null);
  const data = community.data;
  const savedChoice = data?.cover_kind === 'preset' ? data.cover_ref ?? null : data?.cover_kind === 'asset' ? null : '';
  const dirty = selection !== null && selection !== savedChoice;
  const preview = selection === null ? resolveCover(communityId, data?.name, data?.cover_kind, data?.cover_ref)
    : resolveCover(communityId, data?.name, selection ? 'preset' : null, selection || null);
  const save = () => {
    if (!data || !dirty || update.isPending) return;
    update.mutate({ communityId, kind: 'appearance', body: {
      player_id: subject.playerId, expected_version: data.state_version,
      cover_kind: selection ? 'preset' : null, cover_ref: selection || null,
    } }, { onSuccess: () => setSelection(null) });
  };
  const actions = data ? <>
    {update.error ? <div className="w-full"><ErrorNotice error={update.error} message={isConflict(update.error) ? '社群信息刚刚更新，请再试一次。' : undefined} /></div> : null}
    {dirty ? <><SecondaryButton disabled={update.isPending} onClick={() => { setSelection(null); update.reset(); }}>放弃编辑</SecondaryButton>
      <PrimaryButton disabled={update.isPending || !data.capabilities.can_change_cover} onClick={save}>{update.isPending ? '保存中…' : '保存封面'}</PrimaryButton></> :
      <PrimaryButton onClick={() => { set({ communityId, communityName: data.name }); void navigate('/app/chat'); }}>进入社群</PrimaryButton>}
  </> : null;

  return <CommunityDetailLayout title={data?.name ?? '社群详情'} description={data ? `${data.timezone} · ${data.status === 'active' ? '正在运行' : '已暂停'}` : '查看这个世界与住在这里的伙伴。'} cover={preview} actions={actions}>
    {subject.playerId === '' ? <p className="text-[13px] text-content-muted">先登记身份，才能查看社群详情。</p> : community.isPending ? <p role="status" className="text-[13px] text-content-muted">正在读取社群…</p> : null}
    <ErrorNotice error={community.error} />
    {data ? <>
      <section className="glass-soft flex flex-wrap items-center justify-between gap-4 rounded-card p-5">
        <div><h2 className="text-[15px] font-semibold">{data.status === 'active' ? '世界正在运行' : '世界暂时休息'}</h2>
          <p className="mt-2 text-[12px] leading-relaxed text-content-muted">{data.status === 'active' ? '角色会准备记忆并回应消息。暂停后，角色会停止回应。' : '启动社群后，角色会准备记忆并回应消息。你仍然可以查看已有内容。'}</p></div>
        {data.capabilities.can_change_status ? <SecondaryButton disabled={update.isPending} onClick={() => update.mutate({ communityId, kind: 'status', body: {
          player_id: subject.playerId, expected_version: data.state_version, status: data.status === 'active' ? 'paused' : 'active',
        } })}>{update.isPending ? '保存中…' : data.status === 'active' ? '暂停社群' : '启动社群'}</SecondaryButton> : <p className="text-[12px] text-content-muted">当前身份无法调整运行状态。</p>}
      </section>
      <section className="glass-soft space-y-4 rounded-card p-5">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold"><Users size={17} className="text-accent" />这里的伙伴</h2>
        {members.isPending ? <p role="status" className="text-[12px] text-content-muted">正在读取成员…</p> : null}
        <ErrorNotice error={members.error} />
        <div className="flex flex-wrap gap-x-6 gap-y-4">{members.data?.items.map(member => {
          const key = member.actor.kind === 'system' ? `system:${member.actor.source_id}` : `${member.actor.kind}:${member.actor.actor_id}`;
          return <div key={key} className="flex items-center gap-2"><CharacterAvatar identity={key} name={member.display_name} imageUrl={resolveOfficialAvatar({ avatarUrl: member.avatar_url, displayName: member.display_name })} size="sm" /><span className="text-[13px]">{member.display_name}</span></div>;
        })}</div>
      </section>
      <section className="glass-soft space-y-4 rounded-card p-5">
        <h2 className="text-[15px] font-semibold">这个世界的模样</h2>
        {data.capabilities.can_change_cover ? <><p className="text-[12px] text-content-muted">挑选一个封面，预览满意后再保存。</p>
          <CommunityCoverPicker value={selection ?? savedChoice} onChange={setSelection} disabled={update.isPending} />
          {dirty ? <p role="status" className="text-[12px] text-accent">正在预览，封面尚未保存。</p> : null}</> : <p className="text-[12px] text-content-muted">当前身份无法更换封面。</p>}
      </section>
      <details className="px-1 text-[12px] text-content-faint"><summary className="cursor-pointer">邀请朋友</summary><p className="mt-3">把社群标识发给朋友：<span className="select-all text-content-muted">{communityId}</span></p></details>
    </> : null}
  </CommunityDetailLayout>;
}
