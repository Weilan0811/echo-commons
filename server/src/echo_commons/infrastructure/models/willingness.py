import tomllib
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCORING_VERSION = "willingness-json-v1"
SCORING_INSTRUCTION = (
    "依据材料和给出的判断标准选择当前角色是否愿意发言。仅返回JSON对象，恰好包含choice和willingness_score两个字段。"
    "choice只能为speak或silent，与给出的选项含义一致。willingness_score是0到1之间的数值，表示角色当前的发言意愿，数值越大表示越想说话。"
    "该分数为自评意愿，不是词元概率。不要输出Markdown、解释或其他字段。"
)


class WillingnessOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    choice: Literal["speak", "silent"]
    willingness_score: float = Field(strict=True, ge=0, le=1)


def recommended_threshold(model: str, *, local: bool = False, thinking: bool = False) -> float:
    data = tomllib.loads(
        files("echo_commons.resources.config").joinpath("willingness-presets.toml")
        .read_text(encoding="utf-8")
    )
    for preset in data["presets"]:
        if (
            model in preset["models"]
            and preset["local"] == local
            and preset["thinking"] == thinking
            and preset["protocol"] == ("binary-option-v1" if local else SCORING_VERSION)
        ):
            return preset["threshold"]
    return data["defaults"]["local" if local else "remote"]
