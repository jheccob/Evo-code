from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from indicators import TechnicalIndicators
from trading_bot import TradingBot


def _build_resume_frame(side: str, periods: int = 60, freq: str = "15min") -> pd.DataFrame:
    rows = []
    index = pd.date_range("2026-01-01 00:00:00", periods=periods, freq=freq)
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
        rows.extend(
            [
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
                    "rsi": 54.6,
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
        )
    else:
        rows.extend(
            [
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
                    "rsi": 46.4,
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
        )
    frame = pd.DataFrame(rows, index=index)
    frame["prev_rsi"] = frame["rsi"].shift(1)
    return frame


class TradingBotLogicTests(unittest.TestCase):
    def _build_bot(self) -> TradingBot:
        bot = TradingBot.__new__(TradingBot)
        bot.symbol = "BTC/USDT"
        bot.timeframe = "15m"
        bot.rsi_period = 14
        bot.rsi_min = 54
        bot.rsi_max = 47
        bot.indicators = TechnicalIndicators()
        bot.market_state_engine = None
        bot._last_context_evaluation = None
        bot._last_regime_evaluation = None
        bot._last_price_structure_evaluation = None
        bot._last_confirmation_evaluation = None
        bot._last_entry_quality_evaluation = None
        bot._last_scenario_evaluation = None
        bot._last_market_state_evaluation = None
        bot._last_trade_decision = None
        bot._last_hard_block_evaluation = None
        bot._last_candidate_signal = "NEUTRO"
        bot._last_signal_pipeline = None
        return bot

    @mock.patch("requests.get")
    def test_fetch_public_ohlcv_prefers_futures_endpoint_and_normalizes_symbol(self, mock_get):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [[1704067200000, "100.0", "101.0", "99.0", "100.5", "1234.0"]]
        mock_get.return_value = response

        bot = self._build_bot()
        bot.symbol = "BTC/USDT:USDT"
        bot.timeframe = "1h"

        data = TradingBot._fetch_public_ohlcv(bot, limit=1, symbol="BTC/USDT:USDT", timeframe="1h")

        self.assertEqual(len(data), 1)
        first_url = mock_get.call_args_list[0].args[0]
        self.assertIn("https://fapi.binance.com/fapi/v1/klines", first_url)
        self.assertIn("symbol=BTCUSDT", first_url)

    def test_evaluate_contextual_entry_uses_active_long_setup(self):
        bot = self._build_bot()
        data = _build_resume_frame("long")

        evaluation = TradingBot.evaluate_contextual_entry(bot, data, timeframe="15m")

        self.assertEqual(evaluation["setup_type"], "ema_rsi_resume_long")
        self.assertEqual(evaluation["entry_quality"], "strong")
        self.assertGreater(evaluation["entry_score"], 7.0)

    def test_make_trade_decision_returns_buy_for_active_long_setup(self):
        bot = self._build_bot()

        decision = TradingBot.make_trade_decision(
            bot,
            context_result={"market_bias": "bullish"},
            structure_result={"structure_state": "trend_resume", "price_location": "above_ema_fast"},
            confirmation_result={"confirmation_state": "confirmed"},
            entry_result={
                "setup_type": "ema_rsi_resume_long",
                "entry_quality": "strong",
                "entry_score": 7.8,
                "rr_estimate": 2.0,
                "entry_reason": "retomada compradora",
            },
            hard_block_result={"hard_block": False, "block_reason": None},
            scenario_score_result={"scenario_score": 7.6},
            regime_result={"regime": "trend_bull", "regime_score": 7.1, "volatility_state": "normal_volatility"},
        )

        self.assertEqual(decision["action"], "buy")
        self.assertEqual(decision["setup_type"], "ema_rsi_resume_long")
        self.assertEqual(decision["market_state"], "ema_rsi_resume_bull")

    def test_evaluate_signal_pipeline_blocks_setup_outside_allowlist(self):
        bot = self._build_bot()
        data = _build_resume_frame("long")

        pipeline = TradingBot.evaluate_signal_pipeline(
            bot,
            data,
            timeframe="15m",
            require_volume=False,
            allowed_execution_setups=["ema_rsi_resume_short"],
        )

        self.assertEqual(pipeline["approved_signal"], None)
        self.assertEqual(pipeline["blocked_signal"], "COMPRA")
        self.assertIn("ema_rsi_resume_long", pipeline["block_reason"])


if __name__ == "__main__":
    unittest.main()
