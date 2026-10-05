import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Shell } from '@/components/Shell';
import { EmptyState } from '@/components/EmptyState';
import { useCurrentSubject } from '@/identity/useCurrentSubject';

/**
 * 主体与社群入口。
 *
 * 后端当前没有账户认证，这里保存的是本地测试身份：玩家标识与社群标识
 * 由使用者填写，不做账户校验。接入账户认证后，标识由服务端会话决定，
 * 本页改为展示与切换，不再自行保存，见 adr/0001。
 */
export function SetupPage() {
  const { subject, set, clear } = useCurrentSubject();
  const navigate = useNavigate();
  const [playerId, setPlayerId] = useState(subject.playerId);
  const [playerName, setPlayerName] = useState(subject.playerDisplayName);
  const [communityId, setCommunityId] = useState(subject.communityId ?? '');
  const [communityName, setCommunityName] = useState(subject.communityName ?? '');

  const apply = () => {
    if (playerId.trim() === '') return;
    set({
      playerId: playerId.trim(),
      playerDisplayName: playerName.trim() === '' ? playerId.trim() : playerName.trim(),
      communityId: communityId.trim() === '' ? null : communityId.trim(),
      communityName: communityName.trim() === '' ? null : communityName.trim(),
    });
    void navigate('/app/chat');
  };

  return (
    <Shell section="chat" list={null}>
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-6 px-6">
        <div className="w-full max-w-sm">
          <h1 className="text-base font-semibold">主体与社群</h1>
          <p className="mt-1 text-xs leading-relaxed text-content-faint">
            后端当前没有账户认证。这里填写的是本地测试身份，仅用于区分不同读取主体，
            不做权限校验；接入账户认证后由服务端会话决定。
          </p>
        </div>

        <div className="flex w-full max-w-sm flex-col gap-3">
          <Field label="玩家标识" value={playerId} onChange={setPlayerId} placeholder="alice" />
          <Field label="显示名称" value={playerName} onChange={setPlayerName} placeholder="我" />
          <div className="my-1 border-t border-border-subtle" />
          <Field label="社群标识" value={communityId} onChange={setCommunityId} placeholder="community-1" />
          <Field label="社群名称" value={communityName} onChange={setCommunityName} placeholder="深夜食堂" />

          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              onClick={apply}
              className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-surface disabled:opacity-40"
              disabled={playerId.trim() === ''}
            >
              保存并进入
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
        </div>
      </div>
    </Shell>
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
