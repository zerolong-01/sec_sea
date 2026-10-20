"""payload 짝 비교에서 서버의 불확실성·표본 상태를 보존하는 회귀 검사."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "frontend"))

import batch_core  # noqa: E402


def payload_row(delta):
    return batch_core.payload_rows({"payload_comparisons": [{
        "source_id": "rag", "condition_id": "none", "language": "ko",
        "goal_kind": "secret_leak", "attack_variant": "A11", "control_variant": "C01",
        "target_exposure_delta": delta,
    }]})[0]


class PayloadUncertaintyTest(unittest.TestCase):
    def test_interval_uses_percentage_points_and_preserves_crossing_zero(self):
        row = payload_row({
            "value": 0.25, "denominator": 12, "family_count": 4,
            "ci95": [-0.15, 0.55], "inference_status": "available", "excluded": {},
        })
        self.assertEqual(row["노출 차이"], "+25.0%p (n=12)")
        self.assertEqual(row["95% CI"], "95% CI -15.0%p ~ +55.0%p")
        self.assertEqual(row["비교 짝 수"], 12)
        self.assertEqual(row["family 수"], 4)
        self.assertEqual(row["통계 상태"], "CI 계산됨")

    def test_equal_estimates_with_different_uncertainty_remain_distinguishable(self):
        delta = {"value": 0.25, "denominator": 12, "family_count": 4,
                 "ci95": [-0.15, 0.55], "inference_status": "available"}
        original = copy.deepcopy(delta)
        first = payload_row(delta)
        second = payload_row(dict(delta, ci95=[0.10, 0.40], family_count=12,
                                  inference_status="insufficient_sample"))
        self.assertEqual(first["노출 차이"], second["노출 차이"])
        self.assertNotEqual(first["95% CI"], second["95% CI"])
        self.assertNotEqual(first["family 수"], second["family 수"])
        self.assertNotEqual(first["통계 상태"], second["통계 상태"])
        self.assertEqual(delta, original)  # 서버 리포트·다운로드 데이터는 바꾸지 않는다.

    def test_pending_pairs_are_not_a_zero_difference(self):
        pending = payload_row({
            "value": None, "denominator": 0, "family_count": 0, "ci95": None,
            "inference_status": "insufficient_sample", "excluded": {"missing_review_or_pair": 3},
        })
        measured_zero = payload_row({
            "value": 0.0, "denominator": 3, "family_count": 1, "ci95": None,
            "inference_status": "insufficient_sample", "excluded": {},
        })
        self.assertEqual(pending["노출 차이"], batch_core.NO_VALUE)
        self.assertEqual(pending["비교 짝 수"], 0)
        self.assertEqual(pending["family 수"], 0)
        self.assertEqual(pending["95% CI"], batch_core.NO_CI)
        self.assertEqual(pending["통계 상태"], "표본 부족")
        self.assertIn("검토·짝 없음 3", pending["제외"])
        self.assertEqual(measured_zero["노출 차이"], "+0.0%p (n=3)")

    def test_missing_counts_do_not_become_zero(self):
        row = payload_row({})
        self.assertEqual(row["비교 짝 수"], batch_core.NO_VALUE)
        self.assertEqual(row["family 수"], batch_core.NO_VALUE)
        self.assertEqual(row["95% CI"], batch_core.NO_CI)
        self.assertEqual(row["통계 상태"], batch_core.NO_VALUE)


if __name__ == "__main__":
    unittest.main()
