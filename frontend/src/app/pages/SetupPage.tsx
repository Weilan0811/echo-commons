import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Shell } from '@/components/Shell';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { ErrorNotice } from '@/components/ErrorNotice';
import { isNotFound } from '@/api/http';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import {
  useBlueprints,
  useCommunityCharacters,
  useCreateCharacter,
  useCreateCommunity,
  useJoinedCommunities,
  useJoinCommunity,
  usePlayer,
  useRegisterPlayer,
} from '@/api/directory';

/**
 * 主体与社群入口。
 *
 * 后端当前没有账户认证，这里保存的是本地测试身份：玩家标识与社群标识
 * 由使用者填写，不做账户校验。接入账户认证后，标识由服务端会话决定，
 * 本页改为展示与切换，不再自行保存，见 adr/0001。
 *
 * 建立社群、加入社群与创建角色都直接调用后端写入接口，因此本页是平台
 * 唯一的数据入口：没有它，新环境无法产生任何社群、角色或会话。
 */
export function SetupPage() {
  const { subject, set, clear } = useCurrentSubject();
  const navigate = useNavigate();
  const [playerId, setPlayerId] = useState(subject.playerId);
  const [playerName, setPlayerName] = useState(subject.playerDisplayName);
  const [communityId, setCommunityId] = useState(subject.communityId ?? '');
  const [communityName, setCommunityName] = useState('');
  const [joinTarget, setJoinTarget] = useState('');

  const typedPlayerId = playerId.trim();
  // 本地标识由手填，可能指向不存在的玩家。先确认它是否存在，再决定保存还是注册。
  const existingPlayer = usePlayer(typedPlayerId);

  const communities = useJoinedCommunities(subject.playerId);
  const characters = useCommunityCharacters(subject.playerId, subject.communityId);
  const blueprints = useBlueprints();
  const createCommunity = useCreateCommunity();
  const joinCommunity = useJoinCommunity();
  const createCharacter = useCreateCharacter();
  const registerPlayer = useRegisterPlayer();

  // 玩家已存在时不需要注册；输入为空或正在查询时也不给出可点击的注册动作。
  const needsRegister =
    typedPlayerId !== '' && existingPlayer.isError && isNotFound(existingPlayer.error);
  // 除「不存在」以外的失败都说明状态未知，此时不允许用保存身份掩盖问题。
  const identityUnverifiable = existingPlayer.isError && !needsRegister;

  const apply = async () => {
    if (typedPlayerId === '') return;
    if (needsRegister) {
      try {
        await registerPlayer.mutateAsync({
          playerId: typedPlayerId,
          displayName: playerName.trim() === '' ? typedPlayerId : playerName.trim(),
        });
      } catch {
        // 失败信息在下方展示，输入内容保持不变以便修改后重试。
        return;
      }
    }
    set({
      playerId: typedPlayerId,
      playerDisplayName: playerName.trim() === '' ? typedPlayerId : playerName.trim(),
      communityId: communityId.trim() === '' ? null : communityId.trim(),
      communityName: communityName.trim() === '' ? null : communityName.trim(),
    });
    void navigate('/app/chat');
  };

  const enter = (id: string, name: string) => {
    set({
      playerId: playerId.trim() === '' ? subject.playerId : playerId.trim(),
      playerDisplayName:
        playerName.trim() === '' ? (subject.playerDisplayName || playerId.trim()) : playerName.trim(),
      communityId: id,
      communityName: name,
    });
    void navigate('/app/chat');
  };

  return (
    <Shell section="chat" list={null}>
      <div className="flex min-h-0 flex-1 flex-col items-start gap-8 overflow-y-auto px-6 py-8">
        <div className="w-full max-w-sm">
          <h1 className="text-base font-semibold">主体与社群</h1>
          <p className="mt-1 text-xs leading-relaxed text-content-faint">
            后端当前没有账户认证。这里填写的是本地测试身份，仅用于区分不同读取主体，
            不做权限校验；接入账户认证后由服务端会话决定。
          </p>
        </div>

        <section className="w-full max-w-sm">
          <h2 className="text-xs font-medium text-content-muted">本地身份</h2>
          <div className="mt-2 flex flex-col gap-3">
            <Field label="玩家标识" value={playerId} onChange={setPlayerId} placeholder="ache" />
            <Field label="显示名称" value={playerName} onChange={setPlayerName} placeholder="阿澈" />
            <PlayerRegistrationStatus
              playerId={typedPlayerId}
              isChecking={existingPlayer.isPending}
              isRegistered={existingPlayer.isSuccess}
              isMissing={needsRegister}
              isUnverifiable={identityUnverifiable}
            />
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  void apply();
                }}
                className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-surface disabled:opacity-40"
                disabled={
                  typedPlayerId === '' ||
                  existingPlayer.isPending ||
                  registerPlayer.isPending ||
                  identityUnverifiable
                }
              >
                {needsRegister ? '注册并进入' : '保存并进入'}
              </button>
              {subject.playerId !== '' ? (
                <button
                  type="button"
                  onClick={() => {
                    clear();
                  }}
                  className="rounded-md border border-border-subtle px-3 py-2 text-sm text-content-muted hover:text-content"
                >
                  清除身份
                </button>
              ) : null}
            </div>
            {registerPlayer.isError ? <ErrorNotice error={registerPlayer.error} /> : null}
          </div>
        </section>

        <section className="w-full max-w-sm">
          <h2 className="text-xs font-medium text-content-muted">已加入的社群</h2>
          <p className="mt-1 text-[11px] text-content-faint">
            列表来自后端按当前玩家查询的结果。切换社群只改变本地选择，不写入服务端。
          </p>
          {communities.isError ? <ErrorNotice error={communities.error} /> : null}
          <div className="mt-2 flex flex-col gap-1">
            {(communities.data?.items ?? []).map((community) => (
              <button
                key={community.community_id}
                type="button"
                onClick={() => {
                  enter(community.community_id, community.name);
                }}
                className={`flex items-center gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors ${
                  community.community_id === subject.communityId
                    ? 'bg-surface-overlay'
                    : 'hover:bg-surface-raised'
                }`}
              >
                <span className="truncate">{community.name}</span>
                <span className="ml-auto shrink-0 text-[10px] text-content-faint">
                  {community.community_id}
                </span>
              </button>
            ))}
            {subject.playerId !== '' &&
            communities.data !== undefined &&
            communities.data.items.length === 0 ? (
              <p className="text-[11px] text-content-faint">还没有加入任何社群。</p>
            ) : null}
          </div>
        </section>

        <section className="w-full max-w-sm">
          <h2 className="text-xs font-medium text-content-muted">建立社群</h2>
          <p className="mt-1 text-[11px] text-content-faint">
            创建者自动成为成员。创建后直接进入该社群。
          </p>
          <div className="mt-2 flex flex-col gap-3">
            <Field
              label="社群名称"
              value={communityName}
              onChange={setCommunityName}
              placeholder="深夜食堂"
            />
            <Field
              label="社群标识（可留空，由后端生成）"
              value={communityId}
              onChange={setCommunityId}
              placeholder="night-diner"
            />
            <button
              type="button"
              disabled={playerId.trim() === '' || communityName.trim() === '' || createCommunity.isPending}
              onClick={() => {
                void createCommunity
                  .mutateAsync({
                    playerId: playerId.trim(),
                    name: communityName.trim(),
                    communityId: communityId.trim() === '' ? null : communityId.trim(),
                    timezone: 'UTC',
                  })
                  .then((created) => {
                    enter(created.community_id, created.name);
                  })
                  .catch(() => {
                    // 错误由下方 ErrorNotice 呈现，输入内容保持不变以便修改后重试。
                  });
              }}
              className="w-fit rounded-md border border-border-subtle px-3 py-2 text-sm text-content-muted hover:border-border-strong hover:text-content disabled:opacity-40"
            >
              {createCommunity.isPending ? '创建中' : '创建社群'}
            </button>
            {createCommunity.isError ? <ErrorNotice error={createCommunity.error} /> : null}
          </div>
        </section>

        <section className="w-full max-w-sm">
          <h2 className="text-xs font-medium text-content-muted">加入已有社群</h2>
          <p className="mt-1 text-[11px] text-content-faint">
            社群成员列表只有读取接口，加入由后端按玩家标识写入。
          </p>
          <div className="mt-2 flex flex-col gap-3">
            <Field
              label="社群标识"
              value={joinTarget}
              onChange={setJoinTarget}
              placeholder="night-diner"
            />
            <button
              type="button"
              disabled={playerId.trim() === '' || joinTarget.trim() === '' || joinCommunity.isPending}
              onClick={() => {
                void joinCommunity
                  .mutateAsync({ communityId: joinTarget.trim(), playerId: playerId.trim() })
                  .then(() => {
                    setJoinTarget('');
                  })
                  .catch(() => {
                    // 错误由下方 ErrorNotice 呈现。
                  });
              }}
              className="w-fit rounded-md border border-border-subtle px-3 py-2 text-sm text-content-muted hover:border-border-strong hover:text-content disabled:opacity-40"
            >
              {joinCommunity.isPending ? '加入中' : '加入社群'}
            </button>
            {joinCommunity.isError ? <ErrorNotice error={joinCommunity.error} /> : null}
          </div>
        </section>

        <section className="w-full max-w-sm">
          <h2 className="text-xs font-medium text-content-muted">当前社群的角色</h2>
          {subject.communityId === null ? (
            <p className="mt-1 text-[11px] text-content-faint">先选择或创建一个社群。</p>
          ) : (
            <>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(characters.data ?? []).map((character) => (
                  <span
                    key={character.character_id}
                    className="flex items-center gap-1.5 rounded-full bg-surface-raised py-0.5 pl-0.5 pr-2 text-[11px]"
                  >
                    <CharacterAvatar
                      identity={`character:${character.character_id}`}
                      name={character.display_name}
                      imageUrl={character.avatar_url}
                      size="xs"
                    />
                    {character.display_name}
                  </span>
                ))}
                {(characters.data ?? []).length === 0 && !characters.isPending ? (
                  <p className="text-[11px] text-content-faint">还没有角色。</p>
                ) : null}
              </div>

              <div className="mt-3 flex flex-wrap gap-1.5">
                {(blueprints.data ?? []).map((blueprint) => (
                  <button
                    key={blueprint.blueprint_id}
                    type="button"
                    disabled={createCharacter.isPending || subject.communityId === null}
                    onClick={() => {
                      if (subject.communityId === null) return;
                      void createCharacter
                        .mutateAsync({
                          communityId: subject.communityId,
                          playerId: subject.playerId,
                          blueprintId: blueprint.blueprint_id,
                        })
                        .catch(() => {
                          // 错误由下方 ErrorNotice 呈现。
                        });
                    }}
                    className="flex items-center gap-1.5 rounded-full border border-border-subtle py-0.5 pl-0.5 pr-2.5 text-[11px] text-content-muted hover:border-border-strong hover:text-content disabled:opacity-40"
                  >
                    <CharacterAvatar
                      identity={`blueprint:${blueprint.blueprint_id}`}
                      name={blueprint.display_name}
                      imageUrl={blueprint.avatar_url}
                      size="xs"
                    />
                    从「{blueprint.display_name}」创建
                  </button>
                ))}
              </div>
              {createCharacter.isError ? (
                <div className="mt-2">
                  <ErrorNotice error={createCharacter.error} />
                </div>
              ) : null}
            </>
          )}
        </section>
      </div>
    </Shell>
  );
}

/**
 * 玩家注册状态。
 *
 * 标识由手填，因此必须先回答「后端认不认这个玩家」：直接保存一个不存在的
 * 标识，会让后续每个读取都返回 404，而错误出现在与填写动作无关的页面上。
 */
function PlayerRegistrationStatus({
  playerId,
  isChecking,
  isRegistered,
  isMissing,
  isUnverifiable,
}: {
  readonly playerId: string;
  readonly isChecking: boolean;
  readonly isRegistered: boolean;
  readonly isMissing: boolean;
  readonly isUnverifiable: boolean;
}) {
  if (playerId === '' || (!isChecking && !isRegistered && !isMissing && !isUnverifiable)) {
    return null;
  }
  const text = isChecking
    ? '正在确认后端是否已有这个玩家…'
    : isRegistered
      ? '后端已有这个玩家。'
      : isMissing
        ? '后端没有这个玩家，进入时会先注册。'
        : '无法确认后端是否有这个玩家，请先解决后再保存。';
  return (
    <p
      className={`text-[11px] ${
        isRegistered || isChecking ? 'text-content-faint' : isMissing ? 'text-content-muted' : 'text-danger'
      }`}
    >
      {text}
    </p>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  readonly label: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly placeholder: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] text-content-faint">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="rounded-md border border-border-subtle bg-surface-raised px-3 py-2 text-sm text-content outline-none placeholder:text-content-faint focus:border-border-strong"
      />
    </label>
  );
}
