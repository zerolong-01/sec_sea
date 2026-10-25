"""Export the independent multi-model comparison contract."""
import json
from pathlib import Path
from typing import Union

from pydantic import TypeAdapter

from backend.app.experiment_models import ExperimentManifest, ExperimentSpec


def main():
    schema = TypeAdapter(Union[ExperimentSpec, ExperimentManifest]).json_schema()
    schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/zerolong-01/sec_sea/contracts/model-experiment-v0.1.schema.json",
        "title": "Multi-model experiment specification and frozen membership v0.1"})
    path = Path(__file__).resolve().parents[1] / "contracts/model-experiment-v0.1.schema.json"
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
