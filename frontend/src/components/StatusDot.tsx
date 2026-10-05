type Tone = 'ok' | 'warn' | 'danger' | 'idle';

const TONE_COLOR: Record<Tone, string> = {
  ok: 'var(--color-ok)',
  warn: 'var(--color-warn)',
  danger: 'var(--color-danger)',
  idle: 'var(--color-border-strong)',
};

/** 状态指示点。用于诊断与设置类视图，不用于聊天与游戏界面。 */
export function StatusDot({ tone, label }: { readonly tone: Tone; readonly label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <span
        className="inline-block size-2 rounded-full"
        style={{ backgroundColor: TONE_COLOR[tone] }}
        aria-hidden="true"
      />
      {label}
    </span>
  );
}
