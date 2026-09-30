# Call-level usage for attention batches

`signum.usage.CallLedger` records each external model call once, independently of
how many attention packets it contains. It performs no price lookup or inference.
Use it alongside the evidence-only controller described in `ATTENTION.md`.

```python
from signum.usage import CallLedger, CallUsage

ledger = CallLedger()
# Example counts only, not measured provider usage:
ledger.record(CallUsage(
    call_id="provider-request-or-local-attempt-id",
    packet_ids=(12, 13, 14),
    input_tokens=100,
    cached_input_tokens=40,
    output_tokens=20,
    reasoning_output_tokens=5,
))
assert ledger.report()["calls"] == 1
assert ledger.report()["total_tokens"] == 120
```

The normalized input total includes cached input; normalized output includes
reasoning output. Neither diagnostic is added twice. Provider adapters with a
different convention must normalize their usage explicitly before recording it.
Do not copy a batch's usage total into every event's `SemanticResult`; leave
per-event usage unknown when the provider does not allocate it.

A failed call can still be billed and must be recorded. Retries use distinct
call IDs. Re-recording identical content under the same ID is idempotent;
conflicting content raises. Missing counts remain unknown. The subtotal of
reported tokens is available, but `total_tokens` remains null while incomplete.

Optional cost fields require an amount, currency and either `provider_invoice`
or `published_price_estimate`. These are caller-reported inputs, not independently
verified invoices. Currencies and bases are reported in separate groups. A
published-price calculation is never silently promoted to an invoice. For a
comparative claim retain the provider source, pricing snapshot, exact model,
artifacts and protocol separately.

This is a bounded in-memory, single-controller ledger, not a database or a
concurrent billing service. Persist its JSON report before the configured capacity
is reached; exhaustion raises rather than deleting audit history. There is no
paid provider execution in its tests.
