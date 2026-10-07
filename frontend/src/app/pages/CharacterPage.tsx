import { useState } from 'react';
import { Shell } from '@/components/Shell';
import { PageHeading, PrimaryButton } from '@/components/Page';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { EmptyState } from '@/components/EmptyState';
import { ErrorNotice } from '@/components/ErrorNotice';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import {
  useBlueprints, useCommunityCharacters, useCreateCharacter, useRetryCharacterMemory,
} from '@/api/directory';
import { canCharacterChat, characterStatusText, characterPreparationError } from '@/lib/characterReadiness';

/**
 * 角色。
 *
 * 当前提供模板创建与记忆准备管理，自定义人物创作界面另行接入。
 */
export function CharacterPage() {
  const { subject } = useCurrentSubject();
  const [picking, setPicking] = useState(false);

  const characters = useCommunityCharacters(subject.playerId, subject.communityId);
  const blueprints = useBlueprints();
  const create = useCreateCharacter();
  const retryMemory = useRetryCharacterMemory(subject.playerId, subject.communityId);

  const communityMissing = subject.communityId === null;
  const playerMissing = subject.playerId === '';

  return (
    <Shell section="subject" list={null}>
      <PageHeading
        title="角色"
        description="角色是社群里的对话对象。当前从人物模板创建，自定义人物创作界面尚未接入。"
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
        {retryMemory.isError ? <ErrorNotice error={retryMemory.error} /> : null}
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
                  <p className={'mt-1 text-[10px] ' + (canCharacterChat(character) ? 'text-ok' : 'text-content-faint')}>
                    {characterStatusText(character)}
                  </p>
                  {character.memory_status === 'failed' ? (
                    <div className="mt-2 text-xs">
                      <p className="break-words text-danger">
                        {characterPreparationError(character)}
                      </p>
                      {character.memory_error_code !== null ? (
                        <p className="mt-1 break-words text-content-faint">错误编号：{character.memory_error_code}</p>
                      ) : null}
                      <button
                        type="button"
                        disabled={retryMemory.isPending}
                        onClick={() => retryMemory.mutate(character.character_id)}
                        className="mt-1 rounded border border-border-subtle px-2 py-1 text-content disabled:opacity-50"
                      >
                        {retryMemory.isPending && retryMemory.variables === character.character_id ? '正在提交…' : '重新准备'}
                      </button>
                    </div>
                  ) : null}
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
 * 从服务端模板创建简单记忆模式的角色，作者创作流程保持独立。
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
              当前从人物模板创建，采用简单记忆模式。有作者材料时，准备完成后才能加入会话。
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
