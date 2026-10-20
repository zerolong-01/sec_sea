"""CSV 다운로드가 화면의 평가 버전과 필터에 속하는지 검증한다."""
import copy
import csv
import io
import json
import unittest

from tests.test_batch_dashboard import REPORT, batch_core


def csv_bytes(report, overrides=None, *, bom=False, extra_rows=()):
    row = {key: report[key] for key in ("batch_id", "report_version", "evaluation_snapshot_sha256")}
    row["filters"] = json.dumps(batch_core.clean_filters(report["filters"]))
    calculation = report.get("provenance", {}).get("calculation_implementation_sha256")
    if calculation:
        row["calculation_implementation_sha256"] = calculation
    row.update(group_id="group-1", metric="asr", value="0", denominator="3")
    row.update(overrides or {})
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    for extra in extra_rows:
        writer.writerow(dict(row, **extra))
    return stream.getvalue().encode("utf-8-sig" if bom else "utf-8")


class ExportSnapshotTest(unittest.TestCase):
    def test_accepts_api_and_bom_exports_with_extra_metric_columns(self):
        report = copy.deepcopy(REPORT)
        report["filters"]["language"] = "ko"
        for bom in (False, True):
            with self.subTest(bom=bom):
                self.assertIsNone(batch_core.csv_report_error(csv_bytes(report, bom=bom), report))

    def test_rejects_new_snapshot_other_batch_version_or_filter(self):
        mismatches = {
            "evaluation_snapshot_sha256": "new-evaluation",
            "batch_id": "batch-000000000000",
            "report_version": "new-calculation-version",
            "filters": json.dumps({"language": "ko"}),
        }
        for key, value in mismatches.items():
            with self.subTest(key=key):
                error = batch_core.csv_report_error(csv_bytes(REPORT, {key: value}), REPORT)
                self.assertEqual(error["code"], "SNAPSHOT_MISMATCH")

    def test_every_row_must_belong_to_the_same_snapshot(self):
        content = csv_bytes(REPORT, extra_rows=[{"evaluation_snapshot_sha256": "another-snapshot"}])
        self.assertEqual(batch_core.csv_report_error(content, REPORT)["code"], "SNAPSHOT_MISMATCH")

    def test_v03_calculation_hash_is_checked_without_requiring_it_in_v02(self):
        report = copy.deepcopy(REPORT)
        report["provenance"]["calculation_implementation_sha256"] = "implementation-a"
        self.assertIsNone(batch_core.csv_report_error(csv_bytes(report), report))
        different = csv_bytes(report, {"calculation_implementation_sha256": "implementation-b"})
        self.assertEqual(batch_core.csv_report_error(different, report)["code"], "SNAPSHOT_MISMATCH")
        self.assertEqual(batch_core.csv_report_error(csv_bytes(REPORT), report)["code"], "INVALID_RESPONSE")

    def test_rejects_header_only_missing_metadata_and_malformed_content(self):
        header_only = csv_bytes(REPORT).splitlines(keepends=True)[0]
        contents = [header_only, b"group_id,metric\ngroup-1,asr\n", b"\xff",
                    csv_bytes(REPORT, {"filters": "{"}), csv_bytes(REPORT, {"filters": "[]"})]
        for content in contents:
            with self.subTest(content=content):
                self.assertEqual(batch_core.csv_report_error(content, REPORT)["code"], "INVALID_RESPONSE")


if __name__ == "__main__":
    unittest.main()
