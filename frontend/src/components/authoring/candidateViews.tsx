import type { AuthoringCandidate } from '@/api/authoring';
import type { SchemaOf } from '@/api/http';

/**
 * 四类 AI 候选的具体内容呈现。
 *
 * 候选在接受前只是建议，因此都渲染在 acent-soft 的「建议」卡片里；接受后
 * 由后端按操作范围合并，这里不提供写回作者材料的入口。
 */
export function CandidateOutputView({ candidate }: { readonly candidate: AuthoringCandidate }) {
  const output = candidate.output;
  if (output === null) return null;
  switch (output.operation) {
    case 'basic':
      return <BasicOutputView output={output} />;
    case 'story':
      return <StoryOutputView output={output} />;
    case 'interview':
      return <InterviewOutputView candidate={candidate} />;
    case 'calibrate':
      return <CalibrateOutputView output={output}  />;
  }
}

function BasicOutputView({ output }: { readonly output: SchemaOf<'BasicOutput'> }) {
  return (
    <div className="flex flex-col gap-3">
      <SuggestedText label="基础描述" text={output.description} />
      <SuggestedText label="身份与性格（profile）" text={output.profile} />
      <SuggestedText label="说话方式（voice）" text={output.voice} />
      <SuggestedText label="相处倾向（relational_dynamics）" text={output.relational_dynamics} />
      <ChangeList items={output.changes} />
    </div>
  );
}

function StoryOutputView({ output }: { readonly output: SchemaOf<'StoryOutput'> }) {
  return (
    <div className="flex flex-col gap-3">
      <SuggestedText label="故事候选" text={output.story} />
      {(output.relationship_suggestions ?? []).map((item, index) => <SuggestedText key={index} label={`人物关系建议：${item.name}`} text={item.content} />)}
      {(output.relationship_suggestions?.length ?? 0) > 0 && <p className="text-[11px] text-content-faint">接受故事后，在「与 TA 的关系」编辑区逐项选择人物编号。</p>}
      <ChangeList items={output.changes} />
    </div>
  );
}

/**
 * 采访回答逐题展示。题目取自候选冻结输入，保证回答与本次的问题一一对应；
 * 新背景建议是假设性质，作者写入故事后才成为经历。
 */
function InterviewOutputView({ candidate }: { readonly candidate: AuthoringCandidate }) {
  const output = candidate.output;
  if (output === null || output.operation !== 'interview') return null;
  const questions = readFrozenQuestions(candidate);

  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col gap-2.5">
        {output.answers.map((answer) => {
          const question = questions.get(answer.question_id);
          return (
            <li key={answer.question_id} className="rounded-lg bg-surface-sunken/60 p-3">
              <p className="text-[11px] font-medium text-accent">{question ?? answer.question_id}</p>
              <p className="mt-1.5 whitespace-pre-wrap text-[13px] leading-relaxed text-content">
                {answer.answer}
              </p>
            </li>
          );
        })}
      </ul>
      {output.new_background_suggestions.length > 0 ? (
        <div className="rounded-lg border border-dashed border-warn/40 bg-warn/5 p-3">
          <p className="text-[11px] font-semibold text-warn">新的背景建议（尚未成为设定）</p>
          <ul className="mt-1.5 list-disc pl-5 text-[12px] leading-relaxed text-content-muted">
            {output.new_background_suggestions.map((suggestion, index) => (
              <li key={index}>{suggestion}</li>
            ))}
          </ul>
          <p className="mt-1.5 text-[10px] text-content-faint">
            这些经历只是角色在回答里的假设；你接受问答并把它写进故事后，才会成为正式背景。
          </p>
        </div>
      ) : null}
    </div>
  );
}

function CalibrateOutputView({ output }: { readonly output: SchemaOf<'CalibrateOutput'> }) {
  return (
    <div className="flex flex-col gap-3">
      <SuggestedText label="身份与性格（profile）" text={output.profile} />
      <SuggestedText label="说话方式（voice）" text={output.voice} />
      <SuggestedText label="相处倾向（relational_dynamics）" text={output.relational_dynamics} />
      <div className="flex flex-col gap-2">
        <p className="text-[11px] font-semibold text-content-muted">修改依据</p>
        {output.changes.map((change, index) => (
          <div key={`${change.document}-${index}`} className="rounded-lg bg-surface-sunken/60 p-2.5">
            <p className="text-[11px] font-medium text-accent">{documentLabel(change.document)}</p>
            <p className="mt-1 text-[12px] leading-relaxed text-content-muted">{change.explanation}</p>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {change.source_refs.map((ref) => (
                <SourceTag key={ref} refName={ref} />
              ))}
            </div>
          </div>
        ))}
      </div>
      {output.conflicts.length > 0 ? (
        <div className="rounded-lg border border-danger/40 bg-danger/10 p-3">
          <p className="text-[11px] font-semibold text-danger">待你决定的冲突</p>
          <ul className="mt-1.5 flex flex-col gap-1.5">
            {output.conflicts.map((conflict, index) => (
              <li key={index} className="text-[12px] leading-relaxed text-danger/90">
                <span>{conflict.explanation}</span>
                <span className="ml-1.5 inline-flex flex-wrap gap-1 align-middle">
                  {conflict.source_refs.map((ref) => (
                    <SourceTag key={ref} refName={ref} />
                  ))}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-[10px] text-danger/80">
            界面不替你取舍：可以修正材料后重新校准，或手工编辑正文再审核。
          </p>
        </div>
      ) : null}
    </div>
  );
}

function SuggestedText({ label, text }: { readonly label: string; readonly text: string }) {
  return (
    <div className="rounded-lg bg-surface-sunken/60 p-3">
      <p className="text-[11px] font-medium text-content-muted">{label}</p>
      <p className="mt-1 whitespace-pre-wrap text-[13px] leading-relaxed text-content">{text}</p>
    </div>
  );
}

function ChangeList({ items }: { readonly items: readonly string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="rounded-lg bg-surface-sunken/60 p-3">
      <p className="text-[11px] font-semibold text-content-muted">这次改了什么</p>
      <ul className="mt-1 list-disc pl-5 text-[12px] leading-relaxed text-content-muted">
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

/** 来源标签。采访来源形如 interview:daily_rhythm，转成更易读的样子。 */
function SourceTag({ refName }: { readonly refName: string }) {
  const label = refName.startsWith('interview:')
    ? `采访·${refName.slice('interview:'.length)}`
    : sourceLabel(refName);
  return (
    <span className="rounded border border-border-subtle bg-surface-raised px-1.5 py-0.5 text-[10px] text-content-faint">
      {label}
    </span>
  );
}

function sourceLabel(refName: string): string {
  switch (refName) {
    case 'description':
      return '基础描述';
    case 'story':
      return '故事';
    case 'profile':
      return '身份与性格';
    case 'voice':
      return '说话方式';
    case 'relational_dynamics':
      return '相处倾向';
    default:
      return refName;
  }
}

function documentLabel(document: SchemaOf<'CalibrationChange'>['document']): string {
  return sourceLabel(document);
}

/** 从冻结输入读出本批题目；异常响应缺字段时回退编号，不猜测题目正文。 */
function readFrozenQuestions(candidate: AuthoringCandidate): Map<string, string> {
  const result = new Map<string, string>();
  const frozen = candidate.frozen_input as { questions?: unknown };
  if (!Array.isArray(frozen.questions)) return result;
  for (const item of frozen.questions) {
    if (typeof item !== 'object' || item === null) continue;
    const record = item as Record<string, unknown>;
    if (typeof record.id === 'string' && typeof record.question === 'string') {
      result.set(record.id, record.question);
    }
  }
  return result;
}
