"""Export the execution contract from the API models (does not change legacy schemas)."""
import json
from pathlib import Path
from typing import Union

from pydantic import TypeAdapter

from backend.app.models import (DetectorGoldUpdate, DetectorReport, DetectorReportRequest,
                                EvaluationUpdate, RunRequest, RunResponse, RunTrace)
from backend.app.shared_variables import SchemaVersion


def main():
    schema = TypeAdapter(Union[RunRequest, RunResponse, RunTrace, EvaluationUpdate,
                               DetectorGoldUpdate, DetectorReportRequest, DetectorReport]).json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://github.com/zerolong-01/sec_sea/contracts/execution-v{SchemaVersion.EXECUTION}.schema.json"
    schema["title"] = "Execution, detector target gold and report contract"
    target = Path(__file__).resolve().parents[1] / "contracts" / f"execution-v{SchemaVersion.EXECUTION}.schema.json"
    target.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
