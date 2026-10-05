import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Shell } from '@/components/Shell';
import { Field, PageHeading, PrimaryButton, SecondaryButton } from '@/components/Page';
import { ErrorNotice } from '@/components/ErrorNotice';
import { isNotFound } from '@/api/http';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { usePlayer, useRegisterPlayer } from '@/api/directory';

/**
 * 身份登记。
 *
 * 后端当前没有账户认证，这里保存的是本地测试身份：标识由使用者指定，
 * 不做账户校验。接入账户认证后本页整体移除，身份改由服务端会话决定，
 * 见 adr/0001。
 *
 * 保存前先问一次后端认不认这个玩家。标识是手填的，直接保存一个不存在的
 * 标识，会让后续每个读取都返回 404，而错误出现在与填写动作无关的页面上。
 */
export function IdentityPage() {
  const { subject, set, clear } = useCurrentSubject();
  const navigate = useNavigate();
  const [playerId, setPlayerId] = useState(subject.playerId);
  const [playerName, setPlayerName] = useState(subject.playerDisplayName);
  const [communityId, setCommunityId] = useState(subject.communityId ?? '');

  const typedPlayerId = playerId.trim();
  const existing = usePlayer(typedPlayerId);
  const register = useRegisterPlayer();

  // 不存在是有效答案，需要在填写变化后重新询问；其他失败说明状态未知。
  const missing = typedPlayerId !== '' && existing.isError && isNotFound(existing.error);
  const unverifiable = existing.isError && !missing;

  const apply = async () => {
    if (typedPlayerId === '') return;
    const displayName = playerName.trim() === '' ? typedPlayerId : playerName.trim();
    if (missing) {
      try {
        await register.mutateAsync({ playerId: typedPlayerId, displayName });
      } catch {
        // 失败信息在下方展示，输入内容保持不变以便修改后重试。
        return;
      }
    }
    set({
      playerId: typedPlayerId,
      playerDisplayName: displayName,
      communityId: communityId.trim() === '' ? null : communityId.trim(),
      communityName: null,
    });
    void navigate('/app/chat');
  };

  return (
    <Shell section="subject" list={null}>
      <PageHeading
        title="身份登记"
        description="后端当前没有账户认证，这里填写的是本地测试身份，仅用于区分不同读取主体，不做权限校验。接入账户认证后由服务端会话决定。"
      />

      <div className="min-h-0 flex-1 overflow-y-auto px-8 py-7">
        <div className="flex max-w-md flex-col gap-5">
          <div className="flex flex-col gap-4">
            <Field
              label="玩家标识"
              value={playerId}
              onChange={setPlayerId}
              placeholder="ache"
            />
            <Field
              label="显示名称"
              value={playerName}
              onChange={setPlayerName}
              placeholder="阿澈"
            />
            <Field
              label="当前社群标识"
              hint="可留空，之后在社群页选择。"
              value={communityId}
              onChange={setCommunityId}
              placeholder="night-diner"
            />
          </div>

          <p
            className={`text-[11px] ${
              missing ? 'text-content-muted' : unverifiable ? 'text-danger' : 'text-content-faint'
            }`}
          >
            {statusText(typedPlayerId, {
              checking: existing.isPending,
              registered: existing.isSuccess,
              missing,
              unverifiable,
            })}
          </p>

          {register.isError ? <ErrorNotice error={register.error} /> : null}

          <div className="flex items-center gap-2">
            <PrimaryButton
              onClick={() => {
                void apply();
              }}
              disabled={
                typedPlayerId === '' ||
                existing.isPending ||
                register.isPending ||
                unverifiable
              }
            >
              {missing ? '注册并进入' : '保存并进入'}
            </PrimaryButton>
            {subject.playerId === '' ? null : (
              <SecondaryButton
                onClick={() => {
                  clear();
                  setPlayerId('');
                  setPlayerName('');
                  setCommunityId('');
                }}
              >
                清除身份
              </SecondaryButton>
            )}
          </div>
        </div>
      </div>
    </Shell>
  );
}

/** 后端对当前标识的应答。分开写清楚，避免三处条件混在一起读。 */
function statusText(
  playerId: string,
  state: {
    readonly checking: boolean;
    readonly registered: boolean;
    readonly missing: boolean;
    readonly unverifiable: boolean;
  },
): string {
  if (playerId === '') return '';
  if (state.checking) return '正在确认后端是否已有这个玩家…';
  if (state.registered) return '后端已有这个玩家。';
  if (state.missing) return '后端没有这个玩家，进入时会先注册。';
  return '无法确认后端是否有这个玩家，请先解决后再保存。';
}