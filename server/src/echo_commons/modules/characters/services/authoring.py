import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from echo_commons.agents.authoring import AuthoringAgent, AuthoringFailure, AuthoringUsage
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.infrastructure.models.registry import ModelConfigurationError
from echo_commons.infrastructure.models.routing import TaskRouting
from echo_commons.modules.assets.domain import image_url
from echo_commons.modules.assets.repository import AssetRepository
from echo_commons.modules.characters.domain.authoring import (
    OUTPUT_ADAPTER,
    AuthoringContent,
    AuthoringWorkflow,
    BlueprintImmutable,
    CalibrationConflictError,
    CandidateRequest,
    CandidateStale,
    DocumentsReviewRequired,
    DraftRevisionConflict,
    InterviewBasis,
    InterviewSelectionInvalid,
    Stage,
    StageDependencyUnmet,
    merge_candidate,
)
from echo_commons.modules.characters.repositories.authoring import (
    AuthoringRepository,
    candidate_view,
    draft_view,
)
from echo_commons.modules.characters.services.blueprints import BLUEPRINT_ADAPTER
from echo_commons.modules.characters.services.people import CharacterPeople
from echo_commons.modules.characters.templates.authoring import introduction_documents
from echo_commons.modules.characters.templates.catalog import (
    CapabilitiesResource,
    CharacterBlueprint,
    IdentityCapability,
    IdentityResource,
)
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.shared.errors import IdempotencyConflict
from echo_commons.shared.management import PageOptions, read_page


class CharacterAuthoring:
    def __init__(
        self,
        database: Database,
        agent: AuthoringAgent,
        routing: TaskRouting,
    ) -> None:
        self.database, self.agent, self.routing = database, agent, routing
        self.repository = AuthoringRepository()

    def create(
        self,
        player_id: str,
        draft_id: str,
        content: AuthoringContent,
        *,
        copied_from: str | None = None,
        create_request: dict | None = None,
    ) -> tuple[dict, bool]:
        initial = json.dumps(
            {
                "request": create_request or {"content": content.model_dump(mode="json")},
                "copied_from": copied_from,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        with self.database.transaction() as connection:
            CommunityRepository().player(connection, player_id)
            CharacterPeople.validate_materials(connection, player_id, content)
            existing = connection.execute(
                "SELECT * FROM character_authoring_drafts WHERE draft_id=?",
                (draft_id,),
            ).fetchone()
            if existing:
                row = self.repository.draft(connection, draft_id, player_id)
                if row["create_request_json"] != initial:
                    raise IdempotencyConflict("Draft ID already has different creation content")
                return draft_view(row), False
            self.bind_avatar(connection, "draft", draft_id, player_id, content)
            now = utc_text(datetime.now(UTC))
            connection.execute(
                "INSERT INTO character_authoring_drafts "
                "(draft_id,owner_player_id,status,revision,content_json,workflow_json,create_request_json,"
                "created_at_utc,updated_at_utc) VALUES (?,?,'draft',1,?,?,?,?,?)",
                (
                    draft_id,
                    player_id,
                    content.model_dump_json(),
                    AuthoringWorkflow.initial(
                        content, copied=copied_from is not None
                    ).model_dump_json(),
                    initial,
                    now,
                    now,
                ),
            )
            return draft_view(self.repository.draft(connection, draft_id, player_id)), True

    @staticmethod
    def bind_avatar(connection, kind, object_id, player_id, content):
        AssetRepository().bind(
            connection, kind, object_id, content.avatar_asset_id, player_id, "character_avatar"
        )

    @staticmethod
    def editable(row: dict, revision: int) -> None:
        if row["status"] != "draft":
            raise BlueprintImmutable("Confirmed character content is immutable")
        if row["revision"] != revision:
            raise DraftRevisionConflict("Read the current draft before saving")

    def get(self, player_id: str, draft_id: str) -> dict:
        with self.database.read() as connection:
            return draft_view(self.repository.draft(connection, draft_id, player_id))

    def page(self, player_id: str, options: PageOptions, *, blueprints: bool = False) -> dict:
        with self.database.read() as connection:
            CommunityRepository().player(connection, player_id)
            page = self.repository.page(connection, player_id, options, blueprints=blueprints)
            if blueprints:
                page["items"] = [self.blueprint_view(row, detail=False) for row in page["items"]]
            else:
                page["items"] = [draft_view(row) for row in page["items"]]
            return page

    def save(self, connection, row, content, workflow, *, candidate_id=None):
        CharacterPeople.validate_materials(connection, row["owner_player_id"], content)
        changed = (
            content.model_dump_json() != row["content_json"]
            or workflow.model_dump_json() != row["workflow_json"]
        )
        if not changed and candidate_id is None:
            return draft_view(row)
        self.bind_avatar(connection, "draft", row["draft_id"], row["owner_player_id"], content)
        revision = row["revision"] + int(changed or candidate_id is not None)
        connection.execute(
            "UPDATE character_authoring_drafts SET content_json=?,workflow_json=?,revision=?,"
            "accepted_candidate_id=?,accepted_candidate_revision=?,updated_at_utc=? "
            "WHERE draft_id=?",
            (
                content.model_dump_json(),
                workflow.model_dump_json(),
                revision,
                candidate_id or row["accepted_candidate_id"],
                revision if candidate_id else row["accepted_candidate_revision"],
                utc_text(datetime.now(UTC)),
                row["draft_id"],
            ),
        )
        return draft_view(
            self.repository.draft(connection, row["draft_id"], row["owner_player_id"])
        )

    def update(
        self, player_id: str, draft_id: str, revision: int, content: AuthoringContent
    ) -> dict:
        with self.database.transaction() as connection:
            row = self.repository.draft(connection, draft_id, player_id)
            self.editable(row, revision)
            previous = AuthoringContent.model_validate_json(row["content_json"])
            workflow = AuthoringWorkflow.model_validate_json(row["workflow_json"]).edited(
                previous, content
            )
            return self.save(connection, row, content, workflow)

    def confirm_stage(self, player_id: str, draft_id: str, revision: int, stage: Stage):
        with self.database.transaction() as connection:
            row = self.repository.draft(connection, draft_id, player_id)
            self.editable(row, revision)
            content = AuthoringContent.model_validate_json(row["content_json"])
            workflow = AuthoringWorkflow.model_validate_json(row["workflow_json"])
            return self.save(connection, row, content, workflow.confirmed(stage, content))

    def template_documents(self, player_id, draft_id, revision, *, accept=False):
        with self.database.transaction() as connection:
            row = self.repository.draft(connection, draft_id, player_id)
            self.editable(row, revision)
            previous = AuthoringContent.model_validate_json(row["content_json"])
            output = introduction_documents(previous)
            if not accept:
                return {"input_revision": revision, "output": output}
            content = merge_candidate(previous, output)
            workflow = AuthoringWorkflow.model_validate_json(row["workflow_json"])
            return self.save(connection, row, content, workflow.edited(previous, content))

    def confirm_documents(self, player_id: str, draft_id: str, revision: int):
        with self.database.transaction() as connection:
            row = self.repository.draft(connection, draft_id, player_id)
            self.editable(row, revision)
            content = AuthoringContent.model_validate_json(row["content_json"])
            workflow = AuthoringWorkflow.model_validate_json(row["workflow_json"])
            if workflow.basic != "accepted":
                workflow.require_complete_materials(content)
            if content.has_history():
                workflow.require("story", content)
                if workflow.story != "accepted":
                    raise StageDependencyUnmet("Confirm story before reviewing documents")
            return self.save(
                connection,
                row,
                content,
                workflow.model_copy(update={"documents_review": "accepted"}),
            )

    def accept(self, player_id: str, draft_id: str, revision: int, candidate_id: str):
        with self.database.transaction() as connection:
            row = self.repository.draft(connection, draft_id, player_id)
            self.editable(row, revision)
            candidate = self.repository.candidate(connection, draft_id, candidate_id)
            if (
                row["accepted_candidate_id"] == candidate_id
                and row["accepted_candidate_revision"] == revision
            ):
                return draft_view(row)
            if candidate["status"] != "completed" or candidate["input_revision"] != revision:
                raise CandidateStale("Candidate is incomplete or belongs to an older draft")
            output = OUTPUT_ADAPTER.validate_json(candidate["output_json"])
            if output.operation == "calibrate" and output.conflicts:
                raise CalibrationConflictError("Resolve calibration conflicts before accepting")
            previous = AuthoringContent.model_validate_json(row["content_json"])
            content = merge_candidate(previous, output)
            workflow = AuthoringWorkflow.model_validate_json(row["workflow_json"])
            if output.operation == "calibrate":
                workflow = workflow.model_copy(update={"documents_review": "accepted"})
            else:
                workflow = workflow.edited(previous, content)
            return self.save(connection, row, content, workflow, candidate_id=candidate_id)

    def copy(self, player_id: str, source_id: str, draft_id: str) -> tuple[dict, bool]:
        with self.database.read() as connection:
            # 重复复制返回原草稿，不受源草稿后续编辑影响。
            existing = connection.execute(
                "SELECT * FROM character_authoring_drafts WHERE draft_id=?",
                (draft_id,),
            ).fetchone()
            if existing:
                row = self.repository.draft(connection, draft_id, player_id)
                if json.loads(row["create_request_json"])["copied_from"] != source_id:
                    raise IdempotencyConflict("Draft ID belongs to another creation request")
                return draft_view(row), False
            row = self.repository.draft(connection, source_id, player_id)
            content = AuthoringContent.model_validate_json(row["content_json"])
        return self.create(player_id, draft_id, content, copied_from=source_id)

    def confirm(self, player_id: str, draft_id: str, revision: int) -> tuple[dict, bool]:
        with self.database.transaction() as connection:
            row = self.repository.draft(connection, draft_id, player_id)
            if row["revision"] != revision:
                raise DraftRevisionConflict("Read the current draft before confirmation")
            if row["status"] == "confirmed":
                resource = self.repository.blueprint(connection, row["confirmed_blueprint_id"])
                return self.blueprint_view(resource), False
            content = AuthoringContent.model_validate_json(row["content_json"])
            AuthoringWorkflow.model_validate_json(row["workflow_json"]).require_complete(content)
            blueprint_id = "custom:" + str(uuid4())
            now = datetime.now(UTC)
            blueprint = build_blueprint(blueprint_id, content, now)
            self.bind_avatar(connection, "blueprint", blueprint_id, player_id, content)
            if content.avatar_asset_id:
                avatar = AssetRepository().get(connection, content.avatar_asset_id, player_id)
                blueprint = replace(
                    blueprint,
                    avatar_url=image_url(content.avatar_asset_id),
                    illustration_url=image_url(avatar["source_asset_id"]),
                )
            connection.execute(
                "INSERT INTO custom_character_blueprints VALUES (?,?,?,?,?,?,?)",
                (
                    blueprint_id,
                    draft_id,
                    player_id,
                    blueprint.content_version,
                    BLUEPRINT_ADAPTER.dump_json(blueprint).decode(),
                    content.model_dump_json(),
                    utc_text(now),
                ),
            )
            connection.execute(
                "UPDATE character_authoring_drafts SET status='confirmed',"
                "confirmed_blueprint_id=?,updated_at_utc=? WHERE draft_id=?",
                (blueprint_id, utc_text(now), draft_id),
            )
            return self.blueprint_view(self.repository.blueprint(connection, blueprint_id)), True

    def blueprint(self, player_id: str, blueprint_id: str) -> dict:
        with self.database.read() as connection:
            return self.blueprint_view(
                self.repository.blueprint(connection, blueprint_id, player_id)
            )

    @staticmethod
    def blueprint_view(row: dict, *, detail: bool = True) -> dict:
        resource = BLUEPRINT_ADAPTER.validate_json(row["resource_json"])
        view = {
            "blueprint_id": row["blueprint_id"],
            "content_version": row["content_version"],
            "source_draft_id": row["source_draft_id"],
            "owner_player_id": row["owner_player_id"],
            "display_name": resource.display_name,
            "avatar_url": resource.avatar_url,
            "illustration_url": resource.illustration_url,
            "avatar_asset_id": resource.avatar_asset_id,
            "material_processing": "stored_only",
            "created_at_utc": row["created_at_utc"],
        }
        if detail:
            view["content"] = AuthoringContent.model_validate_json(row["materials_json"])
        return view

    def candidate(self, player_id: str, draft_id: str, candidate_id: str) -> dict:
        with self.database.transaction() as connection:
            self.repository.draft(connection, draft_id, player_id)
            row = self.repository.candidate(connection, draft_id, candidate_id)
            if row["status"] == "processing" and row["deadline_utc"] <= utc_text(datetime.now(UTC)):
                connection.execute(
                    "UPDATE character_authoring_candidates SET status='failed',"
                    "error_code='authoring_interrupted',finished_at_utc=? WHERE candidate_id=?",
                    (utc_text(datetime.now(UTC)), candidate_id),
                )
                row = self.repository.candidate(connection, draft_id, candidate_id)
            return candidate_view(row)

    def management_candidates(self, player_id, options):
        with self.database.read() as connection:
            CommunityRepository().player(connection, player_id)
            result = read_page(
                connection,
                "SELECT c.* FROM character_authoring_candidates c "
                "JOIN character_authoring_drafts d ON c.draft_id=d.draft_id "
                "WHERE d.owner_player_id=?",
                (player_id,),
                scope={"query": "managed_character_candidates", "player_id": player_id},
                order=("created_at_utc", "candidate_id"),
                options=options,
                descending=True,
            )
            result["items"] = [candidate_view(row) for row in result["items"]]
            return result

    def start_candidate(
        self,
        player_id: str,
        draft_id: str,
        request: CandidateRequest,
    ) -> tuple[dict, AuthoringContent, list[dict], bool]:
        with self.database.transaction() as connection:
            row = self.repository.draft(connection, draft_id, player_id)
            candidate_id = str(request.candidate_id)
            exists = connection.execute(
                "SELECT * FROM character_authoring_candidates WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
            if exists:
                existing = self.repository.candidate(connection, draft_id, candidate_id)
                saved = json.loads(existing["request_json"])
                if saved["request"] != request.model_dump(mode="json"):
                    raise IdempotencyConflict("Candidate ID already has another request")
                return existing, AuthoringContent.model_validate(saved["content"]), [], False
            self.editable(row, request.expected_revision)
            content = AuthoringContent.model_validate_json(row["content_json"])
            workflow = AuthoringWorkflow.model_validate_json(row["workflow_json"])
            questions = []
            basis = None
            if request.operation == "story":
                workflow.require("story", content)
            elif request.operation == "interview":
                workflow.require("interview", content)
                choices = {item.question_id: item for item in content.interview}
                if any(key not in choices for key in request.question_ids):
                    raise InterviewSelectionInvalid("Question ID is not in this draft's selection")
                questions = [
                    {"id": key, "question": choices[key].question} for key in request.question_ids
                ]
                basis = workflow.interview_basis
                if basis is None:
                    if workflow.documents_review != "accepted":
                        raise DocumentsReviewRequired(
                            "Review persona documents before starting interview"
                        )
                    basis = InterviewBasis(
                        **content.model_dump(
                            include={
                                "profile",
                                "voice",
                                "relational_dynamics",
                                "story",
                                "description",
                                "display_name",
                                "introduction",
                                "relationships",
                            }
                        ),
                        agent_contract=self.agent.prompts["interview"],
                        expression_guidance="",
                    )
                    # 建立依据不属于作者编辑，不推进作者 revision。
                    workflow = workflow.model_copy(update={"interview_basis": basis})
                    connection.execute(
                        "UPDATE character_authoring_drafts SET workflow_json=? WHERE draft_id=?",
                        (workflow.model_dump_json(), draft_id),
                    )
            elif request.operation == "calibrate":
                workflow.require_complete_materials(content)
            now = datetime.now(UTC)
            route = "character_authoring"
            if request.operation == "interview":
                route = (
                    "character_interview"
                    if "character_interview" in self.routing.task_profiles
                    else "conversation_reply"
                )
            profile = self.routing.route_for(route).resolved_profile
            frozen = {
                "request": request.model_dump(mode="json"),
                "content": content.model_dump(mode="json"),
                "questions": questions,
                "workflow": workflow.model_dump(mode="json"),
                "interview_basis": basis.model_copy(
                    update={
                        "agent_contract": self.agent.prompts["interview"],
                        "expression_guidance": "",
                    }
                ).model_dump(mode="json")
                if basis
                else None,
                "model_profile": profile,
                "review_model_profile": self.routing.route_for(
                    "character_interview_review"
                ).resolved_profile
                if request.operation == "interview"
                else None,
                "prompt_version": "2.0",
                "review_reasoning_effort": "low" if request.operation == "interview" else None,
                "interview_review_prompt": self.agent.interview_review
                if request.operation == "interview"
                else None,
                "prompt": self.agent.prepare_prompt(
                    request.operation,
                    basis.model_dump(mode="json") if basis else None,
                ),
            }
            connection.execute(
                "INSERT INTO character_authoring_candidates "
                "(candidate_id,draft_id,input_revision,operation,request_json,status,model_profile,"
                "deadline_utc,created_at_utc) VALUES (?,?,?,?,?,'processing',?,?,?)",
                (
                    candidate_id,
                    draft_id,
                    row["revision"],
                    request.operation,
                    json.dumps(frozen, ensure_ascii=False),
                    profile,
                    utc_text(now + timedelta(seconds=90)),
                    utc_text(now),
                ),
            )
            return (
                self.repository.candidate(connection, draft_id, candidate_id),
                content,
                questions,
                True,
            )

    def finish_candidate(
        self,
        draft_id: str,
        candidate_id: str,
        output: str | None,
        error: str | None,
        usage: AuthoringUsage,
    ) -> dict:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE character_authoring_candidates SET status=?,output_json=?,error_code=?,"
                "model_requests=?,usage_json=?,finished_at_utc=? "
                "WHERE candidate_id=? AND status='processing'",
                (
                    "failed" if error else "completed",
                    output,
                    error,
                    usage.model_requests,
                    json.dumps(usage.summary()),
                    utc_text(datetime.now(UTC)),
                    candidate_id,
                ),
            )
            return candidate_view(self.repository.candidate(connection, draft_id, candidate_id))

    async def generate(
        self,
        player_id: str,
        draft_id: str,
        request: CandidateRequest,
    ) -> tuple[dict, int]:
        row, content, questions, created = await asyncio.to_thread(
            self.start_candidate,
            player_id,
            draft_id,
            request,
        )
        candidate_id = str(request.candidate_id)
        if not created:
            result = await asyncio.to_thread(self.candidate, player_id, draft_id, candidate_id)
            return result, 200
        usage = AuthoringUsage()
        deadline = datetime.fromisoformat(row["deadline_utc"])
        error, output, status = None, None, 201
        try:
            async with asyncio.timeout(max(0, (deadline - datetime.now(UTC)).total_seconds())):
                candidate = await self.agent.generate(
                    content,
                    request,
                    questions,
                    player_id=player_id,
                    profile=row["model_profile"],
                    deadline=deadline,
                    usage=usage,
                    frozen_input=json.loads(row["request_json"]),
                )
                output = candidate.model_dump_json()
        except AuthoringFailure as failure:
            error, status = failure.code, failure.status_code
        except ModelConfigurationError:
            error, status = "authoring_model_unavailable", 503
        except TimeoutError:
            error, status = "authoring_timeout", 504
        except asyncio.CancelledError:
            await asyncio.shield(
                asyncio.to_thread(
                    self.finish_candidate,
                    draft_id,
                    candidate_id,
                    None,
                    "authoring_interrupted",
                    usage,
                )
            )
            raise
        result = await asyncio.to_thread(
            self.finish_candidate,
            draft_id,
            candidate_id,
            output,
            error,
            usage,
        )
        if result["error_code"] and not error:
            status = 409
        return result, status


def build_blueprint(
    blueprint_id: str, content: AuthoringContent, now: datetime
) -> CharacterBlueprint:
    def identity(kind: str, suffix: str, body: str) -> IdentityResource:
        return IdentityResource(
            1,
            kind,
            blueprint_id + "." + suffix,
            "0.1.0",
            "active",
            "zh-CN",
            now.date().isoformat(),
            body,
            source_ref=blueprint_id,
        )

    capabilities = CapabilitiesResource(
        1,
        "character_capabilities",
        blueprint_id + ".capabilities",
        "0.1.0",
        "active",
        "zh-CN",
        now.date().isoformat(),
        (
            IdentityCapability(
                "memory_search",
                "查询自己的允许记忆材料",
                json.dumps(
                    {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 5},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    }
                ),
            ),
        ),
        source_ref=blueprint_id,
    )
    return CharacterBlueprint(
        resource_id=blueprint_id,
        display_name=content.display_name,
        content_version="0.1.0",
        status="active",
        locale="zh-CN",
        updated_at=now.date().isoformat(),
        profile=identity("character_profile", "profile", content.profile),
        voice=identity("character_voice", "voice", content.voice),
        relational_dynamics=identity(
            "relational_dynamics",
            "relations",
            content.relational_dynamics,
        ),
        capabilities_resource=capabilities,
        avatar_url=content.avatar_url,
        avatar_asset_id=content.avatar_asset_id,
        source_ref=blueprint_id,
    )
