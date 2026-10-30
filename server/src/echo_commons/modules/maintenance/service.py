import logging
from collections.abc import Callable

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.maintenance.contracts import CleanupBlocker, CleanupRequest, CleanupResult
from echo_commons.modules.maintenance.repository import CleanupRepository, selected

logger = logging.getLogger(__name__)


class Maintenance:
    def __init__(
        self,
        database: Database,
        notify: Callable[[frozenset[str]], None],
        active_tasks: Callable[[], tuple[str, ...]],
        active_documents: Callable[[], frozenset[int]],
        assets=None,
        active_generations: Callable[[], set[str]] = set,
    ):
        self.database, self.notify = database, notify
        self.active_tasks, self.active_documents = active_tasks, active_documents
        self.repository = CleanupRepository()
        self.assets, self.active_generations = assets, active_generations

    def cleanup(self, request: CleanupRequest) -> CleanupResult:
        transaction = self.database.read if request.dry_run else self.database.transaction
        with transaction() as connection:
            result = self.repository.preview(connection, request)
            selected_assets = [
                row[0]
                for row in connection.execute(
                    selected("image_assets", "asset_id") + " ORDER BY source_asset_id IS NULL"
                )
            ]
            generations = {
                row[0] for row in connection.execute(selected("image_generations", "generation_id"))
            }
            generations.update(
                row[0]
                for row in connection.execute(
                    "SELECT generation_id FROM image_generations WHERE "
                    "json_extract(request_json,'$.draft_id') IN "
                    f"({selected('character_authoring_drafts', 'draft_id')})"
                )
            )
            for generation_id in self.active_generations() & generations:
                result.blockers.append(
                    CleanupBlocker(
                        kind="image_generation", object_id=generation_id, reason="图片调用尚未结束"
                    )
                )
            selected_tasks = {
                row[0]
                for table, column in (
                    ("conversation_tasks", "task_id"),
                    ("activity_tasks", "task_id"),
                    ("reflection_node_tasks", "node_task_id"),
                )
                for row in connection.execute(selected(table, column))
            }
            selected_documents = {
                row[0]
                for row in connection.execute(selected("memory_search_documents", "document_id"))
            }
            for task_id in set(self.active_tasks()) & selected_tasks:
                result.blockers.append(
                    CleanupBlocker(
                        kind="runtime_task", object_id=task_id, reason="任务调用尚未结束"
                    )
                )
            for document_id in self.active_documents() & selected_documents:
                result.blockers.append(
                    CleanupBlocker(
                        kind="memory_vector", object_id=str(document_id), reason="向量索引正在生成"
                    )
                )
            communities = frozenset(
                row[0] for row in connection.execute(selected("communities", "community_id"))
            )
            if not request.dry_run and not result.blockers:
                self.repository.delete(connection)
                result.deleted = True
        if result.deleted and self.assets is not None:
            # 数据库已解除引用；文件删除中断时保留 deleting 状态，启动维护继续执行。
            for asset_id in selected_assets:
                self.assets.finish_delete(asset_id)
        if result.deleted and communities:
            try:
                self.notify(communities)
            except Exception:
                logger.exception("Realtime notification failed after cleanup commit")
        return result
