"""A transferred raw store stays usable without the sender's paths or credentials."""
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
import unittest

from backend.app.batch import digest
from scripts.week4_package import tree_hashes
from scripts import week5_model_handoff as handoff
from tests import test_verify_real_model_experiment as source_fixture


class ModelHandoffTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing real-transport fixture builder, without inheriting
        # and rerunning its unrelated test methods.
        self.source = source_fixture.RealModelExperimentVerificationTests()
        self.addCleanup(self.source.doCleanups)
        self.source.setUp()
        self.source.payload["batch"]["conditions"].append(
            {"condition_id": "D1", "defense_mode": "D1", "comparisons": ["technique"]})
        self.source.save_spec()
        self.initial = self.source.verify(execute=True)
        self.runs = self.source.output / "runs"
        self.package = self.source.folder / "handoff"
        self.experiment_id = self.initial["experiment_id"]
        self.expected_runs = 12
        self.assertEqual(self.initial["planned_runs"], self.expected_runs)

    def export(self, output=None, **kwargs):
        return handoff.export_handoff(self.runs, self.experiment_id, output or self.package,
            expected_runs=self.expected_runs, allow_fixture=True, **kwargs)

    def inspect(self, manifest):
        return handoff.inspect_handoff(self.package, expected_manifest_sha256=manifest["manifest_sha256"],
            expected_runs=self.expected_runs, allow_fixture=True)

    def resign(self, manifest):
        manifest["manifest_sha256"] = digest({k: v for k, v in manifest.items() if k != "manifest_sha256"})
        (self.package / handoff.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")

    def test_relocated_raw_store_verifies_api_ui_csv_without_original_store_or_new_calls(self):
        (self.runs / ".env").write_text("DO_NOT_TRANSFER=private-fixture-key", encoding="utf-8")
        before, calls = tree_hashes(self.runs), len(self.source.fixture.requests)
        manifest = self.export()
        self.assertEqual(tree_hashes(self.runs), before)
        names = manifest["runs_files"]
        self.assertEqual(sum(n.endswith(".raw.json") for n in names), self.expected_runs)
        self.assertEqual(sum(n.endswith(".trace.json") for n in names), self.expected_runs)
        self.assertNotIn(".env", names)
        self.assertFalse((self.package / "runs/.env").exists())
        self.runs.rename(self.source.folder / "unavailable-original")
        with patch("backend.app.providers.OpenAICompatibleProvider.complete", side_effect=AssertionError("Model called")):
            result = handoff.verify_handoff(self.package, self.source.folder / "receiver-verification",
                expected_manifest_sha256=manifest["manifest_sha256"],
                expected_runs=self.expected_runs, allow_fixture=True)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["api_ui_csv_trace_match"] and result["handoff_unchanged"])
        self.assertEqual(result["execution_scope"], "fixture")
        self.assertEqual(result["attempt_count"], self.expected_runs)
        self.assertEqual(result["read_model_calls"], 0)
        self.assertFalse(result["human_acceptance"])
        self.assertEqual(len(self.source.fixture.requests), calls)

    def test_missing_original_raw_is_rejected_before_a_package_is_created(self):
        next(self.runs.glob("*.raw.json")).unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            self.export()
        self.assertFalse(self.package.exists())

    def test_tampering_and_extra_files_are_rejected_before_ui_reads(self):
        manifest = self.export()
        raw = next((self.package / "runs").glob("*.raw.json"))
        original = raw.read_bytes()
        raw.write_bytes(original + b" ")
        with patch.object(handoff, "verify_saved_models") as verify:
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                handoff.verify_handoff(self.package, self.source.folder / "failed-check",
                    expected_manifest_sha256=manifest["manifest_sha256"],
                    expected_runs=self.expected_runs, allow_fixture=True)
            verify.assert_not_called()
        raw.write_bytes(original)
        (self.package / "runs/.env").write_text("DO_NOT_TRANSFER=private", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.inspect(manifest)

    def test_manifest_identity_and_unsafe_paths_cannot_be_rehashed_into_an_accepted_package(self):
        manifest = self.export()
        changed = copy.deepcopy(manifest)
        changed["planned_runs"] += 1
        self.resign(changed)
        with self.assertRaisesRegex(ValueError, "trusted identity"):
            self.inspect(manifest)
        changed = copy.deepcopy(manifest)
        changed["runs_files"]["../outside.json"] = "0" * 64
        changed["runs_files_sha256"] = digest(changed["runs_files"])
        self.resign(changed)
        with self.assertRaisesRegex(ValueError, "artifact path"):
            self.inspect(changed)

    def test_export_refuses_changed_sources_and_does_not_publish_a_ready_manifest(self):
        original_copy = handoff.shutil.copyfile
        changed = False

        def copy_then_change(source, target):
            nonlocal changed
            result = original_copy(source, target)
            if not changed:
                raw = next(self.runs.glob("*.raw.json"))
                raw.write_bytes(raw.read_bytes() + b" ")
                changed = True
            return result

        with patch.object(handoff.shutil, "copyfile", side_effect=copy_then_change):
            with self.assertRaisesRegex(ValueError, "changed"):
                self.export()
        self.assertFalse((self.package / handoff.MANIFEST).exists())

    def test_fixture_and_wrong_counts_never_pass_as_216_real_runs_or_overwrite_sources(self):
        with self.assertRaisesRegex(ValueError, "Real saved evidence"):
            handoff.export_handoff(self.runs, self.experiment_id, self.package, expected_runs=self.expected_runs)
        with self.assertRaisesRegex(ValueError, "complete experiment"):
            handoff.export_handoff(self.runs, self.experiment_id, self.package, allow_fixture=True)
        with self.assertRaisesRegex(ValueError, "non-overlapping"):
            self.export(self.runs / "child")
        manifest = self.export()
        before = tree_hashes(self.package)
        with self.assertRaisesRegex(ValueError, "new handoff"):
            self.export()
        with self.assertRaisesRegex(ValueError, "non-overlapping"):
            handoff.verify_handoff(self.package, self.package / "check",
                expected_manifest_sha256=manifest["manifest_sha256"],
                expected_runs=self.expected_runs, allow_fixture=True)
        self.assertEqual(tree_hashes(self.package), before)

    def test_missing_source_cli_fails_without_claiming_an_export_or_calling_models(self):
        output = io.StringIO()
        with redirect_stdout(output), patch("backend.app.providers.OpenAICompatibleProvider.complete") as complete:
            status = handoff.main(["export", "--runs-dir", str(self.source.folder / "absent"),
                                   "--output", str(self.package)])
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "failed")
        complete.assert_not_called()
        self.assertFalse(self.package.exists())


if __name__ == "__main__":
    unittest.main()
