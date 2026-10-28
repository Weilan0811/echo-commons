from pydantic import BaseModel, ConfigDict, Field, model_validator

from echo_commons.modules.reflection.domain.graph import ReflectionNodeKind


class DiagnosisPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    facts_enabled: bool = False
    summaries_enabled: bool = False
    max_revisions: int = Field(default=2, ge=0, le=10)

    def enabled(self, kind: ReflectionNodeKind) -> bool:
        return (
            self.facts_enabled
            if kind is ReflectionNodeKind.FACT_EXTRACT
            else self.summaries_enabled
            and kind
            in {
                ReflectionNodeKind.SEGMENT_SUMMARY_PLAN,
                ReflectionNodeKind.CONTINUITY_COMPRESS,
                ReflectionNodeKind.COGNITION_REFLECT,
                ReflectionNodeKind.CORE_MEMORY_VIEW,
            }
        )


class DiagnosisIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    location: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    requirement: str = Field(min_length=1)


class DiagnosisReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    passed: bool = Field(strict=True)
    issues: tuple[DiagnosisIssue, ...] = ()

    @model_validator(mode="after")
    def consistent_verdict(self):
        if self.passed == bool(self.issues):
            raise ValueError("A passed diagnosis has no issues; a failed diagnosis requires issues")
        return self
