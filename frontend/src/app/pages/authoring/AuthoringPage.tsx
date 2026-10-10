import type { ReactNode } from 'react';
import { Link, useParams } from 'react-router';
import { useCurrentSubject } from '@/identity/useCurrentSubject';
import { EmptyState } from '@/components/EmptyState';
import { SceneBackground } from '@/components/SceneBackground';
import { NewDraftStart } from './NewDraftStart';
import { AuthoringWizard } from './AuthoringWizard';

/**
 * 自定义人物创作。
 *
 * 整页沉浸式向导，不套三栏 Shell：创作是一段连续的「写人物志」过程，不需要
 * 会话列表与聊天导航。authoring/new 是起始屏，其余路径是具体草稿的四章向导。
 */
export function AuthoringPage() {
  const { draftId } = useParams<{ readonly draftId: string }>();
  const { subject } = useCurrentSubject();

  if (subject.playerId === '') {
    return (
      <AuthoringFrame>
        <EmptyState
          title="先登记身份"
          description="草稿属于作者本人，登记身份后才能开始创作。"
        >
          <Link
            to="/app/identity"
            className="rounded-lg bg-accent px-4 py-2 text-[13px] font-semibold text-accent-ink hover:brightness-110"
          >
            去登记身份
          </Link>
        </EmptyState>
      </AuthoringFrame>
    );
  }

  if (draftId === undefined || draftId === '' || draftId === 'new') {
    return (
      <AuthoringFrame>
        <NewDraftStart playerId={subject.playerId} />
      </AuthoringFrame>
    );
  }

  // 向导同样套统一外框：创作中途随时能经顶栏回到角色页，草稿按修订号保留。
  return (
    <AuthoringFrame>
      <AuthoringWizard playerId={subject.playerId} draftId={draftId} />
    </AuthoringFrame>
  );
}

/** 创作页共同外框：夜景背景上的透明顶栏，主内容由各屏自行排版。 */
export function AuthoringFrame({ children }: { readonly children: ReactNode }) {
  return (
    <div className="relative flex h-screen flex-col overflow-hidden">
      <SceneBackground />
      <header className="z-10 flex shrink-0 items-center gap-3 px-5 py-3.5">
        <Link
          to="/app/characters"
          className="glass-soft rounded-full px-3.5 py-1.5 text-[12px] text-content-muted transition-colors hover:text-content"
        >
          ← 返回角色
        </Link>
        <span className="text-sm font-semibold tracking-wide">人物志</span>
        <span className="rounded-full bg-white/8 px-2 py-0.5 text-[11px] text-content-muted">
          自定义人物
        </span>
      </header>
      <div className="min-h-0 flex-1 overflow-x-clip overflow-y-auto px-4 pb-4">{children}</div>
    </div>
  );
}
