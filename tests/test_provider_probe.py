from __future__ import annotations

import sys
import unittest
from argparse import Namespace
from pathlib import Path


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
sys.path.insert(0, str(EXAMPLES))

from provider_api_probe import estimate_cost  # noqa: E402


class ProviderCostTests(unittest.TestCase):
    def test_openai_cost_separates_cached_input(self) -> None:
        args = Namespace(
            provider="openai",
            input_usd_per_million=5.0,
            output_usd_per_million=30.0,
            cached_input_usd_per_million=0.5,
            cache_write_usd_per_million=None,
        )

        cost = estimate_cost(
            args,
            {
                "input_tokens": 1_000_000,
                "cached_input_tokens": 400_000,
                "output_tokens": 100_000,
            },
        )

        self.assertEqual(6.2, cost)

    def test_anthropic_cost_counts_cache_write_and_read(self) -> None:
        args = Namespace(
            provider="anthropic",
            input_usd_per_million=2.0,
            output_usd_per_million=10.0,
            cached_input_usd_per_million=0.2,
            cache_write_usd_per_million=2.5,
        )

        cost = estimate_cost(
            args,
            {
                "input_tokens": 500_000,
                "cache_creation_input_tokens": 200_000,
                "cache_read_input_tokens": 300_000,
                "output_tokens": 100_000,
            },
        )

        self.assertEqual(2.56, cost)


if __name__ == "__main__":
    unittest.main()
