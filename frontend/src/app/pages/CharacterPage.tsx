import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { Shell } from '@/components/Shell';
import { PageHeading, PrimaryButton, SecondaryButton } from '@/components/Page';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { EmptyState } from '@/components/EmptyState';
import { ErrorNotice } from '@/components/ErrorNotice';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import {
  useBlueprints, useCommunityCharacters, useCreateCharacter, useRetryCharacterMemory,
} from '@/api/directory';
import {
  useCustomBlueprints,
  useDrafts,
  type AuthoringDraft,
  type BlueprintCard,
} from '@/api/authoring';
import { STAGE_LABEL, stageStatusLabel } from '@/lib/authoring';
import { canCharacterChat, characterStatusText, characterPreparationError } from '@/lib/characterReadiness';

/**
 * 角色。
 *
 * 页面分三个维度：当前社群里的实例、玩家私有的创作草稿、玩家已固定的自定义
 * 人物。草稿与人物跟随玩家身份，不需要先选择社群；入住社群才需要社群上下文。
 */
export function CharacterPage() {
  const { subject } = useCurrentSubject();
  const navigate = useNavigate();
  const [picking, setPicking] = useState(false);
  const [installing, setInstalling] = useState<BlueprintCard | null>(null);

  const characters = useCommunityCharacters(subject.playerId, subject.communityId);
  const blueprints = useBlueprints();
  const create = useCreateCharacter();
  const retryMemory = useRetryCharacterMemory(subject.playerId, subject.communityId);
  const drafts = useDrafts(subject.playerId);
  const customBlueprints = useCustomBlueprints(subject.playerId);

  const communityMissing = subject.communityId === null;
  const playerMissing = subject.playerId === '';
  const draftItems = useMemo(
    () => drafts.data?.pages.flatMap((page) => page.items) ?? [],
    [drafts.data],
  );
  const blueprintItems = useMemo(
    () => customBlueprints.data?.pages.flatMap((page) => page.items) ?? [],
    [customBlueprints.data],
  );

  return (
    <Shell section="subject" list={null}>
      <PageHeading
        title="角色"
        description="角色是社群里的对话对象。可以从人物模板直接创建，也可以在人物志里一步步创作属于自己的人物。"
        actions={
          <div className="flex gap-2">
            <SecondaryButton
              onClick={() => {
                setPicking(true);
              }}
              disabled={playerMissing || communityMissing}
            >
              从模板创建
            </SecondaryButton>
            <PrimaryButton
              onClick={() => {
                navigate('/app/characters/authoring/new');
              }}
              disabled={playerMissing}
            >
              创作自定义人物
            </PrimaryButton>
          </div>
        }
      />

      <div className="min-h-0 flex-1 space-y-8 overflow-y-auto px-8 py-7">
        {retryMemory.isError ? <ErrorNotice error={retryMemory.error} /> : null}
        {playerMissing ? (
          <EmptyState title="先登记身份" description="身份决定读取范围，登记后才能看到角色。" />
        ) : null}

        {!playerMissing ? (
          <section>
            <SectionHeading
              title={communityMissing ? '当前社群的角色' : '这个社群的角色'}
              hint={communityMissing ? '先选择一个社群' : undefined}
            />
            {communityMissing ? (
              <p className="text-[12px] text-content-faint">
                选择社群后查看这里的角色，或
                <Link to="/app/communities" className="text-accent hover:underline">去创建社群</Link>。
              </p>
            ) : characters.isError ? (
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
                    这个社群还没有角色。可以从模板创建，或把已经固定的自定义人物入住进来。
                  </p>
                ) : null}
              </div>
            )}
          </section>
        ) : null}

        {!playerMissing ? (
          <section>
            <SectionHeading title="我的人物志" hint="草稿跟随你的玩家身份，不绑定社群" />
            {drafts.isError ? (
              <ErrorNotice error={drafts.error} />
            ) : draftItems.length === 0 ? (
              <p className="text-[12px] text-content-faint">
                {drafts.isLoading ? '正在读取草稿…' : '还没有草稿。点右上角「创作自定义人物」，给一个名字就能开始。'}
              </p>
            ) : (
              <div className="grid max-w-5xl grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {draftItems.map((draft) => (
                  <DraftCard
                    key={draft.draft_id}
                    draft={draft}
                    onOpen={() => navigate(`/app/characters/authoring/${draft.draft_id}`)}
                  />
                ))}
              </div>
            )}
            {drafts.hasNextPage ? (
              <button
                type="button"
                disabled={drafts.isFetchingNextPage}
                onClick={() => {
                  void drafts.fetchNextPage();
                }}
                className="mt-3 text-[11px] text-content-faint hover:text-content disabled:opacity-50"
              >
                {drafts.isFetchingNextPage ? '读取中…' : '读取更多草稿'}
              </button>
            ) : null}
          </section>
        ) : null}

        {!playerMissing ? (
          <section>
            <SectionHeading title="我创作的人物" hint="固定后的人物资源，可以入住任意你所在的社群" />
            {customBlueprints.isError ? (
              <ErrorNotice error={customBlueprints.error} />
            ) : blueprintItems.length === 0 ? (
              <p className="text-[12px] text-content-faint">
                {customBlueprints.isLoading ? '正在读取…' : '草稿完成「定格」后，人物会出现在这里。'}
              </p>
            ) : (
              <div className="grid max-w-5xl grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {blueprintItems.map((blueprint) => (
                  <CustomBlueprintCard
                    key={blueprint.blueprint_id}
                    blueprint={blueprint}
                    canInstall={!communityMissing}
                    onOpen={() => navigate(`/app/characters/authoring/${blueprint.source_draft_id}`)}
                    onInstall={() => setInstalling(blueprint)}
                  />
                ))}
              </div>
            )}
            {customBlueprints.hasNextPage ? (
              <button
                type="button"
                disabled={customBlueprints.isFetchingNextPage}
                onClick={() => {
                  void customBlueprints.fetchNextPage();
                }}
                className="mt-3 text-[11px] text-content-faint hover:text-content disabled:opacity-50"
              >
                {customBlueprints.isFetchingNextPage ? '读取中…' : '读取更多人物'}
              </button>
            ) : null}
          </section>
        ) : null}
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

      {installing !== null ? (
        <InstallModal
          blueprint={installing}
          playerId={subject.playerId}
          onClose={() => setInstalling(null)}
        />
      ) : null}
    </Shell>
  );
}

function SectionHeading({ title, hint }: { readonly title: string; readonly hint?: string | undefined }) {
  return (
    <div className="mb-3 flex items-baseline gap-3">
      <h2 className="text-[13px] font-semibold text-content">{title}</h2>
      {hint !== undefined ? <span className="text-[11px] text-content-faint">{hint}</span> : null}
    </div>
  );
}

/** 草稿卡片：整卡可点回向导；状态行同时呈现创作进度与固定结果。 */
function DraftCard({
  draft,
  onOpen,
}: {
  readonly draft: AuthoringDraft;
  readonly onOpen: () => void;
}) {
  const finalized = draft.status === 'confirmed' || draft.confirmed_blueprint_id !== null;
  const stages = ['basic', 'story', 'interview'] as const;

  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex items-center gap-3 rounded-card border border-border-subtle px-4 py-3.5 text-left transition-colors hover:border-accent/50 hover:bg-surface-overlay/40"
    >
      <CharacterAvatar
        identity={`draft:${draft.draft_id}`}
        name={draft.content.display_name}
        imageUrl={draft.content.avatar_url ?? null}
        size="lg"
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-semibold">{draft.content.display_name}</p>
          <span
            className={
              'shrink-0 rounded px-1.5 py-0.5 text-[10px] '
              + (finalized ? 'bg-ok/15 text-ok' : 'bg-accent-soft text-accent')
            }
          >
            {finalized ? '已固定' : '创作中'}
          </span>
        </div>
        <p className="mt-1.5 flex flex-wrap gap-x-2.5 gap-y-0.5 text-[10px]">
          {stages.map((stage) => {
            const status = draft.workflow[stage];
            return (
              <span
                key={stage}
                className={
                  status === 'accepted'
                    ? 'text-ok'
                    : status === 'review_required'
                      ? 'text-warn'
                      : 'text-content-faint'
                }
              >
                {STAGE_LABEL[stage]}·{stageStatusLabel(status)}
              </span>
            );
          })}
        </p>
        <p className="mt-1 text-[10px] text-content-faint">
          {finalized ? '打开查看与入住社群' : '继续创作'}
        </p>
      </div>
    </button>
  );
}

/** 已固定人物卡片：打开回看材料，或直接入住当前社群。 */
function CustomBlueprintCard({
  blueprint,
  canInstall,
  onOpen,
  onInstall,
}: {
  readonly blueprint: BlueprintCard;
  readonly canInstall: boolean;
  readonly onOpen: () => void;
  readonly onInstall: () => void;
}) {
  return (
    <article className="flex items-center gap-3 rounded-card border border-border-subtle px-4 py-3.5">
      <CharacterAvatar
        identity={`blueprint:${blueprint.blueprint_id}`}
        name={blueprint.display_name}
        imageUrl={blueprint.avatar_url ?? null}
        size="lg"
        glow
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold">{blueprint.display_name}</p>
        <p className="tabular truncate text-[10px] text-content-faint">
          {blueprint.blueprint_id} · v{blueprint.content_version}
        </p>
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={onOpen}
            className="rounded border border-border-subtle px-2 py-0.5 text-[11px] text-content-muted hover:border-border-strong hover:text-content"
          >
            查看
          </button>
          <button
            type="button"
            onClick={onInstall}
            disabled={!canInstall}
            title={canInstall ? undefined : '先选择一个社群'}
            className="rounded border border-accent/50 bg-accent-soft px-2 py-0.5 text-[11px] text-accent hover:bg-accent/20 disabled:opacity-40"
          >
            入住社群
          </button>
        </div>
      </div>
    </article>
  );
}

/**
 * 入住模式选择。
 *
 * 与人物志终章的 InstancePanel 保持同样的模式说明；这里只负责发起创建，
 * 准备状态与失败重试回到角色网格处理，避免两处重复一套状态界面。
 */
function InstallModal({
  blueprint,
  playerId,
  onClose,
}: {
  readonly blueprint: BlueprintCard;
  readonly playerId: string;
  readonly onClose: () => void;
}) {
  const { subject } = useCurrentSubject();
  const create = useCreateCharacter();
  const [mode, setMode] = useState<'simple' | 'full'>('simple');

  const submit = () => {
    if (subject.communityId === null) return;
    void create
      .mutateAsync({
        communityId: subject.communityId,
        playerId,
        blueprintId: blueprint.blueprint_id,
        memoryMode: mode,
      })
      .then(() => {
        onClose();
      })
      .catch(() => undefined);
  };

  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/60 p-6">
      <div className="w-full max-w-lg rounded-card border border-border-subtle bg-surface-raised p-5">
        <header className="flex items-start gap-3">
          <CharacterAvatar
            identity={`blueprint:${blueprint.blueprint_id}`}
            name={blueprint.display_name}
            imageUrl={blueprint.avatar_url ?? null}
            size="md"
          />
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold">让 {blueprint.display_name} 入住当前社群</h2>
            <p className="mt-1 text-[11px] leading-relaxed text-content-faint">
              入住后同社群其他成员都可以与 TA 交流。选择运行模式：
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

        <div className="mt-4 grid gap-2.5 sm:grid-cols-2">
          <InstallModeCard
            active={mode === 'simple'}
            title="简单模式"
            caption="原文分块检索即可聊天，准备更快。"
            recommended
            onClick={() => setMode('simple')}
          />
          <InstallModeCard
            active={mode === 'full'}
            title="完整模式"
            caption="先把材料整理成长期记忆，准备更久，也可能需要模型额度。"
            onClick={() => setMode('full')}
          />
        </div>
        <p className="mt-2 text-[10px] text-warn">运行模式在创建后不可切换。</p>

        {blueprint.material_processing === 'stored_only' ? (
          <p className="mt-3 rounded-lg border border-border-subtle bg-surface-sunken/60 px-3 py-2 text-[11px] leading-relaxed text-content-faint">
            人物原文材料已保存，记忆准备会在后台进行；准备完成前 TA 还不能加入会话。
          </p>
        ) : null}

        {create.isError ? (
          <div className="mt-3"><ErrorNotice error={create.error} /></div>
        ) : null}

        <div className="mt-4 flex justify-end">
          <button
            type="button"
            disabled={create.isPending}
            onClick={submit}
            className="rounded-lg bg-accent px-4 py-1.5 text-[12px] font-semibold text-accent-ink hover:brightness-110 disabled:opacity-40"
          >
            {create.isPending ? '入住中…' : `以${mode === 'simple' ? '简单' : '完整'}模式入住`}
          </button>
        </div>
      </div>
    </div>
  );
}

function InstallModeCard({
  active,
  title,
  caption,
  recommended,
  onClick,
}: {
  readonly active: boolean;
  readonly title: string;
  readonly caption: string;
  readonly recommended?: boolean;
  readonly onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-lg border p-3 text-left transition-colors ${
        active
          ? 'border-accent bg-accent-soft/60 ring-1 ring-accent/40'
          : 'border-border-subtle bg-surface-sunken/50 hover:border-accent/40'
      }`}
    >
      <span className="flex items-center gap-2 text-[13px] font-semibold">
        {title}
        {recommended ? (
          <span className="rounded bg-accent/20 px-1.5 py-0.5 text-[10px] font-medium text-accent">默认</span>
        ) : null}
      </span>
      <span className="mt-1 block text-[11px] leading-relaxed text-content-faint">{caption}</span>
    </button>
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
            <h2 className="text-sm font-semibold">从模板创建角色</h2>
            <p className="mt-1 text-[11px] leading-relaxed text-content-faint">
              采用简单记忆模式。有作者材料时，准备完成后才能加入会话。
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
