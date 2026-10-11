import { useEffect, useRef, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { ArrowLeft } from 'lucide-react';
import { Shell } from './Shell';

export function CommunityDetailLayout({ title, description, cover, children, actions }: {
  readonly title: string; readonly description: string; readonly cover: string | null;
  readonly children: ReactNode; readonly actions: ReactNode;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  const close = () => {
    if (location.state?.fromList) void navigate(-1);
    else void navigate('/app/communities', { replace: true, state: location.state });
  };
  return <Shell section="subject" list={null}>
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <article className="mx-auto max-w-5xl animate-rise-in sm:p-6 lg:p-8">
          <div className="relative h-48 overflow-hidden bg-gradient-to-br from-surface-overlay to-surface-sunken sm:h-60 sm:rounded-card">
            {cover ? <img src={cover} alt={`${title}封面预览`} className="h-full w-full object-cover" /> : null}
            <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-black/10" />
            <button type="button" onClick={close} aria-label="返回社群列表"
              className="absolute left-4 top-4 flex items-center gap-2 rounded-full border border-white/15 bg-black/25 px-3 py-2 text-[12px] text-white backdrop-blur-sm hover:bg-black/45 focus-visible:outline-2 focus-visible:outline-accent"><ArrowLeft size={15} />返回社群</button>
            <div className="absolute inset-x-0 bottom-0 px-5 pb-5 sm:px-7 sm:pb-7">
              <h1 ref={heading} tabIndex={-1} className="display-title break-words text-[26px] text-white outline-none sm:text-[32px]">{title}</h1>
              <p className="mt-2 text-[13px] text-white/70">{description}</p>
            </div>
          </div>
          <div className="space-y-6 px-5 py-6 sm:px-1 sm:py-7">{children}</div>
        </article>
      </div>
      <footer className="shrink-0 border-t border-border-subtle bg-surface-sunken/90 px-5 py-4 backdrop-blur-xl sm:px-8">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-end gap-3">{actions}</div>
      </footer>
    </div>
  </Shell>;
}
