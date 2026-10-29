"""Export the backend comparison and check the two corresponding report tables."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.research_comparison import METRICS, comparison_csv, original_attack_comparison
from backend.app.research_reports import ROOT

DOCUMENT_TABLES = {"data/week4/final-report.md": "### 4.2 기존 원본 공격 전체 비교",
                   "data/week4/defense-comparison.md": "### 2.2 기존 원본 공격 전체"}


def document_errors(report, *, root=ROOT):
    expected = {row["display_condition"]: [f'{row["metrics"][key]["numerator"]}/{row["metrics"][key]["denominator"]}'
                if row["metrics"][key]["denominator"] else "null"
                for key in METRICS] for row in report.rows}
    errors = []
    for name, heading in DOCUMENT_TABLES.items():
        lines = (root / name).read_text(encoding="utf-8").splitlines()
        if lines.count(heading) != 1:
            errors.append(f"{name}: missing or duplicate comparison heading")
            continue
        section = []
        for line in lines[lines.index(heading) + 1:]:
            if line.startswith("##"):
                break
            section.append(line)
        actual = {}
        has_headings = False
        for line in section:
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            has_headings |= cells == ["방어 방식", "공격 목표 달성", "공격 상황 업무 성공"]
            if cells[0] in expected:
                if cells[0] in actual:
                    errors.append(f"{name}: duplicate condition {cells[0]}")
                actual[cells[0]] = cells[1:]
        if not has_headings:
            errors.append(f"{name}: comparison metric headings differ from the backend contract")
        if actual != expected:
            errors.append(f"{name}: comparison values differ from backend AI evidence")
        if not all(f"`{case}`" in "\n".join(section) for case in report.selection["case_ids"]):
            errors.append(f"{name}: selected case identifiers are missing")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-docs", action="store_true")
    parser.add_argument("--output", type=Path, help="New directory for report.json and metrics.csv")
    args = parser.parse_args(argv)
    report = original_attack_comparison()
    errors = document_errors(report) if args.check_docs else []
    if errors:
        print(json.dumps({"status": "failed", "errors": errors}, ensure_ascii=False))
        return 1
    if args.output:
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "report.json").write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        (args.output / "metrics.csv").write_text(comparison_csv(report), encoding="utf-8-sig", newline="")
    print(json.dumps({"status": "passed", "report_version": report.report_version,
                      "report_sha256": report.report_sha256, "evaluation_source": report.evaluation_source,
                      "output_runs": report.selection["output_runs"], "conditions": len(report.rows),
                      "checked_documents": list(DOCUMENT_TABLES) if args.check_docs else [], "model_calls": 0},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
