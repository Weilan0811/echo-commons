import { useDeferredValue, useState } from 'react';
import { Link } from 'react-router';
import { AdminPage, AdminListState, AdminSection, StatusBadge } from '@/components/Admin';
import { useAdminCommunitySearch } from '@/api/admin';

/**
 * 社群总览。
 *
 * 管理侧接入顺序的第一步是发现社群：其余对象的查询都绑定社群范围，
 * 没有社群就无从读起。这里不做筛选与搜索，等社群数量真的多起来再说。
 */
export function AdminCommunityPage() {
  const [search, setSearch] = useState('');
  const query = useDeferredValue(search.trim());
  const communities = useAdminCommunitySearch(query);
  const items = communities.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <AdminPage title="社群" subtitle="管理查询的起点。其余对象都绑定社群范围。">
      <label className="mb-5 flex flex-col gap-2 text-[12px] text-content-muted">
        查找社群
        <input value={search} onChange={(event) => setSearch(event.target.value)}
          placeholder="输入名称或编号，例如 wide-test"
          className="rounded-lg border border-border-subtle bg-surface-sunken px-3 py-2 text-content" />
      </label>
      <AdminSection
        title={`已加载 ${items.length} 个社群${communities.hasNextPage ? '，还有更多' : ''}`}
        count={items.length}
        actions={
          <button
            type="button"
            onClick={() => {
              void communities.fetchNextPage();
            }}
            className="text-[11px] text-content-faint hover:text-content"
            disabled={!communities.hasNextPage || communities.isFetchingNextPage}
          >
            读取更多
          </button>
        }
      >
        <AdminListState
          isPending={communities.isPending}
          error={communities.error}
          isEmpty={items.length === 0}
          emptyText="没有社群。"
        >
          <table className="w-full">
            <thead>
              <tr className="text-left text-[11px] text-content-faint">
                <th className="py-1.5 font-normal">名称</th>
                <th className="py-1.5 font-normal">标识</th>
                <th className="py-1.5 font-normal">时区</th>
                <th className="py-1.5 font-normal">状态</th>
                <th className="py-1.5 font-normal">版本</th>
                <th className="py-1.5 font-normal">世界时间</th>
              </tr>
            </thead>
            <tbody>
              {items.map((community) => (
                <tr key={community.community_id} className="border-t border-border-subtle/60">
                  <td className="py-1.5 pr-3">
                    <Link
                      to={'/admin/communities/' + community.community_id}
                      className="text-[13px] text-content hover:text-accent"
                    >
                      {community.name}
                    </Link>
                  </td>
                  <td className="tabular py-1.5 pr-3 text-[12px] text-content-muted">
                    {community.community_id}
                  </td>
                  <td className="py-1.5 pr-3 text-[12px] text-content-muted">{community.timezone}</td>
                  <td className="py-1.5 pr-3">
                    <StatusBadge value={community.status} />
                  </td>
                  <td className="tabular py-1.5 pr-3 text-[12px] text-content-muted">
                    {community.state_version}
                  </td>
                  <td className="tabular py-1.5 text-[12px] text-content-muted">
                    {community.world_time_utc.replace('T', ' ').slice(0, 19)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </AdminListState>

        {communities.hasNextPage ? (
          <p className="pt-3 text-[11px] text-content-faint">还有更多社群。</p>
        ) : null}
      </AdminSection>
    </AdminPage>
  );
}
