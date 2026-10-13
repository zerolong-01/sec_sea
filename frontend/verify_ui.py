"""2주차 화면 통합 검증 (#24)

대표 3건 × 방어 모드 4개 = 12건을 실행하고, 비교 화면 표에 들어가는 값이
① 실행 응답 ② API 재조회(GET) ③ 저장된 trace 파일 세 곳에서 모두 같은지 확인한다.
공격 케이스는 D2 위치 3개 비교도 함께 실행한다. 결과는 마크다운 기록으로 남긴다.

서버를 먼저 켠 뒤 저장소 루트에서 실행한다.
    py -m scripts.mvp serve --fixture-model        (창 하나)
    .venv\\Scripts\\python frontend\\verify_ui.py    (다른 창)
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from ui_core import (
    BACKEND_URL, COMPARE_SAME, ROOT, SHARED, compare_verdict, label_of, run_case, summary_row,
)

KST = timezone(timedelta(hours=9))
BOTH = SHARED["defense_positions"]["BOTH"]["value"]
D2 = SHARED["defense_modes"]["D2"]["value"]
MODES = [item["value"] for item in SHARED["defense_modes"].values()]
POSITIONS = [item["value"] for item in SHARED["defense_positions"].values()]
# 실행이 정상적으로 끝난 상태: 완료, 방어로 차단됨(정상적인 방어 동작)
FINISHED = {SHARED["run_statuses"][name]["value"] for name in ("COMPLETED", "BLOCKED")}
FAILED = SHARED["run_statuses"]["FAILED"]["value"]


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_run(trace, error, mode, position, runs_dir):
    """한 건의 실행을 점검한다. (문제 목록, 비교 표 한 줄)을 돌려준다."""
    problems = []
    title = label_of("defense_modes", mode)
    if not trace:
        return [f"결과 없음: {(error or {}).get('code') or '서버 연결 실패'}"], summary_row("방어 모드", title, None, error)
    run_id = trace["run_id"]
    shown = summary_row("방어 모드", title, trace, error)

    # ① 실행 자체가 정상적으로 끝났는지. 방어 차단(blocked)은 정상, 실행 오류(failed)는 문제다.
    status = trace.get("status")
    trace_error = trace.get("error") or {}
    if status == FAILED:
        problems.append(f"실행 오류(failed): {trace_error.get('code') or '오류 코드 없음'}")
    elif status not in FINISHED:
        problems.append(f"끝나지 않은 상태: {status}")
    elif trace_error:
        problems.append(f"trace 오류 기록: {trace_error.get('code') or trace_error}")
    if error:
        problems.append(f"요청 오류 {error.get('status')}: {error.get('code') or ''}".strip())
    detector_errors = [e for e in trace.get("defense_events") or [] if e.get("error")]
    if detector_errors:
        problems.append(f"방어 판정 오류 {len(detector_errors)}건")

    # ② API 재조회 값과 비교
    got = requests.get(f"{BACKEND_URL}/api/v1/runs/{run_id}", timeout=30)
    if got.status_code != 200:
        problems.append(f"GET 응답 {got.status_code}")
    elif summary_row("방어 모드", title, got.json(), error) != shown:
        problems.append("화면 값과 GET 값이 다름")

    # ③ 저장된 trace 파일과 비교
    saved = runs_dir / f"{run_id}.trace.json"
    if not saved.exists():
        problems.append(f"저장 파일 없음: {saved.name}")
    else:
        file_trace = json.loads(saved.read_text(encoding="utf-8"))
        if summary_row("방어 모드", title, file_trace, error) != shown:
            problems.append("화면 값과 저장 파일 값이 다름")

    # 요청한 방어가 실제로 적용됐는지 (서버가 남긴 manifest·이벤트 기준)
    manifest = trace.get("manifest") or {}
    applied = set((manifest.get("defense_config_versions") or {}).keys())
    expected = {"none": set(), "D1": {"D1"}, "D2": {"D2"}, "D1+D2": {"D1", "D2"}}[mode]
    if applied != expected:
        problems.append(f"적용된 방어 {sorted(applied)} ≠ 요청 {sorted(expected)}")
    if "D2" in expected:
        if manifest.get("defense_position") != position:
            problems.append(f"D2 위치 {manifest.get('defense_position')} ≠ 요청 {position}")
        if not any(e.get("defense_id") == "D2" for e in trace.get("defense_events") or []):
            problems.append("D2 판정 이벤트 없음")
    return problems, shown


def table(rows):
    """dict 목록을 마크다운 표로 만든다."""
    if not rows:
        return ""
    keys = list(dict.fromkeys(key for row in rows for key in row))
    lines = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(key, "")).replace("|", "/") for key in keys) + " |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="2주차 화면 통합 검증")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("DATA_DIR", ROOT / "data")))
    parser.add_argument("--runs-dir", type=Path, default=Path(os.environ.get("RUNS_DIR", ROOT / "runs")))
    parser.add_argument("--out", type=Path, default=ROOT / "frontend" / "verification" / "week2-ui-verification.md")
    args = parser.parse_args()

    try:
        health = requests.get(f"{BACKEND_URL}/health", timeout=10).json()
    except requests.RequestException:
        print(f"백엔드({BACKEND_URL})에 연결할 수 없습니다. 서버를 먼저 켜세요.")
        return 1

    manifest = json.loads((args.data_dir / "mvp-manifest.v0.1.json").read_text(encoding="utf-8"))
    cases = {case["case_id"]: case for case in load_jsonl(args.data_dir / "cases.v0.1.jsonl")}
    corpus_version = manifest["corpus_version"]
    started = datetime.now(KST)

    all_problems = []
    mode_sections, position_sections = [], []
    scopes = set()
    for item in manifest["representative_cases"]:
        case = cases[item["case_id"]]
        args_run = (case["case_id"], case["scenario"], case["source_version"], corpus_version)

        # 4개 모드 비교
        results, rows = [], []
        for mode in MODES:
            trace, error = run_case(*args_run, mode, BOTH)
            problems, row = check_run(trace, error, mode, BOTH, args.runs_dir)
            if trace:
                scopes.add((trace.get("manifest") or {}).get("execution_scope"))
            row["점검"] = "통과" if not problems else "문제: " + "; ".join(problems)
            all_problems += [f"{case['case_id']} {mode}: {p}" for p in problems]
            rows.append(row)
            results.append({"title": label_of("defense_modes", mode), "trace": trace, "error": error})
        verdict, message, _ = compare_verdict(results)
        if verdict != COMPARE_SAME:
            all_problems.append(f"{case['case_id']} 모드 비교 {verdict}: {message}")
        mode_sections.append((case, rows, f"{verdict} - {message}"))

        # 공격 케이스는 D2 위치 비교도 실행
        if case["label"] == "attack":
            results, rows = [], []
            for position in POSITIONS:
                trace, error = run_case(*args_run, D2, position)
                problems, row = check_run(trace, error, D2, position, args.runs_dir)
                row = {"D2 적용 위치": label_of("defense_positions", position), **row}
                row.pop("방어 모드", None)
                row["점검"] = "통과" if not problems else "문제: " + "; ".join(problems)
                all_problems += [f"{case['case_id']} D2@{position}: {p}" for p in problems]
                rows.append(row)
                results.append({"title": position, "trace": trace, "error": error})
            verdict, message, _ = compare_verdict(results)
            if verdict != COMPARE_SAME:
                all_problems.append(f"{case['case_id']} 위치 비교 {verdict}: {message}")
            position_sections.append((case, rows, f"{verdict} - {message}"))

    scope_text = ", ".join(label_of("execution_scopes", s) or str(s) for s in sorted(scopes, key=str))
    lines = [
        "# 2주차 화면 통합 검증 기록 (#24)",
        "",
        f"- 실행 시각: {started.strftime('%Y-%m-%d %H:%M')} (한국 시간)",
        f"- 실행 범위: {scope_text}  ← fixture는 정해진 가짜 응답이며 실제 모델 성능이 아님",
        f"- 백엔드: {BACKEND_URL} · 계약 버전 {health.get('schema_version')} · 제공자 {health.get('model_provider')}",
        f"- 데이터: {args.data_dir} · 코퍼스 버전 {corpus_version}",
        "- 확인 방법: 비교 화면 표의 값을 ① 실행 응답 ② GET 재조회 ③ runs/{run_id}.trace.json 에서 각각 만들어 같은지 비교.",
        "  요청한 방어(D1/D2)와 D2 위치가 manifest·판정 이벤트에 실제로 남았는지, 비교 조건이 같은지도 확인.",
        "- 실행 상태: 완료와 방어로 차단됨(정상적인 방어 동작)은 통과, 실행 실패(failed)·trace 오류·방어 판정 오류·결과 없음은 문제로 기록.",
        "- 화면은 서버 판정·지표를 그대로 옮기며 성공 여부나 지표를 새로 계산하지 않음.",
        "",
        f"## 결과: {'전체 통과' if not all_problems else f'문제 {len(all_problems)}건'}",
        "",
    ]
    lines += [f"- {p}" for p in all_problems]
    lines += ["", "## 대표 3건 × 4개 모드 (D2 위치: 입력 + 문서)", ""]
    for case, rows, verdict_text in mode_sections:
        lines += [f"### {case['case_id']} · {label_of('case_labels', case['label'])}",
                  f"비교 조건: {verdict_text}", "",
                  table(rows), ""]
    lines += ["## D2 위치 비교 (공격 케이스, D1 없음)", ""]
    for case, rows, verdict_text in position_sections:
        lines += [f"### {case['case_id']}",
                  f"비교 조건: {verdict_text}", "",
                  table(rows), ""]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"검증 기록 저장: {args.out}")
    print("전체 통과" if not all_problems else f"문제 {len(all_problems)}건 (기록 파일 확인)")
    return 0 if not all_problems else 1


if __name__ == "__main__":
    sys.exit(main())
