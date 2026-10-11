import { useState } from 'react';
import { useParams } from 'react-router';
import { AdminPage, AdminListState, AdminSection, FieldRow, MonoCell, TimeCell } from '@/components/Admin';
import { useAdminPlayer, useAdminPlayers } from '@/api/admin';
import { PlayerGenerationDiagnostics } from './PlayerGenerationDiagnostics';

/**
 * 玩家列表。
 *
 * 管理侧的玩家不按社群过滤，因此能看到从未加入任何社群、也从未发言的
 * 玩家。这类记录在玩家端不可见，但排障时经常需要确认「这个人到底存不存在」。
 */
export function AdminPlayerPage() {
  const [limit, setLimit] = useState(20);
  const players = useAdminPlayers({ limit });
  const items = players.data?.items ?? [];

  return (
    <AdminPage title="玩家" subtitle="管理侧不过滤社群，因此这里包含从未加入任何社群的玩家。">
      <AdminSection
        title="全部玩家"
        count={items.length}
        actions={
          <button
            type="button"
            onClick={() => {
              setLimit((value) => value + 20);
            }}
            className="text-[11px] text-content-faint hover:text-content"
          >
            读取更多
          </button>
        }
      >
        <AdminListState
          isPending={players.isPending}
          error={players.error}
          isEmpty={items.length === 0}
          emptyText="没有玩家。"
        >
          <ul className="flex flex-col">
            {items.map((player) => (
              <li key={player.player_id} className="border-t border-border-subtle/60 py-1.5">
                <PlayerRow playerId={player.player_id} name={player.display_name} />
              </li>
            ))}
          </ul>
        </AdminListState>
      </AdminSection>
    </AdminPage>
  );
}

/** 玩家行。展开后读取详情，列表本身不请求两次。 */
function PlayerRow({ playerId, name }: { readonly playerId: string; readonly name: string }) {
  const [open, setOpen] = useState(false);
  const detail = useAdminPlayer(open ? playerId : null);

  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="flex cursor-pointer items-baseline gap-3">
        <span className="min-w-0 flex-1 truncate text-[13px]">{name}</span>
        <MonoCell>{playerId}</MonoCell>
      </summary>
      {open ? (
        <div className="mt-1.5 pl-3">
          <AdminListState
            isPending={detail.isPending}
            error={detail.error}
            isEmpty={false}
            emptyText=""
          >
            <div className="flex flex-col">
              <FieldRow label="创建时间">
                <TimeCell value={detail.data?.created_at_utc} />
              </FieldRow>
            </div>
          </AdminListState>
          <PlayerGenerationDiagnostics playerId={playerId} />
        </div>
      ) : null}
    </details>
  );
}
