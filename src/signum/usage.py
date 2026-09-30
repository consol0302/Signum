"""Caller-reported, call-level accounting independent of observation batching.

No price lookup or token estimate is performed here. Failed calls may still
consume usage. Reasoning tokens are diagnostic and not added to output twice.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CallUsage:
    call_id: str
    packet_ids: tuple[int, ...]
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    latency_seconds: float | None = None
    cost_amount: float | None = None
    currency: str | None = None
    cost_basis: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, str) or not self.call_id.strip():
            raise ValueError("call_id must be a nonempty string")
        if (not self.packet_ids or any(isinstance(i, bool) or not isinstance(i, int) or i < 0
                                      for i in self.packet_ids)):
            raise ValueError("packet_ids must be nonnegative integer identities")
        if len(set(self.packet_ids)) != len(self.packet_ids):
            raise ValueError("packet_ids must be unique within a call")
        object.__setattr__(self, "packet_ids", tuple(self.packet_ids))
        for field in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"):
            value = getattr(self, field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"{field} must be a nonnegative integer or None")
        if (self.input_tokens is not None and self.cached_input_tokens is not None
                and self.cached_input_tokens > self.input_tokens):
            raise ValueError("cached input cannot exceed total input")
        for field in ("latency_seconds", "cost_amount"):
            value = getattr(self, field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or value < 0):
                raise ValueError(f"{field} must be finite, nonnegative or None")
        if self.cost_amount is None:
            if self.currency is not None or self.cost_basis is not None:
                raise ValueError("currency and cost_basis require a cost amount")
        elif (not isinstance(self.currency, str) or not self.currency.strip()
              or self.cost_basis not in ("provider_invoice", "published_price_estimate")):
            raise ValueError("reported costs require currency and a supported explicit basis")


class CallLedger:
    """Bounded audit ledger. Duplicate identical records are idempotent.

    Keep one ledger per evaluation run. Once capacity is reached, persist it and
    start another ledger; this object raises rather than silently losing records.
    Caller-reported amounts are not independently verified provider invoices.
    """
    def __init__(self, max_calls: int = 10000) -> None:
        if isinstance(max_calls, bool) or not isinstance(max_calls, int) or max_calls <= 0:
            raise ValueError("max_calls must be a positive integer")
        self.max_calls = max_calls
        self._calls: dict[str, CallUsage] = {}

    def record(self, usage: CallUsage) -> bool:
        if not isinstance(usage, CallUsage):
            raise TypeError("usage must be CallUsage")
        previous = self._calls.get(usage.call_id)
        if previous is not None:
            if previous != usage:
                raise ValueError("conflicting record for an already recorded call_id")
            return False
        if len(self._calls) >= self.max_calls:
            raise OverflowError("call ledger is full; persist it before recording more calls")
        self._calls[usage.call_id] = usage
        return True

    def report(self) -> dict[str, object]:
        calls = tuple(self._calls.values())
        complete_usage = bool(calls) and all(c.input_tokens is not None and c.output_tokens is not None for c in calls)
        costs: dict[tuple[str, str], dict[str, object]] = {}
        for call in calls:
            if call.cost_amount is not None:
                key = (call.currency, call.cost_basis)
                group = costs.setdefault(key, {"currency": call.currency,
                    "basis": call.cost_basis, "amount": 0.0, "calls": 0})
                group["amount"] += call.cost_amount
                group["calls"] += 1
        reported_tokens = sum((c.input_tokens or 0) + (c.output_tokens or 0) for c in calls)
        return {
            "calls": len(calls),
            "failed_calls": sum(c.error is not None for c in calls),
            "packet_deliveries": sum(len(c.packet_ids) for c in calls),
            "unique_packets": len({p for c in calls for p in c.packet_ids}),
            "usage_complete": complete_usage,
            "reported_token_subtotal": reported_tokens,
            "total_tokens": reported_tokens if complete_usage else None,
            "reported_cached_input_tokens": sum(c.cached_input_tokens or 0 for c in calls),
            "reported_reasoning_output_tokens": sum(c.reasoning_output_tokens or 0 for c in calls),
            "cost_complete": bool(calls) and all(c.cost_amount is not None for c in calls),
            "cost_groups": list(costs.values()),
            "reported_latency_sum_seconds": sum(c.latency_seconds or 0 for c in calls),
            "latency_complete": bool(calls) and all(c.latency_seconds is not None for c in calls),
            "records": [asdict(c) for c in calls],
        }
