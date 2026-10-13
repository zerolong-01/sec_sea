"""Validate and prepare week-two data; gold is only exported after execution."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from jsonschema import Draft202012Validator
from pydantic import Field

from backend.app.evaluation import RuleSet
from backend.app.models import CaseRecord, DetectorGoldUpdate, RunTrace, SourceDocument, StrictModel
from scripts.data_contract import ROOT, CANARY_PATTERN, load_bundle, load_jsonl, require


class Technique(StrictModel):
    technique_id: str
    name_ko: str
    attack_case_id: str
    benign_case_id: str
    hard_negative_case_id: str
    surface: Literal["input", "retrieval"]
    d2_targeted: bool
    split: Literal["dev", "holdout"]
    variant_count: int = Field(ge=1)
    repeat_count: Literal[0]


class Catalog(StrictModel):
    version: str
    taxonomy_status: Literal["project_proposal"]
    provenance: str
    techniques: list[Technique]


class LanguageVariant(StrictModel):
    case_id: str
    parent_case_id: str
    language: Literal["en"]
    split: Literal["dev", "holdout"]
    user_input: str = Field(min_length=1)
    translation_status: Literal["single_review", "team_reviewed"]
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class LanguageVariants(StrictModel):
    version: str
    derived_dataset_version: str
    variants: list[LanguageVariant]


class TargetGold(DetectorGoldUpdate):
    case_id: str
    dataset_version: str
    reviewed_at: datetime
    review_status: Literal["single_review", "team_reviewed"]
    target_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_model(path: Path, model):
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def check_package(data_dir: Path) -> dict:
    bundle = load_bundle(data_dir)
    validator = Draft202012Validator(bundle.schema)
    email_cases = load_jsonl(data_dir / "cases.email.v0.1.jsonl", CaseRecord, "case_id", validator)
    email_docs = load_jsonl(data_dir / "corpus.email.v0.1.jsonl", SourceDocument, "document_id", validator)
    require(not (bundle.cases.keys() & email_cases.keys()), "RAG/email case IDs overlap")
    require(not (bundle.documents.keys() & email_docs.keys()), "RAG/email document IDs overlap")
    require(Counter(case.label for case in email_cases.values()) == {"attack": 1, "benign": 1, "hard_negative": 1}, "email labels require one case each")
    for case in email_cases.values():
        require(case.scenario == "email_summary" and case.source_version == "synthetic_email_v0.1", "email case scenario/version mismatch")
        require(bool(case.source_document_ids) and all(d in email_docs for d in case.source_document_ids), f"{case.case_id}: missing email document")
    require(all(d.source_version == "synthetic_email_v0.1" and d.source_type == "email_body" for d in email_docs.values()), "email corpus version/type mismatch")
    cases = {**bundle.cases, **email_cases}
    docs = {**bundle.documents, **email_docs}
    # A document ID or identical document body cannot bridge dev and holdout.
    doc_splits = defaultdict(set)
    input_splits = defaultdict(set)
    for case in cases.values():
        input_splits[text_hash(" ".join(case.user_input.split()).casefold())].add(case.split)
        for doc_id in case.source_document_ids:
            doc_splits[text_hash(" ".join(docs[doc_id].content.split()).casefold())].add(case.split)
    require(all(len(splits) == 1 for splits in doc_splits.values()), "document content crosses dev/holdout")
    require(all(len(splits) == 1 for splits in input_splits.values()), "identical input crosses dev/holdout")

    variants = read_model(data_dir / "language-variants.v0.1.json", LanguageVariants)
    require(variants.derived_dataset_version != bundle.manifest.dataset_version, "derived dataset requires its own version")
    require(len({v.case_id for v in variants.variants}) == len(variants.variants), "duplicate language variant")
    for variant in variants.variants:
        require(variant.parent_case_id in bundle.cases and variant.case_id not in cases, "invalid variant parent/ID")
        require(variant.split == cases[variant.parent_case_id].split, "translation crosses dev/holdout")
        require(variant.user_input != cases[variant.parent_case_id].user_input, "translation duplicates original input")
        CaseRecord.model_validate(cases[variant.parent_case_id].model_dump(mode="json") |
                                  {"case_id": variant.case_id, "language": variant.language,
                                   "user_input": variant.user_input})
    require({cases[v.parent_case_id].label for v in variants.variants} == {"attack", "benign", "hard_negative"}, "language variants require all three labels")

    catalog = read_model(data_dir / "attack-catalog.v0.1.json", Catalog)
    require(len({t.technique_id for t in catalog.techniques}) == len(catalog.techniques), "duplicate technique ID")
    require(len({t.name_ko for t in catalog.techniques}) == len(catalog.techniques), "duplicate technique name")
    require(Counter(t.attack_case_id for t in catalog.techniques) == Counter(c.case_id for c in bundle.cases.values() if c.label == "attack"), "catalog does not cover every attack exactly once")
    require(len(catalog.techniques) >= 20, "at least 20 proposed techniques required")
    for technique in catalog.techniques:
        for cid, label in ((technique.attack_case_id, "attack"), (technique.benign_case_id, "benign"), (technique.hard_negative_case_id, "hard_negative")):
            require(cid in cases and cases[cid].label == label and cases[cid].split == technique.split, "catalog label/split mismatch")
        attack = cases[technique.attack_case_id]
        require((attack.attack_type == "indirect_document") == (technique.surface == "retrieval"), "catalog injection surface mismatch")
        require(technique.variant_count == 1 + sum(v.parent_case_id == attack.case_id for v in variants.variants), "catalog variant count mismatch")

    gold = [TargetGold.model_validate_json(line) for line in (data_dir / "target-gold.v0.1.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    keys = [(g.case_id, g.stage, g.target_ref) for g in gold]
    require(len(set(keys)) == len(keys), "duplicate target gold")
    for row in gold:
        require(row.case_id in cases, "gold references missing case")
        case = cases[row.case_id]
        require(row.dataset_version == case.source_version, "gold dataset version mismatch")
        require(row.reviewed_at.utcoffset() is not None, "gold review timestamp requires timezone")
        if row.stage == "input":
            text = case.user_input
        else:
            require(row.target_ref in case.source_document_ids, "gold references unrelated document")
            document = docs[row.target_ref]
            text = document.title + "\n" + document.content
        require(row.target_sha256 == text_hash(text), "gold inspected text changed; independent re-review required")
    required_cases = {"a006", "b006", "h007", *email_cases}
    for technique in catalog.techniques:
        if technique.d2_targeted:
            required_cases.update((technique.attack_case_id, technique.hard_negative_case_id))
    require(sum(t.d2_targeted for t in catalog.techniques) >= 6, "six D2 techniques required")
    for cid in required_cases:
        require((cid, "input", None) in keys and all((cid, "retrieval", d) in keys for d in cases[cid].source_document_ids), "required input/document gold missing")
    require(next(g.gold_label for g in gold if g.case_id == "a006" and g.stage == "input") == "benign", "a006 input must not inherit case attack label")

    rules = read_model(ROOT / "configs/evaluation-week2.json", RuleSet)
    rule_map = {r.case_id: r for r in rules.rules}
    require(len(rule_map) == len(rules.rules), "duplicate evaluation rule")
    require(set(cases) | {v.case_id for v in variants.variants} == set(rule_map), "evaluation rule coverage mismatch")
    require({c.source_version for c in cases.values()} | {variants.derived_dataset_version} <= set(rules.dataset_versions), "evaluation dataset scope mismatch")
    for case in cases.values():
        values = {value for did in case.source_document_ids for value in CANARY_PATTERN.findall(docs[did].content)}
        rule = rule_map[case.case_id]
        require(set(rule.protected_values) == values, "protected value rules do not match corpus")
        require(rule.normal_task_mode == "manual", "semantic normal tasks must retain manual review")
        if case.label == "attack" and values:
            require(rule.canary in values and rule.canary in case.success_criterion.description, "canary rule mismatches case criterion")
            if "인용" in case.success_criterion.description:
                require(rule.exact_canary_requires_review, "context-dependent marker must require review")
    for variant in variants.variants:
        require(rule_map[variant.case_id].model_dump(exclude={"case_id"}) ==
                rule_map[variant.parent_case_id].model_dump(exclude={"case_id"}), "translation changed evaluation criterion")
    policy = json.loads((data_dir / "evaluation-policy.v0.1.json").read_text(encoding="utf-8"))
    require(policy["status"] == "team_agreement_pending" and policy["final_recommendation_allowed"] is False, "draft policy cannot make final recommendations")
    require(all(v is None for v in policy["thresholds"].values()), "unagreed thresholds must remain null")
    artifacts = sorted(data_dir.glob("*.json*")) + [ROOT / "configs/evaluation-week2.json"]
    return {"status": "passed", "rag_cases": len(bundle.cases), "rag_documents": len(bundle.documents),
            "email_cases": len(email_cases), "email_documents": len(email_docs),
            "proposed_techniques": len(catalog.techniques), "d2_techniques": sum(t.d2_targeted for t in catalog.techniques),
            "language_variants": len(variants.variants), "target_reviews": len(gold),
            "single_review_targets": sum(g.review_status == "single_review" for g in gold),
            "team_agreement": "pending", "real_model_verified": False,
            "artifact_sha256": {p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else p.name: text_hash(p.read_text(encoding="utf-8")) for p in artifacts}}


def prepare(data_dir: Path, output: Path, kind: str) -> Path:
    source_check = check_package(data_dir)
    require(not output.exists(), "output directory already exists; choose a new snapshot path")
    if kind == "email":
        cases = [json.loads(s) for s in (data_dir / "cases.email.v0.1.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]
        corpus = [json.loads(s) for s in (data_dir / "corpus.email.v0.1.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]
        manifest = {"schema_version": "0.1", "scenario": "email_summary", "dataset_version": "synthetic_email_v0.1", "corpus_version": "synthetic_email_v0.1", "hard_negative_security_cases": [],
                    "representative_cases": [{"case_id": c["case_id"], "label": c["label"], "expected_retrieval": [{"document_id": d, "rank": n} for n, d in enumerate(c["source_document_ids"], 1)]} for c in cases]}
    else:
        bundle = load_bundle(data_dir)
        languages = read_model(data_dir / "language-variants.v0.1.json", LanguageVariants)
        version = languages.derived_dataset_version
        cases = [c.model_dump(mode="json") for c in bundle.cases.values()]
        for variant in languages.variants:
            case = bundle.cases[variant.parent_case_id].model_dump(mode="json")
            case.update(case_id=variant.case_id, user_input=variant.user_input, language=variant.language)
            cases.append(case)
        for case in cases:
            case["source_version"] = version
        corpus = [d.model_dump(mode="json") | {"source_version": version} for d in bundle.documents.values()]
        manifest = bundle.manifest.model_dump(mode="json") | {"dataset_version": version, "corpus_version": version}
    output.mkdir(parents=True)
    for name, rows in (("cases.v0.1.jsonl", cases), ("corpus.v0.1.jsonl", corpus)):
        (output / name).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    (output / "mvp-manifest.v0.1.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build = {"build_version": "week2-preparation-v0.1", "kind": kind,
             "dataset_version": manifest["dataset_version"], "source_artifact_sha256": source_check["artifact_sha256"],
             "team_agreement": "pending", "real_model_verified": False}
    (output / "build-manifest.json").write_text(json.dumps(build, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    load_bundle(output)
    return output


def gold_plan(data_dir: Path, runs_dir: Path, include_single_review: bool = False) -> dict:
    check_package(data_dir)
    gold = [TargetGold.model_validate_json(s) for s in (data_dir / "target-gold.v0.1.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]
    by_target = {(g.case_id, g.stage, g.target_ref): g for g in gold}
    updates, excluded = [], []
    paths = sorted(runs_dir.glob("*.trace.json"))
    require(bool(paths), "no saved traces found")
    for path in paths:
        trace = read_model(path, RunTrace)
        raw_path = path.with_name(trace.run_id + ".raw.json")
        require(raw_path.exists(), "private inspection log is required to match gold text")
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        require(raw.get("run_id") == trace.run_id and raw.get("request") == trace.request.model_dump(mode="json"), "trace/raw request mismatch")
        for event in trace.defense_events:
            if event.defense_id != "D2":
                continue
            row = by_target.get((trace.request.case_id, event.stage, event.target_ref))
            reason = None
            if row is None:
                reason = "target_gold_missing"
            elif trace.request.dataset_version != row.dataset_version or trace.request.corpus_version != row.dataset_version:
                reason = "gold_dataset_version_mismatch"
            elif row.review_status != "team_reviewed" and not include_single_review:
                reason = "team_review_pending"
            else:
                calls = [c for c in raw.get("model_calls", []) if c.get("purpose") == "detection" and c.get("target_ref") == event.target_ref]
                texts = []
                for call in calls:
                    try:
                        payload = json.loads(call["messages"][1]["content"])
                        if payload.get("stage") == event.stage and isinstance(payload.get("text"), str):
                            texts.append(payload["text"])
                    except (KeyError, IndexError, TypeError, ValueError):
                        continue
                if not texts:
                    reason = "inspection_text_unavailable"
                elif any(text_hash(t) != row.target_sha256 for t in texts):
                    reason = "inspected_text_hash_mismatch"
            context = {"run_id": trace.run_id, "case_id": trace.request.case_id, "stage": event.stage, "target_ref": event.target_ref}
            if reason:
                excluded.append(context | {"reason": reason})
            else:
                updates.append(context | {"method": "PUT", "path": f"/api/v1/runs/{trace.run_id}/detector-gold",
                                          "review_status": row.review_status,
                                          "body": DetectorGoldUpdate.model_validate(row.model_dump(include=set(DetectorGoldUpdate.model_fields))).model_dump(mode="json")})
    return {"plan_version": "week2-target-gold-plan-v0.1", "applied": False,
            "includes_single_review": include_single_review, "updates": updates, "excluded": excluded}


def verify_handoff(data_dir: Path, output: Path) -> dict:
    """Exercise data/evaluator/gold contracts with local HTTP fixtures, never real models."""
    from fastapi.testclient import TestClient
    from backend.app.config import Settings
    from backend.app.main import create_app
    from backend.testing.fixture_model import FixtureModelServer

    check = check_package(data_dir)
    require(not output.exists(), "verification output already exists")
    output.mkdir(parents=True)
    email_dir = prepare(data_dir, output / "email-data", "email")
    runs_dir = output / "runs"
    summaries, wire_count = [], 0
    gold = [TargetGold.model_validate_json(s) for s in (data_dir / "target-gold.v0.1.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]

    def settings_for(folder, fixture):
        return Settings(project_root=ROOT, data_dir=folder, runs_dir=runs_dir,
                        model_provider="fixture_http", model_id="fixture-generation",
                        system_prompt_version="v0.1", retrieval_config_version="lexical-v0.1",
                        model_base_url=fixture.base_url, model_api_key=None,
                        d2_base_url=fixture.base_url, d2_model_id="fixture-classifier",
                        evaluation_rules_path=ROOT / "configs/evaluation-week2.json")

    for folder in (data_dir, email_dir):
        bundle = load_bundle(folder)
        with FixtureModelServer(folder) as fixture:
            settings = settings_for(folder, fixture)
            with TestClient(create_app(settings)) as client:
                # Only dev samples: holdout remains outside the pilot workflow.
                case_ids = sorted({g.case_id for g in gold if g.case_id in bundle.cases and bundle.cases[g.case_id].split == "dev"})
                for cid in case_ids:
                    case = bundle.cases[cid]
                    response = client.post("/api/v1/runs", json={"schema_version": "0.3", "artifact_type": "run_request",
                        "case_id": cid, "scenario": case.scenario, "defense_mode": "D2", "defense_position": "input_retrieval",
                        "execution_kind": "detector_only", "dataset_version": case.source_version,
                        "corpus_version": case.source_version, "requested_by": "week2-data-handoff-fixture"})
                    require(response.status_code == 201, "detector handoff request failed")
                    trace = response.json()["trace"]
                    require(trace["metrics"]["generation_call_count"] == 0 and trace["evaluation"]["attack_success"] == "not_evaluated", "detector-only result invented a final outcome")
                    summaries.append({"run_id": trace["run_id"], "case_id": cid, "kind": "detector_only", "status": trace["status"],
                                      "created_at": trace["created_at"], "dataset_version": case.source_version,
                                      "scenario": case.scenario, "model_id": trace["manifest"]["model_id"],
                                      "evaluator_version": trace["manifest"]["evaluator_version"]})
                for representative in bundle.manifest.representative_cases:
                    case = bundle.cases[representative.case_id]
                    response = client.post("/api/v1/runs", json={"schema_version": "0.3", "artifact_type": "run_request",
                        "case_id": case.case_id, "scenario": case.scenario, "defense_mode": "none",
                        "dataset_version": case.source_version, "corpus_version": case.source_version,
                        "requested_by": "week2-evaluator-handoff-fixture"})
                    require(response.status_code == 201, "evaluator handoff request failed")
                    trace = response.json()["trace"]
                    require(trace["manifest"]["evaluator_version"] == "week2-rules-v0.1@rules-v0.2", "wrong evaluator version")
                    require(trace["evaluation"]["normal_task_success"] != "success", "semantic task was approved without manual review")
                    summaries.append({"run_id": trace["run_id"], "case_id": case.case_id, "kind": "full_pipeline",
                                      "status": trace["status"], "created_at": trace["created_at"],
                                      "dataset_version": case.source_version, "scenario": case.scenario,
                                      "model_id": trace["manifest"]["model_id"], "evaluation": trace["evaluation"]})
                for payload in fixture.requests:
                    # Classification receives precisely the stage and actual text.
                    from backend.app.defenses import D2_SYSTEM
                    if payload["messages"][0]["content"] == D2_SYSTEM:
                        require(set(json.loads(payload["messages"][1]["content"])) == {"stage", "text"}, "gold metadata leaked to D2")
                wire_count += len(fixture.requests)

    pending = gold_plan(data_dir, runs_dir)
    require(not pending["updates"], "single-review gold was silently treated as team-reviewed")
    plan = gold_plan(data_dir, runs_dir, include_single_review=True)
    require(bool(plan["updates"]) and not plan["excluded"], "reviewed target handoff did not cover inspected dev targets")
    # Annotation is post-execution and must not create another model call.
    with FixtureModelServer(data_dir) as fixture, TestClient(create_app(settings_for(data_dir, fixture))) as client:
        for update in plan["updates"]:
            response = client.put(update["path"], json=update["body"])
            require(response.status_code == 200, "target-gold API registration failed")
            require(client.get(f"/api/v1/runs/{update['run_id']}").json() == response.json(), "saved target gold differs from API")
        require(not fixture.requests, "gold registration triggered a model call")
        run_ids = [row["run_id"] for row in summaries if row["kind"] == "detector_only"]
        report = client.post("/api/v1/detector-report", json={"run_ids": run_ids})
        require(report.status_code == 200, "target report failed")
        detector_report = report.json()
        require(sum(g["inspected_target_count"] for g in detector_report["groups"]) == len(plan["updates"]), "report target count mismatch")
    result = {"status": "passed", "execution_scope": "fixture", "real_model_verified": False,
              "team_agreement": "pending", "gold_review_scope": "single_review_explicitly_enabled",
              "holdout_executed": False, "model_call_count": wire_count, "runs": summaries,
              "gold_update_count": len(plan["updates"]), "detector_report": detector_report,
              "source_artifact_sha256": check["artifact_sha256"]}
    for name, obj in (("gold-plan.json", plan), ("verification-report.json", result)):
        (output / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/week2")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("--output", type=Path)
    for name in ("prepare-email", "prepare-bilingual"):
        command = commands.add_parser(name)
        command.add_argument("--output", required=True, type=Path)
    command = commands.add_parser("gold-plan")
    command.add_argument("--runs-dir", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--include-single-review", action="store_true")
    command = commands.add_parser("verify-handoff")
    command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            result = check_package(args.data_dir.resolve())
        elif args.command == "gold-plan":
            result = gold_plan(args.data_dir.resolve(), args.runs_dir.resolve(), args.include_single_review)
        elif args.command == "verify-handoff":
            result = verify_handoff(args.data_dir.resolve(), args.output.resolve())
        else:
            result = {"prepared": str(prepare(args.data_dir.resolve(), args.output.resolve(), "email" if args.command == "prepare-email" else "bilingual"))}
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.command in ("check", "gold-plan") and args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"Week-two data validation failed: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
