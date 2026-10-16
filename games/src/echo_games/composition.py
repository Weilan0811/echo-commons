from echo_games.gomoku.rules import GomokuRules
from echo_games.registry import GameRegistry


def default_registry() -> GameRegistry:
    return GameRegistry((GomokuRules(),))
