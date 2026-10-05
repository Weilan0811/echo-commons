// 临时预览数据，仅用于后端接口接入前的界面效果核对。
//
// 删除时机：后端提供会话列表与消息接口后，删除本文件，并把
// src/app/pages/ChatPage.tsx 中的 usePreviewThread 换成真实查询。
//
// 所有标识统一使用 preview- 前缀。这样即使遗漏，失败方式也是响亮的：
// 请求会直接 404，不可能静默写入真实后端数据。显示名使用真实模板名，
// 是为了在预览时看到真实的中文排版长度。

import type { SchemaOf } from '@/api/http';

// 可见范围字段说明：后端已决定移除可见范围（visibility）字段，渲染与输入逻辑
// 都不再读取它。本工作树的契约仍把它列为必填，因此这里保留取值 conversation
// ——这正是当前的实际语义：会话内消息对全部成员可见。
// 后端契约更新并重新生成类型后，删除本文件中的 visibility 行即可。
type MessageView = SchemaOf<'MessageView'>;
type TurnView = SchemaOf<'TurnView'>;

export interface PreviewCharacter {
  readonly characterId: string;
  readonly displayName: string;
}

export const PREVIEW_PLAYER = { playerId: 'preview-me', displayName: '我' } as const;

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
  /** 列表中显示的最后一条消息预览。 */
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

function sender(actorId: string): MessageView['sender'] {
  return { kind: 'character', actor_id: actorId };
}

function at(sequence: number): string {
  return `2026-10-04T0${(sequence % 10)}:15:00Z`;
}

/**
 * 序号刻意不连续：契约说明合法私有缺口存在，玩家看到的序号可能不连续，
 * 界面不得补齐也不得据此断言存在不可见内容。这里用 1、2、3、7、8 覆盖该情况。
 */
export const PREVIEW_GROUP_MESSAGES: readonly MessageView[] = [
  {
    message_id: 'preview-msg-1',
    conversation_id: 'preview-conv-group',
    sequence: 1,
    sender: { kind: 'player', actor_id: 'preview-me' },
    text: '大家还没睡？',
    visibility: 'conversation',
    mentions: [],
    reply_to_message_id: null,
    source_turn_id: 'preview-turn-1',
    created_at_utc: at(1),
  },
  {
    message_id: 'preview-msg-2',
    conversation_id: 'preview-conv-group',
    sequence: 2,
    sender: sender('preview-xiaojin'),
    text: '我在。刚才在整理一批旧照片，翻到很早以前的那张夜市，发现那张照片里居然有你。',
    visibility: 'conversation',
    mentions: [],
    reply_to_message_id: 'preview-msg-1',
    source_turn_id: 'preview-turn-1',
    created_at_utc: at(2),
  },
  {
    message_id: 'preview-msg-3',
    conversation_id: 'preview-conv-group',
    sequence: 3,
    sender: sender('preview-ache'),
    text: '那家面馆十一点才开门',
    visibility: 'conversation',
    mentions: [],
    reply_to_message_id: null,
    source_turn_id: 'preview-turn-2',
    created_at_utc: at(3),
  },
  {
    message_id: 'preview-msg-7',
    conversation_id: 'preview-conv-group',
    sequence: 7,
    sender: { kind: 'player', actor_id: 'preview-me' },
    text: '小槿，那张照片下次给我看看。',
    visibility: 'conversation',
    mentions: [{ kind: 'character', actor_id: 'preview-xiaojin' }],
    reply_to_message_id: 'preview-msg-2',
    source_turn_id: null,
    created_at_utc: at(7),
  },
  {
    message_id: 'preview-msg-8',
    conversation_id: 'preview-conv-group',
    sequence: 8,
    sender: { kind: 'player', actor_id: 'preview-me' },
    text: '@preview-ache 你说的那家在哪？',
    visibility: 'conversation',
    mentions: [{ kind: 'character', actor_id: 'preview-ache' }],
    reply_to_message_id: 'preview-msg-3',
    source_turn_id: null,
    created_at_utc: at(8),
  },
];

export const PREVIEW_TURNS: readonly TurnView[] = [
  {
    social_turn_id: 'preview-turn-1',
    conversation_id: 'preview-conv-group',
    status: 'completed',
    created_at_utc: at(1),
    completed_at_utc: at(2),
    participation: [
      {
        character_id: 'preview-xiaojin',
        reason_code: 'mentioned',
        selection_order: 1,
        status: 'completed',
        outcome: null,
      },
      {
        character_id: 'preview-ache',
        reason_code: 'not_selected',
        selection_order: null,
        status: 'silent',
        outcome: null,
      },
    ],
  },
  {
    social_turn_id: 'preview-turn-2',
    conversation_id: 'preview-conv-group',
    status: 'running',
    created_at_utc: at(3),
    completed_at_utc: null,
    participation: [
      {
        character_id: 'preview-ache',
        reason_code: 'selected',
        selection_order: 1,
        status: 'selected',
        outcome: null,
      },
    ],
  },
  {
    social_turn_id: 'preview-turn-3',
    conversation_id: 'preview-conv-group',
    status: 'completed',
    created_at_utc: at(6),
    completed_at_utc: at(7),
    participation: [
      {
        character_id: 'preview-xiaojin',
        reason_code: 'model_error',
        selection_order: 1,
        status: 'failed',
        outcome: null,
      },
    ],
  },
];

/**
 * 直接会话的消息。
 *
 * 每个私聊有独立内容：早先所有私聊共用同一份数据，导致切到另一个私聊时
 * 标题变了但说话的人与内容不变，看起来像没有打开。
 */
export const PREVIEW_XIAOJIN_MESSAGES: readonly MessageView[] = [
  {
    message_id: 'preview-dm-1',
    conversation_id: 'preview-conv-xiaojin',
    sequence: 1,
    sender: sender('preview-xiaojin'),
    text: '好，我等你消息。',
    visibility: 'conversation',
    mentions: [],
    reply_to_message_id: null,
    source_turn_id: 'preview-turn-4',
    created_at_utc: at(1),
  },
];

export const PREVIEW_ACHE_MESSAGES: readonly MessageView[] = [
  {
    message_id: 'preview-dm-ache-1',
    conversation_id: 'preview-conv-ache',
    sequence: 1,
    sender: sender('preview-ache'),
    text: '在的。',
    visibility: 'conversation',
    mentions: [],
    reply_to_message_id: null,
    source_turn_id: 'preview-turn-5',
    created_at_utc: at(1),
  },
  {
    message_id: 'preview-dm-ache-2',
    conversation_id: 'preview-conv-ache',
    sequence: 2,
    sender: { kind: 'player', actor_id: 'preview-me' },
    text: '那张夜市的照片，是在旧城站那边拍的吗？',
    visibility: 'conversation',
    mentions: [],
    reply_to_message_id: 'preview-dm-ache-1',
    source_turn_id: null,
    created_at_utc: at(2),
  },
  {
    message_id: 'preview-dm-ache-3',
    conversation_id: 'preview-conv-ache',
    sequence: 3,
    sender: sender('preview-ache'),
    text: '不是旧城站，是南边那条巷子。我记错了两次，这次比较确定。要不要我把地址发给你，顺便说说那天还有谁在。',
    visibility: 'conversation',
    mentions: [],
    reply_to_message_id: 'preview-dm-ache-2',
    source_turn_id: 'preview-turn-6',
    created_at_utc: at(3),
  },
];
