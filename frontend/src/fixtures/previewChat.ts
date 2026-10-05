// 临时预览数据，仅用于后端接口接入前的界面效果核对。
//
// 删除时机：会话与消息接口接入后，删除本文件，并把 ChatPage 中的
// usePreviewThread 与 messagesFor 换成真实查询。
//
// 所有标识统一使用 preview- 前缀。这样即使遗漏，失败方式也是响亮的：
// 请求会直接返回未找到，不可能静默写入真实后端数据。显示名使用真实模板名，
// 是为了在预览时看到真实的中文排版长度。

import type { SchemaOf } from '@/api/http';

type PlayerMessageView = SchemaOf<'PlayerMessageView'>;
type TurnView = SchemaOf<'TurnView'>;

export const PREVIEW_PLAYER = { playerId: 'preview-me', displayName: '我' } as const;

export interface PreviewCharacter {
  readonly characterId: string;
  readonly displayName: string;
}

export const PREVIEW_CHARACTERS: readonly PreviewCharacter[] = [
  { characterId: 'preview-xiaojin', displayName: '小槿' },
  { characterId: 'preview-ache', displayName: '阿澈' },
];

export const PREVIEW_COMMUNITY = {
  communityId: 'preview-community',
  name: '深夜食堂',
} as const;

export interface PreviewConversation {
  readonly conversationId: string;
  readonly kind: 'group' | 'direct';
  readonly title: string;
  readonly preview: string;
  readonly characters: readonly PreviewCharacter[];
}

export const PREVIEW_CONVERSATIONS: readonly PreviewConversation[] = [
  {
    conversationId: 'preview-conv-group',
    kind: 'group',
    title: '深夜食堂',
    preview: '那家面馆十一点才开门',
    characters: PREVIEW_CHARACTERS,
  },
  {
    conversationId: 'preview-conv-xiaojin',
    kind: 'direct',
    title: '小槿',
    preview: '好，我等你消息',
    characters: [PREVIEW_CHARACTERS[0]!],
  },
  {
    conversationId: 'preview-conv-ache',
    kind: 'direct',
    title: '阿澈',
    preview: '在的。',
    characters: [PREVIEW_CHARACTERS[1]!],
  },
];

/** 契约中的公开显示信息，含显示名与可选头像地址。 */
function display(actorId: string, displayName: string) {
  return {
    actor: { kind: 'character' as const, actor_id: actorId },
    display_name: displayName,
    avatar_url: null,
  };
}

const XIAOJIN = display('preview-xiaojin', '小槿');
const ACHE = display('preview-ache', '阿澈');
const ME = {
  actor: { kind: 'player' as const, actor_id: 'preview-me' },
  display_name: '我',
  avatar_url: null,
};

function at(hour: number): string {
  return `2026-10-05T${`${hour}`.padStart(2, '0')}:15:00Z`;
}

/** 全部预览消息，按需查找，避免顶层求值顺序问题。 */
/**
 * 序号刻意不连续：契约说明合法私有缺口存在，玩家看到的序号可能不连续，
 * 界面不得补齐也不得据此断言存在不可见内容。这里用 1、2、3、7、8 覆盖该情况。
 */
export const PREVIEW_GROUP_MESSAGES: readonly PlayerMessageView[] = [
  {
    message_id: 'preview-msg-1',
    conversation_id: 'preview-conv-group',
    sequence: 1,
    sender: ME.actor,
    text: '大家还没睡？',
    sender_display: ME,
    visibility: 'conversation',
    mentions: [],
    recipients: [],
    reply_to_message_id: null,
    reply_preview: null,
    source_turn_id: 'preview-turn-1',
    created_at_utc: at(9),
  },
  {
    message_id: 'preview-msg-2',
    conversation_id: 'preview-conv-group',
    sequence: 2,
    sender: XIAOJIN.actor,
    text: '我在。刚才在整理一批旧照片，翻到很早以前的那张夜市，发现那张照片里居然有你。',
    sender_display: XIAOJIN,
    visibility: 'conversation',
    mentions: [],
    recipients: [],
    reply_to_message_id: 'preview-msg-1',
    reply_preview: {
      message_id: 'preview-msg-1',
      sequence: 1,
      sender_display: ME,
      text_preview: '大家还没睡？',
      visibility: 'conversation',
      created_at_utc: at(9),
    },
    source_turn_id: 'preview-turn-1',
    created_at_utc: at(10),
  },
  {
    message_id: 'preview-msg-3',
    conversation_id: 'preview-conv-group',
    sequence: 3,
    sender: ACHE.actor,
    text: '那家面馆十一点才开门',
    sender_display: ACHE,
    visibility: 'conversation',
    mentions: [],
    recipients: [],
    reply_to_message_id: null,
    reply_preview: null,
    source_turn_id: 'preview-turn-2',
    created_at_utc: at(11),
  },
  {
    message_id: 'preview-msg-7',
    conversation_id: 'preview-conv-group',
    sequence: 7,
    sender: ME.actor,
    text: '小槿，那张照片下次给我看看。',
    sender_display: ME,
    visibility: 'conversation',
    mentions: [XIAOJIN.actor],
    recipients: [],
    reply_to_message_id: 'preview-msg-2',
    reply_preview: {
      message_id: 'preview-msg-2',
      sequence: 2,
      sender_display: XIAOJIN,
      text_preview: '我在。刚才在整理一批旧照片',
      visibility: 'conversation',
      created_at_utc: at(10),
    },
    source_turn_id: null,
    created_at_utc: at(15),
  },
  {
    message_id: 'preview-msg-8',
    conversation_id: 'preview-conv-group',
    sequence: 8,
    sender: ME.actor,
    text: '@阿澈 你说的那家在哪？',
    sender_display: ME,
    visibility: 'conversation',
    mentions: [ACHE.actor],
    recipients: [],
    reply_to_message_id: 'preview-msg-3',
    reply_preview: {
      message_id: 'preview-msg-3',
      sequence: 3,
      sender_display: ACHE,
      text_preview: '那家面馆十一点才开门',
      visibility: 'conversation',
      created_at_utc: at(11),
    },
    source_turn_id: null,
    created_at_utc: at(16),
  },
];

export const PREVIEW_TURNS: readonly TurnView[] = [
  {
    social_turn_id: '',
    input_message_ids: [],
    conversation_id: 'preview-conv-group',
    status: 'completed',
    created_at_utc: at(9),
    completed_at_utc: at(10),
    participation: [
      { character_id: 'preview-xiaojin', reason_code: 'mentioned', selection_order: 1, status: 'completed', outcome: null },
      { character_id: 'preview-ache', reason_code: 'not_selected', selection_order: null, status: 'silent', outcome: null },
    ],
  },
  {
    social_turn_id: '',
    input_message_ids: [],
    conversation_id: 'preview-conv-group',
    status: 'running',
    created_at_utc: at(11),
    completed_at_utc: null,
    participation: [
      { character_id: 'preview-ache', reason_code: 'selected', selection_order: 1, status: 'selected', outcome: null },
    ],
  },
  {
    social_turn_id: '',
    input_message_ids: [],
    conversation_id: 'preview-conv-group',
    status: 'completed',
    created_at_utc: at(14),
    completed_at_utc: at(15),
    participation: [
      { character_id: 'preview-xiaojin', reason_code: 'model_error', selection_order: 1, status: 'failed', outcome: null },
    ],
  },
];

/**
 * 直接会话的消息。
 *
 * 每个私聊有独立内容：早先所有私聊共用同一份数据，导致切到另一个私聊时
 * 标题变了但说话的人与内容不变，看起来像没有打开。
 */
export const PREVIEW_XIAOJIN_MESSAGES: readonly PlayerMessageView[] = [
  {
    message_id: 'preview-dm-1',
    conversation_id: 'preview-conv-xiaojin',
    sequence: 1,
    sender: XIAOJIN.actor,
    text: '好，我等你消息。',
    sender_display: XIAOJIN,
    visibility: 'conversation',
    mentions: [],
    recipients: [],
    reply_to_message_id: null,
    reply_preview: null,
    source_turn_id: 'preview-turn-4',
    created_at_utc: at(9),
  },
];

export const PREVIEW_ACHE_MESSAGES: readonly PlayerMessageView[] = [
  {
    message_id: 'preview-dm-ache-1',
    conversation_id: 'preview-conv-ache',
    sequence: 1,
    sender: ACHE.actor,
    text: '在的。',
    sender_display: ACHE,
    visibility: 'conversation',
    mentions: [],
    recipients: [],
    reply_to_message_id: null,
    reply_preview: null,
    source_turn_id: 'preview-turn-5',
    created_at_utc: at(9),
  },
  {
    message_id: 'preview-dm-ache-2',
    conversation_id: 'preview-conv-ache',
    sequence: 2,
    sender: ME.actor,
    text: '那张夜市的照片，是在旧城站那边拍的吗？',
    sender_display: ME,
    visibility: 'conversation',
    mentions: [],
    recipients: [],
    reply_to_message_id: 'preview-dm-ache-1',
    reply_preview: {
      message_id: 'preview-dm-ache-1',
      sequence: 1,
      sender_display: ACHE,
      text_preview: '在的。',
      visibility: 'conversation',
      created_at_utc: at(9),
    },
    source_turn_id: null,
    created_at_utc: at(10),
  },
  {
    message_id: 'preview-dm-ache-3',
    conversation_id: 'preview-conv-ache',
    sequence: 3,
    sender: ACHE.actor,
    text: '不是旧城站，是南边那条巷子。我记错了两次，这次比较确定。要不要我把地址发给你，顺便说说那天还有谁在。',
    sender_display: ACHE,
    visibility: 'conversation',
    mentions: [],
    recipients: [],
    reply_to_message_id: 'preview-dm-ache-2',
    reply_preview: {
      message_id: 'preview-dm-ache-2',
      sequence: 2,
      sender_display: ME,
      text_preview: '那张夜市的照片，是在旧城站那边拍的吗？',
      visibility: 'conversation',
      created_at_utc: at(10),
    },
    source_turn_id: 'preview-turn-6',
    created_at_utc: at(11),
  },
];

/** 全部预览消息，供引用预览查找序号与发送者。 */
