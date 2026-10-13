"""Keep known subtotals separate from an incomplete total cost."""
from __future__ import annotations

from pathlib import Path

from pydantic import Field

from .models import Metrics, ModelCall, StageMetric, StrictModel
from .shared_variables import CallPurpose, METRIC_KEYS, UsageSource


class ModelPrice(StrictModel):
    model_id: str = Field(min_length=1)
    input_usd_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    output_usd_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    source_url: str | None = None
    effective_date: str | None = None
    verified: bool = False


class PriceBook(StrictModel):
    version: str = Field(min_length=1)
    currency: str = "USD"
    models: list[ModelPrice]


class Accounting:
    def __init__(self, path: Path | None = None):
        self.book = PriceBook.model_validate_json(path.read_text(encoding="utf-8")) if path else None
        if self.book and (self.book.currency != "USD" or len({p.model_id for p in self.book.models}) != len(self.book.models)):
            raise ValueError("Price book must use USD and unique model IDs")

    def price(self, call: ModelCall) -> None:
        if call.cost_reason == "offline_demo_no_external_charge":
            return
        price = next((p for p in self.book.models if p.model_id == call.model_id), None) if self.book else None
        if price:
            call.pricing_snapshot = {"version": self.book.version, **price.model_dump(mode="json")}
        if not price or not price.verified or not price.source_url or not price.effective_date:
            call.cost_reason = "verified_price_not_configured"
        elif call.input_tokens is None or call.output_tokens is None:
            call.cost_reason = "provider_usage_unknown"
        elif price.input_usd_per_million is None or price.output_usd_per_million is None:
            call.cost_reason = "price_rate_unknown"
        else:
            call.estimated_cost_usd = (call.input_tokens*price.input_usd_per_million + call.output_tokens*price.output_usd_per_million)/1_000_000
            call.cost_reason = "usage_times_versioned_rates"

    def metrics(self, calls: list[ModelCall], stages: list[StageMetric], latency: int,
                generation_skipped_reason: str | None = None) -> Metrics:
        unknown = sum(call.estimated_cost_usd is None for call in calls)
        known = sum(call.estimated_cost_usd or 0 for call in calls)
        def tokens(attribute):
            values = [getattr(call, attribute) for call in calls]
            return None if any(value is None for value in values) else sum(values)
        source = (UsageSource.NOT_CALLED if not calls else UsageSource.UNKNOWN
                  if any(c.usage_source == UsageSource.UNKNOWN for c in calls) else UsageSource.ESTIMATED
                  if any(c.usage_source == UsageSource.ESTIMATED for c in calls) else UsageSource.OBSERVED)
        return Metrics(**{METRIC_KEYS["LATENCY_MS"]: latency, METRIC_KEYS["INPUT_TOKENS"]: tokens("input_tokens"),
                          METRIC_KEYS["OUTPUT_TOKENS"]: tokens("output_tokens"),
                          METRIC_KEYS["ESTIMATED_COST_USD"]: None if unknown else known},
                       stages=stages, model_call_count=len(calls),
                       generation_call_count=sum(c.purpose == CallPurpose.GENERATION for c in calls),
                       detection_call_count=sum(c.purpose == CallPurpose.DETECTION for c in calls),
                       unpriced_call_count=unknown, known_cost_usd=known, cost_complete=unknown == 0,
                       usage_source=source, generation_skipped_reason=generation_skipped_reason)
