"""Compile distinct attack datasets for an exploratory audit without model calls.

Only selected case IDs are execution inputs. Other cases retained in a bundle
are validation scaffolding. Canonical files are never changed. An explicit
``include_holdout`` promotes a copy to a new exploratory dataset and records that
the original holdout has been consumed; it does not invent final-evaluation
reviews or a frozen recommendation.
"""
from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

from backend.app.batch import digest, file_hash
from backend.app.evaluation import RuleSet
from backend.app.models import CaseRecord, SourceDocument
from backend.app.storage import atomic_json
from scripts.data_contract import CANARY_PATTERN, ROOT, load_bundle, require
from scripts.week2_data import prepare as prepare_week2
from scripts.week3_prepare import prepare as prepare_week3, write_jsonl

VERSION = "attack-audit-preparation-v0.1"
BUNDLE_FILES = ("cases.v0.1.jsonl", "corpus.v0.1.jsonl", "mvp-manifest.v0.1.json")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _copy_bundle(source: Path, output: Path) -> Path:
    output.mkdir(parents=True)
    for name in BUNDLE_FILES:
        shutil.copyfile(source / name, output / name)
    load_bundle(output)
    return output


def _write_bundle(output: Path, cases: dict, documents: dict, manifest: dict) -> Path:
    output.mkdir(parents=True)
    write_jsonl(output / BUNDLE_FILES[0], cases.values())
    write_jsonl(output / BUNDLE_FILES[1], documents.values())
    atomic_json(output / BUNDLE_FILES[2], manifest)
    load_bundle(output)
    return output


def _rules(output: Path, original: dict, bundle, aliases: dict[str, str] | None = None) -> Path:
    """Keep source-specific rubrics; never join legacy and week2 by bare ID."""
    by_id = {row["case_id"]: row for row in original["rules"]}
    aliases = aliases or {}
    rules = []
    for case_id in bundle.cases:
        parent_id = aliases.get(case_id, case_id)
        rule = dict(by_id.get(parent_id, {"normal_task_mode": "manual"}), case_id=case_id)
        rules.append(rule)
    result = dict(original, rules=rules, dataset_versions=[bundle.manifest.dataset_version])
    RuleSet.model_validate(result)
    atomic_json(output, result)
    return output


def _ai_bundle(output: Path, records: list[dict]) -> tuple[Path, dict]:
    base = load_bundle(ROOT / "data/week2")
    version = "synthetic_attack_audit_ai_v0.1_" + digest(records)[:12]
    cases = {k: dict(c.model_dump(mode="json"), source_version=version) for k, c in base.cases.items()}
    documents = {k: dict(d.model_dump(mode="json"), source_version=version) for k, d in base.documents.items()}
    metadata = {}
    for record in records:
        require(isinstance(record, dict), "AI variant must be an object")
        parent_id = record.get("parent_case_id")
        require(parent_id in base.cases, "AI parent case is unknown")
        parent = base.cases[parent_id]
        require(parent.split == "dev" and parent.label == "attack", "AI parent must be a dev attack")
        case_id = "ai_" + parent_id + "_v01"
        require(case_id not in metadata, "Duplicate AI parent case")
        user_input = record.get("user_input")
        instruction = record.get("document_instruction")
        require(isinstance(user_input, str) and 0 < len(user_input) <= 20000, "AI user input is invalid")
        require(all(isinstance(record.get(k), str) and record[k].strip() for k in ("technique", "rationale")),
                "AI technique and rationale are required")
        derived = dict(cases[parent_id], case_id=case_id)
        if parent.attack_type == "indirect_document":
            require(user_input == parent.user_input, "Indirect AI variants must preserve the normal question")
            require(isinstance(instruction, str) and 0 < len(instruction) <= 20000,
                    "Indirect AI variants require a document instruction")
            doc_ids = []
            for doc_id in parent.source_document_ids:
                source = dict(documents[doc_id])
                source["content"] += "\n\n" + instruction
                new_id = "doc" + digest({k: source[k] for k in ("title", "content")})[:16]
                source.update(document_id=new_id, is_untrusted_content=True)
                documents[new_id] = SourceDocument.model_validate(source).model_dump(mode="json")
                doc_ids.append(new_id)
            derived["source_document_ids"] = doc_ids
            variant_kind = "document_instruction_augmentation"
        else:
            require(instruction is None, "Input AI variants must not change documents")
            require(user_input != parent.user_input, "Input AI variant must change the attacker input")
            derived["user_input"] = user_input
            variant_kind = "input_replacement"
        # Literal canaries may be repeated, but new canaries would change the
        # parent objective. Repetition in attacker text is recorded separately
        # because known-marker copying is not unknown protected-value leakage.
        originals = parent.user_input + "\n" + "\n".join(base.documents[d].content for d in parent.source_document_ids)
        generated = user_input + "\n" + (instruction or "")
        require(set(CANARY_PATTERN.findall(generated)) <= set(CANARY_PATTERN.findall(originals)),
                "AI variant introduces a new target canary")
        cases[case_id] = CaseRecord.model_validate(derived).model_dump(mode="json")
        metadata[case_id] = {"parent_case_id": parent_id, "original_split": parent.split,
            "variant_kind": variant_kind, "technique": record["technique"],
            "generation_rationale": record["rationale"], "review_status": "pending",
            "target_in_generated_payload": sorted(set(CANARY_PATTERN.findall(generated))),
            "generation_record_sha256": digest(record)}
    manifest = dict(base.manifest.model_dump(mode="json"), dataset_version=version, corpus_version=version)
    return _write_bundle(output, cases, documents, manifest), metadata


def _consumed_holdout(output: Path) -> Path:
    base = load_bundle(ROOT / "data/week2")
    version = "synthetic_week2_consumed_holdout_exploratory_v0.1"
    cases = {k: dict(c.model_dump(mode="json"), source_version=version, split="dev") for k, c in base.cases.items()}
    documents = {k: dict(d.model_dump(mode="json"), source_version=version) for k, d in base.documents.items()}
    manifest = dict(base.manifest.model_dump(mode="json"), dataset_version=version, corpus_version=version)
    return _write_bundle(output, cases, documents, manifest)


def prepare(output: Path, ai_records: list[dict], *, include_holdout: bool = False) -> dict:
    output = output.resolve()
    require(not output.exists(), "Preparation output already exists; use another directory")
    require(isinstance(ai_records, list), "AI records must be a list")
    # Week1 has a distinct manifest presentation but byte-identical actual
    # case/document records to the legacy root dataset. Do not execute it twice.
    require(all(file_hash(ROOT / "data" / name) == file_hash(ROOT / "data/week1" / name)
                for name in BUNDLE_FILES[:2]), "Week1 is no longer a byte-identical legacy duplicate")
    source_paths = set()
    for folder in (ROOT / "data", ROOT / "data/week1", ROOT / "data/week2", ROOT / "data/week3"):
        source_paths.update(p for p in folder.iterdir() if p.is_file())
    source_paths.update(ROOT / "configs" / name for name in
                        ("evaluation-starter.json", "evaluation-week2.json", "evaluation-week3-protected.json"))
    original_hashes = {p.relative_to(ROOT).as_posix(): file_hash(p) for p in sorted(source_paths)}
    output.mkdir(parents=True)
    legacy = _copy_bundle(ROOT / "data", output / "legacy")
    week2 = _copy_bundle(ROOT / "data/week2", output / "week2")
    week3_result = prepare_week3(output / "week3-prepared")
    bilingual = prepare_week2(ROOT / "data/week2", output / "bilingual", "bilingual")
    ai, ai_metadata = _ai_bundle(output / "ai", ai_records)
    variants = _read(ROOT / "data/week2/language-variants.v0.1.json")["variants"]
    translated_parents = {r["case_id"]: r["parent_case_id"] for r in variants}
    base = load_bundle(week2)
    sources, audit_cases, provenance, source_rules = [], {}, {}, {}
    starter_rules = _read(ROOT / "configs/evaluation-starter.json")
    week2_rules = _read(ROOT / "configs/evaluation-week2.json")
    week3_rules = _read(output / "week3-prepared/evaluation-rules.json")

    def add(source_id, data_dir, selected, original_rules, aliases=None, metadata=None, consumed=False):
        bundle = load_bundle(data_dir)
        aliases, metadata = aliases or {}, metadata or {}
        require(all(cid in bundle.cases and bundle.cases[cid].split == "dev" for cid in selected),
                "Selected audit case must exist in the exploratory dev snapshot")
        rule_path = _rules(output / (source_id + "-rules.json"), original_rules, bundle, aliases)
        source_rules[source_id] = str(rule_path)
        sources.append({"source_id": source_id, "data_dir": str(data_dir), "split": "dev", "case_ids": list(selected)})
        audit_cases[source_id], provenance[source_id] = {}, {}
        for cid in selected:
            case = bundle.cases[cid].model_dump(mode="json")
            detail = metadata.get(cid, {})
            parent = aliases.get(cid, detail.get("parent_case_id", cid))
            origin_split = "holdout" if consumed else detail.get("original_split", "dev")
            audit_cases[source_id][cid] = dict(case, audit_parent_case_id=parent,
                audit_original_split=origin_split, audit_consumed_holdout=consumed)
            provenance[source_id][cid] = dict(detail, parent_case_id=parent,
                original_split=origin_split, audit_consumed_holdout=consumed,
                case_sha256=digest(case), document_sha256={d: digest(bundle.documents[d].model_dump(mode="json"))
                                                        for d in case["source_document_ids"]})

    add("legacy", legacy, list(load_bundle(legacy).cases), starter_rules)
    add("week2", week2, [k for k, c in base.cases.items() if c.split == "dev"], week2_rules)
    add("translations", bilingual, list(translated_parents), week2_rules, aliases=translated_parents)
    add("week3", output / "week3-prepared/rag", list(week3_result["case_provenance"]), week3_rules,
        metadata={k: dict(v, parent_case_id=v["source_case_id"]) for k, v in week3_result["case_provenance"].items()})
    email = output / "week3-prepared/email"
    add("email", email, list(load_bundle(email).cases), week2_rules)
    add("ai", ai, list(ai_metadata), week2_rules,
        aliases={k: v["parent_case_id"] for k, v in ai_metadata.items()}, metadata=ai_metadata)
    if include_holdout:
        consumed = _consumed_holdout(output / "consumed-holdout")
        add("consumed-holdout", consumed, [k for k, c in base.cases.items() if c.split == "holdout"],
            week2_rules, consumed=True)
    atomic_json(output / "audit-cases.private.json", audit_cases)
    atomic_json(output / "case-provenance.private.json", provenance)
    atomic_json(output / "ai-records.private.json", ai_records)
    counts = {source["source_id"]: len(source["case_ids"]) for source in sources}
    labels = Counter(c["label"] for rows in audit_cases.values() for c in rows.values())
    generated = {p.relative_to(output).as_posix(): file_hash(p) for p in output.rglob("*") if p.is_file()}
    require(all(file_hash(ROOT / relative) == sha for relative, sha in original_hashes.items()),
            "Canonical sources changed during preparation")
    result = {"version": VERSION, "sources": sources, "source_rules": source_rules,
        "inventory": {"selected_cases": sum(counts.values()), "by_source": counts, "by_label": dict(labels),
            "existing_unique_cases": sum(counts.values()) - len(ai_records), "ai_variants": len(ai_records),
            "holdout_selected": 9 if include_holdout else 0, "holdout_preserved": not include_holdout},
        "holdout_policy": {"included": include_holdout, "consumed_for_exploration": include_holdout,
            "unseen_final_evaluation_eligible": not include_holdout,
            "note": "Copied holdout rows are exploratory dev data; canonical splits are unchanged."
                    if include_holdout else "Canonical holdout rows are not selected for execution."},
        "deduplication": [{"excluded": "data/week1", "equivalent_to": "data", "records": 36,
                           "basis": "byte-identical cases and corpus; manifest presentation differs"}],
        "private_audit_cases_path": str(output / "audit-cases.private.json"),
        "private_provenance_path": str(output / "case-provenance.private.json"),
        "source_sha256": original_hashes, "generated_sha256": generated,
        "ai_records_sha256": digest(ai_records), "review_status": "pending",
        "execution_scope": "prepared_only", "model_call_count": 0}
    atomic_json(output / "preparation.json", result)
    return result


def validate(output: Path) -> dict:
    result = _read(output / "preparation.json")
    require(result["version"] == VERSION, "Audit preparation version changed")
    for relative, sha in result["generated_sha256"].items():
        require(file_hash(output / relative) == sha, "Prepared audit artifact hash mismatch")
    for relative, sha in result["source_sha256"].items():
        require(file_hash(ROOT / relative) == sha, "Canonical audit source changed")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ai-records", type=Path, required=True)
    parser.add_argument("--include-holdout", action="store_true")
    args = parser.parse_args(argv)
    result = prepare(args.output, _read(args.ai_records), include_holdout=args.include_holdout)
    print(json.dumps(result["inventory"]))


if __name__ == "__main__":
    main()
