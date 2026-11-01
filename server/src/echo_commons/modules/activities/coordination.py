from uuid import UUID, uuid4

from echo_commons.execution.clock import utc_now
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.infrastructure.models.decision_protocol import ChoiceQuestion, DecisionRequest
from echo_commons.modules.activities.domain.task import ActivityMode
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import CharacterNotReady, ConflictError


class ActivityCoordinator:
    def __init__(self, database, context, tasks, decisions, models, lifecycle, sources):
        self.database, self.context, self.tasks = database, context, tasks
        self.decisions, self.models, self.lifecycle = decisions, models, lifecycle
        self.sources = sources

    def scan(self):
        scheduled = []
        with self.database.transaction() as connection:
            now = utc_now()
            self.lifecycle.reconcile_in(connection, now)
            rows = connection.execute(
                "SELECT i.community_id,i.character_id FROM character_instances i "
                "JOIN communities c USING(community_id) WHERE c.status='active' "
                "AND i.memory_status='ready' AND i.availability_status='available'"
            ).fetchall()
            for row in rows:
                for participation in self.context.observations.participation.participations(
                    connection, row["community_id"], ActorRef("character", row["character_id"])
                ):
                    if participation.left_at_utc is not None:
                        continue
                    try:
                        scope = self.context._scope_in(
                            connection,
                            row["community_id"],
                            row["character_id"],
                            participation.game_id,
                            participation.participation_id,
                        )
                        observed = self.context.observations.observe_in(
                            connection,
                            row["community_id"],
                            row["character_id"],
                            participation.game_id,
                            participation_id=participation.participation_id,
                            limit=1,
                        )
                    except (CharacterNotReady, ConflictError):
                        continue
                    active = self.tasks.active(connection, scope)
                    queued = self.sources.queued(connection, scope)
                    opportunities = (
                        observed.view.opportunities
                        if observed.view and observed.context.game.status == "running"
                        else ()
                    )
                    for opportunity in opportunities:
                        previous = connection.execute(
                            "SELECT status FROM activity_tasks WHERE game_id=? "
                            "AND participation_id=? AND opportunity_id=? "
                            "ORDER BY created_at_utc DESC,task_id DESC LIMIT 1",
                            (scope.game_id, scope.participation_id, opportunity.opportunity_id),
                        ).fetchone()
                        if not active and previous and (previous[0] == "completed" or not queued):
                            continue
                        mode = (
                            ActivityMode.AUTOMATIC
                            if len(opportunity.legal_actions) == 1
                            else ActivityMode.DECISION
                            if self.decisions
                            else ActivityMode.ORDINARY
                        )
                        if mode != "automatic":
                            supported = any(
                                (a.game_type, a.ruleset_id, a.ruleset_version)
                                == (
                                    observed.view.game_type,
                                    observed.view.ruleset_id,
                                    observed.view.ruleset_version,
                                )
                                for a in self.context.gameplay.analyzers
                            )
                            if not supported:
                                continue
                        request = self.request(scope, mode)
                        if active:
                            if (
                                active["purpose"] == "reply"
                                and active["status"] != "processing"
                                and not self.tasks.frozen(connection, active)
                            ):
                                connection.execute(
                                    "UPDATE activity_tasks SET purpose='turn',opportunity_id=?,"
                                    "state_version=?,view_json=?,mode=?,model_profile=?,"
                                    "decision_request_json=?,updated_at_utc=? WHERE task_id=?",
                                    (
                                        opportunity.opportunity_id,
                                        observed.view.state_version,
                                        observed.view.model_dump_json(),
                                        mode,
                                        self.models.route_for("activity_turn").resolved_profile,
                                        request.model_copy(
                                            update={"trace_id": UUID(active["trace_id"])}
                                        ).model_dump_json()
                                        if request
                                        else None,
                                        utc_text(now),
                                        active["task_id"],
                                    ),
                                )
                                active = self.tasks.get(connection, active["task_id"])
                            if active["purpose"] == "turn":
                                scheduled.append(active["task_id"])
                            break
                        identity = self.tasks.add(
                            connection,
                            scope,
                            observed.view,
                            opportunity,
                            mode,
                            self.models.route_for("activity_turn").resolved_profile,
                            request,
                            now,
                        )
                        scheduled.append(identity)
                        active = self.tasks.get(connection, identity)
                        break
                    if active is None and queued:
                        identity = str(uuid4())
                        mode = ActivityMode.DECISION if self.decisions else ActivityMode.ORDINARY
                        self.tasks.add(
                            connection,
                            scope,
                            observed.view,
                            None,
                            mode,
                            self.models.route_for("activity_reply").resolved_profile,
                            self.request(scope, mode),
                            now,
                            purpose="reply",
                            identity=identity,
                            state_version=observed.context.game.state_version,
                        )
                        scheduled.append(identity)
                        active = self.tasks.get(connection, identity)
                    if (
                        active
                        and active["mode"] != "automatic"
                        and not self.tasks.frozen(connection, active)
                    ):
                        self.sources.attach(connection, active["task_id"], queued, now)
        return tuple(scheduled)

    def request(self, scope, mode):
        if mode != "decision":
            return None
        return self.decisions.prepare(
            DecisionRequest(
                invocation_id=uuid4(),
                trace_id=uuid4(),
                agent_id=f"character:{scope.community_id}:{scope.character_id}",
                state=None,
                questions={
                    "participation": ChoiceQuestion(
                        instructions="结合眼前语境判断是否交流。",
                        criteria={"understand": "进一步理解"},
                        allow_none=False,
                    )
                },
            )
        ).model_copy(update={"deadline_utc": None})
