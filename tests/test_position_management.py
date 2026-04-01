import unittest

import pandas as pd

from position_management import evaluate_position_management


def _build_recent_df(rows):
    return pd.DataFrame(rows, index=pd.date_range("2026-03-01 00:00:00", periods=len(rows), freq="15min"))


class PositionManagementTests(unittest.TestCase):
    def test_evo_resume_long_activates_percentage_trailing(self):
        recent_df = _build_recent_df(
            [
                {"open": 100.1, "high": 100.5, "low": 99.9, "close": 100.4, "atr": 0.6, "ema_21": 100.0},
                {"open": 100.5, "high": 101.8, "low": 100.4, "close": 101.6, "atr": 0.6, "ema_21": 100.5},
            ]
        )

        result = evaluate_position_management(
            recent_df=recent_df,
            side="long",
            entry_price=100.0,
            current_stop_price=99.2,
            current_take_price=101.8,
            initial_stop_price=99.2,
            initial_take_price=101.8,
            position_age_candles=1,
            timeframe="15m",
            setup_name="ema_rsi_resume_long",
        )

        self.assertEqual(result["action"], "activate_trailing")
        self.assertTrue(result["trailing_active"])
        self.assertFalse(result["break_even_active"])
        self.assertGreater(result["stop_price"], 100.8)

    def test_evo_resume_short_activates_percentage_trailing(self):
        recent_df = _build_recent_df(
            [
                {"open": 99.8, "high": 100.0, "low": 99.3, "close": 99.5, "atr": 0.6, "ema_21": 99.9},
                {"open": 99.4, "high": 99.5, "low": 98.2, "close": 98.4, "atr": 0.6, "ema_21": 99.1},
            ]
        )

        result = evaluate_position_management(
            recent_df=recent_df,
            side="short",
            entry_price=100.0,
            current_stop_price=100.9,
            current_take_price=98.2,
            initial_stop_price=100.9,
            initial_take_price=98.2,
            position_age_candles=1,
            timeframe="15m",
            setup_name="ema_rsi_resume_short",
        )

        self.assertEqual(result["action"], "activate_trailing")
        self.assertTrue(result["trailing_active"])
        self.assertLess(result["stop_price"], 99.3)

    def test_generic_position_still_uses_default_management_path(self):
        recent_df = _build_recent_df(
            [
                {"open": 100.4, "high": 101.1, "low": 100.2, "close": 100.9, "atr": 0.6, "ema_21": 100.2},
                {"open": 100.9, "high": 101.8, "low": 100.7, "close": 101.6, "atr": 0.6, "ema_21": 100.5},
            ]
        )

        result = evaluate_position_management(
            recent_df=recent_df,
            side="long",
            entry_price=100.0,
            current_stop_price=98.0,
            current_take_price=104.0,
            initial_stop_price=98.0,
            initial_take_price=104.0,
            position_age_candles=1,
            timeframe="15m",
            setup_name="swing_generic",
            entry_quality="strong",
        )

        self.assertEqual(result["action"], "hold")
        self.assertEqual(result["stop_price"], 98.0)
        self.assertFalse(result["trailing_active"])


if __name__ == "__main__":
    unittest.main()
