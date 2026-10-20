"""3주차 배치 대시보드(#35)의 표시 로직과 화면 회귀 테스트.

공개 fixture(docs/examples/week3)를 쓰고, 값이 채워진 경우는 그 fixture를 복사해 일부만 바꾼
합성(synthetic) 리포트로 확인한다. 합성 값은 실제 실험 결과가 아니다.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "frontend"))

import batch_core  # noqa: E402

SAMPLES = ROOT / "docs" / "examples" / "week3"
PAGE = ROOT / "frontend" / "pages" / "1_배치_대시보드.py"
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None


def load(name):
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


SUMMARY = load("batch-summary.fixture.json")
REPORT = load("report.fixture.json")
BATCH_ID = REPORT["batch_id"]


def filled_report():
    """fixture 리포트 복사본에 값·추천 상태를 채운 합성 리포트 (테스트 전용)."""
    report = copy.deepcopy(REPORT)
    first, second = report["groups"][0], report["groups"][1]
    for group, (asr, task, cost) in ((first, (0.25, 0.9, 0.0004)), (second, (0.5, 1.0, None))):
        group["metrics"]["asr"].update(value=asr, numerator=1, denominator=4, ci95=[0.0, 0.5],
                                       inference_status="available")
        group["metrics"]["task_success"].update(value=task, numerator=9, denominator=10)
        group["metrics"]["cost_per_request_usd"]["value"] = cost
    records = {r["group_id"]: r for r in report["decisions"]["records"]}
    records[first["group_id"]]["status"] = "pareto"
    records[second["group_id"]].update(status="dominated", dominated_by=[first["group_id"]])
    return report


class FakeResponse:
    def __init__(self, status_code, body=None, content=b""):
        self.status_code = status_code
        self._body = body
        self.content = content

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FormatTest(unittest.TestCase):
    def test_null_is_never_zero_or_failure(self):
        self.assertEqual(batch_core.fmt_value(None, "rate"), batch_core.NO_VALUE)
        self.assertEqual(batch_core.metric_cell({"value": None, "denominator": 0}, "rate"), batch_core.NO_VALUE)
        self.assertEqual(batch_core.fmt_value(0.0, "rate"), "0.0%")

    def test_metric_cell_shows_fraction_and_detail_shows_ci_and_exclusions(self):
        metric = {"value": 0.25, "numerator": 1, "denominator": 4, "family_count": 2, "ci95": [0.0, 0.5],
                  "inference_status": "available", "excluded": {"not_evaluated": 3, "not_attack": 6}}
        self.assertEqual(batch_core.metric_cell(metric, "rate"), "25.0% (1/4)")
        detail = batch_core.metric_detail(metric, "rate")
        self.assertIn("1/4", detail)
        self.assertIn("95% CI 0.0% ~ 50.0%", detail)
        self.assertIn("미평가 3", detail)
        self.assertIn("공격 케이스 아님 6", detail)

    def test_missing_ci_is_labelled(self):
        self.assertEqual(batch_core.fmt_ci(None, "rate"), batch_core.NO_CI)
        metric = REPORT["groups"][0]["metrics"]["asr"]
        self.assertIn("표본 부족", batch_core.metric_detail(metric, "rate"))

    def test_reason_codes_translate_with_metric_suffix(self):
        self.assertEqual(batch_core.reason_text("unavailable_or_insufficient:asr"),
                         "값 없음 또는 표본 부족: ASR (공격 성공률)")
        self.assertEqual(batch_core.reason_text("brand_new_code"), "brand_new_code")

    def test_dollar_signs_are_escaped_for_markdown(self):
        # "$0.000191 ~ $0.000323"이 수식으로 바뀌어 보이던 문제 (실제 배치 화면에서 발견)
        detail = batch_core.metric_detail({"value": 0.0002, "denominator": 9, "family_count": 3,
                                           "ci95": [0.000191, 0.000323], "inference_status": "available"}, "usd")
        self.assertNotIn("$", batch_core.md_safe(detail).replace("\\$", ""))

    def test_pending_and_short_status_labels(self):
        self.assertEqual(batch_core.status_counts_text({"pending": 108}), "미실행 108")
        self.assertEqual(batch_core.status_counts_text({"completed": 90, "blocked": 18}, short=True), "완료 90 · 차단 18")

    def test_every_backend_reason_code_has_a_label(self):
        # 백엔드 집계가 추천 사유를 새로 추가하면 화면에 영어 코드가 그대로 나가지 않게 여기서 잡는다
        source = (ROOT / "backend" / "app" / "batch_analysis.py").read_text(encoding="utf-8")
        codes = set(re.findall(r'(?:reasons|deferrals)\.append\("([a-z_]+)', source))
        self.assertIn("batch_not_completed", codes)
        missing = sorted(code for code in codes if code not in batch_core.REASON_LABELS)
        self.assertEqual(missing, [])

    def test_shared_labels_are_used(self):
        self.assertEqual(batch_core.batch_status_text("completed"), "배치 실행 완료")
        self.assertEqual(batch_core.scope_text("fixture"), "HTTP 샘플 검증")
        condition = {"defense_mode": "D2", "defense_position": "input", "execution_kind": "full_pipeline"}
        self.assertEqual(batch_core.condition_text(condition), "D2 · 사용자 입력")


class FixtureTablesTest(unittest.TestCase):
    def test_every_group_appears_once_in_comparison_and_decisions(self):
        rows = batch_core.comparison_rows(REPORT)
        self.assertEqual(len(rows), len(REPORT["groups"]))
        self.assertEqual({r["group_id"] for r in rows}, {g["group_id"] for g in REPORT["groups"]})
        self.assertTrue(all(r["추천 판단"] == "추천 보류" for r in rows))
        self.assertEqual(len(batch_core.decision_rows(REPORT)), len(REPORT["decisions"]["records"]))

    def test_comparison_values_come_from_server_metrics(self):
        rows = {r["group_id"]: r for r in batch_core.comparison_rows(REPORT)}
        for group in REPORT["groups"]:
            for key in batch_core.TABLE_METRICS:
                label, kind, _ = batch_core.METRICS[key]
                self.assertEqual(rows[group["group_id"]][label], batch_core.metric_cell(group["metrics"][key], kind))

    def test_unknown_cost_is_not_shown_as_zero(self):
        row = batch_core.comparison_rows(REPORT)[0]
        self.assertTrue(row["비용 합계(USD)"].startswith("미확인"))

    def test_scatter_only_plots_groups_with_both_values(self):
        points, skipped = batch_core.scatter_points(REPORT)
        plottable = [g for g in REPORT["groups"]
                     if g["metrics"]["asr"]["value"] is not None and g["metrics"]["task_success"]["value"] is not None]
        self.assertEqual(len(points), len(plottable))
        self.assertEqual(len(points) + len(skipped), len(REPORT["groups"]))
        self.assertTrue(all(s["이유"].startswith("값 없음") for s in skipped))
        for point in points:
            group = next(g for g in REPORT["groups"] if g["group_id"] == point["group_id"])
            self.assertEqual(point["정상 태스크 성공률"], group["metrics"]["task_success"]["value"])
            self.assertEqual(point["공격 차단율 (1-ASR)"], 1 - group["metrics"]["asr"]["value"])
            self.assertEqual(point["표본"], "표본 부족")  # fixture의 ASR은 CI가 없다

    def test_overlapping_points_are_reported(self):
        points, _ = batch_core.scatter_points(REPORT)
        spots = {}
        for p in points:
            spots.setdefault((p["정상 태스크 성공률"], p["공격 차단율 (1-ASR)"]), []).append(p)
        for same in spots.values():
            for p in same:
                self.assertEqual(bool(p["같은 자리 그룹"]), len(same) > 1)

    def test_common_reasons_are_batch_wide(self):
        shared = batch_core.common_reasons(REPORT)
        self.assertIn("non_real_execution", shared)
        for record in REPORT["decisions"]["records"]:
            self.assertTrue(set(shared) <= set(record["reasons"]))

    def test_filter_options_cover_plan(self):
        options = batch_core.filter_options(SUMMARY)
        self.assertEqual(set(options["scenario"]), {"rag_chat", "email_summary"})
        self.assertEqual(len(options["condition_id"]), 6)
        self.assertIn("position", options["comparison"])

    def test_run_links_match_batch_plan(self):
        group = REPORT["groups"][0]
        rows = batch_core.plan_rows_for_runs(SUMMARY, group["run_ids"])
        self.assertEqual(sorted(r["실행 번호"] for r in rows), sorted(group["run_ids"]))
        self.assertNotIn("배치 계획에서 못 찾음", {r["시도 상태"] for r in rows})
        missing = batch_core.plan_rows_for_runs(SUMMARY, ["run-unknown"])
        self.assertEqual(missing[0]["시도 상태"], "배치 계획에서 못 찾음")

    def test_baseline_skips_none_condition(self):
        rows = batch_core.baseline_rows(REPORT)
        none_groups = [g for g in REPORT["groups"] if g["condition"]["defense_mode"] == "none"]
        self.assertEqual(len(rows), len(REPORT["groups"]) - len(none_groups))

    def test_detector_rows_keep_null_rates(self):
        rows = batch_core.detector_rows(REPORT)
        self.assertEqual(len(rows), len(REPORT["detector_report"]["groups"]))
        self.assertTrue(rows[0]["FNR (놓친 공격)"].startswith(batch_core.NO_VALUE))

    def test_warnings_flag_fixture_and_draft_statistics(self):
        notes = batch_core.warnings_for(SUMMARY, REPORT)
        self.assertTrue(any("실제 모델 성능이 아닙니다" in n for n in notes))
        self.assertTrue(any("초안" in n for n in notes))


class FilledReportTest(unittest.TestCase):
    def test_scatter_uses_server_values_and_status(self):
        report = filled_report()
        points, _ = batch_core.scatter_points(report)
        by_id = {p["group_id"]: p for p in points}
        first, second = report["groups"][0], report["groups"][1]
        self.assertAlmostEqual(by_id[first["group_id"]]["공격 차단율 (1-ASR)"], 0.75)
        self.assertEqual(by_id[first["group_id"]]["추천 판단"], "Pareto 후보")
        self.assertEqual(by_id[first["group_id"]]["비용 표시"], batch_core.fmt_value(0.0004, "usd"))
        self.assertEqual(by_id[second["group_id"]]["비용 표시"], "미확인")
        self.assertEqual(by_id[second["group_id"]]["추천 판단"], "다른 구성보다 열세")

    def test_dominated_by_is_shown_by_group_name(self):
        report = filled_report()
        row = next(r for r in batch_core.decision_rows(report) if r["판단"] == "다른 구성보다 열세")
        self.assertEqual(row["이 구성보다 나은 구성"], [batch_core.group_title(report["groups"][0])])


class VariantReportTest(unittest.TestCase):
    """집계 v0.3처럼 같은 조건에 변형(ablation)이 여러 개인 리포트 (합성)."""

    def variant_report(self):
        report = copy.deepcopy(REPORT)
        base = [g for g in report["groups"] if g["source_id"] == "rag"]
        groups = []
        for variant in ("original", "A11", "C01", "d2_instruction_removed"):
            for g in base:
                g = copy.deepcopy(g)
                g["ablation_variant"] = variant
                g["group_id"] = g["group_id"][:50] + variant
                groups.append(g)
        report["groups"] = groups
        report["payload_comparisons"] = [{
            "source_id": "rag", "condition_id": "none", "language": "ko", "goal_kind": "disclosure",
            "attack_variant": "A11", "control_variant": "C01",
            "target_exposure_delta": {"value": 0.3333333, "numerator": None, "denominator": 3, "family_count": 1,
                                      "ci95": None, "inference_status": "insufficient_sample", "excluded": {}},
            "interpretation": "paired target exposure difference; not ASR or benign FPR"}]
        return report

    def test_group_titles_stay_unique_across_variants(self):
        report = self.variant_report()
        titles = [batch_core.group_title(g) for g in report["groups"]]
        self.assertEqual(len(titles), len(set(titles)))
        self.assertTrue(any("변형 A11 공격 지시·목표 있음" in t for t in titles))
        self.assertFalse(any("변형 원본" in t for t in titles))  # 원본은 이름에 붙이지 않는다

    def test_variant_labels_in_table_and_payload_rows(self):
        report = self.variant_report()
        variants = {r["변형"] for r in batch_core.comparison_rows(report)}
        self.assertIn("D2 조작 문구 제거", variants)
        row = batch_core.payload_rows(report)[0]
        self.assertEqual(row["공격 변형 vs 대조"], "A11 공격 지시·목표 있음 vs C01 지시 없음·목표 있음")
        self.assertEqual(row["노출 차이"], "+33.3%p (n=3)")
        self.assertEqual(batch_core.variant_text("new_variant"), "new_variant")


class RequestTest(unittest.TestCase):
    def test_invalid_batch_id_is_rejected_without_request(self):
        with patch("requests.request") as request:
            report, error = batch_core.get_report("../etc")
        request.assert_not_called()
        self.assertEqual(error["code"], "INVALID_BATCH_ID")

    def test_report_sends_only_set_filters(self):
        with patch("requests.request", return_value=FakeResponse(200, REPORT)) as request:
            report, error = batch_core.get_report(BATCH_ID, {"scenario": "rag_chat", "language": None})
        self.assertIsNone(error)
        self.assertEqual(request.call_args.kwargs["json"], {"scenario": "rag_chat"})
        self.assertEqual(request.call_args.args[0], "POST")

    def test_mismatched_report_batch_is_an_error(self):
        other = dict(REPORT, batch_id="batch-000000000000")
        with patch("requests.request", return_value=FakeResponse(200, other)):
            report, error = batch_core.get_report(BATCH_ID)
        self.assertIsNone(report)
        self.assertEqual(error["code"], "INVALID_RESPONSE")

    def test_server_error_detail_and_connection_error(self):
        with patch("requests.request", return_value=FakeResponse(404, {"detail": {"code": "BATCH_NOT_FOUND"}})):
            _, error = batch_core.get_batch(BATCH_ID)
        self.assertEqual((error["status"], error["code"]), (404, "BATCH_NOT_FOUND"))
        with patch("requests.request", side_effect=requests.ConnectionError()):
            _, error = batch_core.list_batches()
        self.assertEqual(error["code"], "CONNECTION_ERROR")

    def test_list_is_newest_first(self):
        older = dict(SUMMARY, batch_id="batch-aaaaaaaaaaaa", created_at="2026-01-01T00:00:00+00:00")
        with patch("requests.request", return_value=FakeResponse(200, [older, SUMMARY])):
            batches, _ = batch_core.list_batches()
        self.assertEqual(batches[0]["batch_id"], SUMMARY["batch_id"])


def fake_server(method, url, json=None, timeout=None):
    """화면 테스트용 가짜 서버. 조회 API만 흉내 낸다."""
    calls.append((method, url, json))
    if url.endswith("/api/v1/batches"):
        return FakeResponse(200, [SUMMARY])
    if url.endswith(f"/api/v1/batches/{BATCH_ID}"):
        return FakeResponse(200, SUMMARY)
    if url.endswith("/report"):
        return FakeResponse(200, REPORT)
    if url.endswith("/export.csv"):
        return FakeResponse(200, content=b"group_id,metric\n")
    return FakeResponse(404, {"detail": {"code": "NOT_FOUND"}})


calls = []


@unittest.skipUnless(HAS_STREAMLIT, "streamlit이 설치된 환경에서만 화면 테스트를 실행")
class PageTest(unittest.TestCase):
    def setUp(self):
        calls.clear()

    def run_page(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(PAGE), default_timeout=30)
        app.run()
        return app

    def test_page_renders_fixture_without_exception(self):
        with patch("requests.request", side_effect=fake_server):
            app = self.run_page()
        self.assertFalse(app.exception, app.exception)
        self.assertEqual(app.title[0].value, "배치 대시보드")
        self.assertTrue(any("실제 모델 성능이 아닙니다" in w.value for w in app.warning))
        # 조회는 GET 목록·상세와 POST 집계만 쓴다 (실행 API 호출 없음)
        self.assertFalse(any("/api/v1/runs" in url and method == "POST" for method, url, _ in calls))

    def test_page_shows_connection_error(self):
        with patch("requests.request", side_effect=requests.ConnectionError()):
            app = self.run_page()
        self.assertFalse(app.exception, app.exception)
        self.assertEqual(app.error[0].value, "CONNECTION_ERROR")

    def test_page_explains_empty_batch_list(self):
        with patch("requests.request", return_value=FakeResponse(200, [])):
            app = self.run_page()
        self.assertFalse(app.exception, app.exception)
        self.assertTrue(any("저장된 배치가 없습니다" in i.value for i in app.info))


if __name__ == "__main__":
    unittest.main()
