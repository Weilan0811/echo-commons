from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    community_ids: list[str] = Field(default_factory=list)
    draft_ids: list[str] = Field(default_factory=list)
    player_ids: list[str] = Field(default_factory=list)
    dry_run: bool = True

    @model_validator(mode="after")
    def validate_scope(self):
        scopes = (self.community_ids, self.draft_ids, self.player_ids)
        if not any(scopes):
            raise ValueError("至少指定一个社群、草稿或玩家编号")
        if any(not value.strip() for scope in scopes for value in scope):
            raise ValueError("对象编号不能为空")
        return self


class CleanupBlocker(BaseModel):
    kind: str
    object_id: str
    reason: str


class CleanupError(BaseModel):
    code: Literal["cleanup_blocked"] = "cleanup_blocked"
    message: str = "运行状态或范围外引用阻止清理，请查看 blockers"


class CleanupResult(BaseModel):
    error: CleanupError | None = None
    dry_run: bool
    deleted: bool = False
    counts: dict[str, int]
    missing: dict[str, list[str]]
    blockers: list[CleanupBlocker]
    retained_resources: list[str] = Field(
        default_factory=lambda: ["诊断捕获文件", "日志", "备份", "数据库全局事件序号"]
    )
