import type { AuthoringContent, AuthoringWorkflow } from '@/api/authoring';
import {
  CHAPTERS,
  canAccessChapter,
  canFinalize,
  type AuthoringChapter,
} from '@/lib/authoring';

/**
 * 顶部创作阶段进度条。
 *
 * 四章一次只聚焦一章，进度横向铺开在向导顶端：编号圆点 + 短连接线，已定稿
 * 章节显示对号。不是单向锁：已定稿的章节随时可以回去修改，修改会让下游进入
 * 待复核，因此完成标记不阻止点击；未解锁章节禁用并以 title 给出原因。
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
  /** 草稿固定后进度条只用于回看，不允许再进入编辑。 */
  readonly locked?: boolean;
  readonly onSelect: (chapter: AuthoringChapter) => void;
}) {
  return (
    <nav aria-label="创作步骤" className="flex min-w-0 flex-1 items-start">
      {CHAPTERS.map((chapter, index) => {
        const unlocked = locked !== true && canAccessChapter(workflow, content, chapter.id);
        const done = chapterDone(workflow, content, chapter.id);
        const status = chapter.id === 'final'
          ? (done ? 'accepted' : 'pending')
          : workflow[chapter.id];
        const isActive = active === chapter.id;
        return (
          <div key={chapter.id} className="flex flex-1 flex-col items-center last:flex-none">
            <div className="relative flex h-7 w-full items-center justify-center">
              {index > 0 ? (
                <span
                  className={`absolute left-0 right-1/2 top-1/2 h-px -translate-y-1/2 ${
                    chapterDone(workflow, content, CHAPTERS[index - 1]!.id)
                      ? 'bg-accent/50'
                      : 'bg-border-subtle'
                  }`}
                  aria-hidden="true"
                />
              ) : null}
              {index < CHAPTERS.length - 1 ? (
                <span
                  className={`absolute left-1/2 right-0 top-1/2 h-px -translate-y-1/2 ${
                    done ? 'bg-accent/50' : 'bg-border-subtle'
                  }`}
                  aria-hidden="true"
                />
              ) : null}
              <button
                type="button"
                disabled={!unlocked}
                onClick={() => {
                  onSelect(chapter.id);
                }}
                title={unlocked ? chapter.subtitle : lockReason(workflow, chapter.id)}
                aria-current={isActive ? 'step' : undefined}
                className={`relative z-10 flex size-7 items-center justify-center rounded-full border text-[12px] font-semibold transition-colors ${railCircleClass(
                  status,
                  isActive,
                  unlocked,
                )}`}
              >
                {done ? <CheckIcon /> : <span>{index + 1}</span>}
              </button>
            </div>
            <button
              type="button"
              disabled={!unlocked}
              onClick={() => {
                onSelect(chapter.id);
              }}
              tabIndex={-1}
              className="mt-1.5 flex flex-col items-center gap-0.5 px-1 text-center disabled:cursor-not-allowed"
            >
              <span
                className={`text-[12px] font-medium leading-4 ${
                  isActive ? 'text-content' : unlocked ? 'text-content-muted' : 'text-content-faint'
                }`}
              >
                {chapter.title}
              </span>
              <span className="text-[10px] leading-3 text-content-faint">{chapter.subtitle}</span>
            </button>
          </div>
        );
      })}
    </nav>
  );
}

/** 该章是否已完成：终章用可定格条件，其余看阶段定稿状态。连接线点亮也用它。 */
function chapterDone(
  workflow: AuthoringWorkflow,
  content: AuthoringContent,
  chapter: AuthoringChapter,
): boolean {
  if (chapter === 'final') return canFinalize(workflow, content);
  return workflow[chapter] === 'accepted';
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
