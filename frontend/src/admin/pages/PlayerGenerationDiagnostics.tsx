import { useInfiniteQuery } from '@tanstack/react-query';
import { request, type SchemaOf } from '@/api/http';
import { ErrorNotice } from '@/components/ErrorNotice';
import { queryKeys } from '@/api/queryKeys';

export function PlayerGenerationDiagnostics({ playerId }: { playerId: string }) {
  const images = useInfiniteQuery({
    queryKey: queryKeys.admin.playerGenerations(playerId, 'images'),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => request<SchemaOf<'Page_ManagementGenerationView_'>>(`/internal/players/${playerId}/image-generations`, { query: { cursor: pageParam, limit: 20 } }),
    getNextPageParam: (page) => page.has_more ? page.cursor ?? undefined : undefined,
    refetchInterval: 10000,
  });
  const candidates = useInfiniteQuery({
    queryKey: queryKeys.admin.playerGenerations(playerId, 'candidates'),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => request<SchemaOf<'Page_ManagementCandidateView_'>>(`/internal/players/${playerId}/character-candidates`, { query: { cursor: pageParam, limit: 20 } }),
    getNextPageParam: (page) => page.has_more ? page.cursor ?? undefined : undefined,
    refetchInterval: 10000,
  });
  return <div className="my-4 space-y-4 text-xs">
    <section className="space-y-2"><h3 className="font-semibold">图片生成诊断</h3>
      {images.data?.pages.flatMap((page) => page.items).map((item) => <dl key={item.generation_id} className="space-y-1 break-all rounded border border-border-subtle p-3">
        <div>任务：{item.generation_id} · {item.purpose} · {item.status}</div>
        <div>错误类型：{item.error_code ?? '无'}</div><div>提供方任务：{item.provider_task_id ?? '无'}</div><div>截止时间：{item.deadline_utc}</div>
      </dl>)}
      {images.data?.pages.every((page) => !page.items.length) ? <p className="text-content-faint">没有图片生成任务。</p> : null}
      {images.hasNextPage ? <button disabled={images.isFetchingNextPage} onClick={() => void images.fetchNextPage()}>读取更多图片任务</button> : null}
      <ErrorNotice error={images.error} diagnostic />
    </section>
    <section className="space-y-2"><h3 className="font-semibold">人物创作诊断</h3>
      {candidates.data?.pages.flatMap((page) => page.items).map((item) => <dl key={item.candidate_id} className="space-y-1 break-all rounded border border-border-subtle p-3">
        <div>候选：{item.candidate_id} · {item.operation} · {item.status}</div><div>草稿：{item.draft_id} · 修订 {item.input_revision}</div>
        <div>错误类型：{item.error_code ?? '无'}</div><div>模型：{item.model_profile} · 请求 {item.model_requests} 次</div><div>截止时间：{item.deadline_utc}</div>
      </dl>)}
      {candidates.data?.pages.every((page) => !page.items.length) ? <p className="text-content-faint">没有人物创作任务。</p> : null}
      {candidates.hasNextPage ? <button disabled={candidates.isFetchingNextPage} onClick={() => void candidates.fetchNextPage()}>读取更多创作任务</button> : null}
      <ErrorNotice error={candidates.error} diagnostic />
    </section>
  </div>;
}
