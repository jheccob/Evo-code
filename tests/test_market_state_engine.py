from __future__ import annotations

import unittest

from market_state_engine import (
    EVO_LONG_SETUP,
    EVO_LONG_STATE,
    EVO_SHORT_SETUP,
    EVO_SHORT_STATE,
    MarketStateEngine,
    market_states_to_setup_allowlist,
    normalize_setup_collection,
    setup_types_to_market_state_allowlist,
)


class MarketStateEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = MarketStateEngine()

    def test_long_setup_generates_tradeable_buy_state(self):
        evaluation = self.engine.evaluate(
            context_result={"market_bias": "bullish"},
            regime_result={"regime": "trend_bull", "regime_score": 7.2, "volatility_state": "normal_volatility"},
            structure_result={"structure_state": "trend_resume", "price_location": "above_ema_fast"},
            confirmation_result={"confirmation_state": "confirmed"},
            entry_result={
                "setup_type": EVO_LONG_SETUP,
                "entry_quality": "strong",
                "entry_score": 7.8,
                "rr_estimate": 2.1,
                "entry_reason": "retomada compradora",
            },
            scenario_score_result={"scenario_score": 7.6},
        )

        self.assertEqual(evaluation["market_state"], EVO_LONG_STATE)
        self.assertEqual(evaluation["action"], "buy")
        self.assertTrue(evaluation["is_tradeable"])
        self.assertEqual(evaluation["legacy_setup_type"], EVO_LONG_SETUP)

    def test_short_setup_generates_tradeable_sell_state(self):
        evaluation = self.engine.evaluate(
            context_result={"market_bias": "bearish"},
            regime_result={"regime": "trend_bear", "regime_score": 7.0, "volatility_state": "normal_volatility"},
            structure_result={"structure_state": "trend_resume", "price_location": "below_ema_fast"},
            confirmation_result={"confirmation_state": "confirmed"},
            entry_result={
                "setup_type": EVO_SHORT_SETUP,
                "entry_quality": "strong",
                "entry_score": 7.5,
                "rr_estimate": 1.9,
                "entry_reason": "retomada vendedora",
            },
            scenario_score_result={"scenario_score": 7.4},
        )

        self.assertEqual(evaluation["market_state"], EVO_SHORT_STATE)
        self.assertEqual(evaluation["action"], "sell")
        self.assertTrue(evaluation["is_tradeable"])
        self.assertEqual(evaluation["legacy_setup_type"], EVO_SHORT_SETUP)

    def test_hard_block_forces_blocked_state(self):
        evaluation = self.engine.evaluate(
            context_result={"market_bias": "bullish"},
            regime_result=None,
            structure_result=None,
            confirmation_result=None,
            entry_result=None,
            scenario_score_result=None,
            hard_block_result={"hard_block": True, "block_reason": "contexto contrario"},
        )

        self.assertEqual(evaluation["market_state"], "blocked")
        self.assertEqual(evaluation["action"], "wait")
        self.assertEqual(evaluation["block_reason"], "contexto contrario")

    def test_setup_and_market_state_normalizers_expand_legacy_aliases(self):
        self.assertEqual(
            normalize_setup_collection(["pullback_trend"]),
            [EVO_LONG_SETUP, EVO_SHORT_SETUP],
        )
        self.assertEqual(
            market_states_to_setup_allowlist(["breakout_expansion"]),
            [EVO_LONG_SETUP, EVO_SHORT_SETUP],
        )
        self.assertEqual(
            setup_types_to_market_state_allowlist([EVO_LONG_SETUP, EVO_SHORT_SETUP]),
            [EVO_LONG_STATE, EVO_SHORT_STATE],
        )


if __name__ == "__main__":
    unittest.main()
