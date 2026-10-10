import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import * as Dialog from '@radix-ui/react-dialog';
import { MessageCircle, Plus, RefreshCw, Search, X } from 'lucide-react';
import { Shell } from '@/components/Shell';
import { PrimaryButton } from '@/components/Page';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { PaperSheet } from '@/components/PaperSheet';
import { EmptyState } from '@/components/EmptyState';
import { ErrorNotice } from '@/components/ErrorNotice';
import { pickAvatarFrame } from '@/components/avatarFrames';
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
import { resolveOfficialAvatar, resolveOfficialIllustration } from '@/lib/officialCharacters';
import { accentColor } from '@/lib/characterColor';
import type { SchemaOf } from '@/api/http';

type CommunityCharacter = SchemaOf<'CharacterView'>;

/**
 * 角色图鉴。
 *
 * 页面分三个维度：当前社群里的实例（大角色卡）、玩家私有的创作草稿、玩家已
 * 固定的自定义人物。技术编号与准备状态收进选中后的信纸档案抽屉，卡面只留
 * 名字与真实可用状态，不摆放无数据来源的标签、亲密度或记忆片段。
 */
export function CharacterPage() {
  const { subject } = useCurrentSubject();
  const navigate = useNavigate();
  const [picking, setPicking] = useState(false);
  const [installing, setInstalling] = useState<BlueprintCard | null>(null);
  const [openedId, setOpenedId] = useState<string | null>(null);
  const [keyword, setKeyword] = useState('');

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
  const match = (name: string) => keyword.trim() === '' || name.includes(keyword.trim());
  const openedCharacter = useMemo(
    () => (characters.data ?? []).find((item) => item.character_id === openedId) ?? null,
    [characters.data, openedId],
  );

  return (
    <Shell section="subject" list={null}>
      <div className="animate-rise-in flex h-full flex-col">
        <header className="flex shrink-0 flex-wrap items-end justify-between gap-4 px-4 pb-6 pt-6 sm:px-9 sm:pt-8">
          <div>
            <h1 className="display-title text-[28px]">角色图鉴</h1>
            <p className="mt-1.5 text-[13px] text-content-faint">
              在这里，遇见与你共同生活的灵魂。
            </p>
          </div>
          <div className="flex items-center gap-2.5">
            <div className="glass-soft flex items-center gap-2 rounded-full px-3.5 py-2">
              <Search className="size-3.5 text-content-faint" strokeWidth={2} />
              <input
                value={keyword}
                onChange={(event) => {
                  setKeyword(event.target.value);
                }}
                placeholder="搜索角色名…"
                className="w-36 bg-transparent text-[12px] text-content outline-none placeholder:text-content-faint"
              />
            </div>
            <button
              type="button"
              onClick={() => {
                setPicking(true);
              }}
              disabled={playerMissing || communityMissing}
              className="glass-soft rounded-full px-4 py-2 text-[12px] text-content-muted transition-colors hover:text-content disabled:opacity-40"
            >
              从模板创建
            </button>
            <PrimaryButton
              onClick={() => {
                navigate('/app/characters/authoring/new');
              }}
              disabled={playerMissing}
            >
              创作自定义人物
            </PrimaryButton>
          </div>
        </header>

        <div className="min-h-0 flex-1 space-y-9 overflow-y-auto px-4 pb-10 sm:px-9">
          {retryMemory.isError ? <ErrorNotice error={retryMemory.error} /> : null}
          {playerMissing ? (
            <EmptyState title="先登记身份" description="身份决定读取范围，登记后才能看到角色。" />
          ) : null}

          {!playerMissing ? (
            <section>
              <SectionHeading
                title="这个社群的角色"
                hint={communityMissing ? '先选择一个社群' : undefined}
              />
              {communityMissing ? (
                <p className="text-[12px] text-content-faint">
                  选择社群后查看这里的角色，或
                  <Link to="/app/communities" className="text-accent hover:underline">
                    去创建社群
                  </Link>
                  。
                </p>
              ) : characters.isError ? (
                <ErrorNotice error={characters.error} />
              ) : (
                <GalleryGrid
                  characters={(characters.data ?? []).filter((item) =>
                    match(item.display_name),
                  )}
                  onOpen={(id) => {
                    setOpenedId(id);
                  }}
                />
              )}
            </section>
          ) : null}

          {!playerMissing && draftItems.some((draft) => match(draft.content.display_name)) ? (
            <section>
              <SectionHeading title="我的人物志" hint="草稿跟随你的玩家身份，不绑定社群" />
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {draftItems
                  .filter((draft) => match(draft.content.display_name))
                  .map((draft) => (
                    <DraftCard
                      key={draft.draft_id}
                      draft={draft}
                      onOpen={() => navigate(`/app/characters/authoring/${draft.draft_id}`)}
                    />
                  ))}
              </div>
              {drafts.hasNextPage ? (
                <LoadMoreButton
                  onClick={() => {
                    void drafts.fetchNextPage();
                  }}
                  loading={drafts.isFetchingNextPage}
                  label="读取更多草稿"
                />
              ) : null}
            </section>
          ) : null}

          {!playerMissing && blueprintItems.some((item) => match(item.display_name)) ? (
            <section>
              <SectionHeading title="我创作的人物" hint="固定后的人物资源，可以入住任意你所在的社群" />
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {blueprintItems
                  .filter((item) => match(item.display_name))
                  .map((blueprint) => (
                    <CustomBlueprintCard
                      key={blueprint.blueprint_id}
                      blueprint={blueprint}
                      canInstall={!communityMissing}
                      onOpen={() => navigate(`/app/characters/authoring/${blueprint.source_draft_id}`)}
                      onInstall={() => setInstalling(blueprint)}
                    />
                  ))}
              </div>
              {customBlueprints.hasNextPage ? (
                <LoadMoreButton
                  onClick={() => {
                    void customBlueprints.fetchNextPage();
                  }}
                  loading={customBlueprints.isFetchingNextPage}
                  label="读取更多人物"
                />
              ) : null}
            </section>
          ) : null}
        </div>
      </div>

      {openedCharacter !== null ? (
        <CharacterFileDrawer
          character={openedCharacter}
          canRetry={!retryMemory.isPending}
          retrying={retryMemory.isPending && retryMemory.variables === openedCharacter.character_id}
          onClose={() => setOpenedId(null)}
          onRetry={() => retryMemory.mutate(openedCharacter.character_id)}
          onChat={() => {
            navigate('/app/chat', {
              state: { inviteCharacterId: openedCharacter.character_id },
            });
          }}
        />
      ) : null}

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
    <div className="mb-3.5 flex items-baseline gap-3">
      <h2 className="text-[14px] font-semibold">{title}</h2>
      {hint !== undefined ? <span className="text-[11px] text-content-faint">{hint}</span> : null}
    </div>
  );
}

function LoadMoreButton({
  onClick,
  loading,
  label,
}: {
  readonly onClick: () => void;
  readonly loading: boolean;
  readonly label: string;
}) {
  return (
    <button
      type="button"
      disabled={loading}
      onClick={onClick}
      className="glass-soft mt-3 rounded-full px-3.5 py-1.5 text-[11px] text-content-faint transition-colors hover:text-content disabled:opacity-50"
    >
      {loading ? '读取中…' : label}
    </button>
  );
}

/**
 * 社群角色大卡。
 *
 * 官方蓝图角色用竖版插画铺满卡面；无插画的自定义角色用角色派生色氛围光加
 * 装饰母题兜底。卡面只承担「认出 TA、知道能不能聊」，其余进档案抽屉。
 */
function GalleryGrid({
  characters,
  onOpen,
}: {
  readonly characters: readonly CommunityCharacter[];
  readonly onOpen: (characterId: string) => void;
}) {
  if (characters.length === 0) {
    return (
      <p className="text-[12px] text-content-faint">
        这个社群还没有角色。可以从模板创建，或把已经固定的自定义人物入住进来。
      </p>
    );
  }
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 2xl:grid-cols-3">
      {characters.map((character, index) => (
        <GalleryCharacterCard
          key={character.character_id}
          character={character}
          appearDelay={Math.min(index, 7) * 45}
          onOpen={() => onOpen(character.character_id)}
        />
      ))}
    </div>
  );
}

function GalleryCharacterCard({
  character,
  appearDelay,
  onOpen,
}: {
  readonly character: CommunityCharacter;
  readonly appearDelay: number;
  readonly onOpen: () => void;
}) {
  const identity = `character:${character.character_id}`;
  const ready = canCharacterChat(character);
  const illustration = resolveOfficialIllustration({
    blueprintId: character.blueprint_id,
    displayName: character.display_name,
  });
  const frame = pickAvatarFrame(identity);
  const Frame = frame.Component;

  return (
    <button
      type="button"
      onClick={onOpen}
      style={{ animationDelay: `${appearDelay}ms` }}
      className="animate-rise-in group relative aspect-[4/3] overflow-hidden rounded-card border border-border-subtle text-left transition-[transform,border-color,box-shadow] duration-300 hover:-translate-y-0.5 hover:border-accent/40 hover:shadow-[0_18px_40px_-18px_rgba(10,7,16,.8)]"
    >
      {illustration !== null ? (
        <img
          src={illustration}
          alt=""
          className="absolute inset-0 h-full w-full object-cover object-top transition-transform duration-500 group-hover:scale-[1.035]"
        />
      ) : (
        <div
          className="absolute inset-0"
          style={{
            color: accentColor(identity),
            background: `radial-gradient(circle at 50% 30%, color-mix(in oklch, ${accentColor(identity)} 38%, transparent), transparent 72%), linear-gradient(160deg, var(--color-surface-overlay), var(--color-surface-sunken))`,
          }}
        >
          <Frame className="absolute inset-0 size-full p-12 opacity-70" />
        </div>
      )}
      <div className="absolute inset-0 bg-gradient-to-t from-black/82 via-black/15 to-transparent" />
      <div className="absolute inset-x-0 bottom-0 p-4">
        <p className="text-[17px] font-semibold text-white drop-shadow-[0_1px_8px_rgba(0,0,0,.6)]">
          {character.display_name}
        </p>
        <p className="mt-1 flex items-center gap-1.5 text-[11px] text-white/75">
          <span
            className={`inline-block size-1.5 rounded-full ${ready ? 'bg-ok' : 'bg-warn animate-breathe'}`}
            aria-hidden="true"
          />
          {characterStatusText(character)}
        </p>
      </div>
    </button>
  );
}

/**
 * 信纸人物档案抽屉。
 *
 * 只放真实字段：状态、来源蓝图与版本、记忆模式、入住时间、准备失败信息。
 * 关系、记忆片段等后端能力不存在的区块直接不出现。
 */
function CharacterFileDrawer({
  character,
  canRetry,
  retrying,
  onClose,
  onRetry,
  onChat,
}: {
  readonly character: CommunityCharacter;
  readonly canRetry: boolean;
  readonly retrying: boolean;
  readonly onClose: () => void;
  readonly onRetry: () => void;
  readonly onChat: () => void;
}) {
  const identity = `character:${character.character_id}`;
  const ready = canCharacterChat(character);
  const illustration = resolveOfficialIllustration({
    blueprintId: character.blueprint_id,
    displayName: character.display_name,
  });
  const avatar = resolveOfficialAvatar({
    avatarUrl: character.avatar_url,
    blueprintId: character.blueprint_id,
    displayName: character.display_name,
  });
  const frame = pickAvatarFrame(identity);
  const Frame = frame.Component;
  const failed = character.memory_status === 'failed';

  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="animate-fade-in fixed inset-0 z-40 bg-black/55 backdrop-blur-[2px]" />
        <Dialog.Content
          className="animate-drawer-in fixed inset-y-0 right-0 z-50 w-full max-w-[440px] outline-none"
          aria-describedby={undefined}
        >
          <PaperSheet className="flex h-full flex-col rounded-r-none border-r-0">
            <div className="relative h-60 shrink-0 overflow-hidden">
              {illustration !== null ? (
                <img src={illustration} alt="" className="h-full w-full object-cover object-top" />
              ) : (
                <div
                  className="flex h-full items-center justify-center"
                  style={{
                    color: accentColor(identity),
                    background: `radial-gradient(circle at 50% 32%, color-mix(in oklch, ${accentColor(identity)} 36%, transparent), transparent 72%), linear-gradient(160deg, var(--color-surface-overlay), var(--color-surface-sunken))`,
                  }}
                >
                  <Frame className="absolute inset-0 size-full p-16 opacity-60" />
                  {avatar !== null ? (
                    <img
                      src={avatar}
                      alt=""
                      className="relative size-24 rounded-full object-cover shadow-2xl"
                    />
                  ) : null}
                </div>
              )}
              <div className="absolute inset-0 bg-gradient-to-t from-[rgba(60,42,24,.28)] to-transparent" />
              {/* 手撕纸边衔接图与信纸 */}
              <img
                src="/assets/decorations/torn-paper-edge.svg"
                alt=""
                className="absolute inset-x-0 bottom-[-1px] h-5 w-full"
              />
              <Dialog.Close asChild>
                <button
                  type="button"
                  className="absolute right-3 top-3 flex size-8 items-center justify-center rounded-full bg-black/35 text-white/85 backdrop-blur-sm transition-colors hover:bg-black/55 hover:text-white"
                  aria-label="关闭档案"
                >
                  <X className="size-4" strokeWidth={2} />
                </button>
              </Dialog.Close>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-8 pb-4 pt-5">
              <Dialog.Title className="flex items-center gap-2">
                <img
                  src="/assets/decorations/quill.svg"
                  alt=""
                  className="size-5 opacity-60"
                  style={{ color: 'var(--color-ink-muted)' }}
                />
                <span className="display-title text-[26px]">{character.display_name}</span>
              </Dialog.Title>
              <p className="mt-2 flex items-center gap-2 text-[12px] text-ink-muted">
                <span
                  className={`inline-block size-2 rounded-full ${ready ? 'bg-ok' : 'bg-warn'}`}
                  aria-hidden="true"
                />
                {ready ? '可以聊聊' : characterStatusText(character)}
              </p>

              {failed ? (
                <div className="mt-5 rounded-lg border border-danger/30 bg-danger/8 px-3.5 py-3">
                  <p className="break-words text-[12px] text-danger">
                    {characterPreparationError(character)}
                  </p>
                  {character.memory_error_code !== null ? (
                    <p className="mt-1 break-words text-[11px] text-ink-faint">
                      错误编号：{character.memory_error_code}
                    </p>
                  ) : null}
                  <button
                    type="button"
                    disabled={!canRetry}
                    onClick={onRetry}
                    className="mt-2.5 inline-flex items-center gap-1.5 rounded-full border border-ink/20 px-3 py-1.5 text-[12px] text-ink transition-colors hover:bg-ink/5 disabled:opacity-50"
                  >
                    <RefreshCw className={`size-3.5 ${retrying ? 'animate-spin' : ''}`} strokeWidth={1.8} />
                    {retrying ? '正在重新准备…' : '重新准备'}
                  </button>
                </div>
              ) : null}

              <h3 className="mt-7 text-[12px] font-semibold tracking-[0.18em] text-ink-faint">
                人物档案
              </h3>
              <dl className="mt-3 divide-y divide-ink/10 border-y border-ink/10 text-[13px]">
                <ArchiveRow label="来源" value={`${character.blueprint_id} · v${character.blueprint_version}`} />
                <ArchiveRow
                  label="记忆方式"
                  value={character.memory_mode === 'full' ? '完整记忆' : '简单记忆'}
                />
                <ArchiveRow
                  label="准备阶段"
                  value={character.memory_phase ?? character.memory_status}
                />
                <ArchiveRow label="入住时间" value={formatDate(character.created_at_utc)} />
              </dl>
            </div>

            <div className="shrink-0 border-t border-ink/10 px-8 py-5">
              <button
                type="button"
                disabled={!ready}
                onClick={onChat}
                className="flex w-full items-center justify-center gap-2 rounded-full bg-accent py-3 text-[14px] font-semibold text-accent-ink transition-[filter,opacity] hover:brightness-110 disabled:opacity-40"
              >
                <MessageCircle className="size-4" strokeWidth={2} />
                {ready ? '开始聊天' : '还不能聊天'}
              </button>
            </div>
          </PaperSheet>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ArchiveRow({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2.5">
      <dt className="shrink-0 text-[12px] text-ink-faint">{label}</dt>
      <dd className="tabular min-w-0 break-words text-right text-[12.5px] text-ink">{value}</dd>
    </div>
  );
}

function formatDate(isoUtc: string): string {
  const parsed = new Date(isoUtc);
  if (Number.isNaN(parsed.getTime())) return '';
  return `${parsed.getFullYear()}/${parsed.getMonth() + 1}/${parsed.getDate()}`;
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
      className="glass-panel flex items-center gap-3.5 rounded-card px-4 py-3.5 text-left transition-colors hover:border-accent/40"
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
              'shrink-0 rounded-full px-2 py-0.5 text-[10px] '
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
    <article className="glass-panel flex items-center gap-3 rounded-card px-4 py-3.5">
      <CharacterAvatar
        identity={`blueprint:${blueprint.blueprint_id}`}
        name={blueprint.display_name}
        imageUrl={resolveOfficialAvatar({
          avatarUrl: blueprint.avatar_url,
          blueprintId: blueprint.blueprint_id,
          displayName: blueprint.display_name,
        })}
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
            className="rounded-full border border-border-subtle px-3 py-1 text-[11px] text-content-muted transition-colors hover:border-border-strong hover:text-content"
          >
            查看
          </button>
          <button
            type="button"
            onClick={onInstall}
            disabled={!canInstall}
            title={canInstall ? undefined : '先选择一个社群'}
            className="rounded-full border border-accent/50 bg-accent-soft px-3 py-1 text-[11px] text-accent transition-colors hover:bg-accent/20 disabled:opacity-40"
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
 * 准备状态与失败重试回到角色图鉴处理，避免两处重复一套状态界面。
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
    <div className="animate-fade-in fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-6 backdrop-blur-[2px]">
      <div className="glass-panel animate-rise-in w-full max-w-lg rounded-card p-6">
        <header className="flex items-start gap-3">
          <CharacterAvatar
            identity={`blueprint:${blueprint.blueprint_id}`}
            name={blueprint.display_name}
            imageUrl={resolveOfficialAvatar({
              avatarUrl: blueprint.avatar_url,
              blueprintId: blueprint.blueprint_id,
              displayName: blueprint.display_name,
            })}
            size="md"
          />
          <div className="min-w-0 flex-1">
            <h2 className="text-[15px] font-semibold">让 {blueprint.display_name} 入住当前社群</h2>
            <p className="mt-1 text-[11px] leading-relaxed text-content-faint">
              入住后同社群其他成员都可以与 TA 交流。选择运行模式：
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-full px-2 py-0.5 text-[11px] text-content-faint transition-colors hover:bg-white/8 hover:text-content"
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
          <p className="mt-3 rounded-xl border border-border-subtle bg-white/5 px-3 py-2 text-[11px] leading-relaxed text-content-faint">
            人物原文材料已保存，记忆准备会在后台进行；准备完成前 TA 还不能加入会话。
          </p>
        ) : null}

        {create.isError ? (
          <div className="mt-3"><ErrorNotice error={create.error} /></div>
        ) : null}

        <div className="mt-5 flex justify-end">
          <button
            type="button"
            disabled={create.isPending}
            onClick={submit}
            className="rounded-full bg-accent px-5 py-2 text-[13px] font-semibold text-accent-ink transition-[filter] hover:brightness-110 disabled:opacity-40"
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
      className={`rounded-2xl border p-3.5 text-left transition-colors ${
        active
          ? 'border-accent bg-accent-soft/60 ring-1 ring-accent/40'
          : 'border-border-subtle bg-white/[0.03] hover:border-accent/40'
      }`}
    >
      <span className="flex items-center gap-2 text-[13px] font-semibold">
        {title}
        {recommended ? (
          <span className="rounded-full bg-accent/20 px-2 py-0.5 text-[10px] font-medium text-accent">
            默认
          </span>
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
    <div className="animate-fade-in fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-6 backdrop-blur-[2px]">
      <div className="glass-panel animate-rise-in flex max-h-[80vh] w-full max-w-lg flex-col overflow-hidden rounded-card">
        <header className="flex shrink-0 items-start justify-between gap-4 px-6 py-5">
          <div>
            <h2 className="text-[15px] font-semibold">从模板创建角色</h2>
            <p className="mt-1 text-[11px] leading-relaxed text-content-faint">
              采用简单记忆模式。有作者材料时，准备完成后才能加入会话。
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-full px-2 py-0.5 text-[11px] text-content-faint transition-colors hover:bg-white/8 hover:text-content"
          >
            关闭
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
          {blueprints.map((blueprint) => (
            <button
              key={blueprint.blueprint_id}
              type="button"
              disabled={pending}
              onClick={() => {
                onPick(blueprint.blueprint_id);
              }}
              className="mx-2 flex w-[calc(100%-1rem)] items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-white/5 disabled:opacity-50"
            >
              <CharacterAvatar
                identity={'blueprint:' + blueprint.blueprint_id}
                name={blueprint.display_name}
                imageUrl={resolveOfficialAvatar({
                  blueprintId: blueprint.blueprint_id,
                  displayName: blueprint.display_name,
                })}
                size="md"
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium">{blueprint.display_name}</span>
                <span className="tabular block truncate text-[11px] text-content-faint">
                  {blueprint.blueprint_id}
                </span>
              </span>
              <Plus className="size-4 shrink-0 text-content-faint" strokeWidth={1.8} />
            </button>
          ))}

          {blueprints.length === 0 ? (
            <p className="px-3 py-4 text-[12px] text-content-faint">正在读取人物模板…</p>
          ) : null}
        </div>

        {error === null ? null : (
          <div className="shrink-0 px-6 pb-5">
            <ErrorNotice error={error} />
          </div>
        )}
      </div>
    </div>
  );
}
