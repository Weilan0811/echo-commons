import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { ArrowRight, Compass, Settings2, Sparkles } from 'lucide-react';
import { Shell } from '@/components/Shell';
import { Field, SecondaryButton } from '@/components/Page';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { ErrorNotice } from '@/components/ErrorNotice';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { useCommunityMembers, useJoinedCommunities, useJoinCommunity, type CommunityCard, type PublicDisplay } from '@/api/directory';
import { resolveCover } from '@/lib/coverPresets';
import { resolveOfficialAvatar } from '@/lib/officialCharacters';
import { accentColor } from '@/lib/characterColor';

type Community = CommunityCard;

export function CommunityPage() {
  const { subject, set } = useCurrentSubject();
  const navigate = useNavigate();
  const location = useLocation();
  const [joining, setJoining] = useState(false);
  const [joinTarget, setJoinTarget] = useState('');
  const joined = useJoinedCommunities(subject.playerId);
  const join = useJoinCommunity();
  const needsIdentity = subject.playerId === '';

  useEffect(() => {
    const focusId = location.state?.returnFocusId as string | undefined;
    if (!focusId) return;
    const frame = requestAnimationFrame(() => document.getElementById(focusId)?.focus());
    return () => cancelAnimationFrame(frame);
  }, [location.state, joined.data]);

  const open = async (path: string, returnFocusId: string) => {
    await navigate('/app/communities', { replace: true, state: { returnFocusId } });
    await navigate(path, { state: { fromList: true, returnFocusId } });
  };
  const joinWorld = () => join.mutate({ communityId: joinTarget.trim(), playerId: subject.playerId }, {
    onSuccess: () => { setJoinTarget(''); setJoining(false); },
  });

  return <Shell section="subject" list={null}>
    <div className="animate-rise-in flex h-full flex-col">
      <header className="shrink-0 px-4 pb-6 pt-6 sm:px-9 sm:pt-8">
        <h1 className="display-title text-[28px]">社群</h1>
        <p className="mt-1.5 text-[13px] text-content-faint">走进一个世界，和住在里面的灵魂一起生活。</p>
      </header>
      <div className="min-h-0 flex-1 space-y-8 overflow-y-auto px-4 pb-10 sm:px-9">
        <section aria-label="已加入的社群">
          <h2 className="mb-4 text-[14px] font-semibold">常去的地方</h2>
          {needsIdentity ? <p className="text-[13px] text-content-faint">先登记身份，才能查看已加入的社群。</p>
            : joined.isPending ? <p role="status" className="text-[13px] text-content-faint">正在读取…</p>
              : joined.data?.items.length === 0 ? <div className="glass-soft rounded-card px-6 py-10 text-center text-[13px] text-content-muted">还没有常去的地方。开辟一个新世界，或前往朋友邀请你的世界。</div> : null}
          <ErrorNotice error={joined.error} />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {joined.data?.items.map((community, index) => <CommunitySceneCard key={community.community_id}
              community={community} playerId={subject.playerId} active={community.community_id === subject.communityId}
              appearDelay={Math.min(index, 7) * 45} onEnter={() => {
                set({ communityId: community.community_id, communityName: community.name });
                void navigate('/app/chat');
              }} onDetails={() => { void open(`/app/communities/${encodeURIComponent(community.community_id)}`, `community-detail-${community.community_id}`); }} />)}
          </div>
        </section>
        <div className="grid gap-4 lg:grid-cols-2">
          <button id="create-community" type="button" disabled={needsIdentity}
            onClick={() => { void open('/app/communities/new', 'create-community'); }}
            className="glass-soft flex items-center gap-4 rounded-card p-6 text-left transition-colors hover:border-accent/40 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"><Sparkles size={20} /></span>
            <span className="flex-1"><span className="block text-[15px] font-semibold">开辟新天地</span><span className="mt-1 block text-[12px] text-content-faint">为朋友和角色准备一个共同生活的地方。</span></span>
            <ArrowRight size={17} className="text-content-faint" />
          </button>
          <section className="glass-soft rounded-card p-6">
            <button type="button" disabled={needsIdentity} aria-expanded={joining} aria-controls="community-invitation"
              onClick={() => setJoining(!joining)} className="flex w-full items-center gap-4 text-left disabled:opacity-50">
              <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"><Compass size={20} /></span>
              <span className="flex-1"><span className="block text-[15px] font-semibold">前往朋友的世界</span><span className="mt-1 block text-[12px] text-content-faint">带上朋友给你的社群标识，加入他们。</span></span>
              <ArrowRight size={17} className={`text-content-faint transition-transform ${joining ? 'rotate-90' : ''}`} />
            </button>
            {joining ? <form id="community-invitation" className="mt-5 space-y-4" onSubmit={event => {
              event.preventDefault(); if (joinTarget.trim() && !join.isPending) joinWorld();
            }}>
              <Field label="社群标识" value={joinTarget} onChange={setJoinTarget} placeholder="朋友给你的标识" />
              <SecondaryButton disabled={!joinTarget.trim() || join.isPending} onClick={joinWorld}>{join.isPending ? '加入中…' : '加入社群'}</SecondaryButton>
              <ErrorNotice error={join.error} />
            </form> : null}
          </section>
        </div>
      </div>
    </div>
  </Shell>;
}

function CommunitySceneCard({
  community,
  playerId,
  active,
  appearDelay,
  onEnter,
  onDetails,
}: {
  readonly community: Community;
  readonly playerId: string;
  readonly active: boolean;
  readonly appearDelay: number;
  readonly onEnter: () => void;
  readonly onDetails: () => void;
}) {
  const members = useCommunityMembers(playerId, community.community_id);
  const items = members.data?.items ?? [];
  const cover = resolveCover(community.community_id, community.name, community.cover_kind, community.cover_ref);
  const hue = accentColor(`community:${community.community_id}`);

  return (
    <article
      style={{ animationDelay: `${appearDelay}ms` }}
      className="animate-rise-in group relative h-44 overflow-hidden rounded-card border border-border-subtle text-left transition-[transform,border-color,box-shadow] duration-300 hover:-translate-y-0.5 hover:border-accent/40 hover:shadow-[0_18px_40px_-18px_rgba(10,7,16,.8)]"
    >
      {cover !== null ? (
        <img
          src={cover}
          alt=""
          className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.035]"
        />
      ) : (
        <div
          className="absolute inset-0"
          style={{
            background: `radial-gradient(circle at 18% 22%, color-mix(in oklch, ${hue} 34%, transparent), transparent 72%), linear-gradient(150deg, var(--color-surface-overlay), var(--color-surface-sunken))`,
          }}
        />
      )}
      <div className="absolute inset-0 bg-gradient-to-t from-black/82 via-black/25 to-black/10" />
      <button type="button" aria-label={`进入${community.name}`} onClick={onEnter}
        className="absolute inset-0 z-10 rounded-card focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-accent" />
      <span className="absolute left-5 top-4 text-[11px] text-white/80">{community.status === 'active' ? '正在运行' : '已暂停'}</span>
      <button id={`community-detail-${community.community_id}`} type="button" aria-label={`${community.name}的社群详情`} onClick={onDetails}
        className="absolute right-3 top-3 z-20 flex size-9 items-center justify-center rounded-full border border-white/15 bg-black/25 text-white/85 backdrop-blur-sm hover:bg-black/45 focus-visible:outline-2 focus-visible:outline-accent"><Settings2 size={16} /></button>

      <div className="absolute inset-x-0 bottom-0 p-5">
        <p className="text-[20px] font-semibold text-white drop-shadow-[0_1px_8px_rgba(0,0,0,.6)]">
          {community.name}
        </p>
        <p className="mt-0.5 text-[11px] text-white/65">{community.timezone}</p>
        <div className="mt-3 flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            {items.length > 0 ? <MemberAvatarStack members={items} /> : null}
            <span className="shrink-0 text-[11px] text-white/75">
              {members.isError ? '成员暂时无法读取' : members.isPending ? '正在读取成员…' : `${items.length} 位伙伴`}
            </span>
          </div>
          {active ? (
            <span className="shrink-0 rounded-full bg-accent-soft px-3 py-1.5 text-[11px] font-medium text-accent">
              当前所在
            </span>
          ) : (
            <span className="glass-soft flex shrink-0 items-center gap-1 rounded-full px-3 py-1.5 text-[11px] text-white/85 transition-colors group-hover:text-white">
              进入
              <ArrowRight className="size-3" strokeWidth={2.2} />
            </span>
          )}
        </div>
      </div>
    </article>
  );
}

/** 成员头像群。最多露出五个，其余以 +N 表示；身份键与消息配色保持同一形状。 */
function MemberAvatarStack({ members }: { readonly members: readonly PublicDisplay[] }) {
  const shown = members.slice(0, 5);
  const rest = members.length - shown.length;
  return (
    <div className="flex items-center">
      {shown.map((member) => {
        const key =
          member.actor.kind === 'system'
            ? `system:${member.actor.source_id}`
            : `${member.actor.kind}:${member.actor.actor_id}`;
        return (
          <span
            key={key}
            className="-ml-2 first:ml-0 rounded-full ring-2 ring-[rgba(18,13,26,.65)]"
          >
            <CharacterAvatar
              identity={key}
              name={member.display_name}
              imageUrl={resolveOfficialAvatar({
                avatarUrl: member.avatar_url,
                displayName: member.display_name,
              })}
              size="sm"
            />
          </span>
        );
      })}
      {rest > 0 ? (
        <span className="-ml-2 rounded-full bg-white/15 px-2 py-1 text-[10px] font-medium text-white ring-2 ring-[rgba(18,13,26,.65)]">
          +{rest}
        </span>
      ) : null}
    </div>
  );
}
