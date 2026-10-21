from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class AuthorMaterial:
    kind: Literal["story", "interview", "relationship"]
    position: int
    content: str
    question_id: str | None = None
    question: str | None = None

    def __post_init__(self) -> None:
        if self.position < 0 or not self.content.strip():
            raise ValueError("Author material requires a position and nonempty content")
        if self.kind == "interview":
            if not self.question_id or not self.question:
                raise ValueError("Interview material requires its original question")
        elif (
            self.kind not in {"story", "relationship"}
            or self.question_id is not None
            or self.question is not None
        ):
            raise ValueError("Invalid story material")
