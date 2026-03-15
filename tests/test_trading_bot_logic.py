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


if __name__ == "__main__":
    unittest.main()
