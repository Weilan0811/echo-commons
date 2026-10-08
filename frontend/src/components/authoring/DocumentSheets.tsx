import type { AuthoringContent } from '@/api/authoring';

/** 三份运行正文的字段定义；各步共用同一组标签与顺序。 */
export const DOCUMENT_FIELDS = [
  { key: 'profile', title: '身份与性格', hint: 'TA 是谁、在意什么' },
  { key: 'voice', title: '说话方式', caption: '措辞、节奏与习惯表达' },
  { key: 'relational_dynamics', title: '相处倾向', caption: '怎样亲近、怎样保持距离' },
] as const;

export type DocumentFieldKey = (typeof DOCUMENT_FIELDS)[number]['key'];

/**
 * 三份运行正文卷轴卡。
 *
 * 它们是角色运行时真正读取的内容，与故事/采访这些作者原稿分开呈现；
 * 支持就地编辑，字数上限取自模板 limits，不由界面假设。
 */
export function DocumentSheets({
  form,
  limits,
  readOnly,
  onPatch,
}: {
  readonly form: AuthoringContent;
  readonly limits: {
    readonly profile: number;
    readonly voice: number;
    readonly relational_dynamics: number;
  };
  readonly readOnly?: boolean;
  /** 只读模式不需要写回入口。 */
  readonly onPatch?: (changes: Partial<AuthoringContent>) => void;
}) {
  const isReadOnly = readOnly === true;
  return (
    <div className="grid gap-3">
      {DOCUMENT_FIELDS.map((field) => (
        <DocumentSheet
          key={field.key}
          field={field}
          value={form[field.key]}
          limit={limits[field.key]}
          readOnly={isReadOnly}
          onChange={(value) => onPatch?.({ [field.key]: value })}
        />
      ))}
    </div>
  );
}

function DocumentSheet({
  field,
  value,
  limit,
  readOnly,
  onChange,
}: {
  readonly field: (typeof DOCUMENT_FIELDS)[number];
  readonly value: string;
  readonly limit: number;
  readonly readOnly: boolean;
  readonly onChange: (value: string) => void;
}) {
  return (
    <article className="rounded-card border border-border-subtle bg-surface-overlay/60 p-4">
      <header className="flex items-baseline justify-between gap-3">
        <div>
          <h4 className="text-[13px] font-semibold text-content">{field.title}</h4>
          {'hint' in field ? (
            <p className="mt-0.5 text-[10px] text-content-faint">{field.hint}</p>
          ) : (
            <p className="mt-0.5 text-[10px] text-content-faint">{field.caption}</p>
          )}
        </div>
        {readOnly ? (
          <span className="text-[10px] text-content-faint">运行正文</span>
        ) : (
          <span className={'tabular text-[10px] ' + (value.length > limit ? 'text-danger' : 'text-content-faint')}>
            {value.length}/{limit}
          </span>
        )}
      </header>
      {readOnly ? (
        <p className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-content-muted">
          {value.trim() === '' ? '（暂无内容）' : value}
        </p>
      ) : (
        <textarea
          value={value}
          maxLength={limit}
          onChange={(event) => onChange(event.target.value)}
          rows={5}
          className="mt-2 w-full resize-y rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2 text-[13px] leading-relaxed outline-none transition-colors focus:border-accent/60"
        />
      )}
    </article>
  );
}
