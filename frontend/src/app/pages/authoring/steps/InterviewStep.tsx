import { StepPlaceholder } from './StepPlaceholder';
import type { StepProps } from './StepProps';

export function InterviewStep(_props: StepProps) {
  return (
    <StepPlaceholder
      title="第三章 · 对谈"
      description="从十五个问题里保留十到十五题，听 TA 用自己的语气回答。"
    />
  );
}
