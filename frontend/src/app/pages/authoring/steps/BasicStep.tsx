import { StepPlaceholder } from './StepPlaceholder';
import type { StepProps } from './StepProps';

export function BasicStep(_props: StepProps) {
  return (
    <StepPlaceholder
      title="第一章 · 初识"
      description="名字、一句话与三份运行正文；可以手写，也可以让 AI 起草。"
    />
  );
}
