"""Export the separate public research overlay contract for issue #10 consumers."""
import json
from pathlib import Path
from typing import Union

from pydantic import TypeAdapter

from backend.app.research_models import ResearchFilters, ResearchReport


def main():
    schema = TypeAdapter(Union[ResearchFilters, ResearchReport]).json_schema()
    schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema",
                   "title": "Explicit public AI research overlay v0.2 (reads archived v0.1 reports)"})
    path = Path(__file__).resolve().parents[1] / "contracts/research-overlay-v0.2.schema.json"
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
