import { WandSparkles } from 'lucide-react';
import type { AuthoringContent } from '@/api/authoring';

type Introduction = NonNullable<AuthoringContent['introduction']>;
const groups: { key: keyof Introduction; title: string; hint: string; fields: [string, string, number, number?][] }[] = [
  { key: 'identity', title: '关于 TA', hint: '资料可以留空，也可以用自己的说法。', fields: [
    ['nickname', '称呼', 80], ['age', '年龄', 80], ['gender', '性别', 80],
    ['occupation', '身份或职业', 300], ['residence', '生活环境', 300],
  ] },
  { key: 'daily_life', title: '生活里的小事', hint: '每行一条，最多十条。', fields: [
    ['hobbies', '爱好', 200, 10], ['likes', '喜欢的事物', 200, 10],
    ['dislikes', '讨厌的事物', 200, 10], ['habits', '小习惯', 200, 10], ['skills', '特长', 200, 10],
  ] },
  { key: 'personality', title: '性格与相处', hint: '可以写一个具体情景里的反应。', fields: [
    ['typical_reactions', '常见反应', 500], ['values', '在意的事情', 500],
    ['stranger_style', '与陌生人的相处', 500], ['close_style', '与熟人的相处', 500], ['boundaries', '明确限制', 500],
  ] },
  { key: 'speech', title: '听 TA 说话', hint: '典型台词每行一句，最多三句。', fields: [
    ['examples', '典型台词', 200, 3], ['notes', '语气补充', 500],
  ] },
  { key: 'appearance', title: 'TA 的模样', hint: '插画会使用这里保存的外貌。', fields: [
    ['hair', '发型与发色', 500], ['eyes', '眼睛', 500], ['physique', '体型或身高', 500],
    ['outfit', '常见衣着', 500], ['distinctive_features', '辨识特征', 500], ['notes', '外貌补充', 500],
  ] },
];

export function IntroductionCard({ introduction, readOnly, onChange, onIllustrate, busy }: {
  introduction: Introduction;
  readOnly: boolean;
  onChange: (value: Introduction) => void;
  onIllustrate: () => void;
  busy: boolean;
}) {
  return <div className="space-y-4">
    {groups.map((group) => <details key={group.key} open={group.key === 'identity' || group.key === 'appearance'} className="paper-sheet rounded-xl border border-border-subtle p-4">
      <summary className="cursor-pointer text-sm font-semibold text-content">{group.title}</summary>
      <div className="mt-3 flex items-center justify-between gap-3">
        <p className="text-xs text-content-faint">{group.hint}</p>
        {group.key === 'appearance' ? <button type="button" aria-label="生成角色形象" title="保存资料并打开插画面板" disabled={busy} onClick={onIllustrate} className="flex shrink-0 items-center gap-1.5 rounded-full border border-accent/30 px-3 py-1.5 text-xs text-accent hover:bg-accent/10 disabled:opacity-40"><WandSparkles size={14} />生成形象</button> : null}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {group.fields.map(([field, label, limit, count]) => {
          const values = (introduction[group.key] ?? {}) as Record<string, string | string[]>;
          const value = values[field] ?? (count ? [] : '');
          const text = Array.isArray(value) ? value.join('\n') : value;
          return <label key={field} className="flex flex-col gap-1.5 text-xs text-content-muted">
            {label}
            <textarea value={text} disabled={readOnly} rows={count || limit > 300 ? 2 : 1}
              maxLength={count ? count * (limit + 1) : limit}
              onChange={(event) => onChange({ ...introduction, [group.key]: {
                ...values, [field]: count ? event.target.value.split('\n') : event.target.value,
              } })}
              className="w-full resize-y rounded-lg border border-border-subtle bg-surface-sunken/50 px-3 py-2 text-sm leading-relaxed outline-none focus:border-accent/60 disabled:opacity-70" />
          </label>;
        })}
      </div>
    </details>)}
  </div>;
}
