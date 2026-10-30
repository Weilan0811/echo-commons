import csv
import re

from echo_commons.infrastructure.game_analysis.rapfi.contracts import RapfiError, RapfiLine


def coordinate(value: str) -> tuple[int, int]:
    x, y = next(csv.reader([value]))
    point = int(x), int(y)
    if not all(0 <= part < 15 for part in point):
        raise RapfiError("invalid_response", f"Rapfi returned an invalid coordinate: {value}")
    return point


def about_version(line: str) -> str | None:
    match = re.search(r'name="Rapfi", version="([^"]+)"', line)
    return match[1] if match else None


class AnalysisReader:
    def __init__(self):
        self.current: dict[str, str] = {}
        self.lines: dict[int, RapfiLine] = {}

    def feed(self, line: str) -> tuple[int, int] | None:
        if line.startswith("ERROR") or line.startswith("UNKNOWN"):
            raise RapfiError("engine_rejected", line)
        if line.startswith("INFO "):
            _, key, value = line.split(" ", 2)
            if key == "PV" and value != "DONE":
                self.current = {"PV": value}
            elif key == "PV" and value == "DONE":
                data = self.current
                if data.get("BESTLINE") and data["BESTLINE"] != "(NONE)":
                    item = RapfiLine(
                        rank=int(data["PV"]),
                        moves=tuple(coordinate(move) for move in data["BESTLINE"].split()),
                        score=data["EVAL"]
                        if re.fullmatch(r"[+-]M(?:\d+|\*)", data["EVAL"])
                        else int(data["EVAL"]),
                        depth=int(data["DEPTH"]),
                        nodes=int(data["NODES"]),
                        time_ms=int(data["TOTALTIME"]),
                    )
                    self.lines[item.rank] = item
                self.current = {}
            elif self.current:
                self.current[key] = value
        elif re.fullmatch(r"\d+,\d+", line):
            return coordinate(line)
        return None


def position_commands(stones: tuple[tuple[int, int, int], ...]) -> tuple[str, ...]:
    return ("YXBOARD", *(f"{x},{y},{side}" for x, y, side in stones), "DONE")
