import json

from echo_commons.modules.social.settings import ParticipationBalance
from echo_commons.shared.actors import ActorKind


def statistics_key(configuration):
    model = configuration["model"]
    return json.dumps(
        {
            "mode": configuration["mode"],
            "model": model["model"],
            "base_url": model["base_url"],
            "parameters": model["extra_body"],
            "protocol": configuration["protocol"],
            "controls": configuration["controls"]
            if configuration["mode"] == "local_willingness"
            else {},
        },
        sort_keys=True,
        separators=(",", ":"),
    )


class ParticipationShares:
    def __init__(self, settings, configuration):
        self.settings, self.configuration = settings, configuration

    def read(self, connection, conversation_id, configuration):
        return {
            row["character_id"]: (row["expected_share"], row["actual_share"])
            for row in connection.execute(
                "SELECT * FROM social_participation_shares "
                "WHERE conversation_id=? AND statistics_key=?",
                (conversation_id, statistics_key(configuration)),
            )
        }

    def published(self, connection, message, turn_id=None):
        if message.sender.kind is not ActorKind.CHARACTER:
            return
        batch = (
            connection.execute(
                "SELECT * FROM social_willingness_batches "
                "WHERE social_turn_id=? AND status='selected'",
                (turn_id,),
            ).fetchone()
            if turn_id
            else None
        )
        if batch is not None and batch["selected_character_id"] == message.sender.actor_id:
            config = json.loads(batch["configuration_json"])
            probabilities = json.loads(batch["selection_json"])["base_probabilities"]
        elif self.settings.mode != "remote_rules":
            config, probabilities = self.configuration(), None
        else:
            return
        key = statistics_key(config)
        inserted = connection.execute(
            "INSERT INTO social_participation_publications(message_id,statistics_key) VALUES (?,?) "
            "ON CONFLICT(message_id) DO NOTHING",
            (message.message_id, key),
        ).rowcount
        if not inserted:
            return
        policy = ParticipationBalance.model_validate(config["balance"])
        shares = self.read(connection, message.conversation_id, config)
        characters = set(shares) | set(probabilities or {}) | {message.sender.actor_id}
        for character in characters:
            expected, actual = shares.get(character, (0, 0))
            if probabilities is not None:
                expected = policy.decay * expected + (1 - policy.decay) * probabilities.get(
                    character, 0
                )
            actual = policy.decay * actual + (1 - policy.decay) * (
                character == message.sender.actor_id
            )
            connection.execute(
                "INSERT INTO social_participation_shares VALUES (?,?,?,?,?) "
                "ON CONFLICT(conversation_id,statistics_key,character_id) DO UPDATE SET "
                "expected_share=excluded.expected_share,actual_share=excluded.actual_share",
                (message.conversation_id, key, character, expected, actual),
            )
