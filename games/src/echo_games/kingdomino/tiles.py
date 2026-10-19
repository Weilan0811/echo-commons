import json
from pathlib import Path
from typing import Any, Literal, NamedTuple, cast

# 地形六类与地块清单来自《Kingdomino 基础规则》第 3 节，键沿用已交付素材命名。
Terrain = Literal["field", "forest", "lake", "meadow", "swamp", "mine"]


class TileHalf(NamedTuple):
    terrain: Terrain
    crowns: int


class Tile(NamedTuple):
    id: int
    a: TileHalf
    b: TileHalf


def _half(raw: Any) -> TileHalf:
    return TileHalf(terrain=cast(Terrain, raw["terrain"]), crowns=int(raw["crowns"]))


def _load() -> dict[int, Tile]:
    data = json.loads(Path(__file__).with_name("tiles.json").read_text(encoding="utf-8"))
    return {
        int(item["id"]): Tile(id=int(item["id"]), a=_half(item["a"]), b=_half(item["b"]))
        for item in data["tiles"]
    }


TILES_BY_ID: dict[int, Tile] = _load()
TILE_IDS: tuple[int, ...] = tuple(sorted(TILES_BY_ID))
