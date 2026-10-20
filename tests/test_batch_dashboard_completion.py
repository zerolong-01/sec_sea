"""#35의 차트·정책·표본·특수 상태를 합성 공개 결과로 검증한다."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "frontend"))
import batch_core
from batch_chart import SELECTION, selected_group, tradeoff_chart

REPORT = json.loads((ROOT / "docs/examples/week3/report.fixture.json").read_text(encoding="utf-8"))
SUMMARY = json.loads((ROOT / "docs/examples/week3/batch-summary.fixture.json").read_text(encoding="utf-8"))
PAGE = ROOT / "frontend/pages/1_배치_대시보드.py"


def complete_values():
    report = copy.deepcopy(REPORT)
    for index, group in enumerate(report["groups"][:2]):
        group["metrics"]["asr"].update(value=.25, numerator=1, denominator=4, family_count=2,
                                       ci95=[.1, .5], inference_status="available")
        group["metrics"]["task_success"].update(value=.9, numerator=9, denominator=10, family_count=3,
                                                ci95=[.7, 1.0], inference_status="available")
        group["metrics"]["cost_per_request_usd"]["value"] = .0004 if index == 0 else None
    return report


class ChartContractTests(unittest.TestCase):
    def test_mixed_costs_keep_unknown_point_and_color_defense_with_ci_and_counts(self):
        points, _ = batch_core.scatter_points(complete_values())
        spec = tradeoff_chart(points).to_dict()
        self.assertEqual(len(spec["layer"]), 2)
        known, unknown = spec["layer"]
        self.assertEqual(known["encoding"]["color"]["field"], "방어 조건")
        self.assertEqual(unknown["encoding"]["color"]["field"], "방어 조건")
        self.assertIn("size", known["encoding"])
        self.assertNotIn("size", unknown["encoding"])
        self.assertEqual(unknown["mark"]["size"], 140)
        self.assertFalse(unknown["mark"]["filled"])
        rows = [row for data in spec["datasets"].values() for row in data]
        self.assertEqual({row["group_id"] for row in rows}, {point["group_id"] for point in points})
        unknown_rows = spec["datasets"][unknown["data"]["name"]]
        self.assertTrue(all(row["요청당 비용"] is None for row in unknown_rows))
        self.assertEqual(points[0]["ASR 95% CI"], "95% CI 10.0% ~ 50.0%")
        self.assertEqual((points[0]["공격 평가 수"], points[0]["정상 평가 수"]), (4, 10))
        self.assertTrue({"ASR 95% CI", "정상 성공률 95% CI", "공격 평가 수", "정상 평가 수"} <=
                        {item["field"] for item in known["encoding"]["tooltip"]})

    def test_all_unknown_costs_remain_visible_without_size_encoding(self):
        points, _ = batch_core.scatter_points(complete_values())
        for point in points:
            point["요청당 비용"] = None
        spec = tradeoff_chart(points).to_dict()
        self.assertEqual(len(spec["layer"]), 1)
        self.assertNotIn("size", spec["layer"][0]["encoding"])
        self.assertEqual(spec["layer"][0]["mark"]["size"], 140)

    def test_server_tradeoff_uses_explicit_normal_reference_without_mutating_goal_metrics(self):
        report = complete_values()
        security, normal = report["groups"][:2]
        security["goal_kind"], normal["goal_kind"] = "secret_leak", "normal"
        security["metrics"]["task_success"]["value"] = None
        normal["metrics"]["asr"]["value"] = None
        point = copy.deepcopy(security)
        point["metrics"]["task_success"] = copy.deepcopy(normal["metrics"]["task_success"])
        point["metrics"]["task_success"]["excluded"] = {"review_needed": 2}
        point["metrics"]["attack_block_rate"] = {"value": .75, "ci95": [.5, .9]}
        point["utility_reference"] = {"benchmark_id": "normal-benchmark-test", "run_ids": ["run-normal-reference"],
                                      "shared_scope": "same frozen condition and filters",
                                      "evaluation_coverage": {"planned_requests": 12, "evaluated_requests": 10, "excluded_requests": 2}}
        point["normal_evaluation_complete"] = False
        point["cost_scope"] = "security_goal_group_only"
        report["tradeoff_points"] = [point]
        points, skipped = batch_core.scatter_points(report)
        self.assertFalse(skipped)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["정상 태스크 성공률"], .9)
        self.assertEqual(points[0]["공격 차단율 (1-ASR)"], .75)
        self.assertEqual(points[0]["공격 차단율 95% CI"], "95% CI 50.0% ~ 90.0%")
        self.assertEqual(points[0]["정상 기준"], "normal-benchmark-test")
        self.assertEqual(points[0]["평가 상태"], "일부 평가 제외")
        self.assertEqual(points[0]["정상 기준 평가 완료"], "일부 평가")
        self.assertEqual(points[0]["정상 기준 평가/계획"], "10/12")
        self.assertEqual(points[0]["정상 기준 제외 수"], 2)
        self.assertIn("검토 필요 2", points[0]["정상 평가 제외"])
        self.assertIn("공격 목표 그룹", points[0]["비용 범위"])
        self.assertIsNone(report["groups"][0]["metrics"]["task_success"]["value"])
        report["tradeoff_points"] = []
        self.assertEqual(batch_core.scatter_points(report), ([], []))

    def test_selection_only_accepts_report_group_ids(self):
        self.assertEqual(selected_group({"selection": {SELECTION: [{"group_id": "saved"}]}}, ["saved"]), "saved")
        for event in ({}, {"selection": []}, {"selection": {SELECTION: [{"group_id": "other"}]}},
                      {"selection": {SELECTION: ["invalid"]}}):
            self.assertIsNone(selected_group(event, ["saved"]))

    def test_policy_sample_counts_and_family_exposure_preserve_server_values_and_nulls(self):
        report = copy.deepcopy(REPORT)
        report["decisions"]["evaluation_policy"] = {
            "status": "draft", "thresholds": {"ASR_MAX": .2, "COST_PER_REQUEST_MAX": None}}
        thresholds = {row["코드"]: row["정책값"] for row in batch_core.policy_rows(report)}
        self.assertEqual(thresholds["ASR_MAX"], "20.0%")
        self.assertEqual(thresholds["COST_PER_REQUEST_MAX"], batch_core.NO_VALUE)
        group = report["groups"][0]
        group["sample_counts"] = {"planned_requests": 12, "unique_case_count": 4, "family_count": 2,
            "repeat_count": 3, "evaluation_status_counts": {"attack_success": {"review_needed": 2}}}
        samples = {row["표본·평가"]: row["수"] for row in batch_core.sample_rows(group)}
        self.assertEqual(samples["고유 케이스"], 4)
        self.assertEqual(samples["반복 수"], 3)
        self.assertEqual(samples["공격 성공 평가 · 검토 필요"], 2)
        delta = {"value": .5, "denominator": 2, "family_count": 1, "ci95": None,
                 "inference_status": "insufficient_sample", "excluded": {}}
        report["payload_comparisons"] = [{"source_id": "rag", "condition_id": "none", "language": "ko",
            "goal_kind": "secret_leak", "attack_variant": "A11", "control_variant": "C01",
            "target_exposure_delta": delta, "family_details": [{"family_id": "synthetic-family",
            "attack_exposure": {"value": 1, "numerator": 2, "denominator": 2},
            "control_exposure": {"value": .5, "numerator": 1, "denominator": 2},
            "target_exposure_delta": delta}]}]
        row = batch_core.payload_rows(report, by_family=True)[0]
        self.assertEqual(row["family"], "synthetic-family")
        self.assertEqual(row["공격 변형 노출률"], "100.0% (2/2)")
        self.assertEqual(row["대조 변형 노출률"], "50.0% (1/2)")
        self.assertEqual(row["95% CI"], "CI 없음")
        self.assertEqual(row["통계 상태"], "표본 부족")

    def test_version_options_and_goal_names_keep_different_attack_objectives_distinct(self):
        report = copy.deepcopy(REPORT)
        report["provenance"]["filter_options"] = {"model_id": ["fixture-generation"],
            "evaluator_version": ["rules-v1"], "evaluation_policy_version": ["draft-v1"], "pricing_version": ["price-v1"]}
        self.assertEqual(batch_core.filter_options(SUMMARY, report)["evaluator_version"], ["rules-v1"])
        a, b = copy.deepcopy(report["groups"][0]), copy.deepcopy(report["groups"][0])
        a["goal_kind"], b["goal_kind"] = "marker", "secret_leak"
        self.assertNotEqual(batch_core.group_title(a), batch_core.group_title(b))


class Response:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return copy.deepcopy(self.body)


class CompletionPageTests(unittest.TestCase):
    def page(self, report, summary=None):
        def request(method, url, **kwargs):
            if method == "GET" and url.endswith("/api/v1/batches"):
                return Response([summary or SUMMARY])
            if method == "GET" and url.endswith("/" + REPORT["batch_id"]):
                return Response(summary or SUMMARY)
            if method == "POST" and url.endswith("/report"):
                return Response(report)
            raise AssertionError(f"Unexpected request: {method} {url}")
        context = patch("requests.request", side_effect=request)
        context.start()
        self.addCleanup(context.stop)
        return AppTest.from_file(str(PAGE), default_timeout=30).run()

    def test_chart_selected_group_opens_matching_saved_trace_without_generation(self):
        report = complete_values()
        group = report["groups"][1]
        event = {"selection": {SELECTION: [{"group_id": group["group_id"]}]}}
        def load(run_id):
            return {"run_id": run_id, "status": "completed", "request": {}, "evaluation": {},
                    "output": {"display_text": "MASKED_SAVED_OUTPUT"}}, None
        with patch("streamlit.altair_chart", return_value=event), patch("ui_core.load_run", side_effect=load) as lookup:
            app = self.page(report)
            self.assertFalse(app.exception, app.exception)
            app.button(key="chart_trace").click().run()
        self.assertFalse(app.exception, app.exception)
        self.assertEqual(app.selectbox(key="trace_group").value, group["group_id"])
        self.assertEqual(lookup.call_count, 1)
        self.assertIn(lookup.call_args.args[0], group["run_ids"])
        self.assertIn("MASKED_SAVED_OUTPUT", [code.value for code in app.code])

    def test_failed_partial_and_empty_reports_do_not_render_as_successful_experiments(self):
        for state in ("all_failed", "one_result_partial", "empty"):
            with self.subTest(state=state):
                summary = copy.deepcopy(SUMMARY)
                summary.update(status="partial" if state == "all_failed" else "paused",
                               status_counts={"failed": 108} if state == "all_failed" else {"pending": 107, "completed": 1})
                report = copy.deepcopy(REPORT)
                if state == "empty":
                    report["groups"] = []
                else:
                    report["groups"] = report["groups"][:1]
                    report["groups"][0]["metrics"]["asr"]["value"] = None
                app = self.page(report, summary)
                self.assertFalse(app.exception, app.exception)
                self.assertTrue(any("아직 모든 계획 항목" in warning.value for warning in app.warning))
                if state == "empty":
                    self.assertTrue(any("맞는 실행이 없습니다" in info.value for info in app.info))
                    self.assertFalse(app.get("download_button"))
                else:
                    asr = next(metric for metric in app.metric if metric.label == "ASR (공격 성공률)")
                    self.assertEqual(asr.value, batch_core.NO_VALUE)

    def test_tied_rejected_and_no_candidate_server_decisions_are_displayed(self):
        for status, no_candidate, label in (("provisional_tied", False, "잠정 동률"),
                                           ("rejected", True, "탈락")):
            with self.subTest(status=status):
                report = complete_values()
                report["decisions"]["records"][0]["status"] = status
                report["decisions"]["no_candidate"] = no_candidate
                app = self.page(report)
                self.assertFalse(app.exception, app.exception)
                self.assertTrue(any(label in expander.label for expander in app.expander))
                candidate = next(metric for metric in app.metric if metric.label == "추천 후보")
                self.assertEqual(candidate.value, "없음" if no_candidate else "있음")

    def test_condition_mismatched_trace_warning_remains_visible(self):
        report = copy.deepcopy(REPORT)
        report["counts"]["invalid_traces"] = [{"run_id": "run-synthetic-mismatch", "reason": "condition differs"}]
        app = self.page(report)
        self.assertFalse(app.exception, app.exception)
        self.assertTrue(any("계획과 맞지 않아" in warning.value and "1개" in warning.value for warning in app.warning))

    def test_budget_and_nullable_sample_counts_serialize_without_arrow_type_coercion(self):
        import pyarrow as pa

        original = copy.deepcopy(SUMMARY)
        app = self.page(copy.deepcopy(REPORT))
        self.assertFalse(app.exception, app.exception)
        frames = [element.value for element in app.dataframe]
        budget = next(frame for frame in frames if set(frame.columns) == {"항목", "값"})
        samples = next(frame for frame in frames if "표본·평가" in frame.columns)
        budget_arrow = pa.Table.from_pandas(budget, preserve_index=False)
        sample_arrow = pa.Table.from_pandas(samples, preserve_index=False)
        display_type = budget_arrow.schema.field("값").type
        self.assertTrue(pa.types.is_string(display_type) or pa.types.is_large_string(display_type))
        self.assertTrue(pa.types.is_int64(sample_arrow.schema.field("수").type))
        self.assertGreater(sample_arrow["수"].null_count, 0)  # 과거 fixture에는 repeat_count가 없다.
        self.assertIn(batch_core.NO_VALUE, samples["기록 상태"].tolist())
        self.assertEqual(SUMMARY, original)
        self.assertIsInstance(SUMMARY["budget"]["admitted_calls"], int)


if __name__ == "__main__":
    unittest.main()
