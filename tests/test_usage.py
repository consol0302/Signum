from __future__ import annotations

import json
import unittest

from signum.usage import CallLedger, CallUsage


class UsageTests(unittest.TestCase):
    def test_one_batch_counts_one_call(self):
        ledger = CallLedger()
        ledger.record(CallUsage("batch", (1, 2, 3), input_tokens=100, output_tokens=20,
                                cached_input_tokens=40, reasoning_output_tokens=5))
        report = ledger.report()
        self.assertEqual(report["calls"], 1)
        self.assertEqual(report["packet_deliveries"], 3)
        self.assertEqual(report["total_tokens"], 120)

    def test_idempotent_record_and_conflict(self):
        ledger = CallLedger()
        record = CallUsage("same", (1,), input_tokens=10, output_tokens=5)
        self.assertTrue(ledger.record(record))
        self.assertFalse(ledger.record(record))
        with self.assertRaises(ValueError):
            ledger.record(CallUsage("same", (1,), input_tokens=10, output_tokens=6))
        self.assertEqual(ledger.report()["total_tokens"], 15)

    def test_failed_calls_and_retries_still_count(self):
        ledger = CallLedger()
        ledger.record(CallUsage("attempt1", (1,), input_tokens=10, output_tokens=1, error="schema_failed"))
        ledger.record(CallUsage("attempt2", (1,), input_tokens=10, output_tokens=5))
        report = ledger.report()
        self.assertEqual(report["failed_calls"], 1)
        self.assertEqual(report["unique_packets"], 1)
        self.assertEqual(report["total_tokens"], 26)

    def test_incomplete_usage_stays_unknown(self):
        ledger = CallLedger()
        ledger.record(CallUsage("unknown", (1,)))
        ledger.record(CallUsage("partial", (2,), input_tokens=10))
        report = ledger.report()
        self.assertFalse(report["usage_complete"])
        self.assertIsNone(report["total_tokens"])
        self.assertEqual(report["reported_token_subtotal"], 10)
        self.assertFalse(report["cost_complete"])
        self.assertFalse(report["latency_complete"])

    def test_currency_and_estimates_are_never_merged(self):
        ledger = CallLedger()
        for i, (currency, basis) in enumerate((("USD", "provider_invoice"),
                ("USD", "published_price_estimate"), ("KRW", "provider_invoice"))):
            ledger.record(CallUsage(str(i), (i,), cost_amount=1, currency=currency, cost_basis=basis))
        self.assertEqual(len(ledger.report()["cost_groups"]), 3)
        json.dumps(ledger.report(), allow_nan=False)

    def test_invalid_usage_rejected(self):
        for fields in ({"input_tokens": -1}, {"input_tokens": True},
                {"input_tokens": 1, "cached_input_tokens": 2},
                {"cost_amount": float("nan")}, {"cost_amount": 1},
                {"latency_seconds": float("inf")}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                CallUsage("a", (1,), **fields)
        with self.assertRaises(ValueError):
            CallUsage("a", (1, 1))

    def test_capacity_failure_is_visible(self):
        ledger = CallLedger(max_calls=1)
        ledger.record(CallUsage("one", (1,)))
        with self.assertRaises(OverflowError):
            ledger.record(CallUsage("two", (2,)))

    def test_empty_ledger_is_not_a_free_success(self):
        report = CallLedger().report()
        self.assertIsNone(report["total_tokens"])
        self.assertFalse(report["cost_complete"])


if __name__ == "__main__":
    unittest.main()
