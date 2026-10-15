"""Generate the separate batch contract without rewriting execution schemas."""
import json
from pathlib import Path
from typing import Union

from pydantic import TypeAdapter

from backend.app.batch_models import (BatchArtifact, BatchFilters, BatchReport, BatchReview,
                                     BatchSpec, BatchSummary, RecommendationPolicy)
from backend.app.shared_variables import BATCH_VERSION


def main():
    schema = TypeAdapter(Union[BatchSpec, BatchArtifact, BatchSummary, BatchReport,
                               BatchFilters, BatchReview, RecommendationPolicy]).json_schema()
    schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema",
                   "$id": f"https://github.com/zerolong-01/sec_sea/contracts/batch-v{BATCH_VERSION}.schema.json",
                   "title": "Batch plan, progress, review, report and recommendation policy v0.1"})
    target = Path(__file__).resolve().parents[1] / "contracts" / f"batch-v{BATCH_VERSION}.schema.json"
    target.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
