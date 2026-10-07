import type { ReactNode } from 'react';

/**
 * 页面区块标题。
 *
 * 三个主体页面共用同一套标题规格：标题、说明、操作区。没有它每页各写一套
 * 标题，间距和字号很快就会漂移。
 */
export function PageHeading({
  title,
  description,
  actions,
}: {
  readonly title: string;
  readonly description: string;
  readonly actions?: ReactNode;
}) {
  return (
    <header className="flex shrink-0 items-start justify-between gap-6 border-b border-border-subtle px-8 pb-5 pt-7">
      <div className="max-w-xl">
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-content-faint">{description}</p>
      </div>
      {actions === undefined ? null : <div className="shrink-0">{actions}</div>}
    </header>
  );
}

/** 主操作。琥珀实心，同一屏只应有一个。 */
export function PrimaryButton({
  onClick,
  disabled,
  children,
}: {
  readonly onClick: () => void;
  readonly disabled?: boolean;
  readonly children: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled ?? false}
      className="rounded-lg bg-accent px-4 py-2 text-[13px] font-semibold text-accent-ink transition-[filter,transform] hover:brightness-110 active:scale-[0.98] disabled:opacity-40"
    >
      {children}
    </button>
  );
}

/** 次要操作。描边按钮，与主操作并排时层次分明。 */
export function SecondaryButton({
  onClick,
  disabled,
  children,
}: {
  readonly onClick: () => void;
  readonly disabled?: boolean;
  readonly children: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled ?? false}
      className="rounded-lg border border-border-subtle px-4 py-2 text-[13px] text-content-muted transition-colors hover:border-border-strong hover:text-content disabled:opacity-40"
    >
      {children}
    </button>
  );
}

/** 表单字段。标签在上、输入在下，三个页面的表单规格一致。 */
export function Field({
  label,
  hint,
  value,
  onChange,
  placeholder,
}: {
  readonly label: string;
  readonly hint?: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly placeholder: string;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[11px] font-medium text-content-muted">{label}</span>
      <input
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        placeholder={placeholder}
        className="rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2.5 text-sm text-content outline-none transition-colors placeholder:text-content-faint focus:border-accent/60"
      />
      {hint === undefined ? null : <span className="text-[11px] text-content-faint">{hint}</span>}
    </label>
  );
}