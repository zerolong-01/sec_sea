"""Durable admission ledger at the actual model transport boundary."""
from __future__ import annotations

import json
import time

from .accounting import Accounting
from .providers import ProviderError


class BatchCallBudget:
    def __init__(self, state, save, accounting: Accounting, attempt_id: str, *, clock=time.monotonic):
        self.state, self.save, self.accounting = state, save, accounting
        self.attempt_id, self.clock = attempt_id, clock
        self.started, self.elapsed_before = clock(), state.elapsed_seconds

    def checkpoint(self):
        self.state.elapsed_seconds = self.elapsed_before + self.clock() - self.started
        self.save(self.state)
        # Durable replacement may wait on a Windows reader. Admission must use
        # time AFTER that wait, not only the timestamp written before it.
        self.state.elapsed_seconds = self.elapsed_before + self.clock() - self.started

    def before(self, call):
        self.checkpoint()
        limits = self.state.spec.budget
        if self.state.elapsed_seconds >= limits.max_seconds:
            raise ProviderError("배치 실행 시간 예산을 소진했습니다.", "BATCH_TIME_BUDGET_EXCEEDED")
        if any(c["status"] == "uncertain" for c in self.state.calls):
            raise ProviderError("사용량 경계를 넘은 호출이 있어 추가 실행을 중단합니다.", "BATCH_USAGE_BOUND_EXCEEDED")
        if len(self.state.calls) >= limits.max_calls:
            raise ProviderError("배치 모델 호출 예산을 소진했습니다.", "BATCH_CALL_BUDGET_EXCEEDED")
        # Conservative UTF-8 byte admission estimate, NOT a provider tokenizer
        # guarantee. The configured ceiling and observed breaches are recorded.
        payload_bytes = len(json.dumps({"messages": [m.model_dump() for m in call.messages],
                                       "parameters": call.parameters}, ensure_ascii=False).encode())
        input_bound = payload_bytes + 256 + 64 * len(call.messages)
        if input_bound > limits.per_call_input_token_ceiling:
            raise ProviderError("입력의 보수적 크기가 호출별 토큰 경계를 초과합니다.", "BATCH_INPUT_BOUND_EXCEEDED")
        output_bound = call.parameters.get("max_tokens")
        if type(output_bound) is not int or output_bound < 1:
            raise ProviderError("호출에 max_tokens 상한이 필요합니다.", "BATCH_OUTPUT_BOUND_REQUIRED")
        reserved_tokens = limits.per_call_input_token_ceiling + output_bound
        if sum(c["reserved_tokens"] for c in self.state.calls) + reserved_tokens > limits.max_reserved_tokens:
            raise ProviderError("배치 예약 토큰 예산을 소진했습니다.", "BATCH_TOKEN_BUDGET_EXCEEDED")
        price = next((p for p in self.accounting.book.models if p.model_id == call.model_id), None) if self.accounting.book else None
        priced = (price and price.verified and price.source_url and price.effective_date
                  and price.input_usd_per_million is not None and price.output_usd_per_million is not None)
        if not priced and limits.unknown_price_policy == "stop":
            raise ProviderError("검증된 단가가 없어 금액 예산을 보장할 수 없습니다.", "BATCH_VERIFIED_PRICE_REQUIRED")
        reserved_usd = ((limits.per_call_input_token_ceiling * price.input_usd_per_million
                         + output_bound * price.output_usd_per_million) / 1_000_000) if priced else None
        committed = sum(c["committed_usd"] or 0 for c in self.state.calls)
        if limits.max_usd is not None and committed + reserved_usd > limits.max_usd:
            raise ProviderError("배치 금액 예약 예산을 소진했습니다.", "BATCH_USD_BUDGET_EXCEEDED")
        if self.state.calls and self.state.spec.min_call_interval_seconds:
            delay = self.state.spec.min_call_interval_seconds - (time.time() - self.state.calls[-1]["admitted_at"])
            if delay > 0:
                if self.state.elapsed_seconds + delay >= limits.max_seconds:
                    raise ProviderError("호출 간격 대기가 시간 예산을 초과합니다.", "BATCH_TIME_BUDGET_EXCEEDED")
                time.sleep(delay)
        entry = {"call_index": len(self.state.calls), "attempt_id": self.attempt_id,
                 "model_id": call.model_id, "purpose": str(call.purpose), "status": "reserved",
                 "admitted_at": time.time(), "input_ceiling": limits.per_call_input_token_ceiling,
                 "output_ceiling": output_bound, "reserved_tokens": reserved_tokens,
                 "reserved_usd": reserved_usd, "committed_usd": reserved_usd,
                 "known_cost_usd": None, "input_tokens": None, "output_tokens": None,
                 "error_code": None}
        self.state.calls.append(entry)
        self.checkpoint()
        remaining = limits.max_seconds - self.state.elapsed_seconds
        if remaining <= 0:
            # Transport has not started. Persist the cancellation, so a slow
            # durable write is not counted as an actually admitted model call.
            self.state.calls.pop()
            self.checkpoint()
            raise ProviderError("예약 저장 중 배치 시간 예산을 소진했습니다.", "BATCH_TIME_BUDGET_EXCEEDED")
        return {"index": entry["call_index"], "timeout_seconds": remaining}

    def after(self, ticket, call):
        self.accounting.price(call)
        entry = self.state.calls[ticket["index"]]
        exceeded = (call.input_tokens is not None and call.input_tokens > entry["input_ceiling"]
                    or call.output_tokens is not None and call.output_tokens > entry["output_ceiling"])
        entry.update(status="uncertain" if exceeded else "settled", input_tokens=call.input_tokens,
                     output_tokens=call.output_tokens, known_cost_usd=call.estimated_cost_usd,
                     error_code=call.error_code)
        # Unknown usage and network failures retain the full reservation.
        if call.estimated_cost_usd is not None:
            entry["committed_usd"] = call.estimated_cost_usd
        self.checkpoint()
        if exceeded:
            entry["error_code"] = "BATCH_USAGE_BOUND_EXCEEDED"
            self.checkpoint()
            raise ProviderError("제공자 사용량이 예약 경계를 초과해 배치를 중단합니다.",
                                "BATCH_USAGE_BOUND_EXCEEDED", call)


def budget_summary(state):
    calls = state.calls
    def total(field):
        return sum(c[field] for c in calls) if all(c[field] is not None for c in calls) else None
    return {"admitted_calls": len(calls), "reserved_tokens": sum(c["reserved_tokens"] for c in calls),
            "observed_input_tokens": total("input_tokens"), "observed_output_tokens": total("output_tokens"),
            "known_cost_usd": sum(c["known_cost_usd"] or 0 for c in calls),
            "total_cost_usd": total("known_cost_usd"), "committed_usd": total("committed_usd"),
            "unresolved_calls": sum(c["status"] != "settled" for c in calls),
            "elapsed_seconds": state.elapsed_seconds,
            "input_bound_method": "utf8_byte_admission_estimate_with_operator_ceiling_not_tokenizer_guarantee"}
