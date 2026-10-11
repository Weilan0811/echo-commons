import type { AuthoringDraft, AuthoringTemplate } from '@/api/authoring';
import type { AuthoringChapter } from '@/lib/authoring';

/**
 * 每个创作步骤的共同入参。
 *
 * 草稿权威数据由向导的查询持有，写操作成功后接口层会更新同一缓存，步骤不
 * 自行复制草稿状态。onNavigate 只改变向导章节，不携带任何业务状态。
 */
export interface StepProps {
  readonly playerId: string;
  readonly draftId: string;
  readonly draft: AuthoringDraft;
  readonly template: AuthoringTemplate;
  readonly onNavigate: (chapter: AuthoringChapter) => void;
}
