import { useState } from 'react';
import { useNavigate } from 'react-router';
import { ArrowRight, Compass, Sparkles } from 'lucide-react';
import { Shell } from '@/components/Shell';
import { Field, PrimaryButton, SecondaryButton } from '@/components/Page';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { ErrorNotice } from '@/components/ErrorNotice';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import {
  useCommunityMembers,
  useCreateCommunity,
  useJoinedCommunities,
  useJoinCommunity,
  type CommunityCard,
  type PublicDisplay,
} from '@/api/directory';
import { resolveCover } from '@/lib/coverPresets';
import { resolveOfficialAvatar } from '@/lib/officialCharacters';
import { accentColor } from '@/lib/characterColor';

type Community = CommunityCard;

/**
 * 社群。
 *
 * 叙事上这里是「选择进入哪个世界」：已加入的社群以横向场景卡呈现（预设
 * 封面或按标识派生的程序化渐变），创建是「开辟新天地」，加入是「前往
 * 朋友的世界」。成员列表只有读取接口，加入由后端按玩家标识写入。
 */
export function CommunityPage() {
  const { subject, set } = useCurrentSubject();
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [newId, setNewId] = useState('');
  const [joinTarget, setJoinTarget] = useState('');

  const joined = useJoinedCommunities(subject.playerId);
  const create = useCreateCommunity();
  const join = useJoinCommunity();

  const enter = (communityId: string, communityName: string) => {
    set({
      playerId: subject.playerId,
      playerDisplayName: subject.playerDisplayName,
      communityId,
      communityName,
    });
    void navigate('/app/chat');
  };

  const needsIdentity = subject.playerId === '';

  return (
    <Shell section="subject" list={null}>
      <div className="animate-rise-in flex h-full flex-col">
        <header className="shrink-0 px-4 pt-6 sm:px-9 sm:pt-8 pb-6">
          <h1 className="display-title text-[28px]">社群</h1>
          <p className="mt-1.5 text-[13px] text-content-faint">
            走进一个世界，和住在里面的灵魂一起生活。
          </p>
        </header>

        <div className="min-h-0 flex-1 space-y-10 overflow-y-auto px-4 pb-10 sm:px-9">
          <section>
            <SectionHeading
              title="常去的地方"
              hint={needsIdentity ? '先登记身份' : undefined}
            />
            {joined.isError ? <ErrorNotice error={joined.error} /> : null}
            {needsIdentity ? (
              <p className="text-[12px] text-content-faint">
                先登记身份，才能查看已加入的社群。
              </p>
            ) : joined.isPending ? (
              <p className="text-[12px] text-content-faint">正在读取…</p>
            ) : joined.data !== undefined && joined.data.items.length === 0 ? (
              <p className="text-[12px] text-content-faint">
                还没有常去的地方。在下方开辟一个新世界，或前往朋友邀请你的世界。
              </p>
            ) : null}
            {!needsIdentity && joined.data !== undefined && joined.data.items.length > 0 ? (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-3">
                {joined.data.items.map((community, index) => (
                  <CommunitySceneCard
                    key={community.community_id}
                    community={community}
                    playerId={subject.playerId}
                    active={community.community_id === subject.communityId}
                    appearDelay={Math.min(index, 7) * 45}
                    onEnter={() => {
                      enter(community.community_id, community.name);
                    }}
                  />
                ))}
              </div>
            ) : null}
          </section>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <section className="glass-soft rounded-card p-6">
              <div className="mb-5 flex items-center gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
                  <Sparkles className="size-4.5" strokeWidth={2} />
                </span>
                <div>
                  <h2 className="text-[15px] font-semibold">开辟新天地</h2>
                  <p className="mt-0.5 text-[11px] text-content-faint">
                    创建者自动成为成员，创建后直接进入该社群。
                  </p>
                </div>
              </div>
              <div className="flex flex-col gap-4">
                <Field label="名称" value={name} onChange={setName} placeholder="深夜食堂" />
                <Field
                  label="标识"
                  hint="可留空，由后端生成。"
                  value={newId}
                  onChange={setNewId}
                  placeholder="night-diner"
                />
                <div>
                  <PrimaryButton
                    onClick={() => {
                      void create
                        .mutateAsync({
                          playerId: subject.playerId,
                          name: name.trim(),
                          communityId: newId.trim() === '' ? null : newId.trim(),
                          timezone: 'UTC',
                        })
                        .then((created) => {
                          enter(created.community_id, created.name);
                        })
                        .catch(() => {
                          // 错误在下方呈现，输入内容保持不变以便修改后重试。
                        });
                    }}
                    disabled={needsIdentity || name.trim() === '' || create.isPending}
                  >
                    {create.isPending ? '创建中' : '开辟世界'}
                  </PrimaryButton>
                </div>
                {create.isError ? <ErrorNotice error={create.error} /> : null}
              </div>
            </section>

            <section className="glass-soft rounded-card p-6">
              <div className="mb-5 flex items-center gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
                  <Compass className="size-4.5" strokeWidth={2} />
                </span>
                <div>
                  <h2 className="text-[15px] font-semibold">前往朋友的世界</h2>
                  <p className="mt-0.5 text-[11px] text-content-faint">
                    成员列表只有读取接口，加入由后端按玩家标识写入。
                  </p>
                </div>
              </div>
              <div className="flex flex-col gap-4">
                <Field
                  label="社群标识"
                  value={joinTarget}
                  onChange={setJoinTarget}
                  placeholder="night-diner"
                />
                <div>
                  <SecondaryButton
                    onClick={() => {
                      void join
                        .mutateAsync({
                          communityId: joinTarget.trim(),
                          playerId: subject.playerId,
                        })
                        .then(() => {
                          setJoinTarget('');
                        })
                        .catch(() => {
                          // 错误在下方呈现。
                        });
                    }}
                    disabled={needsIdentity || joinTarget.trim() === '' || join.isPending}
                  >
                    {join.isPending ? '加入中' : '前往这个世界'}
                  </SecondaryButton>
                </div>
                {join.isError ? <ErrorNotice error={join.error} /> : null}
              </div>
            </section>
          </div>
        </div>
      </div>
    </Shell>
  );
}

function SectionHeading({ title, hint }: { readonly title: string; readonly hint?: string | undefined }) {
  return (
    <div className="mb-3.5 flex items-baseline gap-3">
      <h2 className="text-[14px] font-semibold">{title}</h2>
      {hint !== undefined ? <span className="text-[11px] text-content-faint">{hint}</span> : null}
    </div>
  );
}

/**
 * 社群场景卡。整张卡就是入口：封面横幅、成员头像群与进入动作。
 * 封面在后端字段落地前由前端映射（见 coverPresets），无命中时用派生色
 * 程序化渐变兜底，不放置任何虚构的社群数据。
 */
function CommunitySceneCard({
  community,
  playerId,
  active,
  appearDelay,
  onEnter,
}: {
  readonly community: Community;
  readonly playerId: string;
  readonly active: boolean;
  readonly appearDelay: number;
  readonly onEnter: () => void;
}) {
  const members = useCommunityMembers(playerId, community.community_id);
  const items = members.data?.items ?? [];
  const cover = resolveCover(community.community_id, community.name);
  const hue = accentColor(`community:${community.community_id}`);

  return (
    <button
      type="button"
      onClick={onEnter}
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

      <div className="absolute inset-x-0 bottom-0 p-5">
        <p className="text-[20px] font-semibold text-white drop-shadow-[0_1px_8px_rgba(0,0,0,.6)]">
          {community.name}
        </p>
        <p className="mt-0.5 text-[11px] text-white/65">
          {community.community_id} · {community.timezone}
        </p>
        <div className="mt-3 flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            {items.length > 0 ? <MemberAvatarStack members={items} /> : null}
            <span className="shrink-0 text-[11px] text-white/75">
              {items.length > 0 ? `${items.length} 位伙伴` : '成员读取中…'}
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
    </button>
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
