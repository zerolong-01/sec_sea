"""Pinned published human gold, deterministic disjoint splits and calibration statistics."""
from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from .storage import file_sha256
from .task_evaluation import digest

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "data/judge-reference/llmbar-v1"
POLICY_PATH = ROOT / "configs/judge-calibration-policy.v0.1.json"


def load_reference(folder=REFERENCE, policy_path=POLICY_PATH):
    manifest = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if manifest["source_commit"] != policy["reference_commit"] or manifest["label_provenance"] != "published_author_curated_human_gold":
        raise ValueError("Unexpected human reference provenance")
    pairs, files = [], {}
    for source in manifest["sources"]:
        path = folder / source["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError("Invalid reference path")
        payload = path.read_bytes()
        upstream = payload[:-1] if payload.endswith(b"\n") else payload
        blob = hashlib.sha1(b"blob " + str(len(upstream)).encode() + b"\0" + upstream).hexdigest()
        if blob != source["git_blob_sha1"]:
            raise ValueError("Published reference bytes changed")
        records = json.loads(upstream)
        if len(records) != source["count"]:
            raise ValueError("Published reference membership changed")
        files[source["path"]] = file_sha256(path)
        for index, row in enumerate(records):
            if (set(row) != {"input", "output_1", "output_2", "label"} or type(row["label"]) is not int or
                    row["label"] not in (1, 2) or any(not isinstance(row[key], str) or not row[key].strip()
                    for key in ("input", "output_1", "output_2"))):
                raise ValueError("Invalid published gold record")
            family = digest(row["input"])
            pairs.append({"pair_id": f"llmbar-{source['subset'].lower()}-{index:04d}", "subset": source["subset"],
                "source_index": index, "family_id": family, "source_row_sha256": digest(row), **row})
    if len(pairs) != manifest["total_pairs"] or len({p["pair_id"] for p in pairs}) != len(pairs):
        raise ValueError("Reference identity mismatch")
    for name in ("provenance.json", "LICENSE"):
        files[name] = file_sha256(folder / name)
    return {"manifest": manifest, "policy": policy, "pairs": pairs, "files": files,
            "reference_sha256": digest({"files": files, "policy": policy})}


def select_pairs(reference, split="validation"):
    policy = reference["policy"]
    assignments, used = {"development": [], "validation": []}, set()
    # Assign whole instruction families once, before scoring any answer.
    for subset in sorted({p["subset"] for p in reference["pairs"]}):
        ordered = sorted((p for p in reference["pairs"] if p["subset"] == subset),
            key=lambda p: digest([policy["selection_seed"], p["pair_id"], p["source_row_sha256"]]))
        for target in ("development", "validation"):
            count = policy[target+"_pairs_per_subset"]
            available = [p for p in ordered if p["family_id"] not in used]
            chosen = []
            for pair in available:
                if pair["family_id"] not in used:
                    chosen.append(pair)
                    used.add(pair["family_id"])
                if len(chosen) == count:
                    break
            if len(chosen) != count:
                raise ValueError("Insufficient distinct instruction families")
            assignments[target].extend(chosen)
    if split not in assignments:
        raise ValueError("Unknown calibration split")
    return sorted(assignments[split], key=lambda p: digest([policy["selection_seed"], split, p["pair_id"]]))


def units_for(pairs):
    # Human gold is retained only for scoring, never placed in judge evidence.
    return [{"unit_id": pair["pair_id"]+f"-output-{side}", "pair_id": pair["pair_id"], "subset": pair["subset"],
             "family_id": pair["family_id"], "instruction": pair["input"], "answer": pair[f"output_{side}"],
             "expected": "success" if side == pair["label"] else "failure",
             "source_row_sha256": pair["source_row_sha256"], "source_label": pair["label"], "side": side}
            for pair in pairs for side in (1, 2)]


def summarize(reference, units, predictions):
    rows = [{"unit_id": u["unit_id"], "pair_id": u["pair_id"], "family_id": u["family_id"], "subset": u["subset"],
        "expected": u["expected"], "predicted": predictions.get(u["unit_id"], {}).get("verdict", "not_evaluated"),
        "error_code": predictions.get(u["unit_id"], {}).get("error_code")} for u in units]
    def group(selected):
        total = len(selected)
        correct = sum(r["expected"] == r["predicted"] for r in selected)
        negatives = [r for r in selected if r["expected"] == "failure"]
        false_success = sum(r["predicted"] == "success" for r in negatives)
        decisive = [r for r in selected if r["predicted"] in ("success", "failure")]
        cells = Counter((r["expected"], r["predicted"]) for r in selected)
        return {"count": total, "correct": correct, "accuracy": correct/total if total else None,
            "decisive_count": len(decisive), "decisive_accuracy": sum(r["expected"] == r["predicted"] for r in decisive)/len(decisive) if decisive else None,
            "false_success_count": false_success, "failure_gold_count": len(negatives),
            "false_success_rate": false_success/len(negatives) if negatives else None,
            "review_return_rate": sum(r["predicted"] == "review_needed" for r in selected)/total if total else None,
            "not_evaluated_count": sum(r["predicted"] == "not_evaluated" for r in selected),
            "confusion_matrix": {gold: {v: cells[gold, v] for v in ("success", "failure", "review_needed", "not_evaluated")}
                                 for gold in ("success", "failure")}}
    overall = group(rows)
    families = sorted({r["family_id"] for r in rows})
    scores = [[int(r["expected"] == r["predicted"]) for r in rows if r["family_id"] == family] for family in families]
    rng = random.Random(reference["policy"]["selection_seed"])
    boot = []
    if scores:
        for _ in range(reference["policy"]["bootstrap_samples"]):
            sampled = [score for _ in scores for score in rng.choice(scores)]
            boot.append(sum(sampled)/len(sampled))
        boot.sort()
    overall["accuracy_ci95"] = [boot[int(.025*len(boot))], boot[min(len(boot)-1, int(.975*len(boot)))]] if boot else None
    overall["ci_method"] = "exact_instruction_group_bootstrap"
    overall["distinct_instruction_groups"] = len(families)
    pairs = {r["pair_id"] for r in rows}
    overall["strict_pair_accuracy"] = sum(all(r["expected"] == r["predicted"] for r in rows if r["pair_id"] == p) for p in pairs)/len(pairs) if pairs else None
    gates = reference["policy"]["gates"]
    failures = []
    if len(pairs) < gates["minimum_validation_pairs"]:
        failures.append("insufficient_validation_pairs")
    if len(predictions) != len(units) or overall["not_evaluated_count"]:
        failures.append("missing_or_failed_predictions")
    if overall["accuracy"] is None or overall["accuracy"] < gates["minimum_pointwise_accuracy"]:
        failures.append("accuracy_below_adopted_target")
    if overall["false_success_rate"] is None or overall["false_success_rate"] > gates["maximum_false_success_rate"]:
        failures.append("false_success_rate_above_project_limit")
    return {"overall": overall, "by_subset": {s: group([r for r in rows if r["subset"] == s]) for s in sorted({r["subset"] for r in rows})},
        "rows": rows, "external_reference_gate": {"passed": not failures, "reasons": failures, "criteria": gates},
        "label_provenance": "published_author_curated_human_gold_with_documented_pointwise_adapter",
        "new_project_human_review_performed": False, "project_domain_human_validation": "pending",
        "protocol_limit": "Pointwise success/failure adapter and strict pair accuracy differ from the original forced-choice study; no security/Korean/domain certification."}
