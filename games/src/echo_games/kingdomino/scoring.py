from echo_games.kingdomino.models import (
    NEIGHBORS,
    Kingdom,
    KingdominoResult,
    SeatScore,
)


def domain_totals(kingdom: Kingdom) -> tuple[int, int, int]:
    """
    按地形四邻接划分领域并计分。

    返回 (总分, 最大领域格数, 皇冠总数)；领域得分 = 格数 × 该领域皇冠总数。
    """
    cells = {(cell.x, cell.y): cell for cell in kingdom.cells}
    visited: set[tuple[int, int]] = set()
    total = 0
    largest = 0
    crowns = 0
    for position in cells:
        if position in visited:
            continue
        visited.add(position)
        stack = [position]
        size = 0
        domain_crowns = 0
        while stack:
            x, y = stack.pop()
            cell = cells[(x, y)]
            size += 1
            domain_crowns += cell.crowns
            for dx, dy in NEIGHBORS:
                neighbor = (x + dx, y + dy)
                if neighbor in visited or neighbor not in cells:
                    continue
                if cells[neighbor].terrain != cell.terrain:
                    continue
                visited.add(neighbor)
                stack.append(neighbor)
        total += size * domain_crowns
        largest = max(largest, size)
        crowns += domain_crowns
    return total, largest, crowns


def _score(kingdom: Kingdom) -> SeatScore:
    total, largest, crowns = domain_totals(kingdom)
    return SeatScore(
        seat_id=kingdom.seat_id,
        total=total,
        largest_domain=largest,
        crowns=crowns,
    )


def _ranking(score: SeatScore) -> tuple[int, int, int]:
    return (score.total, score.largest_domain, score.crowns)


def score_kingdoms(kingdoms: tuple[Kingdom, ...]) -> KingdominoResult:
    # 平分依次比较总分、单个最大领域格数、皇冠总数，仍平则共同获胜（《基础规则》第 7 节）。
    scores = tuple(_score(kingdom) for kingdom in kingdoms)
    best = max(_ranking(score) for score in scores)
    winners = tuple(score.seat_id for score in scores if _ranking(score) == best)
    return KingdominoResult(winner_seat_ids=winners, scores=scores)
