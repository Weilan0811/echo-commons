from pydantic import BaseModel, ConfigDict, Field


class ReactionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    quiet_seconds: float = Field(default=60, gt=0)
    minimum_gap_seconds: float = Field(default=10, ge=0)
    frequency_window_seconds: float = Field(default=90, gt=0)
    quiet_saturation_seconds: float = Field(default=90, gt=0)
    recency_saturation_seconds: float = Field(default=30, gt=0)
    base_probability: float = Field(default=0.05, ge=0, le=1)
    significance_weight: float = Field(default=0.55, ge=0)
    quiet_weight: float = Field(default=0.30, ge=0)
    maximum_probability: float = Field(default=0.9, ge=0, le=1)
    frequency_divisor: float = Field(default=2, gt=0)

    def probability(self, significance, silence, recent_messages):
        q = min(silence / self.quiet_saturation_seconds, 1)
        c = min(silence / self.recency_saturation_seconds, 1)
        f = 1 / (1 + recent_messages / self.frequency_divisor)
        return min(
            self.maximum_probability,
            (
                self.base_probability
                + self.significance_weight * significance
                + self.quiet_weight * q
            )
            * c
            * f,
        )
