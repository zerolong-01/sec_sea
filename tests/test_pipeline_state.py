"""One output owns one writer, including the interval before checkpoint creation."""
from __future__ import annotations

import subprocess
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.storage import ConcurrentWriterError, exclusive_file_lock
from scripts.data_contract import ROOT
from scripts.pipeline_state import VerificationError, locked_output, record_verification_failure
from scripts.week3_pipeline import verify


class PipelineOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / "pipeline"

    def test_second_pipeline_cannot_prepare_or_create_another_plan(self):
        with locked_output(self.output, "pipeline.json"), patch("scripts.week3_pipeline._verify") as work:
            with self.assertRaisesRegex(VerificationError, "PIPELINE_ALREADY_RUNNING"):
                verify(self.output)
            work.assert_not_called()
        with locked_output(self.output, "pipeline.json"):
            self.assertTrue((self.output / ".pipeline.lock").is_file())

    def test_unowned_or_missing_read_only_output_is_not_modified(self):
        with self.assertRaisesRegex(VerificationError, "PIPELINE_NOT_CREATED"):
            verify(self.output, report_only=True)
        self.assertFalse(self.output.exists())
        self.output.mkdir()
        (self.output / "unrelated.txt").write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(VerificationError, "OUTPUT_DIRECTORY_NOT_OWNED"):
            verify(self.output)
        self.assertEqual([p.name for p in self.output.iterdir()], ["unrelated.txt"])

    def test_process_lock_conflict_and_crash_release_do_not_use_stale_pid_files(self):
        lock = self.output / ".pipeline.lock"
        code = """import os,sys
from pathlib import Path
from backend.app.storage import ConcurrentWriterError,exclusive_file_lock
try:
    with exclusive_file_lock(Path(sys.argv[1])):
        os._exit(0)
except ConcurrentWriterError:
    sys.exit(17)
"""
        with exclusive_file_lock(lock):
            child = subprocess.run([sys.executable, "-c", code, str(lock)], cwd=ROOT,
                                   capture_output=True, timeout=15)
            self.assertEqual(child.returncode, 17, child.stderr)
        crashed = subprocess.run([sys.executable, "-c", code, str(lock)], cwd=ROOT,
                                 capture_output=True, timeout=15)
        self.assertEqual(crashed.returncode, 0, crashed.stderr)
        self.assertTrue(lock.exists())
        with exclusive_file_lock(lock):
            pass

    def test_failed_or_interrupted_refresh_replaces_stale_success_without_echoing_error_text(self):
        self.output.mkdir()
        (self.output / "pipeline.json").write_text('{"version":"test-v1"}', encoding="utf-8")
        record = self.output / "verification-report.json"
        for error in (RuntimeError("private-provider-text"), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                record.write_text('{"status":"passed"}', encoding="utf-8")
                with self.assertRaises(type(error)):
                    with record_verification_failure(self.output, "test-v1", marker="pipeline.json"):
                        raise error
                result = json.loads(record.read_text(encoding="utf-8"))
                self.assertEqual(result["status"], "failed")
                self.assertNotIn("private-provider-text", record.read_text(encoding="utf-8"))

    def test_foreign_marker_does_not_authorize_replacing_its_completion_record(self):
        self.output.mkdir()
        (self.output / "pipeline.json").write_text('{"version":"foreign-v1"}', encoding="utf-8")
        record = self.output / "verification-report.json"
        record.write_text('{"status":"passed"}', encoding="utf-8")
        original = record.read_bytes()
        with self.assertRaises(RuntimeError):
            with record_verification_failure(self.output, "test-v1", marker="pipeline.json"):
                raise RuntimeError("not owned")
        self.assertEqual(record.read_bytes(), original)
