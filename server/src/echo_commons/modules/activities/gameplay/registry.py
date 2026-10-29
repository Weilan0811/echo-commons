from echo_commons.modules.activities.gameplay.contracts import (
    AnalysisRequest,
    GameplayAnalysis,
    GameplayAnalysisError,
    GameplayAnalyzer,
)


class GameplayRegistry:
    def __init__(self, analyzers: tuple[GameplayAnalyzer, ...], *, max_attempts: int = 3):
        self._analyzers = {}
        if max_attempts < 1:
            raise ValueError("Analysis attempts must be positive")
        self.max_attempts = max_attempts
        for analyzer in analyzers:
            key = analyzer.game_type, analyzer.ruleset_id, analyzer.ruleset_version
            if key in self._analyzers:
                raise ValueError(f"Duplicate gameplay analyzer: {key}")
            self._analyzers[key] = analyzer

    def resolve(self, game_type: str, ruleset_id: str, ruleset_version: int) -> GameplayAnalyzer:
        key = game_type, ruleset_id, ruleset_version
        if key not in self._analyzers:
            raise GameplayAnalysisError("unsupported_gameplay", f"No gameplay analysis for {key}")
        return self._analyzers[key]

    async def analyze(self, request: AnalysisRequest) -> GameplayAnalysis:
        view, opportunity = request.view, request.opportunity
        if (
            opportunity not in view.opportunities
            or opportunity.expected_state_version != view.state_version
            or opportunity.participation_id != view.viewer_participation_id
            or opportunity.seat_id != view.viewer_seat_id
            or opportunity.game_id != view.game_id
            or view.status != "running"
        ):
            raise GameplayAnalysisError(
                "invalid_opportunity", "Analysis requires the visible current opportunity"
            )
        analyzer = self.resolve(view.game_type, view.ruleset_id, view.ruleset_version)
        failures = []
        for attempt in range(self.max_attempts):
            try:
                result = await analyzer.analyze(request)
                return result.model_copy(update={"failures": tuple(failures)})
            except GameplayAnalysisError as error:
                failures.append(error.code)
                error.failures = tuple(failures)
                if not error.retryable or attempt + 1 == self.max_attempts:
                    raise
        raise AssertionError("Analysis attempts exhausted without a result")
