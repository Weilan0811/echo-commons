import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Shell } from '@/components/Shell';
import { Field, PageHeading, PrimaryButton, SecondaryButton } from '@/components/Page';
import { ErrorNotice } from '@/components/ErrorNotice';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import {
  useCreateCommunity,
  useJoinedCommunities,
  useJoinCommunity,
} from '@/api/directory';

/**
 * 社群。
 *
 * 社群是一处角色与对话的容器。当前只有「创建」和「加入现有」两种进入方式：
 * 成员列表只有读取接口，加入由后端按玩家标识写入。
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
      <PageHeading
        title="社群"
        description="社群是一处角色与对话的容器。加入一个社群，或者建立一个新的。"
      />

      <div className="min-h-0 flex-1 overflow-y-auto px-8 py-7">
        <div className="grid max-w-4xl grid-cols-1 gap-8 lg:grid-cols-2">
          <section className="flex flex-col gap-3">
            <h2 className="text-[13px] font-semibold">已加入</h2>
            {joined.isError ? <ErrorNotice error={joined.error} /> : null}
            <div className="flex flex-col gap-1.5">
              {(joined.data?.items ?? []).map((community) => {
                const active = community.community_id === subject.communityId;
                return (
                  <button
                    key={community.community_id}
                    type="button"
                    onClick={() => {
                      enter(community.community_id, community.name);
                    }}
                    className={`flex items-center gap-3 rounded-card border px-4 py-3 text-left transition-colors ${
                      active
                        ? 'border-accent/50 bg-accent-soft'
                        : 'border-border-subtle hover:border-border-strong'
                    }`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{community.name}</span>
                      <span className="tabular block truncate text-[11px] text-content-faint">
                        {community.community_id} · {community.timezone}
                      </span>
                    </span>
                    {active ? (
                      <span className="shrink-0 text-[11px] text-accent">当前</span>
                    ) : null}
                  </button>
                );
              })}
              {needsIdentity ? (
                <p className="text-[12px] text-content-faint">先登记身份，才能查看已加入的社群。</p>
              ) : null}
              {!needsIdentity && joined.data !== undefined && joined.data.items.length === 0 ? (
                <p className="text-[12px] text-content-faint">还没有加入任何社群。</p>
              ) : null}
              {needsIdentity ? null : joined.isPending ? (
                <p className="text-[12px] text-content-faint">正在读取…</p>
              ) : null}
            </div>
          </section>

          <section className="flex flex-col gap-6">
            <div className="flex flex-col gap-3">
              <h2 className="text-[13px] font-semibold">建立社群</h2>
              <p className="text-[11px] leading-relaxed text-content-faint">
                创建者自动成为成员，创建后直接进入该社群。
              </p>
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
                  {create.isPending ? '创建中' : '创建社群'}
                </PrimaryButton>
              </div>
              {create.isError ? <ErrorNotice error={create.error} /> : null}
            </div>

            <div className="flex flex-col gap-3 border-t border-border-subtle pt-6">
              <h2 className="text-[13px] font-semibold">加入已有社群</h2>
              <p className="text-[11px] leading-relaxed text-content-faint">
                成员列表只有读取接口，加入由后端按玩家标识写入。
              </p>
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
                      .mutateAsync({ communityId: joinTarget.trim(), playerId: subject.playerId })
                      .then(() => {
                        setJoinTarget('');
                      })
                      .catch(() => {
                        // 错误在下方呈现。
                      });
                  }}
                  disabled={needsIdentity || joinTarget.trim() === '' || join.isPending}
                >
                  {join.isPending ? '加入中' : '加入社群'}
                </SecondaryButton>
              </div>
              {join.isError ? <ErrorNotice error={join.error} /> : null}
            </div>
          </section>
        </div>
      </div>
    </Shell>
  );
}