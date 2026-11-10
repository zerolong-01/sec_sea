"""Export the independent normal-task overlay contract."""
import json
from pathlib import Path
from typing import Union

from pydantic import TypeAdapter

from backend.app.task_evaluation_models import VERSION, TaskEvaluationReport, TaskEvaluationRequest, TaskReviewRequest


def main():
    schema = TypeAdapter(Union[TaskEvaluationReport, TaskEvaluationRequest, TaskReviewRequest]).json_schema()
    schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema",
                   "title": "Normal task automatic evaluation and manual history v0.2"})
    path = Path(__file__).resolve().parents[1] / "contracts" / f"{VERSION}.schema.json"
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
