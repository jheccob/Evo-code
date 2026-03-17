from __future__ import annotations

import unittest

import pandas as pd

from trading_bot import TradingBot


class TradingBotLogicTests(unittest.TestCase):
    def test_5m_signal_path_keeps_post_filters_after_timeframe_filtering(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 20
        bot.rsi_max = 80
        bot.rsi_period = 14
        bot.timeframe = "5m"
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.30

        candle = pd.DataFrame(
            [
                {
                    "rsi": 15.0,
                    "macd": 1.0,
                    "macd_signal": 0.4,
                    "macd_histogram": 0.6,
                    "adx": 35.0,
                    "volume_ratio": 3.0,
                    "atr": 1.0,
                    "close": 100.0,
                    "stoch_rsi_k": 45.0,
                    "williams_r": -50.0,
                    "bb_width": 0.05,
                    "market_regime": "trending",
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="5m")

        self.assertEqual(signal, "NEUTRO")

    def test_indicators_source_has_single_atr_and_williams_r_definition(self):
        with open("indicators.py", "r", encoding="utf-8") as indicators_file:
            source = indicators_file.read()

        self.assertEqual(source.count("def calculate_atr("), 1)
        self.assertEqual(source.count("def calculate_williams_r("), 1)

    def test_advanced_score_is_direction_aware_for_sell_signals(self):
        bot = TradingBot.__new__(TradingBot)
        row = pd.Series(
            {
                "rsi": 82.0,
                "macd": -1.2,
                "macd_signal": -0.6,
                "macd_histogram": -0.4,
                "adx": 31.0,
                "volume_ratio": 2.2,
                "market_regime": "trending",
            }
        )

        sell_score = TradingBot.calculate_advanced_score(bot, row, signal="VENDA")
        buy_score = TradingBot.calculate_advanced_score(bot, row, signal="COMPRA")

        self.assertGreater(sell_score, buy_score)
        self.assertGreaterEqual(sell_score, 0.65)

    def test_5m_signal_requires_higher_effective_confidence_floor(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 20
        bot.rsi_max = 80
        bot.rsi_period = 14
        bot.timeframe = "5m"
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 63.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.75

        candle = pd.DataFrame(
            [
                {
                    "rsi": 18.0,
                    "macd": 1.0,
                    "macd_signal": 0.4,
                    "macd_histogram": 0.6,
                    "adx": 35.0,
                    "volume_ratio": 3.0,
                    "atr": 1.0,
                    "close": 100.0,
                    "stoch_rsi_k": 40.0,
                    "williams_r": -50.0,
                    "bb_width": 0.05,
                    "market_regime": "trending",
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="5m")

        self.assertEqual(signal, "NEUTRO")

    def test_short_timeframes_reject_ranging_market_before_scoring(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 20
        bot.rsi_max = 80
        bot.rsi_period = 14
        bot.timeframe = "15m"
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 92.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.90

        candle = pd.DataFrame(
            [
                {
                    "rsi": 18.0,
                    "macd": 1.0,
                    "macd_signal": 0.4,
                    "macd_histogram": 0.6,
                    "adx": 35.0,
                    "volume_ratio": 3.0,
                    "atr": 1.0,
                    "close": 100.0,
                    "stoch_rsi_k": 40.0,
                    "williams_r": -50.0,
                    "bb_width": 0.05,
                    "market_regime": "ranging",
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="15m")

        self.assertEqual(signal, "NEUTRO")



    def test_require_trend_uses_di_alignment_for_trend_signal(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 20
        bot.rsi_max = 80
        bot.rsi_period = 14
        bot.timeframe = "15m"
        bot._generate_advanced_signal = lambda row: "NEUTRO"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9

        candle = pd.DataFrame(
            [
                {
                    "rsi": 52.0,
                    "macd": 0.6,
                    "macd_signal": 0.2,
                    "macd_histogram": 0.4,
                    "adx": 32.0,
                    "di_plus": 28.0,
                    "di_minus": 12.0,
                    "volume_ratio": 2.0,
                    "atr": 1.2,
                    "close": 100.0,
                    "stoch_rsi_k": 45.0,
                    "williams_r": -45.0,
                    "bb_width": 0.06,
                    "market_regime": "trending",
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="15m", require_trend=True)

        self.assertEqual(signal, "COMPRA")

    def test_check_signal_uses_last_closed_candle_when_stream_has_open_candle(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 20
        bot.rsi_max = 80
        bot.rsi_period = 14
        bot.timeframe = "15m"
        bot._generate_advanced_signal = lambda row: "COMPRA" if row["close"] == 100.0 else "VENDA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9

        candle = pd.DataFrame(
            [
                {
                    "rsi": 25.0,
                    "macd": 0.8,
                    "macd_signal": 0.2,
                    "macd_histogram": 0.6,
                    "adx": 35.0,
                    "volume_ratio": 2.0,
                    "atr": 1.0,
                    "close": 100.0,
                    "stoch_rsi_k": 40.0,
                    "williams_r": -50.0,
                    "bb_width": 0.05,
                    "market_regime": "trending",
                    "is_closed": True,
                },
                {
                    "rsi": 78.0,
                    "macd": -0.4,
                    "macd_signal": 0.1,
                    "macd_histogram": -0.5,
                    "adx": 30.0,
                    "volume_ratio": 2.0,
                    "atr": 1.0,
                    "close": 99.0,
                    "stoch_rsi_k": 70.0,
                    "williams_r": -20.0,
                    "bb_width": 0.05,
                    "market_regime": "trending",
                    "is_closed": False,
                },
            ],
            index=[
                pd.Timestamp("2026-01-01 10:00:00"),
                pd.Timestamp("2026-01-01 10:15:00"),
            ],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="15m")

        self.assertEqual(signal, "COMPRA")

    def test_context_filter_blocks_countertrend_entry_for_1h(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.rsi_period = 14
        bot.timeframe = "1h"
        bot.symbol = "BTC/USDT"
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9

        entry_df = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 102.0,
                    "low": 99.8,
                    "close": 101.8,
                    "rsi": 34.0,
                    "macd": 0.8,
                    "macd_signal": 0.2,
                    "macd_histogram": 0.6,
                    "adx": 32.0,
                    "di_plus": 28.0,
                    "di_minus": 12.0,
                    "volume_ratio": 1.8,
                    "atr": 1.2,
                    "sma_21": 100.9,
                    "stoch_rsi_k": 40.0,
                    "williams_r": -50.0,
                    "bb_width": 0.05,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=[pd.Timestamp("2026-01-01 12:00:00")],
        )
        context_df = pd.DataFrame(
            [
                {
                    "close": 98.0,
                    "rsi": 42.0,
                    "macd": -0.6,
                    "macd_signal": -0.1,
                    "macd_histogram": -0.5,
                    "adx": 31.0,
                    "di_plus": 14.0,
                    "di_minus": 27.0,
                    "sma_21": 99.2,
                    "sma_50": 100.1,
                    "sma_200": 101.4,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=[pd.Timestamp("2026-01-01 12:00:00")],
        )

        signal = TradingBot.check_signal(
            bot,
            entry_df,
            timeframe="1h",
            context_df=context_df,
            context_timeframe="4h",
        )

        self.assertEqual(signal, "NEUTRO")

    def test_context_filter_allows_aligned_entry_for_1h(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.rsi_period = 14
        bot.timeframe = "1h"
        bot.symbol = "BTC/USDT"
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9

        entry_df = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 102.0,
                    "low": 99.8,
                    "close": 101.8,
                    "rsi": 34.0,
                    "macd": 0.8,
                    "macd_signal": 0.2,
                    "macd_histogram": 0.6,
                    "adx": 32.0,
                    "di_plus": 28.0,
                    "di_minus": 12.0,
                    "volume_ratio": 1.8,
                    "atr": 1.2,
                    "sma_21": 100.9,
                    "stoch_rsi_k": 40.0,
                    "williams_r": -50.0,
                    "bb_width": 0.05,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=[pd.Timestamp("2026-01-01 12:00:00")],
        )
        context_df = pd.DataFrame(
            [
                {
                    "close": 104.0,
                    "rsi": 58.0,
                    "macd": 0.9,
                    "macd_signal": 0.4,
                    "macd_histogram": 0.5,
                    "adx": 31.0,
                    "di_plus": 29.0,
                    "di_minus": 13.0,
                    "sma_21": 102.5,
                    "sma_50": 101.2,
                    "sma_200": 99.8,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=[pd.Timestamp("2026-01-01 12:00:00")],
        )

        signal = TradingBot.check_signal(
            bot,
            entry_df,
            timeframe="1h",
            context_df=context_df,
            context_timeframe="4h",
        )

        self.assertEqual(signal, "COMPRA")

    def test_signal_guardrail_blocks_bullish_signal_on_bearish_candle_structure(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 20
        bot.rsi_max = 80
        bot.rsi_period = 14
        bot.timeframe = "15m"
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9

        candle = pd.DataFrame(
            [
                {
                    "open": 101.0,
                    "high": 102.0,
                    "low": 99.8,
                    "close": 100.2,
                    "rsi": 25.0,
                    "macd": 0.8,
                    "macd_signal": 0.2,
                    "macd_histogram": 0.6,
                    "adx": 35.0,
                    "di_plus": 28.0,
                    "di_minus": 12.0,
                    "volume_ratio": 2.0,
                    "atr": 1.0,
                    "sma_21": 99.5,
                    "stoch_rsi_k": 40.0,
                    "williams_r": -50.0,
                    "bb_width": 0.05,
                    "market_regime": "trending",
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="15m")

        self.assertEqual(signal, "NEUTRO")

    def test_signal_guardrail_blocks_doji_like_weak_entry(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 20
        bot.rsi_max = 80
        bot.rsi_period = 14
        bot.timeframe = "1h"
        bot._generate_advanced_signal = lambda row: "COMPRA_FRACA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.78

        candle = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.1,
                    "rsi": 31.0,
                    "macd": 0.4,
                    "macd_signal": 0.1,
                    "macd_histogram": 0.3,
                    "adx": 32.0,
                    "di_plus": 24.0,
                    "di_minus": 18.0,
                    "volume_ratio": 1.8,
                    "atr": 1.6,
                    "sma_21": 99.7,
                    "stoch_rsi_k": 35.0,
                    "williams_r": -60.0,
                    "bb_width": 0.04,
                    "market_regime": "trending",
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="1h")

        self.assertEqual(signal, "NEUTRO")
if __name__ == "__main__":
    unittest.main()
