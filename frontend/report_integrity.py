"""화면의 JSON과 다운로드 CSV가 같은 보고서인지 검사한다. 집계하지 않는다."""
import csv
import hashlib
import io
import json

from ui_core import api_error


def report_error(report, *, version, identifier, value, source):
    try:
        payload = {k: v for k, v in report.items() if k != "report_sha256"}
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        actual_source = report.get("evaluation_source", (report.get("provenance") or {}).get("evaluation_source"))
        if (report[identifier] != value or report["report_version"] != version or
                actual_source != source or report["report_sha256"] != digest):
            raise ValueError("Report identity mismatch")
    except (KeyError, TypeError, ValueError, AttributeError):
        return api_error(code="INVALID_RESPONSE", message="보고서의 식별·버전·출처 또는 해시를 확인할 수 없습니다.")
    return None


def csv_error(content, expected, *, identity, json_fields=()):
    """분자/분모·null·JSON 메타데이터·행 소속을 전부 대조한다."""
    invalid = api_error(code="INVALID_RESPONSE", message="CSV 형식이 올바르지 않습니다.")
    mismatch = api_error(code="SNAPSHOT_MISMATCH", message="화면 보고서와 CSV의 값·필터·근거 또는 행 소속이 다릅니다.")
    try:
        columns = set(expected[0])
        by_id = {tuple(row[k] for k in identity): row for row in expected}
        if len(by_id) != len(expected):
            return invalid
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
        if len(reader.fieldnames or []) != len(columns) or set(reader.fieldnames or []) != columns:
            return invalid
        seen = set()
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                return invalid
            key = tuple(row[k] for k in identity)
            if key in seen or key not in by_id:
                return mismatch
            seen.add(key)
            for field, value in by_id[key].items():
                if field in json_fields and value != "":
                    if json.loads(row[field]) != value:
                        return mismatch
                elif row[field] != ("" if value is None else str(value)):
                    return mismatch
        return None if seen == set(by_id) else mismatch
    except (UnicodeError, csv.Error, KeyError, ValueError, TypeError, IndexError):
        return invalid
