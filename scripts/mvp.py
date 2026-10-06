"""Repository entry point: setup, check, serve, and HTTP/UI verification."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import venv
from contextlib import contextmanager, nullcontext
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def setup() -> int:
    if not VENV_PYTHON.exists():
        venv.EnvBuilder(with_pip=True).create(ROOT / ".venv")
    subprocess.run([str(VENV_PYTHON), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "-r", str(ROOT / "requirements.txt")], cwd=ROOT, check=True)
    print("Environment ready. Run: python -m scripts.mvp serve")
    return 0


def require_dependencies() -> None:
    missing = [name for name in ("pydantic", "fastapi", "uvicorn", "jsonschema", "streamlit", "requests") if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError(f"Missing dependencies: {', '.join(missing)}. Run: python -m scripts.mvp setup")


def request_json(url: str, payload: dict | None = None, timeout: float = 5) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8") if payload is not None else None, headers={"Content-Type": "application/json"})
    with HTTP.open(request, timeout=timeout) as response:
        return json.load(response)


def available_port(requested: int) -> int:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", requested))
        except OSError as exc:
            raise RuntimeError(f"Port {requested} is in use; choose another port.") from exc
        return sock.getsockname()[1]


class ManagedProcess:
    def __init__(self, name: str, command: list[str], log_dir: Path, env: dict[str, str]):
        self.name = name
        self.log_path = log_dir / f"{name}.log"
        self.log = self.log_path.open("w", encoding="utf-8")
        try:
            self.process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=self.log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, start_new_session=os.name != "nt")
        except BaseException:
            self.log.close()
            raise

    def check_running(self) -> None:
        if self.process.poll() is not None:
            raise RuntimeError(f"{self.name} exited ({self.process.returncode}); see {self.log_path}")

    def wait_ready(self, url: str, timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.check_running()
            try:
                with HTTP.open(url, timeout=1) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.2)
        raise RuntimeError(f"{self.name} did not become ready; see {self.log_path}")

    def close(self) -> None:
        try:
            if self.process.poll() is None:
                if os.name == "nt":
                    # Windows venv's python.exe is a launcher with a real Python
                    # child. Terminating only the launcher leaves servers alive.
                    subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5, check=True)
                else:
                    os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        self.process.kill()
                    else:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=5)
        finally:
            self.log.close()


@contextmanager
def services(bundle, runs_dir: Path, api_port: int, ui_port: int, demo: bool):
    api_port, ui_port = available_port(api_port), available_port(ui_port)
    if api_port == ui_port:
        raise RuntimeError("API and UI ports must be different.")
    runs_dir.mkdir(parents=True, exist_ok=True)
    log_dir = runs_dir / f"services-{uuid.uuid4().hex[:8]}"
    log_dir.mkdir()
    backend_url = f"http://127.0.0.1:{api_port}"
    frontend_url = f"http://127.0.0.1:{ui_port}"
    env = dict(os.environ, DATA_DIR=str(bundle.data_dir), MVP_MANIFEST=str(bundle.manifest_path), RUNS_DIR=str(runs_dir), BACKEND_URL=backend_url, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    if demo:
        env.update(MODEL_PROVIDER="demo", MODEL_ID="demo-rag-v0.1")
        env.pop("MODEL_BASE_URL", None)
        env.pop("MODEL_API_KEY", None)
        env.pop("EVALUATION_RULES_FILE", None)
    children = []
    try:
        backend = ManagedProcess("backend", [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT / "backend"), "--host", "127.0.0.1", "--port", str(api_port)], log_dir, env)
        children.append(backend)
        backend.wait_ready(f"{backend_url}/health")
        frontend = ManagedProcess("frontend", [sys.executable, "-m", "streamlit", "run", str(ROOT / "frontend/app.py"), "--server.address=127.0.0.1", f"--server.port={ui_port}", "--server.headless=true", "--browser.gatherUsageStats=false"], log_dir, env)
        children.append(frontend)
        frontend.wait_ready(f"{frontend_url}/_stcore/health")
        yield backend_url, frontend_url, env, children
    finally:
        shutdown_error = None
        for child in reversed(children):
            try:
                child.close()
            except BaseException as exc:
                shutdown_error = shutdown_error or exc
        if shutdown_error is not None:
            raise shutdown_error


def validate_api_trace(bundle, item, trace: dict, request: dict) -> None:
    from jsonschema import Draft202012Validator
    from backend.app.models import RunTrace
    from scripts.data_contract import CANARY_PATTERN, require

    schema = json.loads((ROOT / "contracts/execution-v0.3.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(trace)
    record = RunTrace.model_validate(trace)
    require(record.status == "completed" and record.error is None, f"{item.case_id}: execution failed")
    from backend.app.models import RunRequest
    require(trace["request"] == RunRequest.model_validate(request).model_dump(mode="json"), f"{item.case_id}: request/version mismatch")
    require(record.output.outcome == "generated" and bool(record.output.display_text), f"{item.case_id}: missing output")
    require(record.metrics.latency_ms is not None and record.metrics.input_tokens is not None and record.metrics.output_tokens is not None, f"{item.case_id}: missing metrics")
    require(bool(record.manifest.model_id) and bool(record.manifest.system_prompt_version) and bool(record.manifest.retrieval_config_version), f"{item.case_id}: incomplete manifest")
    require(not record.defense_events, f"{item.case_id}: unexpected defense events")
    require([(r.document_id, r.rank) for r in record.retrieval] == [(r.document_id, r.rank) for r in item.expected_retrieval], f"{item.case_id}: retrieval mismatch")
    require(all(r.included_in_prompt for r in record.retrieval), f"{item.case_id}: retrieved document not in prompt")
    require([component.component_type for component in record.prompt_assembly] == ["system", "user"] + ["retrieved_document"] * len(record.retrieval), f"{item.case_id}: incomplete prompt assembly")
    require(not CANARY_PATTERN.search(json.dumps(trace)), f"{item.case_id}: unmasked canary in public trace")
    require(set(trace["input"]) == {"user_input", "external_document_ids"}, f"{item.case_id}: evaluation metadata leaked into input")
    require(trace["input"]["user_input"] == bundle.cases[item.case_id].user_input, f"{item.case_id}: input mismatch")
    require(record.evaluation.attack_success == "not_evaluated" and record.evaluation.normal_task_success == "not_evaluated", f"{item.case_id}: smoke verification must not invent evaluation results")


def verify_http(bundle, backend_url: str, runs_dir: Path) -> list[dict]:
    from scripts.data_contract import CANARY_PATTERN, require

    require(request_json(f"{backend_url}/health")["model_provider"] == "demo", "verification must use demo provider")
    results = []
    first_request = first_trace = None
    for item in bundle.manifest.representative_cases:
        case = bundle.cases[item.case_id]
        request = {"schema_version": bundle.manifest.schema_version, "artifact_type": "run_request", "case_id": item.case_id, "scenario": case.scenario, "defense_mode": "none", "dataset_version": bundle.manifest.dataset_version, "corpus_version": bundle.manifest.corpus_version, "requested_by": "mvp-integration"}
        response = request_json(f"{backend_url}/api/v1/runs", request, timeout=30)
        trace = response["trace"]
        require(response["run_id"] == trace["run_id"] and response["status"] == trace["status"], f"{item.case_id}: response mismatch")
        validate_api_trace(bundle, item, trace, request)
        stored = request_json(f"{backend_url}/api/v1/runs/{trace['run_id']}")
        require(stored == trace, f"{item.case_id}: saved trace differs")
        require(json.loads((runs_dir / f"{trace['run_id']}.trace.json").read_text(encoding="utf-8")) == trace, f"{item.case_id}: trace persistence failed")
        raw = json.loads((runs_dir / f"{trace['run_id']}.raw.json").read_text(encoding="utf-8"))
        if item.label == "attack":
            target_values = {value for doc_id in case.source_document_ids for value in CANARY_PATTERN.findall(bundle.documents[doc_id].content)}
            require(all(value in raw["provider_output"] for value in target_values), f"{item.case_id}: demo fixture did not exercise output masking")
            require(trace["output"]["is_masked"], f"{item.case_id}: masking flag missing")
            require(any(component["is_masked"] for component in trace["prompt_assembly"]), f"{item.case_id}: prompt masking flag missing")
        try:
            HTTP.open(f"{backend_url}/api/v1/runs/{trace['run_id']}.raw.json", timeout=5)
        except urllib.error.HTTPError as exc:
            require(exc.code == 404, "raw artifact route must return 404")
        else:
            raise RuntimeError("Raw log was exposed through the trace API.")
        results.append({"case_id": item.case_id, "label": item.label, "run_id": trace["run_id"], "status": trace["status"], "retrieval": trace["retrieval"], "evaluation": trace["evaluation"]})
        if first_request is None:
            first_request, first_trace = request, trace
    repeated = request_json(f"{backend_url}/api/v1/runs", first_request, timeout=30)["trace"]
    validate_api_trace(bundle, bundle.manifest.representative_cases[0], repeated, first_request)
    require(repeated["run_id"] != first_trace["run_id"] and repeated["manifest"] == first_trace["manifest"] and repeated["retrieval"] == first_trace["retrieval"], "rerun did not preserve comparison conditions")
    return results


def verify_ui(bundle, env: dict[str, str]) -> None:
    from streamlit.testing.v1 import AppTest
    from scripts.data_contract import CANARY_PATTERN, require

    with patch.dict(os.environ, env):
        app = AppTest.from_file(str(ROOT / "frontend/app.py"), default_timeout=30).run()
        require(not app.exception, "Streamlit initial render failed")
        require(app.radio(key="case_selector").value["case_id"] == bundle.manifest.representative_cases[0].case_id, "UI did not select the first representative")
        for item in bundle.manifest.representative_cases:
            app.radio(key="case_selector").set_value(bundle.cases[item.case_id].model_dump()).run()
            app.button(key="run_case").click().run()
            require(not app.exception and not app.error, f"{item.case_id}: Streamlit execution failed")
            trace = app.session_state["result"]["trace"]
            require(trace["request"]["case_id"] == item.case_id and trace["request"]["corpus_version"] == bundle.manifest.corpus_version, f"{item.case_id}: UI request/version mismatch")
            displayed = "\n".join(element.value for element in app.code)
            require(bool(displayed) and not CANARY_PATTERN.search(displayed), f"{item.case_id}: UI trace missing or unmasked")
            if item.label == "attack":
                require("[MASKED_CANARY]" in displayed, f"{item.case_id}: UI did not render the masked trace")


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Run and verify the integrated RAG MVP.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="Create .venv and install all dependencies.")
    for name in ("check", "serve", "verify", "verify-week2"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir", type=Path, default=Path(os.environ.get("DATA_DIR", ROOT / "data")))
        command.add_argument("--manifest", type=Path, default=Path(os.environ["MVP_MANIFEST"]) if os.environ.get("MVP_MANIFEST") else None)
        if name != "check":
            command.add_argument("--runs-dir", type=Path, default=None)
            command.add_argument("--api-port", type=int, default=8000 if name == "serve" else 0)
            command.add_argument("--ui-port", type=int, default=8501 if name == "serve" else 0)
        if name == "serve":
            command.add_argument("--fixture-model", action="store_true", help="Local HTTP fixtures for all four defense modes; no actual LLM.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command != "setup" and VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
        child = subprocess.Popen([str(VENV_PYTHON), "-m", "scripts.mvp", *(argv if argv is not None else sys.argv[1:])], cwd=ROOT)
        try:
            return child.wait()
        except KeyboardInterrupt:
            # The foreground child receives the console interrupt too.
            try:
                return child.wait(timeout=12)
            except subprocess.TimeoutExpired:
                child.terminate()
                return child.wait(timeout=5)
    try:
        if args.command == "setup":
            return setup()
        require_dependencies()
        from scripts.data_contract import load_bundle
        bundle = load_bundle(args.data_dir, args.manifest)
        print(f"Data validated: {len(bundle.cases)} cases, {len(bundle.documents)} documents; {bundle.manifest.dataset_version}", flush=True)
        if args.command == "check":
            return 0
        default_runs = ROOT / "runs" if args.command == "serve" else ROOT / "runs" / f"verification-{uuid.uuid4().hex[:8]}"
        runs_dir = (args.runs_dir or Path(os.environ.get("RUNS_DIR", default_runs))).resolve()
        report = None
        from scripts.verify_week2 import fixture_environment, verify as verify_week2
        fixture_context = (fixture_environment(bundle.data_dir)
                           if args.command == "verify-week2" or getattr(args, "fixture_model", False) else nullcontext(None))
        with fixture_context as fixture:
            with services(bundle, runs_dir, args.api_port, args.ui_port, demo=args.command == "verify") as (backend_url, frontend_url, env, children):
                if args.command == "verify":
                    results = verify_http(bundle, backend_url, runs_dir)
                    verify_ui(bundle, env)
                    report = {"status": "passed", "provider": "demo", "dataset_version": bundle.manifest.dataset_version, "corpus_version": bundle.manifest.corpus_version, "ui_verified": True, "rerun_verified": True, "evaluation_scope": "integration_only", "cases": results}
                elif args.command == "verify-week2":
                    report = verify_week2(bundle, backend_url, env, runs_dir, fixture)
                else:
                    print(f"API: {backend_url}/docs\nUI:  {frontend_url}\nStop: Ctrl+C (all services will stop).", flush=True)
                    if fixture:
                        print("Model scope: fixture (predetermined responses, not actual model results).", flush=True)
                    while True:
                        for child in children:
                            child.check_running()
                        time.sleep(0.5)
        # Publish success only after all owned server processes have stopped.
        (runs_dir / "verification-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"HTTP + UI verification passed. Report: {runs_dir / 'verification-report.json'}", flush=True)
        return 0
    except KeyboardInterrupt:
        print("\nMVP services stopped.")
        return 0
    except Exception as exc:
        print(f"MVP pipeline failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
