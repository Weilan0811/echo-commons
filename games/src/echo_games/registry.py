from typing import Any

from echo_games.contracts import GameDefinition, GameTypeView
from echo_games.errors import GameError

# 注册表容纳不同的真实模型组合；具体类型校验仍由各定义的 models 执行。
RegisteredDefinition = GameDefinition[Any, Any, Any, Any, Any, Any, Any]


class GameRegistry:
    def __init__(self, definitions: tuple[RegisteredDefinition, ...]) -> None:
        self._definitions: dict[tuple[str, str, int], RegisteredDefinition] = {}
        for definition in definitions:
            key = (definition.game_type, definition.ruleset_id, definition.ruleset_version)
            if key in self._definitions:
                raise ValueError(f"Duplicate game definition: {key}")
            self._definitions[key] = definition

    def resolve(
        self, game_type: str, ruleset_id: str, ruleset_version: int
    ) -> RegisteredDefinition:
        key = (game_type, ruleset_id, ruleset_version)
        if key not in self._definitions:
            raise GameError("ruleset_unavailable", "The exact game rules are unavailable")
        return self._definitions[key]

    def list_game_types(self) -> tuple[GameTypeView, ...]:
        types = sorted({definition.game_type for definition in self._definitions.values()})
        return tuple(self.read_game_type(game_type) for game_type in types)

    def read_game_type(self, game_type: str) -> GameTypeView:
        definitions = [d for d in self._definitions.values() if d.game_type == game_type]
        if not definitions:
            raise GameError("game_type_not_found", "Unknown game type")
        return GameTypeView(
            game_type=game_type,
            display_name=definitions[0].display_name,
            rulesets=tuple(
                d.models.ruleset_view(
                    ruleset_id=d.ruleset_id,
                    ruleset_version=d.ruleset_version,
                    display_name=d.ruleset_name,
                    min_players=d.min_players,
                    max_players=d.max_players,
                    config=d.default_config,
                )
                for d in sorted(definitions, key=lambda d: (d.ruleset_id, d.ruleset_version))
            ),
        )
