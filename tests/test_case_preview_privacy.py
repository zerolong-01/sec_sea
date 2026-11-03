"""케이스 탐색도 공개 trace와 같은 보호값 경계를 지킨다 (#48, #56 후속)."""
from __future__ import annotations

import base64
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import quote

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "frontend"))

import case_browser as cb


def variants(value):
    encoded = base64.b64encode(value.encode()).decode()
    return [value, encoded, encoded.rstrip("="),
            base64.urlsafe_b64encode(f"문맥: {value} 끝".encode()).decode().rstrip("="),
            "".join(f"%{byte:02x}" for byte in value.encode()),
            quote(value[:4]) + "".join(f"%{byte:02X}" for byte in value[4:].encode()),
            " ".join(value)]


class CasePreviewPrivacyTests(unittest.TestCase):
    def dataset(self, folder):
        canary, protected, credential = "CANARY_PREVIEW_2026", "합성-비밀번호-2026", "sk-preview-fixture-key"
        cases = [json.loads(line) for line in
                 (ROOT / "data/cases.v0.1.jsonl").read_text(encoding="utf-8").splitlines()]
        case = next(c for c in cases if c["case_id"] == "a006")
        case["user_input"] = "요청 " + " | ".join(variants(canary) + variants(protected) + [credential])
        corpus = (ROOT / "data/corpus.v0.1.jsonl").read_text(encoding="utf-8")
        corpus += json.dumps({"content": canary}, ensure_ascii=False) + "\n"
        (folder / "corpus.v0.1.jsonl").write_text(corpus, encoding="utf-8")
        (folder / "cases.v0.1.jsonl").write_text(
            "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n", encoding="utf-8")
        (folder / "mvp-manifest.v0.1.json").write_bytes((ROOT / "data/mvp-manifest.v0.1.json").read_bytes())
        rules = folder / "rules.json"
        rules.write_text(json.dumps({"rules": [{"case_id": "a006", "protected_values": [protected]}]},
                                   ensure_ascii=False), encoding="utf-8")
        return cases, case, rules, canary, protected, credential

    def test_known_targets_are_masked_before_summary_search_and_preview_without_changing_cases(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            cases, case, rules, canary, protected, credential = self.dataset(folder)
            original = copy.deepcopy(cases)
            before = {p.name: p.read_bytes() for p in folder.iterdir()}
            redactor = cb.load_redactor(folder, cases, rules_path=rules, credentials=[credential])
            masked = cb.mask(case["user_input"], redactor=redactor)
            self.assertIn("요청", masked)
            self.assertIn("[MASKED_CANARY]", masked)
            self.assertIn("[MASKED_PROTECTED]", masked)
            self.assertIn("[MASKED_CREDENTIAL]", masked)
            for value in variants(canary) + variants(protected) + [credential]:
                with self.subTest(value_type="encoded_target"):
                    self.assertNotIn(value, masked)
                    self.assertEqual(cb.filter_cases(cases, value, redactor=redactor), [])
            self.assertNotIn(canary, cb.row(case, redactor=redactor)["입력 요약"])
            self.assertNotIn("공격 목표", dict(cb.preview(case, redactor=redactor)))
            self.assertEqual(cb.filter_cases(cases, "a006", redactor=redactor), [case])
            self.assertEqual(cases, original)
            self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir()}, before)

    def test_rules_and_targets_are_reloaded_instead_of_cached_across_datasets(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            cases, _, rules, _, protected, _ = self.dataset(folder)
            first = cb.load_redactor(folder, cases, rules_path=rules)
            self.assertNotEqual(first(protected), protected)
            rules.write_text('{"rules": []}', encoding="utf-8")
            second = cb.load_redactor(folder, cases, rules_path=rules)
            self.assertEqual(second(protected), protected)

    def test_screen_masks_known_encodings_and_credentials_but_keeps_execution_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            cases, case, rules, canary, protected, credential = self.dataset(folder)
            env = {"DATA_DIR": str(folder), "MVP_MANIFEST": str(folder / "mvp-manifest.v0.1.json"),
                   "EVALUATION_RULES_FILE": str(rules), "MODEL_API_KEY": credential}
            with patch.dict(os.environ, env), patch("requests.post") as post:
                app = AppTest.from_file(str(ROOT / "frontend/app.py"), default_timeout=30)
                app.session_state["pending_case"] = case
                app.run()
                app.text_input(key="case_query").set_value("a006").run()
                self.assertFalse(app.exception, app.exception)
                # The raw dictionary is kept for the verifier/execution contract; only display text is redacted.
                self.assertEqual(app.radio(key="case_selector").value, case)
                shown = "\n".join(str(e.value) for e in
                                   [*app.code, *app.text, *app.info, *app.caption, *app.markdown, *app.dataframe])
                self.assertIn("[MASKED_CANARY]", shown)
                self.assertIn("[MASKED_PROTECTED]", shown)
                self.assertIn("[MASKED_CREDENTIAL]", shown)
                for value in variants(canary) + variants(protected) + [credential]:
                    self.assertNotIn(value, shown)
                post.assert_not_called()

    def test_unreadable_or_invalid_redaction_material_does_not_fall_back_to_raw_preview(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            _, case, rules, canary, protected, _ = self.dataset(folder)
            for broken in (None, '{"rules": [{"protected_values": "wrong-type"}]}',
                           '{"rules": [null]}', "{"):
                if broken is None:
                    rules.unlink()
                else:
                    rules.write_text(broken, encoding="utf-8")
                with self.subTest(broken=broken), patch.dict(os.environ, {
                        "DATA_DIR": str(folder), "MVP_MANIFEST": str(folder / "mvp-manifest.v0.1.json"),
                        "EVALUATION_RULES_FILE": str(rules)}), patch("requests.post") as post:
                    app = AppTest.from_file(str(ROOT / "frontend/app.py"), default_timeout=30).run()
                    self.assertFalse(app.exception, app.exception)
                    self.assertIn("마스킹 자료를 읽을 수 없습니다", app.error[0].value)
                    self.assertEqual(len(app.code), 0)
                    self.assertEqual(len(app.dataframe), 0)
                    for key in ("run_case", "run_compare", "run_positions"):
                        self.assertTrue(app.button(key=key).disabled)
                    post.assert_not_called()

    def test_broken_preview_rules_keep_saved_public_trace_lookup_available(self):
        trace = json.loads((ROOT / "docs/examples/week2/a006-D2.json").read_text(encoding="utf-8"))["response"]["trace"]
        with tempfile.TemporaryDirectory() as temporary:
            env = {"DATA_DIR": str(ROOT / "data"), "MVP_MANIFEST": str(ROOT / "data/mvp-manifest.v0.1.json"),
                   "EVALUATION_RULES_FILE": str(Path(temporary) / "missing.json")}
            response = SimpleNamespace(status_code=200, json=lambda: trace)
            with patch.dict(os.environ, env), patch("requests.get", return_value=response) as get, \
                    patch("requests.post") as post:
                app = AppTest.from_file(str(ROOT / "frontend/app.py"), default_timeout=30).run()
                app.text_input(key="stored_run_id").set_value(trace["run_id"])
                app.button(key="load_run").click().run()
                self.assertFalse(app.exception, app.exception)
                self.assertIn(trace["run_id"], [e.value for e in app.text])
                self.assertIn(trace["input"]["user_input"], [e.value for e in app.code])
                self.assertNotIn("case_selector", [e.key for e in app.radio])
                get.assert_called_once()
                post.assert_not_called()

    def test_missing_or_malformed_corpus_refuses_to_build_a_display_redactor(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            cases, _, rules, _, _, _ = self.dataset(folder)
            corpus = folder / "corpus.v0.1.jsonl"
            corpus.unlink()
            with self.assertRaises(OSError):
                cb.load_redactor(folder, cases, rules_path=rules)
            corpus.write_text('{"content": 123}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                cb.load_redactor(folder, cases, rules_path=rules)


if __name__ == "__main__":
    unittest.main()
