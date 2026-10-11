import { useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Sparkles, X } from 'lucide-react';

/**
 * 灵感助手抽屉。
 *
 * 创作时默认收起，信纸始终是视线焦点；需要 AI 帮忙时从右侧滑出一张悬浮信纸。
 * 面板常驻挂载：抽屉关闭期间生成轮询不中断、候选状态不丢失，作者关掉抽屉写完
 * 原文，回来仍能接受同一份建议。
 *
 * 面板必须经 Portal 挂到 body：触发钮在信纸章节内部，祖先上的入场动画
 * （animate-rise-in 保留了最终 transform）会成为 fixed 的包含块，让关闭态
 * 面板没有真正移出视口、只露出一小条，打开时位置也是错的。Portal 后面板
 * 相对视口定位，关闭态整体移到视口外并被外层裁掉，不留下任何缝隙。
 */
export function InspirationDrawer({
  label = '灵感助手',
  disabled = false,
  children,
}: {
  readonly label?: string;
  readonly disabled?: boolean;
  readonly children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  // 打开时聚焦关闭钮、Esc 关闭并把焦点还给触发钮；不锁页面滚动（布局本身满屏）。
  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      triggerRef.current?.focus();
    };
  }, [open]);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        onClick={() => {
          setOpen(true);
        }}
        className="inline-flex items-center gap-1.5 rounded-full border border-accent/50 bg-accent-soft px-3.5 py-1.5 text-[12px] font-medium text-accent transition-colors hover:bg-accent/20 disabled:opacity-40"
      >
        <Sparkles className="size-3.5" strokeWidth={2} />
        {label}
      </button>

      {createPortal(
        /*
         * 外层与视口等大并裁切溢出：面板关闭时停在视口右侧之外，既看不见也
         * 撑不出滚动区域；pointer-events-none 让关闭态完全不拦截交互。
         */
        <div
          className={`fixed inset-0 z-[60] overflow-clip ${open ? '' : 'pointer-events-none'}`}
          aria-hidden={!open}
        >
          <button
            type="button"
            tabIndex={-1}
            aria-label="关闭创作灵感"
            onClick={() => {
              setOpen(false);
            }}
            className={`absolute inset-0 bg-black/45 backdrop-blur-[2px] transition-opacity duration-300 ${
              open ? 'animate-fade-in cursor-default opacity-100' : 'opacity-0'
            }`}
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="创作灵感"
            inert={!open}
            className="paper-sheet absolute inset-y-3 right-3 flex w-[min(460px,calc(100vw-1.5rem))] flex-col rounded-card outline-none transition-transform duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] will-change-transform sm:inset-y-4 sm:right-4"
            style={{ transform: open ? 'translateX(0)' : 'translateX(calc(100% + 1.5rem))' }}
          >
            <header className="relative z-10 flex shrink-0 items-center justify-between border-b border-ink/15 px-7 py-4">
              <div className="flex items-center gap-2.5">
                <span className="flex size-8 items-center justify-center rounded-full bg-ink-accent/12 text-ink-accent">
                  <Sparkles className="size-4" strokeWidth={2} />
                </span>
                <span className="display-title text-[18px] text-ink">创作灵感</span>
              </div>
              <button
                ref={closeRef}
                type="button"
                onClick={() => {
                  setOpen(false);
                }}
                aria-label="关闭灵感助手"
                className="rounded-full p-1.5 text-ink-faint transition-colors hover:bg-ink/10 hover:text-ink"
              >
                <X className="size-4.5" strokeWidth={2} />
              </button>
            </header>
            <div className="paper-zone relative z-10 min-h-0 flex-1 overflow-y-auto px-7 py-6">
              {children}
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
