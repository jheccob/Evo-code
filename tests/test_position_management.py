from __future__ import annotations

import unittest

import pandas as pd

from position_management import build_position_management_preview, evaluate_position_management


class PositionManagementTests(unittest.TestCase):
    def _build_df(self, rows):
        timestamps = pd.date_range("2026-01-01", periods=len(rows), freq="1h")
        return pd.DataFrame(rows, index=timestamps)

    def test_break_even_activates_after_trade_reaches_one_r(self):
        df = self._build_df(
            [
                {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.8, "atr": 1.0, "ema_21": 100.3},
                {"open": 100.8, "high": 102.5, "low": 100.4, "close": 102.2, "atr": 1.0, "ema_21": 100.9},
            ]
        )

        result = evaluate_position_management(
            recent_df=df,
            side="long",
            entry_price=100.0,
            current_stop_price=98.0,
            current_take_price=104.0,
            initial_stop_price=98.0,
            initial_take_price=104.0,
            position_age_candles=1,
        )

        self.assertEqual(result["action"], "move_stop_to_break_even")
        self.assertTrue(result["break_even_active"])
        self.assertEqual(result["stop_price"], 100.0)

    def test_trailing_activates_after_trade_reaches_two_r(self):
        df = self._build_df(
            [
                {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.8, "atr": 1.0, "ema_21": 100.3},
                {"open": 100.8, "high": 105.2, "low": 100.6, "close": 104.6, "atr": 1.0, "ema_21": 101.9},
            ]
        )

        result = evaluate_position_management(
            recent_df=df,
            side="long",
            entry_price=100.0,
            current_stop_price=100.0,
            current_take_price=108.0,
            initial_stop_price=98.0,
            initial_take_price=108.0,
            break_even_active=True,
            position_age_candles=2,
        )

        self.assertIn(result["action"], {"activate_trailing", "tighten_stop"})
        self.assertTrue(result["trailing_active"])
        self.assertGreater(result["stop_price"], 100.0)

    def test_high_volatility_and_parabolic_enable_extra_protection(self):
        df = self._build_df(
            [
                {"open": 100.0, "high": 101.5, "low": 99.8, "close": 101.2, "atr": 1.0, "ema_21": 100.4},
                {"open": 101.2, "high": 103.8, "low": 101.0, "close": 103.4, "atr": 1.4, "ema_21": 101.3},
            ]
        )

        result = evaluate_position_management(
            recent_df=df,
            side="long",
            entry_price=100.0,
            current_stop_price=100.0,
            current_take_price=106.0,
            initial_stop_price=98.0,
            initial_take_price=106.0,
            break_even_active=True,
            position_age_candles=2,
            regime_evaluation={
                "regime": "trend_bull",
                "regime_score": 8.6,
                "volatility_state": "high_volatility",
                "parabolic": True,
                "ema_distance_pct": 3.2,
            },
        )

        self.assertTrue(result["post_pump_protection"])
        self.assertEqual(result["protection_level"], "aggressive")

    def test_structure_deterioration_flags_exit(self):
        df = self._build_df(
            [
                {"open": 100.0, "high": 102.2, "low": 99.8, "close": 101.8, "atr": 1.0, "ema_21": 100.6},
                {"open": 102.0, "high": 102.1, "low": 99.4, "close": 99.8, "atr": 1.0, "ema_21": 100.5},
            ]
        )

        result = evaluate_position_management(
            recent_df=df,
            side="long",
            entry_price=100.0,
            current_stop_price=100.0,
            current_take_price=108.0,
            initial_stop_price=98.0,
            initial_take_price=108.0,
            break_even_active=True,
            position_age_candles=2,
        )

        self.assertEqual(result["action"], "exit_on_structure_failure")
        self.assertTrue(result["structure_exit_flag"])

    def test_preview_reflects_aggressive_mode_for_parabolic_regime(self):
        preview = build_position_management_preview(
            stop_loss_pct=2.0,
            take_profit_pct=4.0,
            regime_evaluation={"volatility_state": "high_volatility", "parabolic": True},
        )

        self.assertEqual(preview["protection_mode"], "aggressive")
        self.assertEqual(preview["break_even_trigger_r"], 1.0)
        self.assertEqual(preview["trailing_trigger_r"], 2.0)


if __name__ == "__main__":
    unittest.main()
