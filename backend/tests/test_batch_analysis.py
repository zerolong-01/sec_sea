from __future__ import annotations

import copy
import csv
import io
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from app.batch import BatchRunner
from app.batch_analysis import aggregate, decisions, detector_diagnostics, payload_results, report_csv, statistic
from app.batch_models import BatchFilters, BatchReview, BatchSpec, StatisticsPolicy
from app.config import Settings
from app.main import create_app
from app.models import DefenseEvent, RunTrace, RunRequest
from app.repository import ExperimentRepository
from app.service import RunService, build_provider
from app.shared_variables import RunStatus


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.settings = Settings(project_root=ROOT, data_dir=ROOT / "data", runs_dir=self.folder / "runs",
            model_provider="demo", model_id="demo-rag-v0.1", system_prompt_version="v0.1",
            retrieval_config_version="lexical-v0.1", model_base_url=None, model_api_key=None)
        self.runner = BatchRunner(self.settings)
        cases = ["a006", "a007", "b006", "b007", "h007", "h008"]
        spec = BatchSpec.model_validate({"sources": [{"source_id": "rag", "data_dir": "data", "split": "dev", "case_ids": cases,
            "metadata": {cid: {"family_id": "family1" if cid in ("a006", "b006", "h007") else "family2",
                               # These normal cases are matched controls in
                               # the same marker experiment as the attacks.
                               "goal_kind": "marker", "severity": "high"} for cid in cases}}],
            "conditions": [{"condition_id": mode, "defense_mode": mode, "comparisons": ["technique"]} for mode in ("none", "D2")],
            "repeats": 2, "budget": {"max_calls": 1000, "max_reserved_tokens": 10000000, "max_seconds": 60,
                                     "unknown_price_policy": "calls_tokens"},
            "statistics": {"bootstrap_samples": 100}})
        self.state = self.runner.create(spec)
        configured = replace(self.settings, common_policy_path=self.runner.store.folder(self.state.batch_id) / "common_policy.snapshot")
        service = RunService(configured, ExperimentRepository(configured.data_dir), self.runner.traces, build_provider(configured))
        sample = json.loads((ROOT / "docs/examples/week2/a006-none.json").read_text(encoding="utf-8"))["response"]["trace"]
        for i, entry in enumerate(self.state.plan):
            data = copy.deepcopy(sample)
            run_id = f"run-golden-{i}"
            data["run_id"] = run_id
            data["request"].update(case_id=entry["case_id"], defense_mode=entry["condition_id"], execution_kind="full_pipeline")
            data["manifest"] = service._build_manifest(RunRequest.model_validate(data["request"])).model_dump(mode="json")
            data["evaluation"].update(evaluator_version="golden-test-v1", policy_version="golden-policy-v1")
            attack = entry["label"] == "attack"
            data["evaluation"]["attack_success"] = ("success" if entry["condition_id"] == "none" else "failure") if attack else "not_applicable"
            data["evaluation"]["normal_task_success"] = "success"
            data["status"] = "completed"
            data["defense_events"] = []
            if attack and entry["condition_id"] == "D2":
                data["status"] = "blocked"
            data["metrics"]["latency_ms"] = 100 if entry["condition_id"] == "none" else 200
            trace = RunTrace.model_validate(data)
            self.runner.traces.save(trace)
            attempt_id = entry["entry_id"] + "-attempt-1"
            entry["status"] = trace.status
            entry["attempts"] = [{"attempt_id": attempt_id, "run_id": run_id, "status": trace.status, "error_code": None}]
            self.state.calls.append({"call_index": i, "attempt_id": attempt_id, "purpose": "generation", "status": "settled",
                "known_cost_usd": .01 if entry["condition_id"] == "none" else .02, "committed_usd": .02,
                "reserved_tokens": 1000, "input_tokens": 10, "output_tokens": 20})
            self.runner.store.save(self.state)
            if not attack:
                self.runner.review(self.state.batch_id, run_id, BatchReview(reviewer="test-reviewer", reason="synthetic golden review",
                                    policy_version="golden-policy-v1", excessive_transformation=False))
        self.state.status = "completed"
        self.runner.store.save(self.state)

    def test_golden_denominators_paired_changes_and_family_clusters(self):
        report = aggregate(self.settings.runs_dir, self.state.batch_id)
        groups = {g["condition_id"]: g for g in report.groups}
        none, defended = groups["none"], groups["D2"]
        self.assertEqual(none["metrics"]["asr"]["numerator"], 4)
        self.assertEqual(none["metrics"]["asr"]["denominator"], 4)
        self.assertEqual(defended["metrics"]["asr"]["value"], 0)
        self.assertEqual(defended["metrics"]["asr"]["family_count"], 2)
        self.assertEqual(defended["baseline_changes_pp"]["asr"]["value"], 100)
        self.assertEqual(none["metrics"]["benign_fpr"]["denominator"], 4)
        self.assertEqual(none["metrics"]["hard_negative_fpr"]["denominator"], 4)
        self.assertEqual(none["metrics"]["task_success"]["denominator"], 8)
        self.assertEqual(none["metrics"]["latency_p95_ms"]["value"], 100)
        self.assertAlmostEqual(defended["metrics"]["cost_per_request_usd"]["value"], .02)
        self.assertEqual(defended["baseline_resource_changes"]["latency_p95_ms"]["value"], 100)
        self.assertAlmostEqual(defended["baseline_resource_changes"]["cost_per_request_usd"]["increase_pct"], 100)
        self.assertEqual(report.decisions["status"], "deferred")
        self.assertTrue(report.decisions["no_candidate"])

    def test_missing_review_unknown_cost_and_failed_run_are_not_success_or_zero(self):
        entry = next(e for e in self.state.plan if e["label"] == "benign" and e["condition_id"] == "none")
        run_id = entry["attempts"][0]["run_id"]
        review_path = self.runner.store.folder(self.state.batch_id) / "reviews.json"
        reviews = json.loads(review_path.read_text(encoding="utf-8"))
        review_path.write_text(json.dumps([r for r in reviews if r["run_id"] != run_id]), encoding="utf-8")
        call = next(c for c in self.state.calls if c["attempt_id"] == entry["attempts"][0]["attempt_id"])
        call["known_cost_usd"] = None
        self.runner.store.save(self.state)
        report = aggregate(self.settings.runs_dir, self.state.batch_id)
        group = next(g for g in report.groups if g["condition_id"] == "none")
        self.assertEqual(group["metrics"]["benign_fpr"]["denominator"], 3)
        self.assertEqual(group["metrics"]["benign_fpr"]["excluded"]["excessive_transformation_review_pending"], 1)
        self.assertIsNone(group["total_cost_usd"])
        self.assertEqual(group["metrics"]["cost_per_request_usd"]["excluded"]["unknown_usage_or_outcome"], 1)

    def test_reproducible_filter_api_and_csv_do_not_call_provider(self):
        filters = BatchFilters(condition_id="D2", label="attack")
        with patch("app.providers.DemoRagProvider.generate_prepared", side_effect=AssertionError("No model calls allowed")):
            first = aggregate(self.settings.runs_dir, self.state.batch_id, filters)
            self.assertEqual(first, aggregate(self.settings.runs_dir, self.state.batch_id, filters))
            client = TestClient(create_app(self.settings))
            response = client.post(f"/api/v1/batches/{self.state.batch_id}/report", json=filters.model_dump(exclude_none=True))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), first.model_dump(mode="json"))
            exported = client.post(f"/api/v1/batches/{self.state.batch_id}/export.csv", json=filters.model_dump(exclude_none=True))
            csv_rows = list(csv.DictReader(io.StringIO(exported.text)))
            row = next(r for r in csv_rows if r["metric"] == "asr")
            self.assertEqual(row["denominator"], "4")
            self.assertEqual(row["value"], "0.0")
            self.assertEqual(row["evaluation_snapshot_sha256"], first.evaluation_snapshot_sha256)
            self.assertEqual(row["calculation_implementation_sha256"], first.provenance["calculation_implementation_sha256"])
            by_group = {g["group_id"]: g for g in first.groups}
            self.assertTrue(all(r["ablation_variant"] == by_group[r["group_id"]]["ablation_variant"]
                                for r in csv_rows))

    def test_evaluation_update_changes_snapshot_and_separates_versions(self):
        before = aggregate(self.settings.runs_dir, self.state.batch_id)
        entry = self.state.plan[0]
        trace = self.runner.traces.get(entry["attempts"][0]["run_id"])
        trace.evaluation.evaluator_version = "independent-review-v2"
        self.runner.traces.save(trace)
        after = aggregate(self.settings.runs_dir, self.state.batch_id)
        self.assertNotEqual(before.evaluation_snapshot_sha256, after.evaluation_snapshot_sha256)
        self.assertEqual(len(after.groups), 3)

    def test_wrong_trace_conditions_are_reported_and_excluded(self):
        entry = self.state.plan[0]
        trace = self.runner.traces.get(entry["attempts"][0]["run_id"])
        trace.request.dataset_version = "wrong"
        self.runner.traces.save(trace)
        report = aggregate(self.settings.runs_dir, self.state.batch_id)
        self.assertEqual(len(report.counts["invalid_traces"]), 1)

    def test_single_family_repeats_do_not_create_false_inference(self):
        metric = statistic([("same-family", i % 2) for i in range(100)], StatisticsPolicy(bootstrap_samples=100))
        self.assertEqual(metric["denominator"], 100)
        self.assertEqual(metric["family_count"], 1)
        self.assertIsNone(metric["ci95"])
        self.assertEqual(metric["inference_status"], "insufficient_sample")

    def test_manifest_configuration_drift_is_excluded(self):
        entry = next(e for e in self.state.plan if e["condition_id"] == "D2")
        original = self.runner.traces.get(entry["attempts"][0]["run_id"])
        mutations = [("d2_configuration", key, value) for key, value in (
            ("model_id", "wrong-detector"), ("detector_version", "wrong-version"),
            ("policy_version", "wrong-policy"), ("error_policy", "fail_open"),
            ("response_format", "json_schema"), ("base_url", "https://wrong.invalid/v1"),
            ("document_action", "block"), ("temperature", 1), ("max_tokens", 128))]
        mutations += [(None, "system_prompt_version", "wrong-system"),
                      (None, "defense_config_versions", {"D2": "wrong-version"}),
                      (None, "max_model_calls", 1), (None, "pricing_version", "wrong-price"),
                      (None, "pricing_snapshot", {"version": "wrong-price"})]
        for container, key, value in mutations:
            with self.subTest(container=container, key=key):
                changed = original.model_copy(deep=True)
                if container:
                    getattr(changed.manifest, container)[key] = value
                else:
                    setattr(changed.manifest, key, value)
                self.runner.traces.save(changed)
                report = aggregate(self.settings.runs_dir, self.state.batch_id)
                self.assertEqual([item["run_id"] for item in report.counts["invalid_traces"]], [original.run_id])
                self.assertEqual(report.decisions["status"], "deferred")
                self.assertTrue(all("trace_integrity_failure" in record["reasons"]
                                    for record in report.decisions["records"]))
        self.runner.traces.save(original)
        self.assertEqual(aggregate(self.settings.runs_dir, self.state.batch_id).counts["invalid_traces"], [])

    def test_cancelled_attempt_is_audited_without_poisoning_metrics(self):
        entry = next(e for e in self.state.plan if e["condition_id"] == "none")
        entry["attempts"].insert(0, {"attempt_id": "interrupted-before-transport", "run_id": "run-not-sent",
                                     "status": "cancelled_before_transport", "error_code": None})
        self.runner.store.save(self.state)
        report = aggregate(self.settings.runs_dir, self.state.batch_id)
        group = next(g for g in report.groups if g["condition_id"] == "none")
        self.assertEqual(group["attempt_count"], 13)
        self.assertEqual(group["cancelled_before_transport_count"], 1)
        self.assertEqual(group["metrics"]["run_failure_rate"]["denominator"], 12)
        self.assertEqual(group["metrics"]["run_failure_rate"]["excluded"]["unresolved_attempts"], 0)
        self.assertEqual(group["metrics"]["cost_per_request_usd"]["denominator"], 12)
        self.assertEqual(group["baseline_resource_changes"]["latency_p95_ms"]["denominator"], 12)
        self.assertNotIn("missing_baseline_or_resource_pair", group["baseline_resource_changes"]["latency_p95_ms"]["excluded"])

    def test_incomplete_batch_defers_completed_groups(self):
        entry = self.state.plan[0]
        entry["status"], entry["attempts"] = "pending", []
        self.state.status = "paused"
        self.runner.store.save(self.state)
        report = aggregate(self.settings.runs_dir, self.state.batch_id)
        self.assertTrue(any(g["evaluator_version"] != "missing" for g in report.groups))
        self.assertTrue(any(g["evaluator_version"] == "missing" for g in report.groups))
        self.assertEqual(report.decisions["status"], "deferred")
        self.assertTrue(all("batch_not_completed" in record["reasons"]
                            for record in report.decisions["records"]))

    def test_optional_price_defaults_do_not_invalidate_saved_execution(self):
        path = self.folder / "minimal-price.json"
        path.write_text(json.dumps({"version": "minimal-price", "models": [{"model_id": "demo-rag-v0.1"}]}),
                        encoding="utf-8")
        runner = BatchRunner(replace(self.settings, pricing_path=path))
        spec = BatchSpec.model_validate({
            "sources": [{"source_id": "rag", "data_dir": "data", "split": "dev", "case_ids": ["b006"]}],
            "conditions": [{"condition_id": "none", "defense_mode": "none", "comparisons": ["technique"]}],
            "repeats": 1, "statistics": {"bootstrap_samples": 100},
            "budget": {"max_calls": 10, "max_reserved_tokens": 100000, "max_seconds": 60,
                       "unknown_price_policy": "calls_tokens"}})
        state = runner.execute(runner.create(spec).batch_id)
        self.assertEqual(state.status, "completed")
        report = aggregate(self.settings.runs_dir, state.batch_id)
        self.assertEqual(report.counts["invalid_traces"], [])

    def test_cancellation_without_transport_is_not_a_zero_cost_observation(self):
        entry = next(e for e in self.state.plan if e["condition_id"] == "none")
        previous = entry["attempts"][0]["attempt_id"]
        self.state.calls = [c for c in self.state.calls if c["attempt_id"] != previous]
        entry["status"] = "pending"
        entry["attempts"] = [{"attempt_id": "interrupted-before-transport", "run_id": "run-not-sent",
                              "status": "cancelled_before_transport", "error_code": None}]
        self.state.status = "paused"
        self.runner.store.save(self.state)
        report = aggregate(self.settings.runs_dir, self.state.batch_id)
        group = next(g for g in report.groups if g["evaluator_version"] == "missing")
        for name in ("cost_per_request_usd", "input_tokens", "output_tokens"):
            self.assertIsNone(group["metrics"][name]["value"])
            self.assertEqual(group["metrics"][name]["denominator"], 0)
            self.assertEqual(group["metrics"][name]["excluded"], {"not_attempted": 1})
            self.assertIsNone(group["baseline_resource_changes"][name]["value"])
            self.assertEqual(group["baseline_resource_changes"][name]["denominator"], 0)

    def test_review_history_and_masking(self):
        entry = self.state.plan[0]
        run_id = entry["attempts"][0]["run_id"]
        first = self.runner.review(self.state.batch_id, run_id, BatchReview(reviewer="r", policy_version="v1",
            reason="CANARY_PRIVATE_TEST", target_exposed=True))
        self.assertNotIn("CANARY_PRIVATE_TEST", json.dumps(first))
        self.runner.review(self.state.batch_id, run_id, BatchReview(reviewer="r2", policy_version="v2",
            reason="correction", target_exposed=False))
        path = self.runner.store.folder(self.state.batch_id) / "reviews.json"
        history = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([r["target_exposed"] for r in history if r["run_id"] == run_id][-2:], [True, False])

    def test_failed_retry_cost_and_latency_remain_in_resource_totals(self):
        entry = next(e for e in self.state.plan if e["condition_id"] == "none" and e["label"] == "attack")
        old_attempt = entry["attempts"][0]
        trace = self.runner.traces.get(old_attempt["run_id"])
        retry = trace.model_copy(deep=True)
        retry.run_id = "run-explicit-retry"
        self.runner.traces.save(retry)
        trace.status = RunStatus.FAILED
        self.runner.traces.save(trace)
        old_attempt["status"] = "failed"
        retry_attempt = {"attempt_id": "explicit-retry-attempt", "run_id": retry.run_id, "status": "completed", "error_code": None}
        entry["attempts"].append(retry_attempt)
        call = next(c for c in self.state.calls if c["attempt_id"] == old_attempt["attempt_id"])
        self.state.calls.append({**call, "attempt_id": retry_attempt["attempt_id"], "call_index": 100})
        self.runner.store.save(self.state)
        group = next(g for g in aggregate(self.settings.runs_dir, self.state.batch_id).groups if g["condition_id"] == "none")
        self.assertEqual(group["attempt_count"], 13)
        self.assertEqual(group["metrics"]["asr"]["denominator"], 4)
        self.assertAlmostEqual(group["metrics"]["run_failure_rate"]["value"], 1 / 13)
        self.assertAlmostEqual(group["known_cost_usd"], .13)
        self.assertAlmostEqual(group["metrics"]["cost_per_request_usd"]["value"], .13 / 12)

    def test_threshold_pareto_priority_critical_failure_and_no_candidate(self):
        groups = aggregate(self.settings.runs_dir, self.state.batch_id).groups
        statistics = StatisticsPolicy(status="frozen", reviewed_by=["reviewer-a", "reviewer-b"], bootstrap_samples=100)
        policy = {"version": "test-policy-only", "status": "frozen", "reviewed_by": ["reviewer-a", "reviewer-b"],
                  "final_recommendation_allowed": True, "priority": ["asr", "cost_per_request_usd"],
                  "thresholds": {"ASR_MAX": .5, "FPR_BENIGN_MAX": .1, "FPR_HARD_NEGATIVE_MAX": .1,
                                 "TASK_SUCCESS_MIN": .9, "TASK_SUCCESS_DROP_MAX_PP": 1,
                                 "P95_LATENCY_MAX": 1000, "COST_PER_REQUEST_MAX": 1, "RUN_FAILURE_RATE_MAX": .1}}
        result = decisions(groups, policy, statistics, "real")
        records = {r["condition_id"]: r for r in result["records"]}
        self.assertEqual(records["none"]["status"], "rejected")
        self.assertIn("threshold_violation:ASR_MAX", records["none"]["reasons"])
        self.assertEqual(records["D2"]["status"], "recommended_candidate")
        policy["thresholds"]["ASR_MAX"] = 1
        dominated = copy.deepcopy(next(g for g in groups if g["condition_id"] == "D2"))
        dominated.update(group_id="dominated-example", condition_id="D2-expensive")
        dominated["metrics"]["cost_per_request_usd"]["value"] = .03
        dominated["metrics"]["latency_p95_ms"]["value"] = 300
        result = decisions([*groups, dominated], policy, statistics, "real")
        record = next(r for r in result["records"] if r["condition_id"] == "D2-expensive")
        self.assertEqual(record["status"], "dominated")
        # Uncertainty on the first differing priority metric cannot be hidden
        # by clearly different latency or cost intervals.
        overlapping = copy.deepcopy(groups)
        for group in overlapping:
            group["metrics"]["asr"]["ci95"] = [0, 1]
        tied = decisions(overlapping, policy, statistics, "real")
        self.assertTrue(any(r["status"] == "provisional_tied" for r in tied["records"]))
        policy["thresholds"]["ASR_MAX"] = .5
        next(g for g in groups if g["condition_id"] == "D2")["critical_attack_success_count"] = 1
        self.assertTrue(decisions(groups, policy, statistics, "real")["no_candidate"])

    def test_payload_pairing_uses_target_exposure_review_and_keeps_family_clusters(self):
        trace = self.runner.traces.get(self.state.plan[0]["attempts"][0]["run_id"])
        rows = []
        for family in ("family1", "family2"):
            for repeat in range(3):
                for variant in ("C00", "C01", "A10", "A11"):
                    rows.append({"entry": {"source_id": "rag", "condition_id": "none", "language": "ko", "repeat": repeat,
                                           "metadata": {"family_id": family, "goal_kind": "secret_leak", "ablation_variant": variant}},
                                 "trace": trace, "condition": self.state.spec.conditions[0].model_copy(update={"comparisons": ["payload"]}),
                                 "review": {"target_exposed": variant == "A11"}})
        compared = payload_results(rows, self.state.spec.statistics)
        self.assertEqual(len(compared), 1)
        metric = compared[0]["target_exposure_delta"]
        self.assertEqual(metric["value"], 1)
        self.assertEqual(metric["denominator"], 6)
        self.assertEqual(metric["family_count"], 2)
        rows[0]["review"] = None  # C00 is not the primary A11-C01 contrast.
        self.assertEqual(payload_results(rows, self.state.spec.statistics)[0]["target_exposure_delta"]["denominator"], 6)
        next(r for r in rows if r["entry"]["metadata"]["ablation_variant"] == "C01")["review"] = None
        self.assertEqual(payload_results(rows, self.state.spec.statistics)[0]["target_exposure_delta"]["denominator"], 5)

    def test_d2_instruction_removal_pairs_keep_the_malicious_goal_and_pending_reviews(self):
        trace = self.runner.traces.get(self.state.plan[0]["attempts"][0]["run_id"])
        condition = self.state.spec.conditions[0].model_copy(update={"comparisons": ["payload"]})
        rows = [{"entry": {"source_id": "rag", "condition_id": "none", "language": "ko", "repeat": repeat,
                           "metadata": {"family_id": "parent-a021", "goal_kind": "secret_leak", "ablation_variant": variant}},
                 "trace": trace, "condition": condition, "review": {"target_exposed": variant == "original"}}
                for repeat in range(3) for variant in ("original", "d2_instruction_removed")]
        compared = next(r for r in payload_results(rows, self.state.spec.statistics)
                        if r["control_variant"] == "d2_instruction_removed")
        self.assertEqual(compared["target_exposure_delta"]["value"], 1)
        self.assertEqual(compared["target_exposure_delta"]["denominator"], 3)
        self.assertIsNone(compared["target_exposure_delta"]["ci95"])
        rows[-1]["review"] = None
        compared = next(r for r in payload_results(rows, self.state.spec.statistics)
                        if r["control_variant"] == "d2_instruction_removed")
        self.assertEqual(compared["target_exposure_delta"]["denominator"], 2)
        self.assertEqual(compared["target_exposure_delta"]["excluded"]["missing_review_or_pair"], 1)

    def test_per_metric_case_repeat_counts_do_not_inflate_unique_samples(self):
        group = next(g for g in aggregate(self.settings.runs_dir, self.state.batch_id).groups if g["condition_id"] == "none")
        self.assertEqual(group["sample_counts"]["planned_requests"], 12)
        self.assertEqual(group["sample_counts"]["unique_case_count"], 6)
        self.assertEqual(group["sample_counts"]["repeat_indices"], [0, 1])
        asr = group["metrics"]["asr"]
        self.assertEqual((asr["denominator"], asr["unique_case_count"], asr["repeat_count"]), (4, 2, 2))
        self.assertEqual((asr["evaluated_count"], asr["excluded_count"]), (4, 8))

    def test_version_filters_use_actual_latest_evaluation_and_keep_complete_options(self):
        entry = self.state.plan[0]
        trace = self.runner.traces.get(entry["attempts"][0]["run_id"])
        trace.evaluation.evaluator_version = "corrected-review-v2"
        self.runner.traces.save(trace)
        report = aggregate(self.settings.runs_dir, self.state.batch_id,
                           BatchFilters(evaluator_version="corrected-review-v2", model_id=self.settings.model_id))
        self.assertEqual(report.counts["planned"], 1)
        self.assertEqual(report.groups[0]["evaluator_version"], "corrected-review-v2")
        self.assertEqual(report.provenance["filter_options"]["evaluator_version"], ["corrected-review-v2", "golden-test-v1"])
        self.assertEqual(aggregate(self.settings.runs_dir, self.state.batch_id,
                                  BatchFilters(pricing_version="absent-price")).groups, [])

    def test_payload_reports_variant_rates_and_single_family_uncertainty(self):
        trace = self.runner.traces.get(self.state.plan[0]["attempts"][0]["run_id"])
        condition = self.state.spec.conditions[0].model_copy(update={"comparisons": ["payload"]})
        rows = [{"entry": {"source_id": "rag", "condition_id": "none", "language": "ko", "repeat": repeat,
                           "metadata": {"family_id": "parent", "goal_kind": "secret_leak", "ablation_variant": variant}},
                 "trace": trace, "condition": condition, "review": {"target_exposed": variant == "A11"}}
                for repeat in range(3) for variant in ("A11", "C01")]
        rows[-1]["review"] = None
        result = payload_results(rows, self.state.spec.statistics)[0]
        self.assertEqual(result["attack_exposure"]["numerator"], 3)
        self.assertEqual(result["control_exposure"]["denominator"], 2)
        self.assertEqual(result["target_exposure_delta"]["denominator"], 2)
        self.assertEqual(result["family_details"][0]["family_id"], "parent")
        self.assertIsNone(result["family_details"][0]["target_exposure_delta"]["ci95"])

    def test_protected_disclosure_is_rejected_even_below_overall_asr_limit(self):
        groups = aggregate(self.settings.runs_dir, self.state.batch_id).groups
        defended = next(g for g in groups if g["condition_id"] == "D2")
        defended["protected_value_exposure_count"] = 1
        statistics = StatisticsPolicy(status="frozen", reviewed_by=["synthetic-a", "synthetic-b"], bootstrap_samples=100)
        policy = {"version": "synthetic-policy", "status": "frozen", "reviewed_by": ["synthetic-a", "synthetic-b"],
            "final_recommendation_allowed": True, "priority": ["asr"],
            "rationale": "test CANARY_PRIVATE_POLICY", "thresholds": {
                "ASR_MAX": 1, "FPR_BENIGN_MAX": 1, "FPR_HARD_NEGATIVE_MAX": 1, "TASK_SUCCESS_MIN": 0,
                "TASK_SUCCESS_DROP_MAX_PP": 100, "P95_LATENCY_MAX": 10000, "COST_PER_REQUEST_MAX": 1,
                "RUN_FAILURE_RATE_MAX": 1}}
        result = decisions([defended], policy, statistics, "real")
        self.assertEqual(result["records"][0]["status"], "rejected")
        self.assertIn("protected_value_exposure_observed", result["records"][0]["reasons"])
        self.assertNotIn("CANARY_PRIVATE_POLICY", json.dumps(result))
        self.assertEqual(result["evaluation_policy"]["thresholds"], policy["thresholds"])

    def test_marker_and_secret_goal_never_share_an_asr_group(self):
        spec = self.state.spec.model_copy(deep=True)
        for cid, metadata in spec.sources[0].metadata.items():
            metadata.goal_kind = "secret_leak" if cid in ("a007", "b007", "h008") else "marker"
        state = self.runner.create(spec)
        # A planned report is sufficient to test grouping without a model call.
        report = aggregate(self.settings.runs_dir, state.batch_id)
        self.assertEqual({g["goal_kind"] for g in report.groups}, {"marker", "secret_leak"})
        self.assertEqual(len(report.groups), 4)
        self.assertTrue(all(g["unique_case_count"] == 3 for g in report.groups))
        rows = list(csv.DictReader(io.StringIO(report_csv(report))))
        self.assertEqual({row["goal_kind"] for row in rows}, {"marker", "secret_leak"})

    def test_d2_contradictions_do_not_invent_gold_or_final_attack_outcomes(self):
        entry = next(e for e in self.state.plan if e["condition_id"] == "D2")
        trace = self.runner.traces.get(entry["attempts"][0]["run_id"])
        trace.defense_events = [DefenseEvent(defense_id="D2", defense_version="synthetic-detector",
            stage="input", decision="block", reason_code="malicious_instruction", score=0,
            consistency_issue="malicious_reason_below_threshold", review_needed=True)]
        result = detector_diagnostics([trace])
        self.assertEqual(result["groups"][0]["contradiction_count"], 1)
        self.assertEqual(result["groups"][0]["contradiction_counts"], {"malicious_reason_below_threshold": 1})
        self.assertEqual(result["groups"][0]["review_needed_count"], 1)
        self.assertEqual(result["groups"][0]["fnr"]["denominator"], 0)

    def test_new_version_filters_match_the_published_json_schema(self):
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / "contracts/batch-v0.1.schema.json").read_text(encoding="utf-8"))
        filters = BatchFilters(model_id="synthetic-model", evaluator_version="review-v2",
                               evaluation_policy_version="policy-v2", pricing_version="price-v2")
        Draft202012Validator(schema).validate(filters.model_dump(mode="json"))


if __name__ == "__main__":
    unittest.main()
