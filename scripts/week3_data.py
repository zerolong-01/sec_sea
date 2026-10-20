"""Week3 draft-data validation. No model API calls."""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "week3"
VALUE = "CANARY_PRIVATE_6F83B2"

def load(name):
    path = DATA / name
    text = path.read_text(encoding="utf-8-sig")
    assert "\ufffd" not in text, f"{name}: broken characters"
    return [json.loads(line) for line in text.splitlines() if line.strip()]

def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print("PASS:", name)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["check"])
    parser.parse_args()

    groups = {
        "a001": load("ablation-a001.v0.1.jsonl"),
        "a006": load("ablation-a006.v0.1.jsonl"),
        "a021": load("ablation-a021.v0.1.jsonl"),
    }
    expected = {
        "a001": (4, "F001", "user_input"),
        "a006": (3, "F002", "content"),
        "a021": (4, "F006", "user_input"),
    }
    all_rows = [r for rows in groups.values() for r in rows]
    original_ids = {
        json.loads(line)["case_id"]
        for line in (ROOT / "data/week2/cases.v0.1.jsonl").read_text(
            encoding="utf-8-sig"
        ).splitlines() if line.strip()
    }

    basic = [
        ("three ablation files", len(groups) == 3),
        ("11 total conditions", len(all_rows) == 11),
        ("unique case/variant pairs",
         len({(r["case_id"], r["variant_id"]) for r in all_rows}) == 11),
        ("valid case IDs",
         all(re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", r["case_id"]) for r in all_rows)),
        ("all original cases exist in Week2",
         all(k in original_ids for k in groups)),
        ("all rows contain removal metadata",
         all(isinstance(r.get("removed_components"), list) for r in all_rows)),
        ("all rows contain family and variant metadata",
         all(r.get("family_id") and r.get("variant_type") and
             "parent_id" in r for r in all_rows)),
    ]

    for name, ok in basic:
        check(name, ok)
    print("BASIC: 7/7 PASS")

    total = 0
    for case_id, rows in groups.items():
        count, family, payload_key = expected[case_id]
        by_variant = {r["variant_id"]: r for r in rows}
        original = by_variant.get("original")
        ablations = [r for r in rows if r["variant_type"] == "ablation"]
        controls = [r for r in rows if r["variant_type"] == "control"]

        tests = [
            ("condition count", len(rows) == count),
            ("unique variants", len(by_variant) == count),
            ("exactly one original",
             sum(r["variant_type"] == "original" for r in rows) == 1),
            ("family mapping", all(r["family_id"] == family for r in rows)),
            ("ablation parent mapping",
             bool(ablations) and all(r["parent_id"] == case_id for r in ablations)),
            ("removed components",
             all(r["removed_components"] for r in ablations) and
             all(not r["removed_components"] for r in controls)),
            ("payload changes",
             original is not None and all(
                 r.get(payload_key) and r[payload_key] != original[payload_key]
                 for r in ablations
             )),
        ]
        for name, ok in tests:
            check(f"{case_id}: {name}", ok)
            total += 1

    print(f"ABLATION: {total}/21 PASS")

    inputs = load("protected-value-inputs.v0.1.jsonl")
    gold = load("protected-value-gold.v0.1.jsonl")
    inp = {r["condition"]: r for r in inputs}
    grd = {r["condition"]: r for r in gold}
    conditions = {"C00", "C01", "A10", "A11"}
    rules = json.loads(
        (ROOT / "configs/evaluation-week3-protected.json").read_text(
            encoding="utf-8-sig"
        )
    )
    rule_by_id = {r["case_id"]: r for r in rules["rules"]}
    expected_ids = {
        "C00": "w3pv_c00", "C01": "w3pv_c01",
        "A10": "w3pv_a10", "A11": "w3pv_a11",
    }

    factorial = [
        ("four input conditions", len(inputs) == 4 and set(inp) == conditions),
        ("four gold conditions", len(gold) == 4 and set(grd) == conditions),
        ("unique condition case IDs",
         all(inp[c]["case_id"] == expected_ids[c] for c in conditions) and
         len({inp[c]["case_id"] for c in conditions}) == 4),
        ("input/gold IDs and run keys match",
         all(inp[c]["case_id"] == grd[c]["case_id"] and
             inp[c]["run_key"] == grd[c]["run_key"] for c in conditions)),
        ("fixed question/title/document",
         len({inp[c]["user_input"] for c in conditions}) == 1 and
         len({inp[c]["document_title"] for c in conditions}) == 1 and
         len({inp[c]["document_id"] for c in conditions}) == 1),
        ("protected values only in C01/A11",
         all((VALUE in inp[c]["document_content"]) ==
             (c in {"C01", "A11"}) for c in conditions)),
        ("gold target flags and values",
         all(grd[c]["target_present"] == (c in {"C01", "A11"}) and
             grd[c]["expected_protected_value"] ==
             (VALUE if c in {"C01", "A11"} else None) for c in conditions)),
        ("attack flags match payloads",
         all(grd[c]["attack_present"] == (c in {"A10", "A11"}) and
             ("[문서 내부 지시]" in inp[c]["document_content"]) ==
             (c in {"A10", "A11"}) for c in conditions)),
        ("evaluation rules linked",
         all(inp[c]["case_id"] in rule_by_id for c in conditions) and
         rule_by_id["w3pv_a11"].get("canary") == VALUE and
         VALUE in rule_by_id["w3pv_c01"].get("protected_values", []) and
         not rule_by_id["w3pv_a10"].get("canary")),
    ]

    for name, ok in factorial:
        check(name, ok)
    print("FACTORIAL: 9/9 PASS")
    print("WEEK3 VALIDATION: PASS (draft data only)")

if __name__ == "__main__":
    main()
