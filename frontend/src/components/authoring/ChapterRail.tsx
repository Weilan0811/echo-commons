import type { AuthoringContent, AuthoringWorkflow } from '@/api/authoring';
import {
  CHAPTERS,
  canAccessChapter,
  canFinalize,
  type AuthoringChapter,
} from '@/lib/authoring';

/**
 * 章节进度轨。
 *
 * 不是单向锁：已定稿的章节随时可以回去修改，修改会让下游进入待复核，因此
 * 完成标记不阻止点击。未解锁章节禁用并给出原因；终章在基础确认后即可进入，
 * 它是提前结束创作的出口。
 */
export function ChapterRail({
  workflow,
  content,
  active,
  locked,
  onSelect,
}: {
  readonly workflow: AuthoringWorkflow;
  readonly content: AuthoringContent;
  readonly active: AuthoringChapter;
  /** 草稿固定后章节轨只用于回看，不允许再进入编辑。 */
  readonly locked?: boolean;
  readonly onSelect: (chapter: AuthoringChapter) => void;
}) {
  return (
    <nav aria-label="创作步骤" className="flex flex-col">
      {CHAPTERS.map((chapter, index) => {
        const unlocked = locked !== true && canAccessChapter(workflow, content, chapter.id);
        const status = chapter.id === 'final'
          ? (canFinalize(workflow, content) ? 'accepted' : 'pending')
          : workflow[chapter.id];
        const isActive = active === chapter.id;
        return (
          <div key={chapter.id} className="flex flex-1 last:flex-none">
            <div className="flex flex-col items-center">
              <button
                type="button"
                disabled={!unlocked}
                onClick={() => {
                  onSelect(chapter.id);
                }}
                title={unlocked ? chapter.subtitle : lockReason(workflow, chapter.id)}
                aria-current={isActive ? 'step' : undefined}
                className={railCircleClass(status, isActive, unlocked)}
              >
                {status === 'accepted' ? <CheckIcon /> : <span>{index + 1}</span>}
              </button>
              {index < CHAPTERS.length - 1 ? (
                <span
                  className={`my-1 w-px flex-1 min-h-4 ${
                    status === 'accepted' ? 'bg-accent/50' : 'bg-border-subtle'
                  }`}
                  aria-hidden="true"
                />
              ) : null}
            </div>
            <button
              type="button"
              disabled={!unlocked}
              onClick={() => {
                onSelect(chapter.id);
              }}
              tabIndex={-1}
              className="mb-1 ml-3 flex -translate-y-1 flex-col items-start text-left disabled:cursor-not-allowed"
            >
              <span
                className={`text-[13px] font-medium leading-5 ${
                  isActive ? 'text-content' : unlocked ? 'text-content-muted' : 'text-content-faint'
                }`}
              >
                {chapter.title}
              </span>
              <span className="text-[10px] leading-4 text-content-faint">{chapter.subtitle}</span>
            </button>
          </div>
        );
      })}
    </nav>
  );
}

function lockReason(workflow: AuthoringWorkflow, chapter: AuthoringChapter): string {
  if (chapter === 'story' || chapter === 'final') return '先确认基础人设';
  if (chapter === 'interview') {
    return workflow.story === 'unused'
      ? '完成「来历」故事后才能进入对谈'
      : '先确认过去故事';
  }
  return '';
}

function railCircleClass(status: string, active: boolean, unlocked: boolean): string {
  const base =
    'flex size-7 shrink-0 items-center justify-center rounded-full border text-[12px] font-semibold transition-colors';
  if (!unlocked) return `${base} border-border-subtle text-content-faint/60 cursor-not-allowed`;
  if (status === 'accepted') {
    return `${base} border-accent bg-accent text-accent-ink ${active ? 'ring-2 ring-accent/30' : ''}`;
  }
  if (status === 'review_required') {
    return `${base} border-warn bg-warn/15 text-warn animate-breathe ${active ? 'ring-2 ring-warn/30' : ''}`;
  }
  if (active) return `${base} border-accent bg-accent-soft text-accent`;
  return `${base} border-border-strong text-content-muted hover:border-accent/60`;
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2}>
      <path d="M3.5 8.5l3 3 6-7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
