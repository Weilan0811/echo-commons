import { StepPlaceholder } from './StepPlaceholder';
import type { StepProps } from './StepProps';

export function ConfirmStep(_props: StepProps) {
  return (
    <StepPlaceholder
      title="终章 · 定格"
      description="校准并审核三份正文，固定人物后让 TA 入住社群。"
    />
  );
}
