"""Private consensus plans use explicit fixture reviewers, never real approval.

One six-run local HTTP fixture is copied for each test. Preparing and planning
reviews must not call a model, apply an API update, or alter saved run evidence.
"""
from __future__ import annotations

import base64
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from backend.app.batch import BatchRunner, digest
from backend.app.batch_models import BatchReview, BatchSpec
from backend.app.config import Settings
from backend.app.models import DetectorGoldUpdate, EvaluationUpdate
from backend.app.providers import OpenAICompatibleProvider
from backend.testing.fixture_model import FixtureModelServer
from scripts.data_contract import ROOT, load_bundle
from scripts.week3_review_handoff import plan, prepare, read, rows, sha, write_rows


class ReviewHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.baseline = cls.root / "original-runs"
        cls.synthetic_target = "fixture-private-reference-71@sample.invalid"
        rules = read(ROOT / "configs/evaluation-week2.json")
        next(rule for rule in rules["rules"] if rule["case_id"] == "a006")["protected_values"].append(cls.synthetic_target)
        rules_path = cls.root / "fixture-rules.json"
        rules_path.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
        prices = cls.root / "fixture-prices.json"
        prices.write_text(json.dumps({"version": "handoff-test-price", "currency": "USD", "models": [
            {"model_id": model, "input_usd_per_million": .4, "output_usd_per_million": 1.6,
             "source_url": "https://example.invalid/test-only", "effective_date": "2026-10-20", "verified": True}
            for model in ("fixture-generation", "fixture-classifier")]}), encoding="utf-8")
        with FixtureModelServer(ROOT / "data/week2") as fixture:
            settings = Settings(project_root=ROOT, data_dir=ROOT / "data/week2", runs_dir=cls.baseline,
                model_provider="fixture_http", model_id="fixture-generation", system_prompt_version="v0.1",
                retrieval_config_version="lexical-v0.1", model_base_url=fixture.base_url,
                model_api_key="fixture-review-only-key", d2_model_id="fixture-classifier",
                pricing_path=prices, evaluation_rules_path=rules_path,
                common_policy_path=ROOT / "configs/week3-common-policy.txt")
            spec = BatchSpec.model_validate({"sources": [{"source_id": "rag", "data_dir": "data/week2",
                "split": "dev", "case_ids": ["a006", "b006", "h007"], "metadata": {
                    "a006": {"family_id": "fixture-attack", "goal_kind": "marker"},
                    "b006": {"family_id": "fixture-benign", "goal_kind": "normal"},
                    "h007": {"family_id": "fixture-negative", "goal_kind": "normal"}}}],
                "repeats": 1, "conditions": [
                    {"condition_id": "none", "defense_mode": "none", "comparisons": ["technique"]},
                    {"condition_id": "D2-input", "defense_mode": "D2", "defense_position": "input", "comparisons": ["position"]}],
                "budget": {"max_calls": 30, "max_reserved_tokens": 2_000_000, "max_seconds": 60,
                           "max_usd": 1.0}, "evaluation_policy_file": "configs/week3-evaluation-policy.json"})
            runner = BatchRunner(settings)
            state = runner.execute(runner.create(spec).batch_id)
            if state.status != "completed" or len(state.plan) != 6:
                raise AssertionError("local six-run fixture did not complete")
            cls.batch_id = state.batch_id

    def setUp(self):
        self.folder = self.root / self.id().rsplit(".", 1)[-1]
        self.runs = self.folder / "runs"
        shutil.copytree(self.baseline, self.runs)
        self.packet = self.folder / "packet"
        with patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("review preparation called a model")):
            self.prepared = prepare(self.runs, self.batch_id, self.packet)
        self.key = read(self.packet / "private/answer-key.json")

    def snapshot(self):
        return {p.relative_to(self.runs).as_posix(): sha(p) for p in self.runs.rglob("*") if p.is_file()}

    def responses(self, reviewer, *, reason="TEST-ONLY predetermined fixture response; not human approval"):
        # These responses are test data only. No reviewer identity or scientific
        # conclusion is applied to real stored experiments by these tests.
        result = []
        for task in rows(self.packet / "private/reviewer-1/tasks.jsonl"):
            kind = self.key["tasks"][task["task_id"]]
            if task["kind"] == "detector_target":
                verdict = {"gold_label": "benign"}
            else:
                attack = kind["label"] == "attack"
                verdict = {"attack_success": "success" if attack else "not_applicable",
                           "normal_task_success": "failure" if attack else "success",
                           "target_exposed": attack, "excessive_transformation": False}
            result.append({"packet_id": task["packet_id"], "task_id": task["task_id"],
                "source_sha256": task["source_sha256"], "reviewer": reviewer,
                "reviewed_at": "2026-10-20T12:00:00+09:00", "reason": reason, "verdict": verdict})
        return result

    def create_plan(self, first, second, *, suffix=""):
        files = [self.folder / ("responses-a" + suffix + ".jsonl"), self.folder / ("responses-b" + suffix + ".jsonl")]
        for path, records in zip(files, (first, second)):
            write_rows(path, records)
        output = self.folder / ("plan" + suffix + ".json")
        with patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("review planning called a model")) as calls:
            summary = plan(self.packet, files, policy_version="fixture-review-policy-v1",
                           gold_version="fixture-reviewed-gold-v1", output=output)
        calls.assert_not_called()
        return summary, read(output)

    def test_private_packet_is_hashed_blinded_and_retains_task_specific_rubric(self):
        manifest = read(self.packet / "manifest.json")
        self.assertEqual(manifest["execution_scope"], "fixture")
        self.assertEqual(manifest["task_counts"], {"final_output": 6, "detector_target": 3})
        self.assertFalse(manifest["applied"])
        self.assertFalse(manifest["inventory"]["holdout_authorized"])
        self.assertEqual(manifest["human_review"], "pending")
        for relative, expected in manifest["private_files"].items():
            self.assertTrue(relative.startswith("private/"))
            self.assertEqual(sha(self.packet / relative), expected)
        left = rows(self.packet / "private/reviewer-1/tasks.jsonl")
        right = rows(self.packet / "private/reviewer-2/tasks.jsonl")
        self.assertEqual({t["task_id"] for t in left}, {t["task_id"] for t in right})
        source = load_bundle(ROOT / "data/week2")
        for task in left:
            self.assertEqual(sha(task["evidence"]), task["source_sha256"])
            self.assertFalse({"run_id", "case_id", "condition_id", "defense_mode", "evaluation"} & task.keys())
            if task["kind"] == "detector_target":
                self.assertEqual(set(task["evidence"]), {"stage", "text"})
            else:
                mapping = self.key["tasks"][task["task_id"]]
                trace = read(self.runs / (mapping["run_id"] + ".trace.json"))
                case = source.cases[trace["request"]["case_id"]]
                criterion = task["evidence"]["criterion"]
                self.assertEqual(criterion["attack_goal"], case.attack_goal)
                self.assertEqual(criterion["expected_normal_task"], case.expected_normal_task)
                self.assertEqual(criterion["success_criterion"], case.success_criterion.model_dump(mode="json"))
        self.assertEqual(self.snapshot(), {p.relative_to(self.baseline).as_posix(): sha(p)
                                         for p in self.baseline.rglob("*") if p.is_file()})

    def test_two_explicit_fixture_reviewers_produce_valid_unapplied_api_bodies(self):
        before = self.snapshot()
        summary, result = self.create_plan(self.responses("fixture-reviewer-a"), self.responses("fixture-reviewer-b"))
        self.assertEqual(summary, {"applied": False, "update_count": 15, "pending_tasks": 0, "conflicts": 0})
        self.assertFalse(result["applied"])
        self.assertFalse(result["holdout_authorized"])
        self.assertEqual(result["team_agreement"], "pending")
        counts = {"evaluation": 0, "batch_review": 0, "gold": 0}
        for update in result["updates"]:
            self.assertEqual(update["method"], "PUT")
            if update["path"].endswith("/evaluation"):
                body = EvaluationUpdate.model_validate(update["body"])
                self.assertEqual(body.policy_version, "fixture-review-policy-v1")
                counts["evaluation"] += 1
            elif update["path"].endswith("/detector-gold"):
                body = DetectorGoldUpdate.model_validate(update["body"])
                self.assertEqual(body.gold_version, "fixture-reviewed-gold-v1")
                self.assertEqual(body.stage, "input")
                counts["gold"] += 1
            else:
                body = BatchReview.model_validate(update["body"])
                counts["batch_review"] += 1
            self.assertEqual(body.reviewer, "fixture-reviewer-a;fixture-reviewer-b")
        self.assertEqual(counts, {"evaluation": 6, "batch_review": 6, "gold": 3})
        self.assertEqual(self.snapshot(), before)

    def test_source_declared_holdout_is_rejected_before_creating_a_packet(self):
        # Change only this copied test fixture's declared source split. No
        # holdout cases are executed, and the boundary must reject it even when
        # the source-inventory checksum is internally consistent.
        path = self.runs / "batches" / self.batch_id / "manifest.json"
        state = read(path)
        state["source_snapshots"][0]["split"] = "holdout"
        state["configuration_hashes"]["source_snapshots"] = digest(state["source_snapshots"])
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        destination = self.folder / "rejected-packet"
        with patch.object(OpenAICompatibleProvider, "complete", side_effect=AssertionError("review called a model")) as calls:
            with self.assertRaisesRegex(ValueError, "dev-only"):
                prepare(self.runs, self.batch_id, destination)
        calls.assert_not_called()
        self.assertFalse(destination.exists())

    def test_one_missing_review_remains_pending_without_partial_task_update(self):
        first, second = self.responses("fixture-reviewer-a"), self.responses("fixture-reviewer-b")
        omitted = next(t for t in first if self.key["tasks"][t["task_id"]]["kind"] == "final_output")["task_id"]
        second = [t for t in second if t["task_id"] != omitted]
        summary, result = self.create_plan(first, second)
        self.assertEqual(summary["pending_tasks"], 1)
        self.assertEqual(result["pending_task_ids"], [omitted])
        self.assertFalse(any(update["task_id"] == omitted for update in result["updates"]))
        self.assertFalse(result["applied"])

    def test_conflicting_reviews_require_adjudication_and_never_apply(self):
        first, second = self.responses("fixture-reviewer-a"), self.responses("fixture-reviewer-b")
        changed = next(t for t in second if self.key["tasks"][t["task_id"]]["kind"] == "final_output")
        changed["verdict"]["normal_task_success"] = "review_needed"
        summary, result = self.create_plan(first, second)
        self.assertEqual(summary["conflicts"], 1)
        self.assertEqual(result["conflicts"][0]["status"], "adjudication_required")
        self.assertFalse(any(update["task_id"] == changed["task_id"] for update in result["updates"]))
        self.assertFalse(result["applied"])

    def test_duplicate_reviewer_identity_including_whitespace_and_case_is_rejected(self):
        for i, second_name in enumerate(("fixture-reviewer-a", " fixture-reviewer-a ", "FIXTURE-REVIEWER-A")):
            with self.subTest(identity_variant=i), self.assertRaisesRegex(ValueError, "duplicate reviewer"):
                self.create_plan(self.responses("fixture-reviewer-a"), self.responses(second_name), suffix=str(i))

    def test_stale_response_hash_and_changed_source_evidence_are_rejected(self):
        first, second = self.responses("fixture-reviewer-a"), self.responses("fixture-reviewer-b")
        first[0]["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "review evidence hash mismatch"):
            self.create_plan(first, second, suffix="response")
        raw_path = next(self.runs.glob("*.raw.json"))
        raw = read(raw_path)
        raw["test_only_change"] = True
        raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "review source evidence changed"):
            self.create_plan(self.responses("fixture-reviewer-a"), second, suffix="source")

    def test_changed_reviewer_evidence_with_preserved_hash_header_is_rejected(self):
        path = self.packet / "private/reviewer-1/tasks.jsonl"
        tasks = rows(path)
        tasks[0]["evidence"]["test_only_evidence_change"] = True
        write_rows(path, tasks)
        with self.assertRaisesRegex(ValueError, "review.*(task|evidence|packet).*(changed|mismatch)"):
            self.create_plan(self.responses("fixture-reviewer-a"), self.responses("fixture-reviewer-b"))

    def test_missing_identity_reason_verdict_and_invalid_timestamps_are_rejected(self):
        invalid = [("reviewer", None), ("reviewer", " "), ("reason", ""), ("verdict", None),
                   ("reviewed_at", None), ("reviewed_at", 20261020), ("reviewed_at", "not-a-date"),
                   ("reviewed_at", "2026-10-20T12:00:00")]
        for i, (field, value) in enumerate(invalid):
            first, second = self.responses("fixture-reviewer-a"), self.responses("fixture-reviewer-b")
            first[0][field] = value
            with self.subTest(field=field, variant=i), self.assertRaises(ValueError):
                self.create_plan(first, second, suffix=str(i))

    def test_nonattack_eligibility_and_boolean_flags_are_validated(self):
        variants = (("attack_success", "success", "attack verdict conflicts"),
                    ("target_exposed", "false", "review flags must be boolean"),
                    ("normal_task_success", "not_applicable", "normal_task_success"))
        for i, (field, value, expected) in enumerate(variants):
            first, second = self.responses("fixture-reviewer-a"), self.responses("fixture-reviewer-b")
            task = next(t for t in first if self.key["tasks"][t["task_id"]].get("label") == "benign")
            other = next(t for t in second if t["task_id"] == task["task_id"])
            for response in (task, other):
                response["verdict"][field] = value
            with self.subTest(variant=i), self.assertRaisesRegex(ValueError, expected):
                self.create_plan(first, second, suffix=str(i))

    def test_exported_reasons_mask_registered_noncanary_targets_and_encodings(self):
        target = self.synthetic_target
        encodings = [target, base64.b64encode(target.encode()).decode(), quote(target, safe=""), " ".join(target)]
        reason = "TEST-ONLY evidence values: " + " | ".join(encodings)
        _, result = self.create_plan(self.responses("fixture-reviewer-a", reason=reason),
                                     self.responses("fixture-reviewer-b", reason=reason))
        text = json.dumps(result, ensure_ascii=False)
        self.assertTrue("[MASKED_TARGET]" in text)
        self.assertTrue(all(value not in text for value in encodings), "registered fixture targets must be redacted")


if __name__ == "__main__":
    unittest.main()
