from __future__ import annotations

import unittest

import pandas as pd

from indicators import TechnicalIndicators
from trading_bot import TradingBot
from trading_core import pipeline_v2


def _build_trend_frame(
    side: str,
    periods: int = 60,
    start: str = "2026-01-01 00:00:00",
    freq: str = "15min",
) -> pd.DataFrame:
    rows = []
    index = pd.date_range(start, periods=periods, freq=freq)

    for step in range(periods - 2):
        if side == "long":
            close = 100.0 + (step * 0.20)
            open_price = close - 0.08
            ema_fast = close - 0.12
            ema_slow = close - 0.28
            ema_trend = close - 0.58
            rsi = 48.0 + min(step * 0.03, 2.5)
            di_plus, di_minus = 28.0, 12.0
            macd_value, macd_signal, macd_histogram = 0.22, 0.08, 0.14
        else:
            close = 100.0 - (step * 0.20)
            open_price = close + 0.08
            ema_fast = close + 0.12
            ema_slow = close + 0.28
            ema_trend = close + 0.58
            rsi = 52.0 - min(step * 0.03, 2.5)
            di_plus, di_minus = 12.0, 28.0
            macd_value, macd_signal, macd_histogram = -0.22, -0.08, -0.14

        high = max(open_price, close) + 0.10
        low = min(open_price, close) - 0.10
        rows.append(
            {
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000.0 + (step * 5.0),
                "ema_9": ema_fast,
                "ema_21": ema_slow,
                "ema_50": ema_trend,
                "ema_200": ema_trend - 0.60 if side == "long" else ema_trend + 0.60,
                "rsi": rsi,
                "atr": 0.70,
                "macd": macd_value,
                "macd_signal": macd_signal,
                "macd_histogram": macd_histogram,
                "adx": 25.0,
                "di_plus": di_plus,
                "di_minus": di_minus,
                "volume_ratio": 1.05,
                "is_closed": True,
            }
        )

    if side == "long":
        trailing_rows = [
            {
                "open": 111.10,
                "high": 111.28,
                "low": 111.02,
                "close": 111.20,
                "volume": 1320.0,
                "ema_9": 111.28,
                "ema_21": 111.18,
                "ema_50": 110.74,
                "ema_200": 109.90,
                "rsi": 51.0,
                "atr": 0.72,
                "macd": 0.24,
                "macd_signal": 0.09,
                "macd_histogram": 0.15,
                "adx": 26.0,
                "di_plus": 30.0,
                "di_minus": 11.0,
                "volume_ratio": 1.10,
                "is_closed": True,
            },
            {
                "open": 111.18,
                "high": 111.62,
                "low": 111.12,
                "close": 111.56,
                "volume": 1380.0,
                "ema_9": 111.42,
                "ema_21": 111.30,
                "ema_50": 110.86,
                "ema_200": 110.02,
                "rsi": 53.5,
                "atr": 0.72,
                "macd": 0.28,
                "macd_signal": 0.10,
                "macd_histogram": 0.18,
                "adx": 27.0,
                "di_plus": 31.0,
                "di_minus": 10.0,
                "volume_ratio": 1.12,
                "is_closed": True,
            },
        ]
    else:
        trailing_rows = [
            {
                "open": 88.90,
                "high": 88.98,
                "low": 88.72,
                "close": 88.80,
                "volume": 1320.0,
                "ema_9": 88.72,
                "ema_21": 88.84,
                "ema_50": 89.26,
                "ema_200": 90.10,
                "rsi": 48.8,
                "atr": 0.72,
                "macd": -0.24,
                "macd_signal": -0.09,
                "macd_histogram": -0.15,
                "adx": 26.0,
                "di_plus": 11.0,
                "di_minus": 30.0,
                "volume_ratio": 1.10,
                "is_closed": True,
            },
            {
                "open": 88.82,
                "high": 88.88,
                "low": 88.38,
                "close": 88.46,
                "volume": 1380.0,
                "ema_9": 88.58,
                "ema_21": 88.72,
                "ema_50": 89.14,
                "ema_200": 89.98,
                "rsi": 45.5,
                "atr": 0.72,
                "macd": -0.28,
                "macd_signal": -0.10,
                "macd_histogram": -0.18,
                "adx": 27.0,
                "di_plus": 10.0,
                "di_minus": 31.0,
                "volume_ratio": 1.12,
                "is_closed": True,
            },
        ]

    rows.extend(trailing_rows)
    frame = pd.DataFrame(rows, index=index)
    frame["prev_rsi"] = frame["rsi"].shift(1)
    return frame


class PipelineV2ResumeEngineTests(unittest.TestCase):
    def _build_bot(self) -> TradingBot:
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 52
        bot.rsi_max = 47
        bot.rsi_period = 14
        bot.timeframe = "15m"
        bot.indicators = TechnicalIndicators()
        return bot

    def test_resume_engine_generates_long_signal(self):
        bot = self._build_bot()
        frame = _build_trend_frame("long")

        signal = pipeline_v2.check_signal(bot, frame, timeframe="15m", require_volume=False)

        self.assertEqual(signal, "COMPRA")
        self.assertEqual(bot._last_entry_quality_evaluation["setup_type"], "ema_rsi_resume_long")
        self.assertEqual(bot._last_market_state_evaluation["market_state"], "ema_rsi_resume_bull")

    def test_resume_engine_generates_short_signal(self):
        bot = self._build_bot()
        frame = _build_trend_frame("short")

        signal = pipeline_v2.check_signal(bot, frame, timeframe="15m", require_volume=False)

        self.assertEqual(signal, "VENDA")
        self.assertEqual(bot._last_entry_quality_evaluation["setup_type"], "ema_rsi_resume_short")
        self.assertEqual(bot._last_market_state_evaluation["market_state"], "ema_rsi_resume_bear")

    def test_resume_engine_blocks_long_below_ema200(self):
        bot = self._build_bot()
        frame = _build_trend_frame("long")
        frame["ema_200"] = frame["close"] + 1.0

        signal = pipeline_v2.check_signal(bot, frame, timeframe="15m", require_volume=False)

        self.assertEqual(signal, "NEUTRO")
        self.assertIn("EMA200", bot._last_entry_quality_evaluation["rejection_reason"])

    def test_resume_engine_blocks_long_without_full_ema200_stack(self):
        bot = self._build_bot()
        frame = _build_trend_frame("long")
        frame["ema_50"] = frame["ema_200"] - 0.1

        signal = pipeline_v2.check_signal(bot, frame, timeframe="15m", require_volume=False)

        self.assertEqual(signal, "NEUTRO")
        self.assertIn("empilhamento", bot._last_entry_quality_evaluation["rejection_reason"])

    def test_resume_engine_blocks_long_without_positive_macd(self):
        bot = self._build_bot()
        frame = _build_trend_frame("long")
        frame["macd"] = -0.1
        frame["macd_signal"] = 0.1
        frame["macd_histogram"] = -0.2

        signal = pipeline_v2.check_signal(bot, frame, timeframe="15m", require_volume=False)

        self.assertEqual(signal, "NEUTRO")
        self.assertIn("MACD", bot._last_entry_quality_evaluation["rejection_reason"])

    def test_resume_engine_blocks_short_above_ema200(self):
        bot = self._build_bot()
        frame = _build_trend_frame("short")
        frame["ema_200"] = frame["close"] - 1.0

        signal = pipeline_v2.check_signal(bot, frame, timeframe="15m", require_volume=False)

        self.assertEqual(signal, "NEUTRO")
        self.assertIn("EMA200", bot._last_entry_quality_evaluation["rejection_reason"])

    def test_resume_engine_blocks_short_without_negative_macd(self):
        bot = self._build_bot()
        frame = _build_trend_frame("short")
        frame["macd"] = 0.1
        frame["macd_signal"] = -0.1
        frame["macd_histogram"] = 0.2

        signal = pipeline_v2.check_signal(bot, frame, timeframe="15m", require_volume=False)

        self.assertEqual(signal, "NEUTRO")
        self.assertIn("MACD", bot._last_entry_quality_evaluation["rejection_reason"])

    def test_resume_engine_blocks_short_with_weak_adx(self):
        bot = self._build_bot()
        frame = _build_trend_frame("short")
        frame["adx"] = 15.0

        signal = pipeline_v2.check_signal(bot, frame, timeframe="15m", require_volume=False)

        self.assertEqual(signal, "NEUTRO")
        self.assertIn("ADX", bot._last_entry_quality_evaluation["rejection_reason"])

    def test_resume_engine_blocks_signal_against_context(self):
        bot = self._build_bot()
        frame = _build_trend_frame("long")
        context_frame = _build_trend_frame("short", freq="1h")

        signal = pipeline_v2.check_signal(
            bot,
            frame,
            timeframe="15m",
            context_df=context_frame,
            require_volume=False,
        )

        self.assertEqual(signal, "NEUTRO")
        self.assertTrue(bot._last_hard_block_evaluation["hard_block"])
        self.assertEqual(bot._last_hard_block_evaluation["block_source"], "higher_timeframe_context")


if __name__ == "__main__":
    unittest.main()
