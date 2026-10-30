from uuid import uuid4

from echo_commons.execution.clock import utc_now
from echo_commons.infrastructure.models.decision_protocol import ChoiceQuestion, DecisionRequest
from echo_commons.modules.activities.domain.task import ActivityMode
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import CharacterNotReady, ConflictError


class ActivityCoordinator:
    def __init__(self, database, context, tasks, decisions, models, lifecycle):
        self.database, self.context, self.tasks = database, context, tasks
        self.decisions, self.models, self.lifecycle = decisions, models, lifecycle

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
                    if observed.view is None or observed.context.game.status != "running":
                        continue
                    for opportunity in observed.view.opportunities:
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
                        request = None
                        if mode == "decision":
                            request = self.decisions.prepare(
                                DecisionRequest(
                                    invocation_id=uuid4(),
                                    trace_id=uuid4(),
                                    agent_id=f"character:{scope.community_id}:{scope.character_id}",
                                    state=None,
                                    questions={
                                        "action": ChoiceQuestion(
                                            instructions="结合人物和局势选择行动，必要时进一步理解。",
                                            criteria={"understand": "进一步理解"},
                                        )
                                    },
                                )
                            ).model_copy(update={"deadline_utc": None})
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
        return tuple(scheduled)
