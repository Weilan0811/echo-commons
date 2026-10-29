from pydantic import BaseModel, ConfigDict, Field

from echo_commons.infrastructure.game_analysis.rapfi.contracts import RapfiSettings


class GameAnalysisSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rapfi: RapfiSettings = Field(default_factory=RapfiSettings)
