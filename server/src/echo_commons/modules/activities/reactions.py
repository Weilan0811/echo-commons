import json
import random
from datetime import timedelta
from uuid import uuid4

from echo_commons.execution.clock import utc_now
from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.modules.activities.gameplay.contracts import GameplayAnalysisError
from echo_commons.modules.social.participation import Candidate, choose
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import CharacterNotReady, ConflictError, NotFoundError


class ActivityReactions:
    def __init__(self, database, context, initiation, planner, policy):
        self.database, self.context, self.initiation = database, context, initiation
        self.planner, self.policy = planner, policy

    def scan(self):
        arranged = []
        with self.database.transaction() as connection:
            now = utc_now()
            self.reconcile_in(connection, now)
            games = {}
            for row in connection.execute(
                "SELECT i.community_id,i.character_id FROM character_instances i JOIN "
                "communities c USING(community_id) WHERE c.status='active' AND "
                "i.memory_status='ready' AND i.availability_status='available'"
            ).fetchall():
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
                            scope.community_id,
                            scope.character_id,
                            scope.game_id,
                            participation_id=scope.participation_id,
                            limit=self.context.policy.event_limit,
                        )
                    except (ConflictError, NotFoundError, CharacterNotReady):
                        continue
                    if observed.context.game.status not in ("running", "finished"):
                        continue
                    if (
                        self.planner.conversations.get(
                            connection, scope.community_id, scope.conversation_id
                        ).status
                        != "active"
                    ):
                        continue
                    games.setdefault(scope.game_id, []).append((scope, observed))
            for scopes in games.values():
                result = self._game(connection, scopes, now)
                if result:
                    arranged.append(result)
        return tuple(arranged)

    def reconcile_in(self, connection, now):
        for row in connection.execute(
            "SELECT o.opportunity_id,o.game_id,o.community_id,g.conversation_id "
            "FROM activity_reaction_opportunities o JOIN community_games g USING(game_id) "
            "WHERE o.status='pending'"
        ).fetchall():
            conversation = self.planner.conversations.get(
                connection, row["community_id"], row["conversation_id"]
            )
            valid = False
            if conversation.status == "active":
                for member in self.planner.conversations.members(
                    connection, row["conversation_id"]
                ):
                    if member.actor.kind != "character":
                        continue
                    try:
                        context = self.context.observations.participation.participant_context(
                            connection, row["community_id"], member.actor, row["game_id"]
                        )
                        valid = context.game.status in ("running", "finished")
                        break
                    except NotFoundError:
                        continue
            if not valid:
                connection.execute(
                    "UPDATE activity_reaction_opportunities SET status='cancelled' "
                    "WHERE opportunity_id=?",
                    (row["opportunity_id"],),
                )

    def _clock(self, connection, scope, observed, now):
        conversation = self.planner.conversations.get(
            connection, scope.community_id, scope.conversation_id
        )
        message = connection.execute(
            "SELECT created_at_utc FROM messages WHERE conversation_id=? ORDER BY sequence "
            "DESC LIMIT 1",
            (scope.conversation_id,),
        ).fetchone()
        last_message = utc_datetime(message[0]) if message else observed.context.game.created_at_utc
        row = connection.execute(
            "SELECT * FROM activity_reaction_clocks WHERE game_id=?", (scope.game_id,)
        ).fetchone()
        community = self.planner.communities.get(connection, scope.community_id)
        if row:
            previous = utc_datetime(row["last_scanned_at_utc"])
            start = max(previous, community.updated_at_utc)
            elapsed = max(0, (now - start).total_seconds())
            same_message = row["message_sequence"] == conversation.next_sequence - 1
            same_action = row["state_version"] == observed.context.game.state_version
            silence = (
                row["since_message_seconds"] + elapsed
                if same_message
                else max(0, (now - max(last_message, start)).total_seconds())
            )
            quiet = row["quiet_seconds"] + elapsed if same_message and same_action else 0
            done = row["quiet_done"] if same_message and same_action else 0
        else:
            start = max(
                last_message, observed.context.game.updated_at_utc, community.updated_at_utc
            )
            quiet = max(0, (now - start).total_seconds())
            silence = max(0, (now - max(last_message, community.updated_at_utc)).total_seconds())
            done = 0
        connection.execute(
            "INSERT INTO activity_reaction_clocks VALUES (?,?,?,?,?,?,?,?) ON "
            "CONFLICT(game_id) DO UPDATE SET last_scanned_at_utc=excluded.last_scanned_at_utc"
            ",message_sequence=excluded.message_sequence,state_version=excluded.state_version"
            ",quiet_seconds=excluded.quiet_seconds,since_message_seconds=excluded.since_messa"
            "ge_seconds,quiet_done=excluded.quiet_done",
            (
                scope.game_id,
                scope.community_id,
                utc_text(now),
                conversation.next_sequence - 1,
                observed.context.game.state_version,
                quiet,
                silence,
                done,
            ),
        )
        return quiet, silence, done

    def _game(self, connection, scopes, now):
        scope, observed = scopes[0]
        quiet, silence, done = self._clock(connection, scope, observed, now)
        cursor = connection.execute(
            "SELECT COALESCE(MAX(through_sequence),0) FROM activity_reaction_opportunities "
            "WHERE game_id=?",
            (scope.game_id,),
        ).fetchone()[0]
        fresh = self.context.observations.observe_in(
            connection,
            scope.community_id,
            scope.character_id,
            scope.game_id,
            participation_id=scope.participation_id,
            after_sequence=cursor,
            limit=self.context.policy.event_limit,
        )
        new_events = {e.event_id: e for e in fresh.events.items}
        for other_scope, _ in scopes[1:]:
            other = self.context.observations.observe_in(
                connection,
                other_scope.community_id,
                other_scope.character_id,
                other_scope.game_id,
                participation_id=other_scope.participation_id,
                after_sequence=cursor,
                limit=self.context.policy.event_limit,
            )
            new_events.update({e.event_id: e for e in other.events.items})
        pending = connection.execute(
            "SELECT * FROM activity_reaction_opportunities WHERE game_id=? AND "
            "status='pending' ORDER BY created_at_utc LIMIT 1",
            (scope.game_id,),
        ).fetchone()
        if fresh.events.next_sequence > cursor:
            events = tuple(
                e
                for e in sorted(new_events.values(), key=lambda event: event.sequence)
                if e.type not in ("game_created", "participant_joined")
            )
            kind = "settlement" if any(e.type == "game_finished" for e in events) else "events"
            ids = tuple(e.event_id for e in events)
            if pending:
                ids = tuple(dict.fromkeys((*json.loads(pending["event_ids_json"]), *ids)))
                connection.execute(
                    "UPDATE activity_reaction_opportunities SET "
                    "through_sequence=?,event_ids_json=?,kind=? WHERE opportunity_id=?",
                    (fresh.events.next_sequence, json.dumps(ids), kind, pending["opportunity_id"]),
                )
            else:
                self._add(
                    connection,
                    scope,
                    kind,
                    cursor,
                    fresh.events.next_sequence,
                    observed.context.game.updated_at_utc,
                    ids,
                    now,
                )
        elif (
            pending is None
            and observed.context.game.status == "running"
            and quiet >= self.policy.quiet_seconds
            and not done
        ):
            self._add(connection, scope, "quiet", cursor, cursor, now, (), now)
            connection.execute(
                "UPDATE activity_reaction_clocks SET quiet_done=1 WHERE game_id=?", (scope.game_id,)
            )
        pending = connection.execute(
            "SELECT * FROM activity_reaction_opportunities WHERE game_id=? AND "
            "status='pending' ORDER BY created_at_utc LIMIT 1",
            (scope.game_id,),
        ).fetchone()
        if pending is None:
            return None
        # 所有角色共用一次开场机会；玩家回应与已有表达先完成。
        if not self.planner.initiation_available(connection, scope.conversation_id):
            return None
        if connection.execute(
            "SELECT 1 FROM activity_expression_tasks e JOIN activity_results r ON "
            "r.result_id=e.task_id JOIN activity_tasks t ON t.task_id=r.task_id WHERE "
            "t.conversation_id=? AND e.status IN "
            "('pending','processing','retry_wait','suspended')",
            (scope.conversation_id,),
        ).fetchone():
            return None
        if pending["kind"] != "settlement" and silence < self.policy.minimum_gap_seconds:
            return None
        chain = self.planner.social.active_chain(connection, scope.conversation_id)
        candidates, details, significance = [], {}, 0.0
        ids = set(json.loads(pending["event_ids_json"]))
        for candidate_scope, _ in scopes:
            local = self.context.observations.observe_in(
                connection,
                candidate_scope.community_id,
                candidate_scope.character_id,
                candidate_scope.game_id,
                participation_id=candidate_scope.participation_id,
                after_sequence=pending["after_sequence"],
                limit=self.context.policy.event_limit,
            )
            events = list(local.events.items)
            while (
                local.events.has_more and local.events.next_sequence < pending["through_sequence"]
            ):
                local = self.context.observations.observe_in(
                    connection,
                    candidate_scope.community_id,
                    candidate_scope.character_id,
                    candidate_scope.game_id,
                    participation_id=candidate_scope.participation_id,
                    after_sequence=local.events.next_sequence,
                    limit=self.context.policy.event_limit,
                )
                events.extend(local.events.items)
            events = tuple(e for e in events if e.sequence <= pending["through_sequence"])
            visible = ids & {e.event_id for e in events}
            covered = {
                r[0]
                for r in connection.execute(
                    "SELECT c.event_id FROM activity_event_coverage c JOIN activity_results r"
                    " USING(result_id) JOIN activity_tasks t USING(task_id) WHERE t.game_id=?"
                    " AND t.participation_id=?",
                    (candidate_scope.game_id, candidate_scope.participation_id),
                )
            }
            if ids and (not visible or visible <= covered):
                continue
            self.planner.conversations.current(
                connection,
                candidate_scope.conversation_id,
                ActorRef("character", candidate_scope.character_id),
            )
            candidates.append(
                Candidate(
                    candidate_scope.character_id,
                    False,
                    self.planner.messages.last_spoke(
                        connection, scope.conversation_id, candidate_scope.character_id
                    ),
                    chain_attempts=self.planner.social.attempts(
                        connection, chain.chain_id, candidate_scope.character_id
                    )
                    if chain
                    else 0,
                )
            )
            details[candidate_scope.character_id] = (candidate_scope, local, events)
            if local.view:
                try:
                    analyzer = self.context.gameplay.resolve(
                        local.view.game_type, local.view.ruleset_id, local.view.ruleset_version
                    )
                    previous_rows = connection.execute(
                        "SELECT snapshot_json FROM activity_inputs WHERE game_id=? AND "
                        "participation_id=? AND snapshot_json IS NOT NULL ORDER BY "
                        "created_at_utc DESC LIMIT 2",
                        (scope.game_id, candidate_scope.participation_id),
                    ).fetchall()
                    previous = [json.loads(r[0]) for r in previous_rows]
                    view = previous[0]["material"]["game"]["view"] if previous else None
                    analyses = tuple(p["analysis"] for p in previous if "analysis" in p)
                    significance = max(
                        significance, analyzer.reaction_significance(local.view, view, analyses)
                    )
                except GameplayAnalysisError:
                    pass
        if not candidates:
            connection.execute(
                "UPDATE activity_reaction_opportunities SET status='skipped',probability=0 "
                "WHERE opportunity_id=?",
                (pending["opportunity_id"],),
            )
            return None
        recent = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id=? AND "
            "sender_kind='character' AND created_at_utc>?",
            (
                scope.conversation_id,
                utc_text(now - timedelta(seconds=self.policy.frequency_window_seconds)),
            ),
        ).fetchone()[0]
        probability = (
            1.0
            if pending["kind"] == "settlement"
            else self.policy.probability(significance, silence, recent)
        )
        sample = random.random()
        connection.execute(
            "UPDATE activity_reaction_opportunities SET probability=?,sample=? WHERE "
            "opportunity_id=?",
            (probability, sample, pending["opportunity_id"]),
        )
        if sample >= probability:
            connection.execute(
                "UPDATE activity_reaction_opportunities SET status='skipped' WHERE "
                "opportunity_id=?",
                (pending["opportunity_id"],),
            )
            return None
        (selected,) = choose(tuple(candidates), 1)
        selected_scope, local, events = details[selected]
        situation = (
            "你获得一次游戏观察交流机会，可以自然评论、提问或保持安静。以下为原参与范围可见的正式事件：\n"
            + json.dumps([e.model_dump(mode="json") for e in events], ensure_ascii=False)
        )
        if pending["kind"] == "quiet":
            situation = "游戏与交流安静了一段时间，你可以结合眼前局面主动交流，也可以继续安静。"
        source = self.initiation.request_in(
            connection,
            scope.community_id,
            scope.conversation_id,
            selected,
            situation,
            request_id=f"activity-reaction:{pending['opportunity_id']}",
        )
        connection.execute(
            "UPDATE activity_reaction_opportunities SET "
            "status='arranged',character_id=?,source_id=?,visible_event_ids_json=? WHERE "
            "opportunity_id=?",
            (
                selected,
                source,
                json.dumps([e.event_id for e in events if e.event_id in ids]),
                pending["opportunity_id"],
            ),
        )
        return source

    @staticmethod
    def _add(connection, scope, kind, after, through, boundary, ids, now):
        connection.execute(
            "INSERT INTO activity_reaction_opportunities(opportunity_id,community_id,game_id,"
            "kind,after_sequence,through_sequence,boundary_utc,event_ids_json,status,created_"
            "at_utc) VALUES (?,?,?,?,?,?,?,?,'pending',?)",
            (
                str(uuid4()),
                scope.community_id,
                scope.game_id,
                kind,
                after,
                through,
                utc_text(boundary),
                json.dumps(ids),
                utc_text(now),
            ),
        )
