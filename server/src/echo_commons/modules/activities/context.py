import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from weakref import WeakValueDictionary

from pydantic import BaseModel, TypeAdapter

from echo_commons.agents.contracts.activity import (
    ACTIVITY_REPLY_CONTRACT,
    ACTIVITY_REPLY_SELECTION_CONTRACT,
    PREPARATION_ADAPTER,
    ActivityEvidence,
    ActivityMaterial,
    ActivityObservationSnapshot,
    ActivityPrivateThought,
    ActivityReactionInput,
    ActivityReplyInput,
    ActivityResponseProgress,
    ActivityScope,
    ActivityTurnInput,
    ActivityUnderstanding,
    PersonaProjection,
    ReactionPreparation,
    ReplyPreparation,
    TurnPreparation,
    selection_contract,
    turn_contract,
)
from echo_commons.agents.contracts.context import ContextSnapshot, MemoryItem, SnapshotScope
from echo_commons.agents.contracts.input import ActionSpace, SourceVersion
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.models.decision_protocol import DecisionRequest
from echo_commons.modules.activities.contracts import ActivityContextPolicy
from echo_commons.modules.activities.gameplay.contracts import AnalysisRequest, GameplayAnalysis
from echo_commons.modules.activities.gameplay.registry import GameplayRegistry
from echo_commons.modules.activities.observation import GameObservationService
from echo_commons.modules.activities.persona import ActivityPersona
from echo_commons.modules.activities.repositories.inputs import (
    ActivityInputRepository,
    scope_values,
)
from echo_commons.modules.activities.repositories.sources import ActivitySources
from echo_commons.modules.activities.tasks.prompt import (
    decision_material,
    decision_questions,
    material_size,
)
from echo_commons.modules.activities.working_memory import ActivityWorkingMemory
from echo_commons.modules.conversations.tasks.context import ConversationContext
from echo_commons.modules.conversations.tasks.memory import budget_snapshot
from echo_commons.modules.memory.services.retrieval import SearchScope
from echo_commons.modules.perspective.contracts import ObservationScope
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError, IdempotencyConflict


class ActivityContext:
    def __init__(
        self,
        database: Database,
        observations: GameObservationService,
        conversation: ConversationContext,
        gameplay: GameplayRegistry,
        persona: ActivityPersona,
        working_memory: ActivityWorkingMemory,
        policy: ActivityContextPolicy,
    ) -> None:
        self.database, self.observations, self.conversation = database, observations, conversation
        self.gameplay, self.persona, self.working_memory, self.policy = (
            gameplay,
            persona,
            working_memory,
            policy,
        )
        self.inputs = ActivityInputRepository()
        self.expression_permissions = None
        self._locks: WeakValueDictionary[tuple[str, str, str], asyncio.Lock] = WeakValueDictionary()

    def _scope_in(self, connection, community_id, character_id, game_id, participation_id):
        context = self.observations.participation.participant_context(
            connection, community_id, ActorRef("character", character_id), game_id, participation_id
        )
        member = self.conversation.conversations.current(
            connection, context.conversation_id, ActorRef("character", character_id)
        )
        return ActivityScope(
            community_id=community_id,
            character_id=character_id,
            game_id=game_id,
            participation_id=context.access.participation_id,
            seat_id=context.access.seat_id,
            conversation_id=context.conversation_id,
            membership_id=member.membership_id,
        )

    def _sources_in(self, connection, scope):
        after_event, after_message, version = self.inputs.progress(connection, scope)
        observed = self.observations.observe_in(
            connection,
            scope.community_id,
            scope.character_id,
            scope.game_id,
            participation_id=scope.participation_id,
            after_sequence=after_event,
            limit=self.policy.event_limit,
        )
        conversation = self.conversation.conversations.get(
            connection, scope.community_id, scope.conversation_id
        )
        if conversation.status != "active" or observed.context.game.status == "cancelled":
            raise ConflictError("The activity no longer accepts new inputs")
        if self.conversation.communities.get(connection, scope.community_id).status != "active":
            raise ConflictError("The activity community is paused")
        messages = self.conversation.perspective.perspective.messages(
            connection,
            ObservationScope(
                scope.community_id,
                scope.conversation_id,
                ActorRef("character", scope.character_id),
                conversation.next_sequence - 1,
                scope.membership_id,
            ),
        )
        pending = tuple(
            m
            for m in messages
            if m.sequence > after_message and m.sender != ActorRef("character", scope.character_id)
        )
        return observed, conversation, messages, pending, (after_event, after_message, version)

    def pending_sources(self, community_id, character_id, game_id, *, participation_id=None):
        with self.database.read() as connection:
            scope = self._scope_in(
                connection, community_id, character_id, game_id, participation_id
            )
            observed, _, _, messages, _ = self._sources_in(connection, scope)
            return {
                "scope": scope,
                "message_ids": tuple(m.message_id for m in messages),
                "event_ids": tuple(e.event_id for e in observed.events.items),
                "has_more_events": observed.events.has_more,
            }

    def _capture(
        self, community_id, character_id, game_id, input_id, kind, participation_id, suggestions
    ):
        request = json.dumps(
            {
                "game_id": game_id,
                "kind": kind,
                "participation_id": participation_id,
                "suggested_actions": [a.model_dump(mode="json") for a in suggestions],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        with self.database.transaction() as connection:
            existing = self.inputs.find(connection, community_id, character_id, input_id)
            if existing:
                if existing["request_json"] != request:
                    raise IdempotencyConflict(
                        "Activity input ID has different preparation parameters"
                    )
                return dict(existing)
            scope = self._scope_in(
                connection, community_id, character_id, game_id, participation_id
            )
            observed, conversation, visible, pending, progress = self._sources_in(connection, scope)
            sources = connection.execute(
                "SELECT a.* FROM activity_task_sources a JOIN activity_tasks t USING(task_id) "
                "WHERE t.input_id=? AND a.status='attached'",
                (input_id,),
            ).fetchall()
            selected = set()
            situations = []
            for source in sources:
                selected.update(ActivitySources.message_ids(connection, source))
                initiation = connection.execute(
                    "SELECT i.situation FROM social_turns s JOIN conversation_initiations i "
                    "USING(initiation_id) WHERE s.social_turn_id=?",
                    (source["social_turn_id"],),
                ).fetchone()
                if initiation:
                    situations.append(initiation[0])
            pending = tuple(m for m in visible if m in pending or m.message_id in selected)
            work = self.working_memory.current_in(connection, scope)
            if kind == "turn" and (observed.view is None or not observed.view.opportunities):
                raise ConflictError("An activity turn requires a real current opportunity")
            if kind == "reply" and not pending and not situations:
                raise ConflictError("An activity reply requires an unprocessed visible message")
            if kind == "reaction" and not observed.events.items:
                raise ConflictError("An activity reaction requires visible game events")
            pinned = {m.reply_to_message_id for m in pending if m.reply_to_message_id}
            pinned.update(identity for intent in work.intents for identity in intent.message_ids)
            mandatory = tuple(m for m in visible if m in pending or m.message_id in pinned)
            member = self.conversation.conversations.current(
                connection, scope.conversation_id, ActorRef("character", character_id)
            )
            now = datetime.now(UTC)
            common = self.conversation.prepare_for(
                connection,
                SnapshotScope(
                    community_id=community_id,
                    character_id=character_id,
                    conversation_id=scope.conversation_id,
                    membership_id=scope.membership_id,
                    observation_upper_sequence=conversation.next_sequence - 1,
                ),
                member,
                mandatory,
                now,
                membership_version=conversation.membership_version,
                apply_budget=False,
                trigger_message_ids=tuple(m.message_id for m in pending),
                current_membership_only=True,
                situation=f"正在参加{observed.context.game.game_type}，当前游戏状态为{observed.context.game.status}。"
                + "\n".join(situations),
            )
            game = observed.context.game
            view = (
                observed.view
                if kind == "turn" or observed.view is None
                else observed.view.model_copy(update={"opportunities": ()})
            )
            frozen = ActivityObservationSnapshot(
                rules=self.observations.games.registry.resolve(
                    game.game_type, game.ruleset_id, game.ruleset_version
                ).instructions,
                game_type=game.game_type,
                ruleset_id=game.ruleset_id,
                ruleset_version=game.ruleset_version,
                status=game.status,
                state_version=game.state_version,
                occurred_at_utc=game.updated_at_utc,
                view=view,
                events=observed.events.items,
                after_event_sequence=progress[0],
                through_event_sequence=observed.events.next_sequence,
                has_more_events=observed.events.has_more,
                after_message_sequence=progress[1],
                through_message_sequence=conversation.next_sequence - 1,
                progress_version=progress[2],
            )
            thought_rows = connection.execute(
                "SELECT input_id,understood_at_utc,understanding_json FROM activity_inputs "
                "WHERE community_id=? AND character_id=? AND game_id=? AND participation_id=? "
                "AND understanding_json IS NOT NULL "
                "ORDER BY understood_at_utc DESC,input_id DESC LIMIT ?",
                (*scope_values(scope), self.policy.private_thought_limit),
            ).fetchall()
            thoughts = tuple(
                ActivityPrivateThought(
                    input_id=row["input_id"],
                    occurred_at_utc=row["understood_at_utc"],
                    thought=ActivityUnderstanding.model_validate_json(
                        row["understanding_json"]
                    ).thought,
                )
                for row in reversed(thought_rows)
                if ActivityUnderstanding.model_validate_json(
                    row["understanding_json"]
                ).thought.strip()
            )
            responses = []
            visible_ids = {m.message_id for m in visible}
            for source in connection.execute(
                "SELECT a.*,t.input_id,r.result_id FROM activity_task_sources a "
                "JOIN social_turns s USING(social_turn_id) "
                "LEFT JOIN activity_tasks t USING(task_id) "
                "LEFT JOIN activity_results r USING(task_id) "
                "WHERE s.conversation_id=? AND a.membership_id=? "
                "ORDER BY a.created_at_utc,a.source_id",
                (scope.conversation_id, scope.membership_id),
            ):
                ids = tuple(
                    identity
                    for identity in ActivitySources.message_ids(connection, source)
                    if identity in visible_ids
                )
                responses.append(
                    ActivityResponseProgress(
                        source_id=source["source_id"],
                        social_turn_id=source["social_turn_id"],
                        message_ids=ids,
                        status=source["status"],
                        current=source["input_id"] == input_id,
                        result_id=source["result_id"],
                    )
                )
            evidence = ActivityEvidence(
                conversation=common,
                game=frozen,
                working_memory=work,
                private_thoughts=thoughts,
                responses=tuple(responses),
                expression_allowed=bool(sources)
                or self.expression_permissions is None
                or self.expression_permissions(connection, scope.conversation_id),
                reaction_event_ids=tuple(
                    dict.fromkeys(
                        event_id
                        for source in sources
                        for opportunity in connection.execute(
                            "SELECT visible_event_ids_json FROM "
                            "activity_reaction_opportunities WHERE"
                            " source_id=?",
                            (source["source_id"],),
                        )
                        for event_id in json.loads(opportunity[0])
                    )
                ),
            )
            arguments = dict(input_id=input_id, scope=scope, evidence=evidence)
            if kind == "turn":
                preparation = TurnPreparation(
                    **arguments,
                    opportunity_id=view.opportunities[0].opportunity_id,
                    suggested_actions=tuple(a.model_dump(mode="json") for a in suggestions),
                )
            elif kind == "reply":
                preparation = ReplyPreparation(**arguments)
            else:
                preparation = ReactionPreparation(**arguments)
            self.inputs.add(connection, preparation, request)
            connection.execute(
                "UPDATE activity_task_sources SET status='frozen' WHERE task_id IN "
                "(SELECT task_id FROM activity_tasks WHERE input_id=?) AND status='attached'",
                (input_id,),
            )
            return dict(self.inputs.get(connection, community_id, character_id, input_id))

    def _save_stage(self, scope, input_id, stage, value):
        with self.database.transaction() as connection:
            self.inputs.save_stage(
                connection,
                scope.community_id,
                scope.character_id,
                input_id,
                stage,
                value.model_dump_json(),
            )

    async def _memory(self, common: ContextSnapshot) -> ContextSnapshot:
        if common.memory.retrieval_prepared:
            return common
        retrieval = self.conversation.retrieval
        policy = common.read_policy
        scope = SearchScope(
            common.scope.community_id,
            common.scope.character_id,
            common.prepared_at_utc,
            policy.conversation_id,
            policy.upper_sequence,
            conversations=policy.conversations,
        )
        version = next(v.version for v in common.source_versions if v.kind == "memory_search")
        hits = await retrieval.search_async(
            self.database,
            scope,
            common.memory.retrieval_query,
            limit=retrieval.policy.candidate_limit,
            expected_source_version=version,
        )
        existing = {i.content for i in (*common.memory.resident, *common.memory.segment_summaries)}
        existing.update(m.text for m in (*common.perspective.inputs, *common.perspective.history))
        recalled = tuple(
            MemoryItem(
                memory_id=h.source_id,
                content_version=h.source_version,
                content=h.text,
                source_kind=h.source_kind,
                occurred_at_utc=h.occurred_at_utc,
                context_label=h.context_label,
            )
            for h in retrieval.select_automatic(hits, existing)
        )
        return common.model_copy(
            update={
                "memory": common.memory.model_copy(
                    update={"recalled": recalled, "retrieval_prepared": True}
                ),
                "source_versions": (
                    *common.source_versions,
                    *(
                        SourceVersion(
                            kind=i.source_kind, source_id=i.memory_id, version=i.content_version
                        )
                        for i in recalled
                    ),
                ),
            }
        )

    def _restore(
        self, row: sqlite3.Row | dict
    ) -> ActivityTurnInput | ActivityReplyInput | ActivityReactionInput:
        data = json.loads(row["snapshot_json"])
        if row["kind"] == "turn":
            game = data["material"]["game"]
            analyzer = self.gameplay.resolve(
                game["game_type"], game["ruleset_id"], game["ruleset_version"]
            )
            return TypeAdapter(ActivityTurnInput[analyzer.action_model]).validate_python(data)
        cls = ActivityReplyInput if row["kind"] == "reply" else ActivityReactionInput
        return cls.model_validate(data)

    def restore(
        self, community_id: str, character_id: str, input_id: str
    ) -> ActivityTurnInput | ActivityReplyInput | ActivityReactionInput:
        with self.database.read() as connection:
            row = self.inputs.get(connection, community_id, character_id, input_id)
            if row["snapshot_json"] is None:
                raise ConflictError("Activity input preparation is incomplete")
            return self._restore(row)

    async def prepare_turn(
        self,
        community_id: str,
        character_id: str,
        game_id: str,
        *,
        input_id: str,
        participation_id: str | None = None,
        suggested_actions: tuple[BaseModel, ...] = (),
    ) -> ActivityTurnInput:
        return await self._prepare(
            community_id,
            character_id,
            game_id,
            input_id,
            "turn",
            participation_id,
            suggested_actions,
        )

    async def prepare_reply(
        self,
        community_id: str,
        character_id: str,
        game_id: str,
        *,
        input_id: str,
        participation_id: str | None = None,
    ) -> ActivityReplyInput:
        return await self._prepare(
            community_id, character_id, game_id, input_id, "reply", participation_id, ()
        )

    async def prepare_reaction(
        self,
        community_id: str,
        character_id: str,
        game_id: str,
        *,
        input_id: str,
        participation_id: str | None = None,
    ) -> ActivityReactionInput:
        return await self._prepare(
            community_id, character_id, game_id, input_id, "reaction", participation_id, ()
        )

    async def _prepare(
        self, community_id, character_id, game_id, input_id, kind, participation_id, suggestions
    ):
        key = (community_id, character_id, input_id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            row = await asyncio.to_thread(
                self._capture,
                community_id,
                character_id,
                game_id,
                input_id,
                kind,
                participation_id,
                suggestions,
            )
            if row["snapshot_json"] is not None:
                return self._restore(row)
            draft = PREPARATION_ADAPTER.validate_json(row["preparation_json"])
            scope = draft.scope
            common = (
                ContextSnapshot.model_validate_json(row["memory_json"])
                if row["memory_json"]
                else await self._memory(draft.evidence.conversation)
            )
            if row["memory_json"] is None:
                await asyncio.to_thread(self._save_stage, scope, input_id, "memory_json", common)
            persona = (
                PersonaProjection.model_validate_json(row["projection_json"])
                if row["projection_json"]
                else await self.persona.prepare(common)
            )
            if row["projection_json"] is None:
                await asyncio.to_thread(
                    self._save_stage, scope, input_id, "projection_json", persona
                )
            material = ActivityMaterial(
                **draft.evidence.model_dump(exclude={"conversation"}),
                conversation=common,
                decision_persona=persona,
            )
            arguments = dict(
                snapshot_id=input_id,
                prepared_at_utc=common.prepared_at_utc,
                scope=scope,
                action_space=ActionSpace(
                    output_contracts=(
                        turn_contract(material.game.game_type),
                        selection_contract(material.game.game_type),
                    )
                    if kind == "turn"
                    else (ACTIVITY_REPLY_CONTRACT, ACTIVITY_REPLY_SELECTION_CONTRACT),
                    tools=common.action_space.tools,
                ),
                source_versions=(
                    *common.source_versions,
                    SourceVersion(
                        kind="game", source_id=game_id, version=str(material.game.state_version)
                    ),
                    SourceVersion(
                        kind="activity_working_memory",
                        source_id=scope.participation_id,
                        version=str(material.working_memory.version),
                    ),
                ),
                material=material,
            )
            if kind == "turn":
                view = material.game.view
                analyzer = self.gameplay.resolve(
                    view.game_type, view.ruleset_id, view.ruleset_version
                )
                opportunity = next(
                    o for o in view.opportunities if o.opportunity_id == draft.opportunity_id
                )
                analysis = (
                    GameplayAnalysis[analyzer.action_model].model_validate_json(
                        row["analysis_json"]
                    )
                    if row["analysis_json"]
                    else await self.gameplay.analyze(
                        AnalysisRequest(
                            view=view,
                            opportunity=opportunity,
                            suggested_actions=tuple(
                                analyzer.action_model.model_validate(a)
                                for a in draft.suggested_actions
                            ),
                        )
                    )
                )
                if row["analysis_json"] is None:
                    await asyncio.to_thread(
                        self._save_stage, scope, input_id, "analysis_json", analysis
                    )
                result = ActivityTurnInput[analyzer.action_model](
                    **arguments, opportunity=opportunity, analysis=analysis
                )
            else:
                cls = ActivityReplyInput if kind == "reply" else ActivityReactionInput
                result = cls(**arguments)

            with self.database.read() as connection:
                decision_task = connection.execute(
                    "SELECT decision_request_json FROM activity_tasks WHERE input_id=?", (input_id,)
                ).fetchone()
            frozen_request = (
                DecisionRequest.model_validate_json(decision_task[0])
                if decision_task and decision_task[0]
                else None
            )

            def measure(value):
                candidate = result.model_copy(
                    update={"material": material.model_copy(update={"conversation": value})}
                )
                measured = max(material_size(candidate), material_size(candidate, decision=True))
                if frozen_request:
                    request = frozen_request.model_copy(
                        update={
                            "state": decision_material(candidate),
                            "questions": decision_questions(candidate),
                        }
                    )
                    size = len(json.dumps(request.payload(), ensure_ascii=False))
                    measured = max(
                        measured, size + self.policy.input_max_chars - request.route.input_max_chars
                    )
                return measured

            common = budget_snapshot(common, self.policy.input_max_chars, measure=measure)
            result = result.model_copy(
                update={"material": material.model_copy(update={"conversation": common})}
            )
            await asyncio.to_thread(self._save_stage, scope, input_id, "snapshot_json", result)
            return result

    def record_understanding(
        self, community_id: str, character_id: str, input_id: str, result: ActivityUnderstanding
    ) -> None:
        with self.database.transaction() as connection:
            return self.record_understanding_in(
                connection, community_id, character_id, input_id, result
            )

    def record_understanding_in(self, connection, community_id, character_id, input_id, result):
        row = self.inputs.get(connection, community_id, character_id, input_id)
        if row["snapshot_json"] is None:
            raise ConflictError("Activity input preparation is incomplete")
        if row["understanding_json"] is not None:
            if row["understanding_json"] != result.model_dump_json():
                raise IdempotencyConflict("Activity input already has a different understanding")
            return
        draft = PREPARATION_ADAPTER.validate_json(row["preparation_json"])
        current = self._scope_in(
            connection,
            community_id,
            character_id,
            draft.scope.game_id,
            draft.scope.participation_id,
        )
        if current != draft.scope:
            raise ConflictError("The activity membership changed")
        self._sources_in(connection, current)
        pending = draft.evidence.conversation.perspective.trigger_message_ids
        understood = tuple(m.message_id for m in result.messages)
        if (
            set(understood) != set(pending)
            or len(set(understood)) != len(understood)
            or set(result.event_ids) != {e.event_id for e in draft.evidence.game.events}
            or len(set(result.event_ids)) != len(result.event_ids)
        ):
            raise ValueError("Understanding must cover exactly the frozen visible sources")
        game = draft.evidence.game
        if self.inputs.progress(connection, current)[2] != game.progress_version:
            raise ConflictError("Another input already advanced these observation sources")
        connection.execute(
            "INSERT INTO activity_observation_progress VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(community_id,character_id,game_id,participation_id) DO UPDATE SET "
            "event_sequence=excluded.event_sequence,message_sequence=excluded.message_sequenc"
            "e,version=excluded.version",
            (
                *scope_values(current),
                game.through_event_sequence,
                game.through_message_sequence,
                game.progress_version + 1,
            ),
        )
        connection.execute(
            "UPDATE activity_inputs SET understanding_json=?,understood_at_utc=? WHERE input_id=?",
            (result.model_dump_json(), datetime.now(UTC).isoformat(), input_id),
        )
