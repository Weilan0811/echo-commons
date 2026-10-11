import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { useCreateCommunity } from '@/api/directory';
import { isConflict } from '@/api/http';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { CommunityDetailLayout } from '@/components/CommunityDetailLayout';
import { CommunityCoverPicker } from '@/components/CommunityCoverPicker';
import { ErrorNotice } from '@/components/ErrorNotice';
import { Field, PrimaryButton } from '@/components/Page';
import { resolveCover } from '@/lib/coverPresets';

export function CommunityCreatePage() {
  const { subject } = useCurrentSubject();
  const navigate = useNavigate();
  const location = useLocation();
  const create = useCreateCommunity();
  const [name, setName] = useState('');
  const [communityId, setCommunityId] = useState('');
  const [cover, setCover] = useState('');
  const [timezone, setTimezone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
  const [zones] = useState(() => [...new Set(['UTC', Intl.DateTimeFormat().resolvedOptions().timeZone, ...Intl.supportedValuesOf('timeZone')])]);
  const submit = () => {
    if (!subject.playerId || !name.trim() || create.isPending) return;
    create.mutate({ playerId: subject.playerId, name: name.trim(), communityId: communityId.trim() || null, timezone, coverRef: cover || null }, {
      onSuccess: result => { void navigate(`/app/communities/${encodeURIComponent(result.community_id)}`, { replace: true, state: location.state }); },
    });
  };
  return <CommunityDetailLayout title={name.trim() || '开辟新天地'} description="给这个世界取个名字，准备迎接住在这里的伙伴。"
    cover={resolveCover(null, name, cover ? 'preset' : null, cover || null)}
    actions={<>{create.error ? <div className="w-full"><ErrorNotice error={create.error} message={isConflict(create.error) ? '这个社群标识已经被使用，请换一个再创建。' : undefined} /></div> : null}<span className="mr-auto text-[12px] text-content-faint">创建后暂时休息，由你选择何时启动。</span><PrimaryButton disabled={!subject.playerId || !name.trim() || create.isPending} onClick={submit}>{create.isPending ? '创建中…' : '创建社群'}</PrimaryButton></>}>
    {!subject.playerId ? <p className="text-[13px] text-content-muted">先登记身份，才能创建社群。</p> : null}
    <section className="glass-soft grid gap-5 rounded-card p-5 sm:grid-cols-2">
      <Field label="社群名称" value={name} onChange={setName} placeholder="深夜食堂" />
      <label className="flex min-w-0 flex-col gap-1.5"><span className="text-[11px] font-medium text-content-muted">世界时区</span>
        <select value={timezone} onChange={event => setTimezone(event.target.value)} className="w-full min-w-0 rounded-xl border border-white/10 bg-surface-sunken px-3.5 py-2.5 text-sm text-content focus:outline-accent">
          {zones.map(zone => <option key={zone} value={zone}>{zone}</option>)}
        </select><span className="text-[11px] text-content-faint">默认使用你所在的时区。</span></label>
    </section>
    <section className="glass-soft space-y-4 rounded-card p-5"><h2 className="text-[15px] font-semibold">这个世界的模样</h2><CommunityCoverPicker value={cover} onChange={setCover} disabled={create.isPending} /></section>
    <details className="glass-soft rounded-card p-5"><summary className="cursor-pointer text-[13px] text-content-muted">详细选项</summary>
      <div className="mt-4"><Field label="社群标识" hint="留空会自动分配。朋友可以用这个标识加入。" value={communityId} onChange={setCommunityId} placeholder="例如 night-diner" /></div>
    </details>
  </CommunityDetailLayout>;
}
