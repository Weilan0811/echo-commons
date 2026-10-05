import { useMemo } from 'react';
import { useNavigate, useParams } from 'react-router';
import { CharacterAvatar } from '@/components/CharacterAvatar';
import { Composer, type ComposerTarget } from '@/components/Composer';
import { EmptyState } from '@/components/EmptyState';
import { MessageGroupView } from '@/components/MessageGroup';
import { TurnStatusLane } from '@/components/TurnStatusLane';
import { Shell } from '@/components/Shell';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { deriveTurnStates } from '@/lib/deriveTurnStates';
import { groupMessages } from '@/lib/groupMessages';
import type { SchemaOf } from '@/api/http';
import {
  PREVIEW_ACHE_MESSAGES,
  PREVIEW_CHARACTERS,
  PREVIEW_CONVERSATIONS,
  PREVIEW_GROUP_MESSAGES,
  PREVIEW_PLAYER,
  PREVIEW_TURNS,
  PREVIEW_XIAOJIN_MESSAGES,
  type PreviewConversation,
} from '@/fixtures/previewChat';

type MessageView = SchemaOf<'MessageView'>;

/**
 * 聊天页：左侧会话列表常驻，右侧展开选中的会话。
 *
 * 当前数据来自临时预览数据，用于后端接口接入前核对界面效果。
 * 接入后替换 usePreviewThread 的实现与身份来源，页面结构不变。
 */
export function ChatPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const navigate = useNavigate();
  const { subject, set: setSubject } = useCurrentSubject();

  // 预览期间沿用 fixture 身份，便于查看真实排版；接入后由主体与社群入口决定。
  if (subject.playerId === '') {
    setSubject({
      playerId: PREVIEW_PLAYER.playerId,
      playerDisplayName: PREVIEW_PLAYER.displayName,
      communityId: 'preview-community',
      communityName: '深夜食堂',
    });
  }

  const playerId = subject.playerId === '' ? PREVIEW_PLAYER.playerId : subject.playerId;
  const active = PREVIEW_CONVERSATIONS.find((item) => item.conversationId === conversationId);
  const thread = usePreviewThread(active);

  const nameOf = useMemo(() => {
    const map = new Map<string, string>(
      PREVIEW_CHARACTERS.map((character) => [character.characterId, character.displayName]),
    );
    map.set(playerId, subject.playerDisplayName === '' ? PREVIEW_PLAYER.displayName : subject.playerDisplayName);
    return (sender: MessageView['sender']) =>
      sender.kind === 'system' ? '系统' : (map.get(sender.actor_id) ?? sender.actor_id);
  }, [playerId, subject.playerDisplayName]);

  return (
    <Shell
      section="chat"
      list={
        <ConversationList
          conversations={PREVIEW_CONVERSATIONS}
          activeId={conversationId ?? null}
          onSelect={(id) => {
            void navigate(`/app/chat/${id}`);
          }}
        />
      }
    >
      {active === undefined ? (
        <EmptyState
          title="选择一个会话"
          description="聊天页面已就绪。会话与消息来自临时预览数据，后端接口接入后替换。"
        />
      ) : (
        <>
          <ThreadHeader conversation={active} />
          <MessageScroller messages={thread.messages} playerId={playerId} nameOf={nameOf} />
          <div className="shrink-0 border-t border-border-subtle px-4 py-3">
            <TurnStatusLane
              displays={thread.turns}
              resolveName={(id) => nameOf({ kind: 'character', actor_id: id })}
            />
            <div className="mt-2">
              <Composer
                currentPlayerId={playerId}
                characters={toMentionTargets(active.characters)}
                onSend={async () => {
                  throw new Error('预览模式不发送消息，接入后端后可用。');
                }}
              />
            </div>
          </div>
        </>
      )}
    </Shell>
  );
}

/** 临时数据来源。接入后替换为按身份与社群查询的真实数据。 */
function usePreviewThread(active: PreviewConversation | undefined) {
  if (active === undefined) return { messages: [] as readonly MessageView[], turns: [] };
  const messages = messagesFor(active);
  const turns = active.kind === 'group' ? deriveTurnStates(PREVIEW_TURNS) : [];
  return { messages, turns };
}

/** 每个会话的预览消息。接入后由按会话与身份查询的真实数据替换。 */
function messagesFor(conversation: PreviewConversation): readonly MessageView[] {
  if (conversation.kind === 'group') return PREVIEW_GROUP_MESSAGES;
  return conversation.conversationId === 'preview-conv-ache'
    ? PREVIEW_ACHE_MESSAGES
    : PREVIEW_XIAOJIN_MESSAGES;
}
function toMentionTargets(
  characters: readonly { readonly characterId: string; readonly displayName: string }[],
): readonly ComposerTarget[] {
  return characters.map((character) => ({
    identity: character.characterId,
    name: character.displayName,
    kind: 'character' as const,
  }));
}

function ThreadHeader({ conversation }: { readonly conversation: PreviewConversation }) {
  return (
    <header className="flex shrink-0 items-center gap-2.5 border-b border-border-subtle px-4 py-3">
      <span className="text-sm font-medium">{conversation.title}</span>
      <span className="rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-content-faint">
        {conversation.kind === 'group' ? '群聊' : '私聊'}
      </span>
      <span className="ml-auto text-[11px] text-content-faint">
        {conversation.characters.map((character) => character.displayName).join('、')}
      </span>
    </header>
  );
}

function ConversationList({
  conversations,
  activeId,
  onSelect,
}: {
  readonly conversations: readonly PreviewConversation[];
  readonly activeId: string | null;
  readonly onSelect: (conversationId: string) => void;
}) {
  const groups = conversations.filter((item) => item.kind === 'group');
  const directs = conversations.filter((item) => item.kind === 'direct');

  return (
    <nav aria-label="会话列表" className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <ListSection title="群聊" conversations={groups} activeId={activeId} onSelect={onSelect} />
      <ListSection title="私聊" conversations={directs} activeId={activeId} onSelect={onSelect} />
    </nav>
  );
}

function ListSection({
  title,
  conversations,
  activeId,
  onSelect,
}: {
  readonly title: string;
  readonly conversations: readonly PreviewConversation[];
  readonly activeId: string | null;
  readonly onSelect: (conversationId: string) => void;
}) {
  if (conversations.length === 0) return null;
  return (
    <div className="flex flex-col">
      <p className="px-3 pb-1 pt-3 text-[10px] uppercase tracking-wide text-content-faint">{title}</p>
      {conversations.map((conversation) => (
        <button
          key={conversation.conversationId}
          type="button"
          onClick={() => onSelect(conversation.conversationId)}
          className={`flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors ${
            conversation.conversationId === activeId
              ? 'bg-surface-overlay'
              : 'hover:bg-surface-raised'
          }`}
        >
          <CharacterAvatar identity={conversation.conversationId} name={conversation.title} size="sm" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-medium">{conversation.title}</span>
            <span className="block truncate text-[11px] text-content-faint">{conversation.preview}</span>
          </span>
        </button>
      ))}
    </div>
  );
}

function MessageScroller({
  messages,
  playerId,
  nameOf,
}: {
  readonly messages: readonly MessageView[];
  readonly playerId: string;
  readonly nameOf: (sender: MessageView['sender']) => string;
}) {
  if (messages.length === 0) {
    return <EmptyState title="还没有消息" description="发送一条消息开始对话。" />;
  }
  const groups = groupMessages(messages);
  return (
    <div role="log" aria-label="消息" className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 py-4">
      {groups.map((group, index) => (
        <div key={`${group.sender.kind}-${index}`} className="animate-rise-in">
          <MessageGroupView group={group} playerId={playerId} resolveName={nameOf} />
        </div>
      ))}
    </div>
  );
}
