from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.batch import file_hash
from app.repository import RunTraceStore
from app.storage import ConcurrentWriterError, exclusive_file_lock, file_sha256


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def test_artifact_hashes_match_existing_format_without_whole_file_reads(self):
        path = self.folder / "artifact.bin"
        for content in (b"", bytes(range(256)), bytes(range(256)) * 12289):
            with self.subTest(size=len(content)):
                path.write_bytes(content)
                expected = hashlib.sha256(content).hexdigest()
                with patch.object(Path, "read_bytes", side_effect=AssertionError("Unbounded read")):
                    self.assertEqual(file_sha256(path), expected)
                    self.assertEqual(file_hash(path), expected)

    def test_review_lock_coordinates_processes_and_releases_after_exceptions(self):
        store = RunTraceStore(self.folder)
        code = """import sys
from pathlib import Path
from app.repository import RunTraceStore
from app.storage import ConcurrentWriterError
try:
    with RunTraceStore(Path(sys.argv[1])).review_lock('run-test'):
        pass
except ConcurrentWriterError:
    sys.exit(17)
"""
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            with store.review_lock("run-test"):
                child = subprocess.run([sys.executable, "-c", code, str(self.folder)],
                                       cwd=Path(__file__).resolve().parents[1],
                                       capture_output=True, timeout=15)
                self.assertEqual(child.returncode, 17, child.stderr)
                raise RuntimeError("interrupted")
        child = subprocess.run([sys.executable, "-c", code, str(self.folder)],
                               cwd=Path(__file__).resolve().parents[1],
                               capture_output=True, timeout=15)
        self.assertEqual(child.returncode, 0, child.stderr)

    def test_audit_append_conflicts_leave_history_unchanged_and_can_retry(self):
        first, second = RunTraceStore(self.folder), RunTraceStore(self.folder)
        for kind, method in (("evaluation", "save_evaluation"), ("detector-gold", "save_detector_gold")):
            with self.subTest(kind=kind):
                path = getattr(first, method)("run-test", {"reviewer": "first"})
                before = path.read_bytes()
                with exclusive_file_lock(path.with_suffix(".lock")):
                    with self.assertRaises(ConcurrentWriterError):
                        getattr(second, method)("run-test", {"reviewer": "second"})
                self.assertEqual(path.read_bytes(), before)
                getattr(second, method)("run-test", {"reviewer": "second"})
                self.assertEqual(first._read_json(path, list, []),
                                 [{"reviewer": "first"}, {"reviewer": "second"}])
