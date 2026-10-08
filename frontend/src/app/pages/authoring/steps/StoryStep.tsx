import { StepPlaceholder } from './StepPlaceholder';
import type { StepProps } from './StepProps';

export function StoryStep(_props: StepProps) {
  return (
    <StepPlaceholder
      title="第二章 · 来历"
      description="写下关键词或完整故事，也可以让 AI 根据已确认的人设构思经历。"
    />
  );
}
