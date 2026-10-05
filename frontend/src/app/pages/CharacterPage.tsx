import { useState } from 'react';
import { Shell } from '@/components/Shell';
import { PageHeading, PrimaryButton } from '@/components/Page';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { EmptyState } from '@/components/EmptyState';
import { ErrorNotice } from '@/components/ErrorNotice';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { useBlueprints, useCommunityCharacters, useCreateCharacter } from '@/api/directory';

/**
 * 角色。
 *
 * 这一页现在是过渡状态。后端正在实现自定义角色系统：作者用少量文字创建
 * 可运行人物，人设分基础、过去故事与日常采访三层，创建后可以重置记忆
 * 重新初始化。届时本页整个替换为人物创建流程。
 *
 * 在那之前只提供从模板创建。刻意不做向导形状的空壳：点进去发现大半步骤
 * 不可用，比现在这个朴素的入口更让人困惑。
 */
export function CharacterPage() {
  const { subject } = useCurrentSubject();
  const [picking, setPicking] = useState(false);

  const characters = useCommunityCharacters(subject.playerId, subject.communityId);
  const blueprints = useBlueprints();
  const create = useCreateCharacter();

  const communityMissing = subject.communityId === null;
  const playerMissing = subject.playerId === '';

  return (
    <Shell section="subject" list={null}>
      <PageHeading
        title="角色"
        description="角色是社群里的对话对象。当前从人物模板创建，自定义人物正在实现中。"
        actions={
          <PrimaryButton
            onClick={() => {
              setPicking(true);
            }}
            disabled={playerMissing || communityMissing}
          >
            创建角色
          </PrimaryButton>
        }
      />

      <div className="min-h-0 flex-1 overflow-y-auto px-8 py-7">
        {playerMissing ? (
          <EmptyState title="先登记身份" description="身份决定读取范围，登记后才能看到角色。" />
        ) : null}

        {playerMissing || communityMissing ? null : characters.isError ? (
          <ErrorNotice error={characters.error} />
        ) : (
          <div className="grid max-w-5xl grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {(characters.data ?? []).map((character) => (
              <article
                key={character.character_id}
                className="flex items-center gap-3.5 rounded-card border border-border-subtle px-4 py-3.5"
              >
                <CharacterAvatar
                  identity={`character:${character.character_id}`}
                  name={character.display_name}
                  imageUrl={character.avatar_url}
                  size="lg"
                  glow
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold">{character.display_name}</p>
                  <p className="tabular truncate text-[11px] text-content-faint">
                    {character.blueprint_id} · v{character.blueprint_version}
                  </p>
                  <p className={'mt-1 text-[10px] ' + (character.availability_status === 'available' ? 'text-ok' : 'text-content-faint')}>
                    {character.availability_status === 'available' ? '可参与对话' : '暂不可用'}
                  </p>
                </div>
              </article>
            ))}

            {characters.data !== undefined && characters.data.length === 0 ? (
              <p className="text-[12px] text-content-faint">
                这个社群还没有角色。点右上角「创建角色」从模板开始。
              </p>
            ) : null}
          </div>
        )}
      </div>

      {picking ? (
        <TemplatePicker
          blueprints={blueprints.data ?? []}
          pending={create.isPending}
          error={create.isError ? create.error : null}
          onClose={() => {
            setPicking(false);
          }}
          onPick={(blueprintId) => {
            if (subject.communityId === null) return;
            void create
              .mutateAsync({
                communityId: subject.communityId,
                playerId: subject.playerId,
                blueprintId,
              })
              .then(() => {
                setPicking(false);
              })
              .catch(() => {
                // 错误在对话框内呈现，保持打开以便改选。
              });
          }}
        />
      ) : null}
    </Shell>
  );
}
/**
 * 模板选择。
 *
 * 只列出现有模板，不提供自定义选项：后端还没有这个能力，给一个点不动的
 * 入口不如不给。入口本身说明后续方向，让使用者知道这里将来会变成什么。
 */
function TemplatePicker({
  blueprints,
  pending,
  error,
  onClose,
  onPick,
}: {
  readonly blueprints: ReadonlyArray<{ readonly blueprint_id: string; readonly display_name: string }>;
  readonly pending: boolean;
  readonly error: unknown;
  readonly onClose: () => void;
  readonly onPick: (blueprintId: string) => void;
}) {
  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/60 p-6">
      <div className="flex max-h-[80vh] w-full max-w-lg flex-col overflow-hidden rounded-card border border-border-subtle bg-surface-raised">
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-border-subtle px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold">创建角色</h2>
            <p className="mt-1 text-[11px] leading-relaxed text-content-faint">
              当前只能从人物模板创建。作者用文字创建自定义人物的能力正在实现，
              届时这一页会替换为完整的创建流程。
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded px-1.5 py-0.5 text-[11px] text-content-faint hover:text-content"
          >
            关闭
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
          {blueprints.map((blueprint) => (
            <button
              key={blueprint.blueprint_id}
              type="button"
              disabled={pending}
              onClick={() => {
                onPick(blueprint.blueprint_id);
              }}
              className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-surface-overlay disabled:opacity-50"
            >
              <CharacterAvatar
                identity={'blueprint:' + blueprint.blueprint_id}
                name={blueprint.display_name}
                size="md"
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium">{blueprint.display_name}</span>
                <span className="tabular block truncate text-[11px] text-content-faint">
                  {blueprint.blueprint_id}
                </span>
              </span>
            </button>
          ))}

          {blueprints.length === 0 ? (
            <p className="px-3 py-4 text-[12px] text-content-faint">正在读取人物模板…</p>
          ) : null}
        </div>

        {error === null ? null : (
          <div className="shrink-0 px-5 pb-4">
            <ErrorNotice error={error} />
          </div>
        )}
      </div>
    </div>
  );
}