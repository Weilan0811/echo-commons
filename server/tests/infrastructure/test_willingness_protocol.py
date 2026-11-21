import pytest
from pydantic import ValidationError

from echo_commons.infrastructure.models.willingness import WillingnessOutput, recommended_threshold


def test_willingness_output_preserves_score_and_label_independently():
    result = WillingnessOutput.model_validate({"choice": "silent", "willingness_score": 0.7})
    assert result.choice == "silent"
    assert result.willingness_score == 0.7


@pytest.mark.parametrize("payload", [
    {"choice": "speak", "willingness_score": 1.01},
    {"choice": "silent", "willingness_score": "0.8"},
    {"choice": "understand", "willingness_score": 0.8},
    {"choice": "speak", "willingness_score": 0.8, "reason": "额外字段"},
])
def test_willingness_output_rejects_invalid_contract(payload):
    with pytest.raises(ValidationError):
        WillingnessOutput.model_validate(payload)


def test_static_presets_keep_probability_and_self_rating_separate():
    assert recommended_threshold("qwen3.8-flash") == 0.85
    assert recommended_threshold("MiniMax-M3.1-Flash", thinking=True) == 0.86
    assert recommended_threshold("unknown") == pytest.approx((0.85+0.85+0.86)/3)
    assert recommended_threshold("unknown", local=True) == 0.5
    assert recommended_threshold("C2-binary-all-seed17", local=True) == 0.594788
