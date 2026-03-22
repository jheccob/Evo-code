from __future__ import annotations

import unittest
from unittest import mock

import numpy as np
import pandas as pd

from indicators import TechnicalIndicators
from trading_bot import TradingBot


def _build_confirmation_frame(
    closes,
    rsis,
    macds,
    macd_signals,
    macd_histograms,
    adx_values,
    volume_ratios,
    atr_values,
    sma_21_values,
    sma_50_values,
    sma_200_values,
):
    volumes = [float(value) * 1000.0 for value in volume_ratios]
    frame = pd.DataFrame(
        {
            "close": closes,
            "volume": volumes,
            "rsi": rsis,
            "macd": macds,
            "macd_signal": macd_signals,
            "macd_histogram": macd_histograms,
            "adx": adx_values,
            "volume_ratio": volume_ratios,
            "atr": atr_values,
            "sma_21": sma_21_values,
            "sma_50": sma_50_values,
            "sma_200": sma_200_values,
            "market_regime": ["trending"] * len(closes),
            "is_closed": [True] * len(closes),
        },
        index=pd.date_range("2026-01-01 00:00:00", periods=len(closes), freq="1h"),
    )
    frame["open"] = frame["close"].shift(1).fillna(frame["close"] - 0.4)
    frame["high"] = frame[["open", "close"]].max(axis=1) + 0.4
    frame["low"] = frame[["open", "close"]].min(axis=1) - 0.4
    frame["prev_close"] = frame["close"].shift(1)
    frame["prev_rsi"] = frame["rsi"].shift(1)
    frame["prev_macd_histogram"] = frame["macd_histogram"].shift(1)
    return frame


class TradingBotLogicTests(unittest.TestCase):
    @mock.patch("requests.get")
    def test_fetch_public_ohlcv_prefers_futures_endpoint_and_normalizes_symbol(self, mock_get):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            [1704067200000, "100.0", "101.0", "99.0", "100.5", "1234.0"]
        ]
        mock_get.return_value = response

        bot = TradingBot.__new__(TradingBot)
        bot.symbol = "BTC/USDT:USDT"
        bot.timeframe = "1h"

        data = TradingBot._fetch_public_ohlcv(bot, limit=1, symbol="BTC/USDT:USDT", timeframe="1h")

        self.assertEqual(len(data), 1)
        first_url = mock_get.call_args_list[0].args[0]
        self.assertIn("https://fapi.binance.com/fapi/v1/klines", first_url)
        self.assertIn("symbol=BTCUSDT", first_url)

    def test_get_market_data_real_only_falls_back_to_public_rest_when_stream_fails(self):
        bot = TradingBot.__new__(TradingBot)
        bot.symbol = "BTC/USDT"
        bot.timeframe = "1h"
        bot.rsi_period = 14
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.allow_simulated_data = False
        bot._cache_data = {}
        bot.calculate_indicators = lambda df: df

        rest_df = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.5,
                    "close": 100.8,
                    "volume": 1234.0,
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        stream_client = mock.Mock()
        stream_client.get_market_data.side_effect = ConnectionError("stream down")
        bot._get_realtime_stream_client = mock.Mock(return_value=stream_client)
        bot._fetch_public_ohlcv = mock.Mock(return_value=rest_df.copy())

        data = TradingBot.get_market_data(bot, limit=50, symbol="BTC/USDT", timeframe="1h")

        self.assertEqual(len(data), 1)
        self.assertTrue(bool(data.iloc[-1]["is_closed"]))
        bot._fetch_public_ohlcv.assert_called_once()

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
        bot.evaluate_market_regime = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "regime": "trend_bull",
            "legacy_regime": "trending",
            "market_bias": "bullish",
            "regime_score": 7.2,
            "volatility_state": "normal_volatility",
            "trend_state": "trend_bull",
            "parabolic": False,
            "is_tradeable": True,
            "notes": [],
            "reason": "mercado em trend_bull",
        }
        bot._passes_signal_structure_guardrail = lambda row, signal, timeframe, structure_evaluation=None: True
        bot.get_price_structure_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "structure_state": "continuation",
            "price_location": "trend_zone",
            "structure_quality": 7.0,
            "reversal_risk": False,
            "against_market_bias": False,
        }
        bot.get_confirmation_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "confirmation_state": "confirmed",
            "confirmation_score": 7.4,
            "conflicts": [],
        }
        bot.get_entry_quality_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "entry_quality": "strong",
            "rr_estimate": 2.0,
            "late_entry": False,
            "stretched_price": False,
        }
        bot.build_scenario_score = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "scenario_score": 7.4,
            "scenario_grade": "B",
            "score_breakdown": {"context": 6.0, "structure": 7.0, "confirmation": 7.4, "entry": 7.0},
            "notes": [],
        }

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

        self.assertIn(signal, {"COMPRA", "COMPRA_FRACA"})

    def test_check_signal_uses_last_closed_candle_when_stream_has_open_candle(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 20
        bot.rsi_max = 80
        bot.rsi_period = 14
        bot.timeframe = "15m"
        bot._generate_advanced_signal = lambda row: "COMPRA" if row["close"] == 100.0 else "VENDA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9
        bot.evaluate_market_regime = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "regime": "trend_bull",
            "legacy_regime": "trending",
            "market_bias": "bullish",
            "regime_score": 7.2,
            "volatility_state": "normal_volatility",
            "trend_state": "trend_bull",
            "parabolic": False,
            "is_tradeable": True,
            "notes": [],
            "reason": "mercado em trend_bull",
        }
        bot._passes_signal_structure_guardrail = lambda row, signal, timeframe, structure_evaluation=None: True
        bot.get_price_structure_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "structure_state": "continuation",
            "price_location": "trend_zone",
            "structure_quality": 7.0,
            "reversal_risk": False,
            "against_market_bias": False,
        }
        bot.get_confirmation_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "confirmation_state": "confirmed",
            "confirmation_score": 7.4,
            "conflicts": [],
        }
        bot.get_entry_quality_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "entry_quality": "strong",
            "rr_estimate": 2.0,
            "late_entry": False,
            "stretched_price": False,
        }
        bot.build_scenario_score = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "scenario_score": 7.4,
            "scenario_grade": "B",
            "score_breakdown": {"context": 6.0, "structure": 7.0, "confirmation": 7.4, "entry": 7.0},
            "notes": [],
        }

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

        self.assertIn(signal, {"COMPRA", "COMPRA_FRACA"})

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
        bot.get_context_evaluation = lambda *args, **kwargs: {
            "market_bias": "bearish",
            "bias": "bearish",
            "context_strength": 7.1,
            "regime": "trend_bear",
            "is_tradeable": True,
            "reason": "contexto bearish",
        }
        bot._passes_signal_structure_guardrail = lambda row, signal, timeframe, structure_evaluation=None: True
        bot.get_price_structure_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "structure_state": "continuation",
            "price_location": "trend_zone",
            "structure_quality": 7.0,
            "reversal_risk": False,
            "against_market_bias": False,
        }
        bot.get_confirmation_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "confirmation_state": "confirmed",
            "confirmation_score": 7.4,
            "conflicts": [],
        }
        bot.get_entry_quality_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "entry_quality": "strong",
            "rr_estimate": 2.0,
            "late_entry": False,
            "stretched_price": False,
        }
        bot.build_scenario_score = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "scenario_score": 7.4,
            "scenario_grade": "B",
            "score_breakdown": {"context": 6.0, "structure": 7.0, "confirmation": 7.4, "entry": 7.0},
            "notes": [],
        }

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
                    "open": 103.0 - i * 0.55,
                    "high": 103.4 - i * 0.5,
                    "low": 101.7 - i * 0.55,
                    "close": 102.8 - i * 0.55,
                    "rsi": 47.0 - i * 0.6,
                    "macd": -0.35 - i * 0.03,
                    "macd_signal": -0.1 - i * 0.02,
                    "macd_histogram": -0.2 - i * 0.01,
                    "adx": 28.0 + i * 0.4,
                    "di_plus": 16.0 - i * 0.2,
                    "di_minus": 26.0 + i * 0.3,
                    "atr": 1.1 + i * 0.02,
                    "sma_21": 102.6 - i * 0.45,
                    "sma_50": 103.2 - i * 0.35,
                    "sma_200": 104.5 - i * 0.15,
                    "market_regime": "trending",
                    "is_closed": True,
                }
                for i in range(8)
            ],
            index=pd.date_range("2026-01-01 00:00:00", periods=8, freq="4h"),
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
        bot.get_context_evaluation = lambda *args, **kwargs: {
            "market_bias": "bullish",
            "bias": "bullish",
            "context_strength": 7.6,
            "regime": "trend_bull",
            "is_tradeable": True,
            "reason": "contexto bullish",
        }
        bot._passes_signal_structure_guardrail = lambda row, signal, timeframe, structure_evaluation=None: True
        bot.get_price_structure_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "structure_state": "continuation",
            "price_location": "trend_zone",
            "structure_quality": 7.0,
            "reversal_risk": False,
            "against_market_bias": False,
        }
        bot.get_confirmation_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "confirmation_state": "confirmed",
            "confirmation_score": 7.4,
            "conflicts": [],
        }
        bot.get_entry_quality_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "entry_quality": "strong",
            "rr_estimate": 2.0,
            "late_entry": False,
            "stretched_price": False,
        }
        bot.build_scenario_score = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "scenario_score": 7.4,
            "scenario_grade": "B",
            "score_breakdown": {"context": 6.0, "structure": 7.0, "confirmation": 7.4, "entry": 7.0},
            "notes": [],
        }

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
                    "open": 100.0 + i * 0.55,
                    "high": 100.6 + i * 0.55,
                    "low": 99.5 + i * 0.52,
                    "close": 100.3 + i * 0.58,
                    "rsi": 54.0 + i * 0.5,
                    "macd": 0.35 + i * 0.04,
                    "macd_signal": 0.15 + i * 0.03,
                    "macd_histogram": 0.2 + i * 0.02,
                    "adx": 28.0 + i * 0.5,
                    "di_plus": 24.0 + i * 0.4,
                    "di_minus": 14.0 - i * 0.15,
                    "atr": 1.05 + i * 0.02,
                    "sma_21": 99.9 + i * 0.48,
                    "sma_50": 99.1 + i * 0.35,
                    "sma_200": 97.8 + i * 0.14,
                    "market_regime": "trending",
                    "is_closed": True,
                }
                for i in range(8)
            ],
            index=pd.date_range("2026-01-01 00:00:00", periods=8, freq="4h"),
        )

        signal = TradingBot.check_signal(
            bot,
            entry_df,
            timeframe="1h",
            context_df=context_df,
            context_timeframe="4h",
        )

        self.assertEqual(signal, "COMPRA")

    def test_context_evaluation_returns_bullish_trend_low_vol_block(self):
        bot = TradingBot.__new__(TradingBot)

        context_df = pd.DataFrame(
            [
                {
                    "open": 100.0 + i * 0.6,
                    "high": 100.9 + i * 0.6,
                    "low": 99.7 + i * 0.6,
                    "close": 100.5 + i * 0.6,
                    "rsi": 54.0 + i * 0.4,
                    "macd": 0.35 + i * 0.05,
                    "macd_signal": 0.15 + i * 0.03,
                    "macd_histogram": 0.20 + i * 0.02,
                    "adx": 29.0 + i * 0.7,
                    "di_plus": 27.0 + i * 0.5,
                    "di_minus": 14.0 - i * 0.2,
                    "atr": 1.2 + i * 0.01,
                    "sma_21": 99.8 + i * 0.45,
                    "sma_50": 98.8 + i * 0.35,
                    "sma_200": 96.5 + i * 0.12,
                    "market_regime": "trending",
                    "is_closed": True,
                }
                for i in range(8)
            ],
            index=pd.date_range("2026-01-01 00:00:00", periods=8, freq="4h"),
        )

        evaluation = TradingBot.get_context_evaluation(bot, context_df, context_timeframe="4h")

        self.assertEqual(evaluation["market_bias"], "bullish")
        self.assertEqual(evaluation["bias"], "bullish")
        self.assertEqual(evaluation["regime"], "trend_bull")
        self.assertGreaterEqual(evaluation["context_strength"], 6.0)
        self.assertTrue(evaluation["is_tradeable"])

    def test_context_evaluation_returns_neutral_range_high_vol_block(self):
        bot = TradingBot.__new__(TradingBot)

        context_df = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 106.0 if i % 2 == 0 else 104.5,
                    "low": 94.0 if i % 2 == 0 else 95.5,
                    "close": 100.4 if i % 2 == 0 else 99.6,
                    "rsi": 50.0 + (0.3 if i % 2 == 0 else -0.3),
                    "macd": 0.05 if i % 2 == 0 else -0.05,
                    "macd_signal": 0.04 if i % 2 == 0 else -0.04,
                    "macd_histogram": 0.01 if i % 2 == 0 else -0.01,
                    "adx": 17.5,
                    "di_plus": 19.0,
                    "di_minus": 18.0,
                    "atr": 3.0,
                    "sma_21": 100.0,
                    "sma_50": 100.0,
                    "sma_200": 100.0,
                    "market_regime": "volatile",
                    "is_closed": True,
                }
                for i in range(8)
            ],
            index=pd.date_range("2026-01-01 00:00:00", periods=8, freq="4h"),
        )

        evaluation = TradingBot.get_context_evaluation(bot, context_df, context_timeframe="4h")

        self.assertEqual(evaluation["market_bias"], "neutral")
        self.assertEqual(evaluation["regime"], "range")
        self.assertEqual(evaluation["volatility_state"], "high_volatility")
        self.assertLess(evaluation["context_strength"], 5.0)
        self.assertFalse(evaluation["is_tradeable"])

    def test_evaluate_market_regime_classifies_trend_bull(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"
        bot.indicators = TechnicalIndicators()

        closes = np.linspace(100.0, 128.0, 40)
        df = pd.DataFrame(
            {
                "open": closes - 0.4,
                "high": closes + 0.8,
                "low": closes - 0.9,
                "close": closes,
                "volume": np.linspace(1000, 1450, 40),
                "atr": np.linspace(1.1, 1.5, 40),
                "adx": np.linspace(24, 36, 40),
                "di_plus": np.linspace(24, 31, 40),
                "di_minus": np.linspace(16, 10, 40),
                "ema_21": pd.Series(closes).ewm(span=21, adjust=False).mean().to_numpy(),
                "ema_200": pd.Series(closes).ewm(span=200, adjust=False).mean().to_numpy(),
                "is_closed": True,
            },
            index=pd.date_range("2026-01-01 00:00:00", periods=40, freq="1h"),
        )

        evaluation = TradingBot.evaluate_market_regime(bot, df, timeframe="1h", persist=False)

        self.assertEqual(evaluation["regime"], "trend_bull")
        self.assertEqual(evaluation["market_bias"], "bullish")
        self.assertGreaterEqual(evaluation["regime_score"], 6.0)

    def test_evaluate_market_regime_classifies_trend_bear(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"
        bot.indicators = TechnicalIndicators()

        closes = np.linspace(128.0, 100.0, 40)
        df = pd.DataFrame(
            {
                "open": closes + 0.4,
                "high": closes + 0.9,
                "low": closes - 0.8,
                "close": closes,
                "volume": np.linspace(1000, 1450, 40),
                "atr": np.linspace(1.1, 1.5, 40),
                "adx": np.linspace(24, 36, 40),
                "di_plus": np.linspace(14, 9, 40),
                "di_minus": np.linspace(24, 31, 40),
                "ema_21": pd.Series(closes).ewm(span=21, adjust=False).mean().to_numpy(),
                "ema_200": pd.Series(closes).ewm(span=200, adjust=False).mean().to_numpy(),
                "is_closed": True,
            },
            index=pd.date_range("2026-01-01 00:00:00", periods=40, freq="1h"),
        )

        evaluation = TradingBot.evaluate_market_regime(bot, df, timeframe="1h", persist=False)

        self.assertEqual(evaluation["regime"], "trend_bear")
        self.assertEqual(evaluation["market_bias"], "bearish")
        self.assertGreaterEqual(evaluation["regime_score"], 6.0)

    def test_evaluate_market_regime_classifies_range_with_high_volatility_flag(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"
        bot.indicators = TechnicalIndicators()

        closes = np.array([100.0, 101.0, 99.2, 100.8, 99.5] * 8, dtype=float)
        df = pd.DataFrame(
            {
                "open": closes,
                "high": closes + 4.0,
                "low": closes - 4.0,
                "close": closes + np.array([0.1, -0.1, 0.15, -0.12, 0.08] * 8),
                "volume": [1200.0] * 40,
                "atr": [3.4] * 40,
                "adx": [16.5] * 40,
                "di_plus": [18.0] * 40,
                "di_minus": [17.5] * 40,
                "ema_21": pd.Series(closes).ewm(span=21, adjust=False).mean().to_numpy(),
                "ema_200": pd.Series(closes).ewm(span=200, adjust=False).mean().to_numpy(),
                "is_closed": True,
            },
            index=pd.date_range("2026-01-01 00:00:00", periods=40, freq="1h"),
        )

        evaluation = TradingBot.evaluate_market_regime(bot, df, timeframe="1h", persist=False)

        self.assertEqual(evaluation["regime"], "range")
        self.assertEqual(evaluation["volatility_state"], "high_volatility")
        self.assertEqual(evaluation["market_bias"], "neutral")

    def test_price_structure_evaluation_returns_breakout_in_trend_zone(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        structure_df = pd.DataFrame(
            [
                {
                    "open": 100.0 + i * 0.35,
                    "high": 100.8 + i * 0.35,
                    "low": 99.7 + i * 0.35,
                    "close": 100.4 + i * 0.35,
                    "atr": 1.0,
                    "sma_21": 99.5 + i * 0.3,
                    "sma_50": 98.8 + i * 0.24,
                    "volume_ratio": 1.2,
                    "market_regime": "trending",
                    "is_closed": True,
                }
                for i in range(7)
            ]
            + [
                {
                    "open": 102.6,
                    "high": 105.2,
                    "low": 102.4,
                    "close": 105.0,
                    "atr": 1.1,
                    "sma_21": 101.9,
                    "sma_50": 100.8,
                    "volume_ratio": 2.1,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=pd.date_range("2026-01-01 00:00:00", periods=8, freq="1h"),
        )

        evaluation = TradingBot.get_price_structure_evaluation(bot, structure_df, timeframe="1h")

        self.assertEqual(evaluation["structure_state"], "breakout")
        self.assertEqual(evaluation["price_location"], "resistance")
        self.assertGreaterEqual(evaluation["structure_quality"], 6.5)
        self.assertTrue(evaluation["is_tradeable"])

    def test_analyze_price_structure_returns_standardized_output(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        structure_df = pd.DataFrame(
            [
                {
                    "open": 100.0 + i * 0.35,
                    "high": 100.8 + i * 0.35,
                    "low": 99.7 + i * 0.35,
                    "close": 100.4 + i * 0.35,
                    "atr": 1.0,
                    "sma_21": 99.5 + i * 0.3,
                    "sma_50": 98.8 + i * 0.24,
                    "volume_ratio": 1.2,
                    "market_regime": "trending",
                    "is_closed": True,
                }
                for i in range(7)
            ]
            + [
                {
                    "open": 102.6,
                    "high": 105.2,
                    "low": 102.4,
                    "close": 105.0,
                    "atr": 1.1,
                    "sma_21": 101.9,
                    "sma_50": 100.8,
                    "volume_ratio": 2.1,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=pd.date_range("2026-01-01 00:00:00", periods=8, freq="1h"),
        )

        evaluation = TradingBot.analyze_price_structure(bot, structure_df, market_bias="bullish", timeframe="1h")

        self.assertTrue(evaluation["breakout"])
        self.assertFalse(evaluation["reversal_risk"])
        self.assertIsInstance(evaluation["notes"], list)
        self.assertIn("distance_from_ema_pct", evaluation)
        self.assertIsNotNone(evaluation["distance_from_ema_pct"])

    def test_price_structure_evaluation_returns_pullback_in_trend_zone(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        structure_df = pd.DataFrame(
            [
                {
                    "open": 100.0 + i * 0.5,
                    "high": 100.8 + i * 0.5,
                    "low": 99.6 + i * 0.5,
                    "close": 100.6 + i * 0.5,
                    "atr": 1.1,
                    "sma_21": 99.7 + i * 0.42,
                    "sma_50": 98.9 + i * 0.32,
                    "volume_ratio": 1.1,
                    "market_regime": "trending",
                    "is_closed": True,
                }
                for i in range(7)
            ]
            + [
                {
                    "open": 103.8,
                    "high": 104.1,
                    "low": 103.0,
                    "close": 103.9,
                    "atr": 1.0,
                    "sma_21": 103.2,
                    "sma_50": 101.9,
                    "volume_ratio": 1.3,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=pd.date_range("2026-01-01 00:00:00", periods=8, freq="1h"),
        )

        evaluation = TradingBot.get_price_structure_evaluation(bot, structure_df, timeframe="1h")

        self.assertEqual(evaluation["structure_state"], "pullback")
        self.assertEqual(evaluation["price_location"], "trend_zone")
        self.assertGreaterEqual(evaluation["structure_quality"], 5.5)
        self.assertTrue(evaluation["is_tradeable"])

    def test_price_structure_evaluation_classifies_moderate_pullback_after_relief_sequence(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        structure_df = pd.DataFrame(
            [
                {
                    "open": 100.0 + i * 0.55,
                    "high": 100.9 + i * 0.55,
                    "low": 99.7 + i * 0.55,
                    "close": 100.7 + i * 0.55,
                    "atr": 1.1,
                    "sma_21": 99.8 + i * 0.45,
                    "sma_50": 99.0 + i * 0.34,
                    "volume_ratio": 1.1,
                    "market_regime": "trending",
                    "is_closed": True,
                }
                for i in range(5)
            ]
            + [
                {
                    "open": 103.6,
                    "high": 103.7,
                    "low": 102.9,
                    "close": 103.2,
                    "atr": 1.0,
                    "sma_21": 103.1,
                    "sma_50": 101.9,
                    "volume_ratio": 0.98,
                    "market_regime": "trending",
                    "is_closed": True,
                },
                {
                    "open": 103.2,
                    "high": 103.35,
                    "low": 102.7,
                    "close": 102.95,
                    "atr": 1.0,
                    "sma_21": 103.05,
                    "sma_50": 102.0,
                    "volume_ratio": 0.95,
                    "market_regime": "trending",
                    "is_closed": True,
                },
                {
                    "open": 102.98,
                    "high": 103.45,
                    "low": 102.72,
                    "close": 103.18,
                    "atr": 1.0,
                    "sma_21": 103.0,
                    "sma_50": 102.05,
                    "volume_ratio": 1.02,
                    "market_regime": "trending",
                    "is_closed": True,
                },
            ],
            index=pd.date_range("2026-01-01 00:00:00", periods=8, freq="1h"),
        )

        evaluation = TradingBot.get_price_structure_evaluation(bot, structure_df, timeframe="1h")

        self.assertEqual(evaluation["structure_state"], "pullback")
        self.assertEqual(evaluation["price_location"], "trend_zone")

    def test_analyze_price_structure_ignores_open_breakout_candle(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        structure_df = pd.DataFrame(
            [
                {
                    "open": 100.0 + i * 0.2,
                    "high": 100.6 + i * 0.2,
                    "low": 99.7 + i * 0.2,
                    "close": 100.3 + i * 0.2,
                    "atr": 1.0,
                    "sma_21": 99.7 + i * 0.18,
                    "sma_50": 99.1 + i * 0.14,
                    "volume_ratio": 1.1,
                    "market_regime": "trending",
                    "is_closed": True,
                }
                for i in range(7)
            ]
            + [
                {
                    "open": 101.7,
                    "high": 102.0,
                    "low": 101.4,
                    "close": 101.8,
                    "atr": 1.0,
                    "sma_21": 101.1,
                    "sma_50": 100.2,
                    "volume_ratio": 1.2,
                    "market_regime": "trending",
                    "is_closed": True,
                },
                {
                    "open": 101.8,
                    "high": 106.0,
                    "low": 101.7,
                    "close": 105.8,
                    "atr": 1.2,
                    "sma_21": 101.4,
                    "sma_50": 100.4,
                    "volume_ratio": 2.5,
                    "market_regime": "trending",
                    "is_closed": False,
                },
            ],
            index=pd.date_range("2026-01-01 00:00:00", periods=9, freq="1h"),
        )

        evaluation = TradingBot.analyze_price_structure(bot, structure_df, market_bias="bullish", timeframe="1h")

        self.assertNotEqual(evaluation["structure_state"], "breakout")
        self.assertEqual(evaluation["timestamp"], pd.Timestamp("2026-01-01 07:00:00").isoformat())

    def test_check_signal_blocks_actionable_signal_when_structure_is_weak(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.rsi_period = 14
        bot.timeframe = "1h"
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9
        bot._passes_signal_structure_guardrail = lambda row, signal, timeframe, structure_evaluation=None: True

        data = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.1 if i % 2 == 0 else 99.9,
                    "rsi": 38.0,
                    "macd": 0.3,
                    "macd_signal": 0.1,
                    "macd_histogram": 0.2,
                    "adx": 19.0,
                    "di_plus": 20.0,
                    "di_minus": 19.0,
                    "volume_ratio": 0.85,
                    "atr": 1.4,
                    "sma_21": 100.0,
                    "sma_50": 100.0,
                    "stoch_rsi_k": 45.0,
                    "williams_r": -48.0,
                    "bb_width": 0.04,
                    "market_regime": "ranging",
                    "is_closed": True,
                }
                for i in range(8)
            ],
            index=pd.date_range("2026-01-01 00:00:00", periods=8, freq="1h"),
        )

        signal = TradingBot.check_signal(bot, data, timeframe="1h")

        self.assertEqual(signal, "NEUTRO")

    def test_check_signal_allows_actionable_signal_on_breakout_structure(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.rsi_period = 14
        bot.timeframe = "1h"
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9
        bot._passes_signal_structure_guardrail = lambda row, signal, timeframe, structure_evaluation=None: True

        data = pd.DataFrame(
            [
                {
                    "open": 100.0 + i * 0.35,
                    "high": 100.8 + i * 0.35,
                    "low": 99.7 + i * 0.35,
                    "close": 100.4 + i * 0.35,
                    "rsi": 36.0,
                    "macd": 0.4,
                    "macd_signal": 0.15,
                    "macd_histogram": 0.25,
                    "adx": 30.0,
                    "di_plus": 27.0,
                    "di_minus": 14.0,
                    "volume_ratio": 1.4,
                    "atr": 1.0,
                    "sma_21": 99.5 + i * 0.3,
                    "sma_50": 98.8 + i * 0.24,
                    "stoch_rsi_k": 42.0,
                    "williams_r": -52.0,
                    "bb_width": 0.06,
                    "market_regime": "trending",
                    "is_closed": True,
                }
                for i in range(7)
            ]
            + [
                {
                    "open": 103.0,
                    "high": 103.7,
                    "low": 102.9,
                    "close": 103.55,
                    "rsi": 39.0,
                    "macd": 0.9,
                    "macd_signal": 0.35,
                    "macd_histogram": 0.55,
                    "adx": 34.0,
                    "di_plus": 30.0,
                    "di_minus": 12.0,
                    "volume_ratio": 2.1,
                    "atr": 1.1,
                    "sma_21": 101.9,
                    "sma_50": 100.8,
                    "stoch_rsi_k": 48.0,
                    "williams_r": -49.0,
                    "bb_width": 0.08,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=pd.date_range("2026-01-01 00:00:00", periods=8, freq="1h"),
        )

        signal = TradingBot.check_signal(bot, data, timeframe="1h")

        self.assertIn(signal, {"COMPRA", "COMPRA_FRACA"})

    def test_check_signal_blocks_reversal_risk_against_higher_timeframe_bias(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.rsi_period = 14
        bot.timeframe = "1h"
        bot.symbol = "BTC/USDT"
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9
        bot._passes_signal_structure_guardrail = lambda row, signal, timeframe, structure_evaluation=None: True
        bot.get_price_structure_evaluation = lambda df, timeframe=None, market_bias=None: {
            "has_minimum_history": True,
            "structure_state": "reversal_risk",
            "price_location": "resistance",
            "structure_quality": 6.4,
            "reversal_risk": True,
            "against_market_bias": True,
            "distance_from_ema_pct": 2.9,
            "notes": ["estrutura contra vies bullish"],
            "reason": "estrutura contra vies bullish",
        }

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
                    "sma_50": 100.1,
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
                    "open": 100.0 + i * 0.48,
                    "high": 100.7 + i * 0.5,
                    "low": 99.6 + i * 0.45,
                    "close": 100.4 + i * 0.5,
                    "rsi": 54.0 + i * 0.4,
                    "macd": 0.28 + i * 0.03,
                    "macd_signal": 0.11 + i * 0.02,
                    "macd_histogram": 0.17 + i * 0.015,
                    "adx": 28.0 + i * 0.45,
                    "di_plus": 24.0 + i * 0.35,
                    "di_minus": 15.0 - i * 0.15,
                    "atr": 1.0 + i * 0.02,
                    "sma_21": 99.8 + i * 0.42,
                    "sma_50": 99.0 + i * 0.3,
                    "sma_200": 97.8 + i * 0.12,
                    "market_regime": "trending",
                    "is_closed": True,
                }
                for i in range(8)
            ],
            index=pd.date_range("2026-01-01 00:00:00", periods=8, freq="4h"),
        )

        signal = TradingBot.check_signal(
            bot,
            entry_df,
            timeframe="1h",
            context_df=context_df,
            context_timeframe="4h",
        )

        self.assertEqual(signal, "NEUTRO")

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

    def test_signal_guardrail_accepts_imperfect_bullish_1h_candle(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        row = pd.Series(
            {
                "open": 100.0,
                "high": 101.0,
                "low": 99.7,
                "close": 100.38,
                "atr": 1.6,
                "sma_21": 100.32,
                "macd_histogram": 0.08,
                "di_plus": 21.0,
                "di_minus": 19.0,
            }
        )

        allowed = TradingBot._passes_signal_structure_guardrail(bot, row, "COMPRA", "1h")

        self.assertTrue(allowed)

    def test_signal_guardrail_accepts_soft_bullish_1h_candle_when_structure_is_supportive(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        row = pd.Series(
            {
                "open": 100.25,
                "high": 100.82,
                "low": 99.60,
                "close": 100.05,
                "atr": 1.8,
                "sma_21": 99.96,
            }
        )

        allowed = TradingBot._passes_signal_structure_guardrail(
            bot,
            row,
            "COMPRA",
            "1h",
            structure_evaluation={
                "structure_state": "continuation",
                "structure_quality": 5.8,
                "price_location": "trend_zone",
            },
        )

        self.assertTrue(allowed)

    def test_price_structure_evaluation_prefers_continuation_over_weak_structure_on_trend_progression(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        structure_df = pd.DataFrame(
            [
                {
                    "open": 100.0 + i * 0.28,
                    "high": 100.7 + i * 0.28,
                    "low": 99.7 + i * 0.28,
                    "close": 100.35 + i * 0.28,
                    "atr": 1.0,
                    "sma_21": 99.6 + i * 0.22,
                    "sma_50": 99.0 + i * 0.18,
                    "volume_ratio": 1.05,
                    "market_regime": "trending",
                    "is_closed": True,
                }
                for i in range(7)
            ]
            + [
                {
                    "open": 102.15,
                    "high": 102.85,
                    "low": 101.95,
                    "close": 102.48,
                    "atr": 1.05,
                    "sma_21": 101.92,
                    "sma_50": 100.82,
                    "volume_ratio": 1.02,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=pd.date_range("2026-01-01 00:00:00", periods=8, freq="1h"),
        )

        evaluation = TradingBot.get_price_structure_evaluation(bot, structure_df, timeframe="1h")

        self.assertIn(evaluation["structure_state"], {"continuation", "continuation_weak_but_valid", "pullback"})
        self.assertGreaterEqual(evaluation["structure_quality"], 4.5)

    def test_price_structure_evaluation_returns_continuation_weak_but_valid_when_trend_is_preserved(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        base_rows = [
            {
                "open": 100.0 + i * 0.35,
                "high": 100.8 + i * 0.35,
                "low": 99.7 + i * 0.35,
                "close": 100.45 + i * 0.35,
                "atr": 1.0,
                "sma_21": 99.6 + i * 0.25,
                "sma_50": 98.9 + i * 0.20,
                "volume_ratio": 1.05,
                "market_regime": "trending",
                "is_closed": True,
            }
            for i in range(7)
        ]
        base_rows.append(
            {
                "open": 102.50,
                "high": 102.86,
                "low": 102.45,
                "close": 102.58,
                "atr": 1.05,
                "sma_21": 101.92,
                "sma_50": 100.82,
                "volume_ratio": 1.02,
                "market_regime": "trending",
                "is_closed": True,
            }
        )
        structure_df = pd.DataFrame(
            base_rows,
            index=pd.date_range("2026-01-01 00:00:00", periods=8, freq="1h"),
        )

        evaluation = TradingBot.get_price_structure_evaluation(bot, structure_df, timeframe="1h")

        self.assertEqual(evaluation["structure_state"], "continuation_weak_but_valid")
        self.assertTrue(evaluation["is_tradeable"])
        self.assertGreaterEqual(evaluation["structure_quality"], 4.8)

    def test_check_signal_1h_allows_moderate_confidence_when_pipeline_is_strong(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.rsi_period = 14
        bot.timeframe = "1h"
        bot._last_context_evaluation = None
        bot._last_price_structure_evaluation = None
        bot._last_confirmation_evaluation = None
        bot._last_entry_quality_evaluation = None
        bot._last_scenario_evaluation = None
        bot._last_trade_decision = None
        bot._last_hard_block_evaluation = None
        bot._last_candidate_signal = "NEUTRO"
        bot._last_signal_pipeline = None
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 61.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.82
        bot._passes_signal_structure_guardrail = lambda row, signal, timeframe, structure_evaluation=None: True
        bot.get_price_structure_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "structure_state": "continuation",
            "price_location": "trend_zone",
            "structure_quality": 6.2,
            "reversal_risk": False,
            "against_market_bias": False,
            "notes": ["continuidade valida"],
        }
        bot.get_confirmation_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "confirmation_state": "confirmed",
            "confirmation_score": 7.0,
            "hypothesis_side": "bullish",
            "conflicts": [],
        }
        bot.get_entry_quality_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "entry_quality": "acceptable",
            "entry_score": 5.8,
            "rr_estimate": 1.4,
            "late_entry": False,
            "stretched_price": False,
        }
        bot.build_scenario_score = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "scenario_score": 6.6,
            "scenario_grade": "B",
        }

        candle = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.8,
                    "close": 100.7,
                    "rsi": 38.0,
                    "macd": 0.4,
                    "macd_signal": 0.2,
                    "macd_histogram": 0.2,
                    "adx": 24.0,
                    "di_plus": 22.0,
                    "di_minus": 18.0,
                    "volume_ratio": 1.2,
                    "atr": 1.1,
                    "stoch_rsi_k": 42.0,
                    "williams_r": -48.0,
                    "bb_width": 0.04,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="1h", require_volume=False)

        self.assertIn(signal, {"COMPRA", "COMPRA_FRACA"})

    def test_confirmation_evaluation_returns_confirmed_for_aligned_bullish_setup(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        data = _build_confirmation_frame(
            closes=[100.0, 100.6, 101.2, 101.9, 102.6, 103.3],
            rsis=[49.0, 52.0, 55.0, 58.0, 60.0, 63.0],
            macds=[0.20, 0.24, 0.31, 0.42, 0.55, 0.68],
            macd_signals=[0.10, 0.13, 0.18, 0.26, 0.34, 0.42],
            macd_histograms=[0.10, 0.11, 0.13, 0.16, 0.21, 0.26],
            adx_values=[24.0, 26.0, 28.0, 30.0, 32.0, 34.0],
            volume_ratios=[1.20, 1.25, 1.35, 1.45, 1.70, 1.95],
            atr_values=[1.00, 1.02, 1.01, 1.03, 1.02, 1.04],
            sma_21_values=[99.4, 99.8, 100.2, 100.7, 101.1, 101.6],
            sma_50_values=[98.7, 98.9, 99.2, 99.6, 100.0, 100.4],
            sma_200_values=[97.0, 97.1, 97.2, 97.3, 97.4, 97.5],
        )

        evaluation = TradingBot.get_confirmation_evaluation(
            bot,
            data,
            signal_hypothesis="COMPRA",
            timeframe="1h",
        )

        self.assertEqual(evaluation["confirmation_state"], "confirmed")
        self.assertGreaterEqual(evaluation["confirmation_score"], 7.0)
        self.assertEqual(evaluation["hypothesis_side"], "bullish")
        self.assertLessEqual(len(evaluation["conflicts"]), 1)

    def test_analyze_confirmation_returns_confirmed_for_aligned_bearish_setup(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        data = _build_confirmation_frame(
            closes=[105.0, 104.6, 104.1, 103.5, 103.0, 102.4],
            rsis=[49.0, 47.0, 45.0, 42.0, 40.0, 38.0],
            macds=[-0.10, -0.16, -0.24, -0.33, -0.42, -0.54],
            macd_signals=[-0.02, -0.06, -0.11, -0.18, -0.27, -0.36],
            macd_histograms=[-0.08, -0.10, -0.13, -0.15, -0.15, -0.18],
            adx_values=[24.0, 26.0, 28.0, 30.0, 31.0, 33.0],
            volume_ratios=[1.05, 1.10, 1.18, 1.24, 1.30, 1.42],
            atr_values=[1.10, 1.09, 1.08, 1.10, 1.12, 1.15],
            sma_21_values=[104.8, 104.4, 104.0, 103.6, 103.1, 102.7],
            sma_50_values=[105.4, 105.0, 104.6, 104.2, 103.8, 103.4],
            sma_200_values=[106.5, 106.4, 106.3, 106.2, 106.1, 106.0],
        )

        evaluation = TradingBot.analyze_confirmation(bot, data, market_bias="bearish", structure_state="continuation")

        self.assertEqual(evaluation["confirmation_state"], "confirmed")
        self.assertEqual(evaluation["rsi_state"], "favorable")
        self.assertEqual(evaluation["macd_state"], "aligned")
        self.assertIn(evaluation["volume_state"], {"above_average", "average"})
        self.assertEqual(evaluation["atr_state"], "healthy")

    def test_analyze_confirmation_returns_mixed_when_context_and_indicators_conflict(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        data = _build_confirmation_frame(
            closes=[100.0, 100.4, 100.8, 101.0, 100.9, 101.2],
            rsis=[52.0, 55.0, 57.0, 58.0, 56.0, 54.0],
            macds=[0.08, 0.12, 0.18, 0.20, 0.16, 0.08],
            macd_signals=[0.05, 0.08, 0.11, 0.15, 0.16, 0.12],
            macd_histograms=[0.03, 0.04, 0.07, 0.05, 0.00, -0.04],
            adx_values=[20.0, 21.0, 22.0, 22.0, 21.0, 20.0],
            volume_ratios=[1.00, 1.04, 1.10, 1.08, 0.98, 0.97],
            atr_values=[0.95, 0.96, 0.98, 0.99, 0.96, 0.94],
            sma_21_values=[99.9, 100.2, 100.5, 100.7, 100.8, 100.9],
            sma_50_values=[99.4, 99.7, 100.0, 100.2, 100.4, 100.6],
            sma_200_values=[98.6, 98.7, 98.8, 98.9, 99.0, 99.1],
        )

        evaluation = TradingBot.analyze_confirmation(bot, data, market_bias="bullish", structure_state="pullback")

        self.assertEqual(evaluation["confirmation_state"], "mixed")
        self.assertGreaterEqual(evaluation["confirmation_score"], 4.0)
        self.assertLess(evaluation["confirmation_score"], 7.0)
        self.assertGreaterEqual(len(evaluation["conflicts"]), 1)

    def test_analyze_confirmation_returns_weak_when_atr_and_volume_are_too_weak(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        data = _build_confirmation_frame(
            closes=[100.0, 100.2, 100.4, 100.5, 100.55, 100.56],
            rsis=[51.0, 52.0, 53.0, 54.0, 54.0, 53.0],
            macds=[0.04, 0.05, 0.06, 0.06, 0.05, 0.04],
            macd_signals=[0.03, 0.04, 0.05, 0.05, 0.05, 0.05],
            macd_histograms=[0.01, 0.01, 0.01, 0.01, 0.00, -0.01],
            adx_values=[18.0, 18.0, 18.0, 17.5, 17.0, 16.5],
            volume_ratios=[1.00, 0.98, 0.96, 0.92, 0.85, 0.70],
            atr_values=[1.10, 1.08, 1.05, 1.00, 0.70, 0.18],
            sma_21_values=[99.8, 99.9, 100.0, 100.1, 100.2, 100.3],
            sma_50_values=[99.2, 99.3, 99.4, 99.5, 99.6, 99.7],
            sma_200_values=[98.0, 98.1, 98.2, 98.3, 98.4, 98.5],
        )

        evaluation = TradingBot.analyze_confirmation(bot, data, market_bias="bullish", structure_state="continuation")

        self.assertEqual(evaluation["confirmation_state"], "weak")
        self.assertEqual(evaluation["volume_state"], "weak")
        self.assertEqual(evaluation["atr_state"], "compressed")
        self.assertIn("Volume fraco para confirmar o movimento", evaluation["conflicts"])
        self.assertIn("ATR fraco para confirmar o movimento", evaluation["conflicts"])

    def test_confirmation_evaluation_returns_weak_when_indicators_conflict(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        data = _build_confirmation_frame(
            closes=[101.0, 100.8, 100.4, 100.1, 99.8, 99.2],
            rsis=[48.0, 45.0, 42.0, 39.0, 37.0, 35.0],
            macds=[0.12, 0.05, -0.02, -0.12, -0.22, -0.35],
            macd_signals=[0.10, 0.09, 0.06, 0.02, -0.05, 0.01],
            macd_histograms=[0.02, -0.04, -0.08, -0.14, -0.17, -0.36],
            adx_values=[22.0, 21.0, 20.0, 18.0, 17.0, 15.0],
            volume_ratios=[1.05, 0.98, 0.92, 0.88, 0.84, 0.78],
            atr_values=[1.10, 1.06, 1.02, 0.96, 0.82, 0.24],
            sma_21_values=[100.6, 100.5, 100.4, 100.3, 100.2, 100.1],
            sma_50_values=[99.8, 99.9, 100.0, 100.0, 100.1, 100.2],
            sma_200_values=[98.8, 98.9, 99.0, 99.1, 99.2, 99.3],
        )

        evaluation = TradingBot.get_confirmation_evaluation(
            bot,
            data,
            signal_hypothesis="COMPRA",
            timeframe="1h",
        )

        self.assertEqual(evaluation["confirmation_state"], "weak")
        self.assertLess(evaluation["confirmation_score"], 4.0)
        self.assertGreaterEqual(len(evaluation["conflicts"]), 3)
        self.assertIn("MACD conflita com o vies bullish", evaluation["conflicts"])

    def test_check_signal_downgrades_to_weak_when_confirmation_is_mixed(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.rsi_period = 14
        bot.timeframe = "1h"
        bot._last_context_evaluation = None
        bot._last_confirmation_evaluation = None
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9
        bot._passes_signal_structure_guardrail = lambda row, signal, timeframe, structure_evaluation=None: True
        bot.get_price_structure_evaluation = lambda df, timeframe=None: {
            "has_minimum_history": True,
            "structure_state": "breakout",
            "price_location": "trend_zone",
            "structure_quality": 7.0,
        }
        bot.get_confirmation_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "confirmation_state": "mixed",
            "confirmation_score": 5.6,
            "conflicts": ["Volume apenas moderado"],
        }

        candle = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 101.5,
                    "low": 99.8,
                    "close": 101.2,
                    "rsi": 38.0,
                    "macd": 0.7,
                    "macd_signal": 0.2,
                    "macd_histogram": 0.5,
                    "adx": 31.0,
                    "volume_ratio": 1.6,
                    "atr": 1.1,
                    "stoch_rsi_k": 45.0,
                    "williams_r": -50.0,
                    "bb_width": 0.06,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="1h")

        self.assertEqual(signal, "COMPRA_FRACA")

    def test_check_signal_blocks_actionable_signal_when_confirmation_is_weak(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.rsi_period = 14
        bot.timeframe = "1h"
        bot._last_context_evaluation = None
        bot._last_confirmation_evaluation = None
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9
        bot._passes_signal_structure_guardrail = lambda row, signal, timeframe, structure_evaluation=None: True
        bot.get_price_structure_evaluation = lambda df, timeframe=None: {
            "has_minimum_history": True,
            "structure_state": "breakout",
            "price_location": "trend_zone",
            "structure_quality": 7.0,
        }
        bot.get_confirmation_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "confirmation_state": "weak",
            "confirmation_score": 2.8,
            "conflicts": ["MACD conflita com a hipotese"],
        }

        candle = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 101.5,
                    "low": 99.8,
                    "close": 101.2,
                    "rsi": 38.0,
                    "macd": 0.7,
                    "macd_signal": 0.2,
                    "macd_histogram": 0.5,
                    "adx": 31.0,
                    "volume_ratio": 1.6,
                    "atr": 1.1,
                    "stoch_rsi_k": 45.0,
                    "williams_r": -50.0,
                    "bb_width": 0.06,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="1h")

        self.assertEqual(signal, "NEUTRO")

    def test_entry_quality_evaluation_returns_strong_for_pullback_with_healthy_rr(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        data = _build_confirmation_frame(
            closes=[100.0, 100.8, 101.5, 102.1, 102.6, 102.3],
            rsis=[50.0, 54.0, 57.0, 59.0, 61.0, 58.0],
            macds=[0.18, 0.26, 0.34, 0.42, 0.49, 0.46],
            macd_signals=[0.10, 0.14, 0.20, 0.28, 0.34, 0.37],
            macd_histograms=[0.08, 0.12, 0.14, 0.14, 0.15, 0.09],
            adx_values=[24.0, 26.0, 28.0, 30.0, 31.0, 29.0],
            volume_ratios=[1.10, 1.18, 1.24, 1.32, 1.28, 1.22],
            atr_values=[1.00, 1.02, 1.03, 1.05, 1.04, 1.02],
            sma_21_values=[99.4, 99.9, 100.5, 101.1, 101.8, 101.9],
            sma_50_values=[98.7, 99.0, 99.4, 99.9, 100.3, 100.7],
            sma_200_values=[97.0, 97.1, 97.2, 97.3, 97.4, 97.5],
        )
        data.iloc[-1, data.columns.get_loc("open")] = 101.95
        data.iloc[-1, data.columns.get_loc("high")] = 102.55
        data.iloc[-1, data.columns.get_loc("low")] = 101.70

        structure_evaluation = {
            "has_minimum_history": True,
            "structure_state": "pullback",
            "price_location": "trend_zone",
            "structure_quality": 7.2,
            "distance_from_sma21_atr": 0.39,
            "recent_high": 102.9,
            "recent_low": 100.4,
        }

        evaluation = TradingBot.get_entry_quality_evaluation(
            bot,
            data,
            signal_hypothesis="COMPRA",
            timeframe="1h",
            regime_evaluation={
                "regime": "trend_bull",
                "market_bias": "bullish",
                "regime_score": 7.8,
                "volatility_state": "normal_volatility",
                "parabolic": False,
            },
            structure_evaluation=structure_evaluation,
            stop_loss_pct=1.5,
            take_profit_pct=4.0,
        )

        self.assertEqual(evaluation["entry_quality"], "strong")
        self.assertEqual(evaluation["setup_type"], "pullback_trend")
        self.assertAlmostEqual(evaluation["rr_estimate"], 2.67, places=2)
        self.assertGreaterEqual(evaluation["entry_score"], 7.0)
        self.assertFalse(evaluation["late_entry"])
        self.assertFalse(evaluation["stretched_price"])

    def test_validate_entry_quality_returns_acceptable_when_rr_is_only_marginal(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        data = _build_confirmation_frame(
            closes=[100.0, 100.6, 101.0, 101.4, 101.8, 101.9],
            rsis=[48.0, 50.0, 53.0, 55.0, 56.0, 55.0],
            macds=[0.10, 0.14, 0.19, 0.23, 0.24, 0.20],
            macd_signals=[0.05, 0.08, 0.12, 0.16, 0.18, 0.18],
            macd_histograms=[0.05, 0.06, 0.07, 0.07, 0.06, 0.02],
            adx_values=[22.0, 24.0, 26.0, 27.0, 27.0, 26.0],
            volume_ratios=[1.02, 1.06, 1.08, 1.10, 1.04, 1.00],
            atr_values=[0.90, 0.92, 0.94, 0.95, 0.96, 0.97],
            sma_21_values=[99.8, 100.1, 100.4, 100.8, 101.1, 101.3],
            sma_50_values=[99.2, 99.4, 99.7, 100.0, 100.3, 100.6],
            sma_200_values=[98.0, 98.1, 98.2, 98.3, 98.4, 98.5],
        )
        data.iloc[-1, data.columns.get_loc("open")] = 101.55
        data.iloc[-1, data.columns.get_loc("high")] = 102.10
        data.iloc[-1, data.columns.get_loc("low")] = 101.42

        evaluation = TradingBot.validate_entry_quality(bot, data, market_bias="bullish", structure_state="continuation")

        self.assertEqual(evaluation["entry_quality"], "acceptable")
        self.assertGreaterEqual(evaluation["rr_estimate"], 1.1)
        self.assertLess(evaluation["rr_estimate"], 1.8)
        self.assertGreaterEqual(evaluation["entry_score"], 5.0)

    def test_validate_entry_quality_returns_bad_when_risk_reward_is_weak(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        data = _build_confirmation_frame(
            closes=[100.0, 100.5, 100.9, 101.0, 101.05, 101.08],
            rsis=[50.0, 52.0, 54.0, 55.0, 55.0, 54.0],
            macds=[0.09, 0.12, 0.16, 0.17, 0.16, 0.14],
            macd_signals=[0.04, 0.07, 0.10, 0.12, 0.13, 0.13],
            macd_histograms=[0.05, 0.05, 0.06, 0.05, 0.03, 0.01],
            adx_values=[20.0, 22.0, 23.0, 23.0, 22.0, 21.0],
            volume_ratios=[1.00, 1.02, 1.05, 1.03, 0.98, 0.95],
            atr_values=[1.10, 1.12, 1.14, 1.15, 1.14, 1.13],
            sma_21_values=[99.7, 99.9, 100.2, 100.5, 100.7, 100.8],
            sma_50_values=[99.1, 99.3, 99.5, 99.7, 99.9, 100.0],
            sma_200_values=[98.0, 98.1, 98.2, 98.3, 98.4, 98.5],
        )
        data.iloc[-1, data.columns.get_loc("open")] = 100.95
        data.iloc[-1, data.columns.get_loc("high")] = 101.20
        data.iloc[-1, data.columns.get_loc("low")] = 99.95

        evaluation = TradingBot.validate_entry_quality(bot, data, market_bias="bullish", structure_state="continuation")

        self.assertEqual(evaluation["entry_quality"], "bad")
        self.assertEqual(evaluation["setup_type"], "continuation_breakout")
        self.assertEqual(evaluation["candle_quality"], "bad")
        self.assertTrue(
            any(
                token in evaluation["reason"]
                for token in (
                    "continuacao sem candle minimamente aceitavel",
                    "candle atual oferece baixa qualidade",
                )
            )
        )

    def test_validate_entry_quality_accepts_imperfect_but_valid_entry(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        data = _build_confirmation_frame(
            closes=[100.0, 100.4, 100.9, 101.2, 101.4, 101.55],
            rsis=[48.0, 50.0, 52.0, 54.0, 55.0, 56.0],
            macds=[0.08, 0.10, 0.14, 0.18, 0.20, 0.22],
            macd_signals=[0.04, 0.06, 0.09, 0.12, 0.15, 0.17],
            macd_histograms=[0.04, 0.04, 0.05, 0.06, 0.05, 0.05],
            adx_values=[20.0, 21.0, 23.0, 24.0, 24.0, 25.0],
            volume_ratios=[0.92, 0.96, 1.00, 1.04, 0.98, 0.94],
            atr_values=[0.95, 0.97, 0.98, 1.00, 1.01, 0.92],
            sma_21_values=[99.7, 99.9, 100.2, 100.5, 100.8, 101.0],
            sma_50_values=[99.1, 99.2, 99.4, 99.6, 99.8, 100.0],
            sma_200_values=[98.0, 98.1, 98.2, 98.3, 98.4, 98.5],
        )
        data.iloc[-1, data.columns.get_loc("open")] = 101.22
        data.iloc[-1, data.columns.get_loc("high")] = 101.78
        data.iloc[-1, data.columns.get_loc("low")] = 101.02

        evaluation = TradingBot.validate_entry_quality(bot, data, market_bias="bullish", structure_state="continuation")

        self.assertEqual(evaluation["entry_quality"], "acceptable")
        self.assertGreaterEqual(evaluation["entry_score"], 5.0)
        self.assertTrue(any("imperfeito" in note or "aceitavel" in note for note in evaluation["notes"]))

    def test_validate_entry_quality_blocks_dead_range_with_low_volatility(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        data = _build_confirmation_frame(
            closes=[100.0, 100.02, 100.01, 100.03, 100.02, 100.025],
            rsis=[49.0, 49.5, 50.0, 49.8, 50.1, 50.0],
            macds=[0.01, 0.01, 0.01, 0.01, 0.01, 0.01],
            macd_signals=[0.01, 0.01, 0.01, 0.01, 0.01, 0.01],
            macd_histograms=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            adx_values=[11.0, 10.8, 10.6, 10.4, 10.2, 10.0],
            volume_ratios=[0.84, 0.82, 0.81, 0.80, 0.79, 0.78],
            atr_values=[1.10, 1.08, 1.05, 1.02, 1.00, 0.48],
            sma_21_values=[100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
            sma_50_values=[100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
            sma_200_values=[100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
        )
        data.iloc[-1, data.columns.get_loc("open")] = 100.01
        data.iloc[-1, data.columns.get_loc("high")] = 100.06
        data.iloc[-1, data.columns.get_loc("low")] = 99.99

        evaluation = TradingBot.validate_entry_quality(bot, data, market_bias="bullish", structure_state="weak_structure")

        self.assertEqual(evaluation["entry_quality"], "bad")
        self.assertLess(evaluation["entry_score"], 5.0)
        self.assertIn("volatilidade muito baixa para entrada", evaluation["conflicts"])

    def test_validate_entry_quality_exposes_probabilistic_entry_score(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        data = _build_confirmation_frame(
            closes=[100.0, 100.5, 100.9, 101.3, 101.8, 102.1],
            rsis=[48.0, 51.0, 54.0, 57.0, 58.0, 59.0],
            macds=[0.10, 0.14, 0.20, 0.26, 0.31, 0.34],
            macd_signals=[0.05, 0.08, 0.12, 0.17, 0.22, 0.25],
            macd_histograms=[0.05, 0.06, 0.08, 0.09, 0.09, 0.09],
            adx_values=[22.0, 24.0, 25.0, 27.0, 28.0, 29.0],
            volume_ratios=[1.00, 1.05, 1.08, 1.10, 1.15, 1.18],
            atr_values=[0.90, 0.92, 0.95, 0.98, 1.00, 1.02],
            sma_21_values=[99.7, 100.0, 100.4, 100.8, 101.2, 101.5],
            sma_50_values=[99.0, 99.2, 99.4, 99.7, 100.0, 100.3],
            sma_200_values=[98.0, 98.1, 98.2, 98.3, 98.4, 98.5],
        )
        data.iloc[-1, data.columns.get_loc("open")] = 101.62
        data.iloc[-1, data.columns.get_loc("high")] = 102.35
        data.iloc[-1, data.columns.get_loc("low")] = 101.46

        evaluation = TradingBot.validate_entry_quality(bot, data, market_bias="bullish", structure_state="pullback")

        self.assertIn("entry_score", evaluation)
        self.assertAlmostEqual(evaluation["entry_score"], evaluation["quality_score"], places=2)
        self.assertGreaterEqual(evaluation["entry_score"], 0.0)
        self.assertLessEqual(evaluation["entry_score"], 10.0)

    def test_entry_quality_evaluation_returns_bad_for_late_stretched_entry(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        data = _build_confirmation_frame(
            closes=[100.0, 100.7, 101.3, 102.0, 102.8, 105.5],
            rsis=[49.0, 53.0, 56.0, 60.0, 64.0, 74.0],
            macds=[0.18, 0.24, 0.31, 0.40, 0.54, 0.86],
            macd_signals=[0.10, 0.13, 0.19, 0.27, 0.36, 0.48],
            macd_histograms=[0.08, 0.11, 0.12, 0.13, 0.18, 0.38],
            adx_values=[24.0, 26.0, 28.0, 30.0, 33.0, 36.0],
            volume_ratios=[1.20, 1.28, 1.34, 1.42, 1.58, 2.35],
            atr_values=[1.00, 1.01, 1.02, 1.03, 1.05, 1.10],
            sma_21_values=[99.4, 99.9, 100.4, 100.9, 101.5, 102.0],
            sma_50_values=[98.7, 99.0, 99.4, 99.8, 100.2, 100.5],
            sma_200_values=[97.0, 97.1, 97.2, 97.3, 97.4, 97.5],
        )
        data.iloc[-1, data.columns.get_loc("open")] = 103.4
        data.iloc[-1, data.columns.get_loc("high")] = 105.9
        data.iloc[-1, data.columns.get_loc("low")] = 103.1

        structure_evaluation = {
            "has_minimum_history": True,
            "structure_state": "breakout",
            "price_location": "resistance",
            "structure_quality": 6.7,
            "distance_from_sma21_atr": 3.25,
            "recent_high": 104.7,
            "recent_low": 100.9,
        }

        evaluation = TradingBot.get_entry_quality_evaluation(
            bot,
            data,
            signal_hypothesis="COMPRA",
            timeframe="1h",
            structure_evaluation=structure_evaluation,
            stop_loss_pct=3.0,
            take_profit_pct=3.0,
        )

        self.assertEqual(evaluation["entry_quality"], "bad")
        self.assertTrue(evaluation["late_entry"])
        self.assertTrue(evaluation["stretched_price"])
        self.assertLess(evaluation["rr_estimate"], 1.1)

    def test_evaluate_contextual_entry_supports_continuation_breakout_setup(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        data = _build_confirmation_frame(
            closes=[100.0, 100.8, 101.4, 101.9, 102.2, 102.8],
            rsis=[49.0, 53.0, 56.0, 60.0, 63.0, 66.0],
            macds=[0.12, 0.18, 0.26, 0.35, 0.44, 0.56],
            macd_signals=[0.06, 0.10, 0.15, 0.22, 0.30, 0.39],
            macd_histograms=[0.06, 0.08, 0.11, 0.13, 0.14, 0.17],
            adx_values=[23.0, 25.0, 27.0, 30.0, 32.0, 34.0],
            volume_ratios=[1.00, 1.05, 1.10, 1.14, 1.20, 1.28],
            atr_values=[0.95, 0.98, 1.00, 1.02, 1.04, 1.06],
            sma_21_values=[99.8, 100.1, 100.5, 100.9, 101.4, 101.8],
            sma_50_values=[99.2, 99.4, 99.7, 100.0, 100.3, 100.6],
            sma_200_values=[98.1, 98.2, 98.3, 98.4, 98.5, 98.6],
        )
        data.iloc[-1, data.columns.get_loc("open")] = 102.15
        data.iloc[-1, data.columns.get_loc("high")] = 103.05
        data.iloc[-1, data.columns.get_loc("low")] = 102.05

        evaluation = TradingBot.evaluate_contextual_entry(
            bot,
            data,
            market_bias="bullish",
            regime_evaluation={
                "regime": "trend_bull",
                "market_bias": "bullish",
                "regime_score": 8.1,
                "volatility_state": "normal_volatility",
                "parabolic": False,
            },
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "breakout",
                "price_location": "trend_zone",
                "structure_quality": 7.3,
                "recent_high": 102.55,
                "recent_low": 100.8,
                "distance_from_ema_pct": 0.98,
            },
            signal_hypothesis="COMPRA",
            timeframe="1h",
        )

        self.assertEqual(evaluation["setup_type"], "continuation_breakout")
        self.assertEqual(evaluation["entry_signal"], "long_candidate")
        self.assertIn(evaluation["entry_quality"], {"acceptable", "strong"})

    def test_evaluate_contextual_entry_penalizes_continuation_setup_in_range(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        data = _build_confirmation_frame(
            closes=[100.0, 100.15, 100.22, 100.28, 100.31, 100.36],
            rsis=[50.0, 52.0, 53.0, 54.0, 55.0, 55.5],
            macds=[0.03, 0.04, 0.05, 0.05, 0.05, 0.06],
            macd_signals=[0.02, 0.03, 0.04, 0.04, 0.04, 0.05],
            macd_histograms=[0.01, 0.01, 0.01, 0.01, 0.01, 0.01],
            adx_values=[13.0, 12.5, 12.0, 11.8, 11.5, 11.2],
            volume_ratios=[0.92, 0.95, 0.96, 0.94, 0.95, 0.96],
            atr_values=[0.85, 0.84, 0.83, 0.82, 0.81, 0.80],
            sma_21_values=[99.95, 100.00, 100.05, 100.10, 100.14, 100.18],
            sma_50_values=[99.90, 99.95, 100.00, 100.04, 100.08, 100.12],
            sma_200_values=[99.80, 99.82, 99.84, 99.86, 99.88, 99.90],
        )
        data.iloc[-1, data.columns.get_loc("open")] = 100.24
        data.iloc[-1, data.columns.get_loc("high")] = 100.40
        data.iloc[-1, data.columns.get_loc("low")] = 100.21

        evaluation = TradingBot.evaluate_contextual_entry(
            bot,
            data,
            market_bias="bullish",
            regime_evaluation={
                "regime": "range",
                "market_bias": "neutral",
                "regime_score": 3.1,
                "volatility_state": "low_volatility",
                "parabolic": False,
            },
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "continuation",
                "price_location": "mid_range",
                "structure_quality": 5.2,
                "recent_high": 100.41,
                "recent_low": 99.95,
                "distance_from_ema_pct": 0.18,
            },
            signal_hypothesis="COMPRA",
            timeframe="1h",
        )

        self.assertEqual(evaluation["entry_quality"], "bad")
        self.assertIn("regime lateral reduz setup direcional", evaluation["conflicts"])
        self.assertIn("continuacao fraca em mercado lateral", evaluation["reason"])

    def test_evaluate_contextual_entry_blocks_simple_reversal_against_strong_trend(self):
        bot = TradingBot.__new__(TradingBot)
        bot.timeframe = "1h"

        data = _build_confirmation_frame(
            closes=[100.0, 101.0, 102.1, 103.2, 104.4, 104.1],
            rsis=[55.0, 60.0, 64.0, 68.0, 73.0, 69.0],
            macds=[0.20, 0.35, 0.52, 0.71, 0.92, 0.80],
            macd_signals=[0.10, 0.18, 0.28, 0.40, 0.56, 0.63],
            macd_histograms=[0.10, 0.17, 0.24, 0.31, 0.36, 0.17],
            adx_values=[24.0, 27.0, 30.0, 33.0, 36.0, 35.0],
            volume_ratios=[1.08, 1.12, 1.18, 1.22, 1.30, 1.10],
            atr_values=[0.95, 1.00, 1.05, 1.08, 1.10, 1.12],
            sma_21_values=[99.7, 100.1, 100.8, 101.6, 102.4, 103.0],
            sma_50_values=[99.1, 99.4, 99.8, 100.3, 100.8, 101.2],
            sma_200_values=[98.0, 98.1, 98.2, 98.3, 98.4, 98.5],
        )
        data.iloc[-1, data.columns.get_loc("open")] = 104.55
        data.iloc[-1, data.columns.get_loc("high")] = 104.70
        data.iloc[-1, data.columns.get_loc("low")] = 103.90

        evaluation = TradingBot.evaluate_contextual_entry(
            bot,
            data,
            market_bias="bearish",
            regime_evaluation={
                "regime": "trend_bull",
                "market_bias": "bullish",
                "regime_score": 8.7,
                "volatility_state": "high_volatility",
                "parabolic": True,
            },
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "reversal_risk",
                "price_location": "resistance",
                "structure_quality": 6.0,
                "recent_high": 104.8,
                "recent_low": 101.8,
                "distance_from_ema_pct": 1.4,
            },
            signal_hypothesis="VENDA",
            timeframe="1h",
        )

        self.assertEqual(evaluation["entry_quality"], "bad")
        self.assertIn("reversao simples contra trend forte", evaluation["reason"])

    def test_check_signal_downgrades_when_entry_quality_is_only_acceptable(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.rsi_period = 14
        bot.timeframe = "1h"
        bot._last_context_evaluation = None
        bot._last_confirmation_evaluation = None
        bot._last_entry_quality_evaluation = None
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9
        bot._passes_signal_structure_guardrail = lambda row, signal, timeframe, structure_evaluation=None: True
        bot.get_price_structure_evaluation = lambda df, timeframe=None: {
            "has_minimum_history": True,
            "structure_state": "pullback",
            "price_location": "trend_zone",
            "structure_quality": 7.0,
            "distance_from_sma21_atr": 0.8,
            "recent_high": 102.0,
            "recent_low": 99.0,
        }
        bot.get_confirmation_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "confirmation_state": "confirmed",
            "confirmation_score": 7.4,
            "conflicts": [],
        }
        bot.get_entry_quality_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "entry_quality": "acceptable",
            "rr_estimate": 1.35,
            "late_entry": False,
            "stretched_price": False,
        }

        candle = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 101.5,
                    "low": 99.8,
                    "close": 101.2,
                    "rsi": 38.0,
                    "macd": 0.7,
                    "macd_signal": 0.2,
                    "macd_histogram": 0.5,
                    "adx": 31.0,
                    "volume_ratio": 1.6,
                    "atr": 1.1,
                    "stoch_rsi_k": 45.0,
                    "williams_r": -50.0,
                    "bb_width": 0.06,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="1h", stop_loss_pct=1.5, take_profit_pct=2.1)

        self.assertEqual(signal, "COMPRA_FRACA")

    def test_check_signal_blocks_when_entry_quality_is_bad(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.rsi_period = 14
        bot.timeframe = "1h"
        bot._last_context_evaluation = None
        bot._last_confirmation_evaluation = None
        bot._last_entry_quality_evaluation = None
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9
        bot._passes_signal_structure_guardrail = lambda row, signal, timeframe, structure_evaluation=None: True
        bot.get_price_structure_evaluation = lambda df, timeframe=None: {
            "has_minimum_history": True,
            "structure_state": "breakout",
            "price_location": "resistance",
            "structure_quality": 6.2,
            "distance_from_sma21_atr": 3.0,
            "recent_high": 104.0,
            "recent_low": 100.0,
        }
        bot.get_confirmation_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "confirmation_state": "confirmed",
            "confirmation_score": 8.2,
            "conflicts": [],
        }
        bot.get_entry_quality_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "entry_quality": "bad",
            "rr_estimate": 1.0,
            "late_entry": True,
            "stretched_price": True,
        }

        candle = pd.DataFrame(
            [
                {
                    "open": 103.5,
                    "high": 105.0,
                    "low": 103.2,
                    "close": 104.7,
                    "rsi": 40.0,
                    "macd": 0.9,
                    "macd_signal": 0.3,
                    "macd_histogram": 0.6,
                    "adx": 34.0,
                    "volume_ratio": 2.0,
                    "atr": 1.2,
                    "stoch_rsi_k": 48.0,
                    "williams_r": -45.0,
                    "bb_width": 0.07,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="1h", stop_loss_pct=3.0, take_profit_pct=3.0)

        self.assertEqual(signal, "NEUTRO")

    def test_build_scenario_score_returns_grade_a_for_strong_setup(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.build_scenario_score(
            bot,
            context_result={"context_strength": 8.8, "is_tradeable": True, "has_minimum_history": True},
            structure_result={"structure_quality": 8.0, "has_minimum_history": True},
            confirmation_result={"confirmation_score": 7.8, "has_minimum_history": True},
            entry_result={
                "entry_quality": "good",
                "quality_score": 7.2,
                "rr_estimate": 2.0,
                "late_entry": False,
                "stretched_price": False,
                "has_minimum_history": True,
            },
        )

        self.assertGreaterEqual(evaluation["scenario_score"], 8.0)
        self.assertEqual(evaluation["scenario_grade"], "A")
        self.assertGreaterEqual(evaluation["score_breakdown"]["context"], 8.5)

    def test_build_scenario_score_returns_grade_c_for_medium_setup(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.build_scenario_score(
            bot,
            context_result={"context_strength": 6.2, "is_tradeable": True, "has_minimum_history": True},
            structure_result={"structure_quality": 5.8, "has_minimum_history": True},
            confirmation_result={"confirmation_score": 5.0, "has_minimum_history": True},
            entry_result={
                "entry_quality": "acceptable",
                "quality_score": 4.6,
                "rr_estimate": 1.35,
                "late_entry": False,
                "stretched_price": False,
                "has_minimum_history": True,
            },
        )

        self.assertGreaterEqual(evaluation["scenario_score"], 5.0)
        self.assertLess(evaluation["scenario_score"], 6.5)
        self.assertEqual(evaluation["scenario_grade"], "C")

    def test_build_scenario_score_returns_grade_d_for_weak_setup(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.build_scenario_score(
            bot,
            context_result={"context_strength": 3.4, "is_tradeable": False, "has_minimum_history": True},
            structure_result={"structure_quality": 3.2, "has_minimum_history": True},
            confirmation_result={"confirmation_score": 2.8, "has_minimum_history": True},
            entry_result={
                "entry_quality": "bad",
                "quality_score": 2.4,
                "rr_estimate": 0.95,
                "late_entry": True,
                "stretched_price": True,
                "has_minimum_history": True,
            },
        )

        self.assertLess(evaluation["scenario_score"], 5.0)
        self.assertEqual(evaluation["scenario_grade"], "D")

    def test_build_scenario_score_penalizes_bullish_setup_near_non_extreme_resistance(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.build_scenario_score(
            bot,
            context_result={"market_bias": "bullish", "context_strength": 7.2, "has_minimum_history": True},
            structure_result={
                "structure_state": "continuation",
                "price_location": "resistance",
                "structure_quality": 6.6,
                "resistance_zone_distance": 0.12,
                "has_minimum_history": True,
            },
            confirmation_result={"confirmation_state": "confirmed", "confirmation_score": 7.1, "hypothesis_side": "bullish", "has_minimum_history": True},
            entry_result={"entry_quality": "acceptable", "entry_score": 5.8, "rr_estimate": 1.5, "has_minimum_history": True},
        )

        self.assertLess(evaluation["scenario_score"], 6.9)
        self.assertIn("resistencia proxima penaliza o cenario", evaluation["notes"])

    def test_build_scenario_score_adds_strong_pullback_bonus(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.build_scenario_score(
            bot,
            context_result={"market_bias": "bullish", "context_strength": 6.5, "has_minimum_history": True},
            structure_result={
                "structure_state": "pullback",
                "price_location": "trend_zone",
                "structure_quality": 6.2,
                "has_minimum_history": True,
            },
            confirmation_result={"confirmation_state": "confirmed", "confirmation_score": 6.4, "has_minimum_history": True},
            entry_result={
                "entry_quality": "acceptable",
                "entry_score": 5.5,
                "rr_estimate": 1.3,
                "setup_type": "pullback_trend",
                "has_minimum_history": True,
            },
        )

        self.assertEqual(evaluation["pullback_intensity"], "strong")
        self.assertEqual(evaluation["pullback_score"], 3.0)
        self.assertGreaterEqual(evaluation["scenario_score"], 8.0)

    def test_build_scenario_score_adds_moderate_pullback_bonus(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.build_scenario_score(
            bot,
            context_result={"market_bias": "bullish", "context_strength": 6.2, "has_minimum_history": True},
            structure_result={
                "structure_state": "pullback",
                "price_location": "trend_zone",
                "structure_quality": 5.2,
                "has_minimum_history": True,
            },
            confirmation_result={"confirmation_state": "confirmed", "confirmation_score": 6.0, "has_minimum_history": True},
            entry_result={
                "entry_quality": "acceptable",
                "entry_score": 5.2,
                "rr_estimate": 1.2,
                "setup_type": "pullback_trend",
                "has_minimum_history": True,
            },
        )

        self.assertEqual(evaluation["pullback_intensity"], "moderate")
        self.assertEqual(evaluation["pullback_score"], 1.5)
        self.assertGreaterEqual(evaluation["scenario_score"], 6.0)

    def test_build_scenario_score_keeps_valid_continuation_without_pullback_bonus(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.build_scenario_score(
            bot,
            context_result={"market_bias": "bullish", "context_strength": 6.0, "has_minimum_history": True},
            structure_result={
                "structure_state": "continuation",
                "price_location": "trend_zone",
                "structure_quality": 6.0,
                "has_minimum_history": True,
            },
            confirmation_result={"confirmation_state": "confirmed", "confirmation_score": 6.1, "has_minimum_history": True},
            entry_result={
                "entry_quality": "acceptable",
                "entry_score": 5.0,
                "rr_estimate": 1.2,
                "setup_type": "pullback_trend",
                "has_minimum_history": True,
            },
        )

        self.assertEqual(evaluation["pullback_intensity"], "continuation_valid")
        self.assertEqual(evaluation["pullback_score"], 0.0)
        self.assertGreaterEqual(evaluation["scenario_score"], 5.0)

    def test_check_signal_downgrades_when_scenario_grade_is_c(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.rsi_period = 14
        bot.timeframe = "1h"
        bot._last_context_evaluation = None
        bot._last_confirmation_evaluation = None
        bot._last_entry_quality_evaluation = None
        bot._last_scenario_evaluation = None
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9
        bot._passes_signal_structure_guardrail = lambda row, signal, timeframe, structure_evaluation=None: True
        bot.get_price_structure_evaluation = lambda df, timeframe=None, market_bias=None: {
            "has_minimum_history": True,
            "structure_state": "continuation",
            "price_location": "trend_zone",
            "structure_quality": 7.0,
        }
        bot.get_confirmation_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "confirmation_state": "confirmed",
            "confirmation_score": 7.4,
            "conflicts": [],
        }
        bot.get_entry_quality_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "entry_quality": "good",
            "rr_estimate": 2.0,
            "late_entry": False,
            "stretched_price": False,
        }
        bot.build_scenario_score = lambda *args, **kwargs: {
            "scenario_score": 5.6,
            "scenario_grade": "C",
            "score_breakdown": {"context": 6.0, "structure": 6.0, "confirmation": 5.0, "entry": 5.0},
            "notes": ["cenario medio"],
            "has_minimum_history": True,
        }

        candle = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 101.5,
                    "low": 99.8,
                    "close": 101.2,
                    "rsi": 38.0,
                    "macd": 0.7,
                    "macd_signal": 0.2,
                    "macd_histogram": 0.5,
                    "adx": 31.0,
                    "volume_ratio": 1.6,
                    "atr": 1.1,
                    "stoch_rsi_k": 45.0,
                    "williams_r": -50.0,
                    "bb_width": 0.06,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="1h")

        self.assertEqual(signal, "COMPRA_FRACA")

    def test_structure_alignment_downgrades_buy_near_resistance_when_structure_is_strong(self):
        bot = TradingBot.__new__(TradingBot)

        signal = TradingBot._apply_structure_alignment(
            bot,
            "COMPRA",
            {
                "has_minimum_history": True,
                "structure_state": "continuation",
                "price_location": "resistance",
                "structure_quality": 6.4,
                "resistance_zone_distance": 0.12,
                "reversal_risk": False,
                "against_market_bias": False,
            },
        )

        self.assertEqual(signal, "COMPRA_FRACA")

    def test_make_trade_decision_allows_buy_near_non_extreme_resistance_when_pipeline_is_strong(self):
        bot = TradingBot.__new__(TradingBot)

        decision = TradingBot.make_trade_decision(
            bot,
            context_result={"market_bias": "bullish", "has_minimum_history": True},
            structure_result={
                "structure_state": "continuation",
                "price_location": "resistance",
                "structure_quality": 5.6,
                "resistance_zone_distance": 0.05,
                "has_minimum_history": True,
            },
            confirmation_result={
                "confirmation_state": "confirmed",
                "confirmation_score": 7.0,
                "hypothesis_side": "bullish",
                "has_minimum_history": True,
            },
            entry_result={
                "entry_quality": "acceptable",
                "entry_score": 5.9,
                "rr_estimate": 1.35,
                "has_minimum_history": True,
            },
            hard_block_result={"hard_block": False},
            scenario_score_result={
                "scenario_score": 5.9,
                "scenario_grade": "B",
                "has_minimum_history": True,
            },
        )

        self.assertEqual(decision["action"], "buy")
        self.assertIsNone(decision["block_reason"])

    def test_check_signal_blocks_when_scenario_grade_is_d(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.rsi_period = 14
        bot.timeframe = "1h"
        bot._last_context_evaluation = None
        bot._last_confirmation_evaluation = None
        bot._last_entry_quality_evaluation = None
        bot._last_scenario_evaluation = None
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9
        bot._passes_signal_structure_guardrail = lambda row, signal, timeframe, structure_evaluation=None: True
        bot.get_price_structure_evaluation = lambda df, timeframe=None, market_bias=None: {
            "has_minimum_history": True,
            "structure_state": "continuation",
            "price_location": "trend_zone",
            "structure_quality": 7.0,
        }
        bot.get_confirmation_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "confirmation_state": "confirmed",
            "confirmation_score": 7.4,
            "conflicts": [],
        }
        bot.get_entry_quality_evaluation = lambda *args, **kwargs: {
            "has_minimum_history": True,
            "entry_quality": "good",
            "rr_estimate": 2.0,
            "late_entry": False,
            "stretched_price": False,
        }
        bot.build_scenario_score = lambda *args, **kwargs: {
            "scenario_score": 3.8,
            "scenario_grade": "D",
            "score_breakdown": {"context": 3.0, "structure": 4.0, "confirmation": 4.0, "entry": 4.0},
            "notes": ["cenario fraco"],
            "has_minimum_history": True,
        }

        candle = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 101.5,
                    "low": 99.8,
                    "close": 101.2,
                    "rsi": 38.0,
                    "macd": 0.7,
                    "macd_signal": 0.2,
                    "macd_histogram": 0.5,
                    "adx": 31.0,
                    "volume_ratio": 1.6,
                    "atr": 1.1,
                    "stoch_rsi_k": 45.0,
                    "williams_r": -50.0,
                    "bb_width": 0.06,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="1h")

        self.assertEqual(signal, "NEUTRO")

    def test_make_trade_decision_returns_buy_for_valid_bullish_setup(self):
        bot = TradingBot.__new__(TradingBot)

        decision = TradingBot.make_trade_decision(
            bot,
            context_result={"market_bias": "bullish", "is_tradeable": True},
            structure_result={"structure_state": "pullback", "price_location": "trend_zone"},
            confirmation_result={"confirmation_state": "confirmed", "hypothesis_side": "bullish"},
            entry_result={"entry_quality": "good"},
            hard_block_result={"hard_block": False, "block_reason": None},
            scenario_score_result={"scenario_score": 7.8, "scenario_grade": "B"},
        )

        self.assertEqual(decision["action"], "buy")
        self.assertEqual(decision["market_bias"], "bullish")
        self.assertEqual(decision["setup_type"], "pullback")
        self.assertIsNone(decision["block_reason"])
        self.assertIn("pullback", decision["entry_reason"])
        self.assertIn("bullish", decision["entry_reason"])

    def test_make_trade_decision_returns_sell_for_valid_bearish_setup(self):
        bot = TradingBot.__new__(TradingBot)

        decision = TradingBot.make_trade_decision(
            bot,
            context_result={"market_bias": "bearish", "is_tradeable": True},
            structure_result={"structure_state": "continuation", "price_location": "trend_zone"},
            confirmation_result={"confirmation_state": "confirmed", "hypothesis_side": "bearish"},
            entry_result={"entry_quality": "acceptable"},
            hard_block_result={"hard_block": False, "block_reason": None},
            scenario_score_result={"scenario_score": 7.1, "scenario_grade": "B"},
        )

        self.assertEqual(decision["action"], "sell")
        self.assertEqual(decision["market_bias"], "bearish")
        self.assertEqual(decision["setup_type"], "continuation")
        self.assertIsNone(decision["block_reason"])

    def test_make_trade_decision_waits_when_hard_block_is_active(self):
        bot = TradingBot.__new__(TradingBot)

        decision = TradingBot.make_trade_decision(
            bot,
            context_result={"market_bias": "bullish", "is_tradeable": True},
            structure_result={"structure_state": "breakout", "price_location": "trend_zone"},
            confirmation_result={"confirmation_state": "confirmed", "hypothesis_side": "bullish"},
            entry_result={"entry_quality": "good"},
            hard_block_result={"hard_block": True, "block_reason": "Governanca bloqueou"},
            scenario_score_result={"scenario_score": 8.2, "scenario_grade": "A"},
        )

        self.assertEqual(decision["action"], "wait")
        self.assertEqual(decision["block_reason"], "Governanca bloqueou")

    def test_make_trade_decision_waits_when_scenario_score_is_low(self):
        bot = TradingBot.__new__(TradingBot)

        decision = TradingBot.make_trade_decision(
            bot,
            context_result={"market_bias": "bullish", "is_tradeable": True},
            structure_result={"structure_state": "continuation", "price_location": "trend_zone"},
            confirmation_result={"confirmation_state": "confirmed", "hypothesis_side": "bullish"},
            entry_result={"entry_quality": "good"},
            hard_block_result={"hard_block": False, "block_reason": None},
            scenario_score_result={"scenario_score": 4.3, "scenario_grade": "D"},
        )

        self.assertEqual(decision["action"], "wait")
        self.assertIn("Score do cenario", decision["block_reason"])

    def test_make_trade_decision_waits_when_market_bias_is_neutral(self):
        bot = TradingBot.__new__(TradingBot)

        decision = TradingBot.make_trade_decision(
            bot,
            context_result={"market_bias": "neutral", "is_tradeable": True},
            structure_result={"structure_state": "continuation", "price_location": "trend_zone"},
            confirmation_result={"confirmation_state": "confirmed", "hypothesis_side": "neutral"},
            entry_result={"entry_quality": "good"},
            hard_block_result={"hard_block": False, "block_reason": None},
            scenario_score_result={"scenario_score": 7.4, "scenario_grade": "B"},
        )

        self.assertEqual(decision["action"], "wait")
        self.assertIn("neutro", decision["block_reason"])

    def test_make_trade_decision_allows_mid_scenario_when_structure_and_confirmation_are_strong(self):
        bot = TradingBot.__new__(TradingBot)

        decision = TradingBot.make_trade_decision(
            bot,
            context_result={"market_bias": "bullish", "is_tradeable": True},
            structure_result={
                "structure_state": "continuation",
                "price_location": "trend_zone",
                "structure_quality": 6.4,
                "has_minimum_history": True,
            },
            confirmation_result={"confirmation_state": "confirmed", "hypothesis_side": "bullish", "has_minimum_history": True},
            entry_result={"entry_quality": "strong", "has_minimum_history": True},
            hard_block_result={"hard_block": False, "block_reason": None},
            scenario_score_result={"scenario_score": 4.8, "scenario_grade": "C", "has_minimum_history": True},
        )

        self.assertEqual(decision["action"], "buy")
        self.assertIsNone(decision["block_reason"])

    def test_make_trade_decision_prefers_continuation_breakout_with_mid_score(self):
        bot = TradingBot.__new__(TradingBot)

        decision = TradingBot.make_trade_decision(
            bot,
            context_result={"market_bias": "bullish", "is_tradeable": True},
            structure_result={
                "structure_state": "continuation",
                "price_location": "trend_zone",
                "structure_quality": 6.0,
                "has_minimum_history": True,
            },
            confirmation_result={"confirmation_state": "confirmed", "hypothesis_side": "bullish", "has_minimum_history": True},
            entry_result={"entry_quality": "acceptable", "setup_type": "continuation_breakout", "has_minimum_history": True},
            hard_block_result={"hard_block": False, "block_reason": None},
            scenario_score_result={"scenario_score": 5.25, "scenario_grade": "C", "has_minimum_history": True},
        )

        self.assertEqual(decision["action"], "buy")
        self.assertIsNone(decision["block_reason"])

    def test_make_trade_decision_keeps_pullback_trend_selective_with_acceptable_entry(self):
        bot = TradingBot.__new__(TradingBot)

        decision = TradingBot.make_trade_decision(
            bot,
            context_result={"market_bias": "bullish", "is_tradeable": True},
            structure_result={
                "structure_state": "pullback",
                "price_location": "trend_zone",
                "structure_quality": 6.1,
                "has_minimum_history": True,
            },
            confirmation_result={"confirmation_state": "confirmed", "hypothesis_side": "bullish", "has_minimum_history": True},
            entry_result={"entry_quality": "acceptable", "setup_type": "pullback_trend", "has_minimum_history": True},
            hard_block_result={"hard_block": False, "block_reason": None},
            scenario_score_result={"scenario_score": 5.1, "scenario_grade": "C", "has_minimum_history": True},
        )

        self.assertEqual(decision["action"], "wait")
        self.assertIn("Score do cenario", decision["block_reason"])

    def test_make_trade_decision_allows_pullback_trend_with_strong_pullback_score(self):
        bot = TradingBot.__new__(TradingBot)

        decision = TradingBot.make_trade_decision(
            bot,
            context_result={"market_bias": "bullish", "is_tradeable": True},
            structure_result={
                "structure_state": "pullback",
                "price_location": "trend_zone",
                "structure_quality": 6.0,
                "has_minimum_history": True,
            },
            confirmation_result={"confirmation_state": "confirmed", "hypothesis_side": "bullish", "has_minimum_history": True},
            entry_result={"entry_quality": "acceptable", "setup_type": "pullback_trend", "has_minimum_history": True},
            hard_block_result={"hard_block": False, "block_reason": None},
            scenario_score_result={
                "scenario_score": 5.35,
                "scenario_grade": "C",
                "pullback_intensity": "strong",
                "pullback_score": 3.0,
                "has_minimum_history": True,
            },
        )

        self.assertEqual(decision["action"], "buy")
        self.assertIsNone(decision["block_reason"])

    def test_apply_entry_quality_alignment_downgrades_soft_bad_entry_to_weak_signal(self):
        bot = TradingBot.__new__(TradingBot)

        signal = TradingBot._apply_entry_quality_alignment(
            bot,
            "COMPRA",
            {
                "has_minimum_history": True,
                "entry_quality": "bad",
                "soft_bad_entry": True,
            },
        )

        self.assertEqual(signal, "COMPRA_FRACA")

    def test_check_hard_blocks_softens_bad_entry_when_context_is_strong(self):
        bot = TradingBot.__new__(TradingBot)
        entry_evaluation = {
            "has_minimum_history": True,
            "entry_quality": "bad",
            "rr_estimate": 1.05,
            "late_entry": False,
            "stretched_price": False,
            "entry_in_middle": False,
            "structure_state": "continuation",
            "rejection_reason": "candle atual oferece baixa qualidade",
            "conflicts": ["candle atual oferece baixa qualidade"],
            "notes": [],
        }

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="COMPRA",
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "continuation",
                "price_location": "trend_zone",
                "structure_quality": 6.3,
            },
            confirmation_evaluation={
                "has_minimum_history": True,
                "confirmation_state": "confirmed",
                "conflicts": [],
            },
            entry_quality_evaluation=entry_evaluation,
            atr_pct=0.8,
            min_atr_pct=0.12,
        )

        self.assertFalse(evaluation["hard_block"])
        self.assertTrue(entry_evaluation.get("soft_bad_entry"))
        self.assertTrue(any("suavizada" in note for note in evaluation.get("notes", [])))

    def test_make_trade_decision_allows_soft_bad_entry_when_pipeline_is_strong(self):
        bot = TradingBot.__new__(TradingBot)

        decision = TradingBot.make_trade_decision(
            bot,
            context_result={"market_bias": "bullish", "has_minimum_history": True},
            structure_result={
                "structure_state": "continuation",
                "price_location": "trend_zone",
                "structure_quality": 6.2,
                "has_minimum_history": True,
            },
            confirmation_result={
                "confirmation_state": "confirmed",
                "hypothesis_side": "bullish",
                "has_minimum_history": True,
            },
            entry_result={
                "entry_quality": "bad",
                "soft_bad_entry": True,
                "entry_score": 5.1,
                "rr_estimate": 1.05,
                "late_entry": False,
                "stretched_price": False,
                "has_minimum_history": True,
            },
            hard_block_result={"hard_block": False, "block_reason": None},
            scenario_score_result={"scenario_score": 6.6, "scenario_grade": "B", "has_minimum_history": True},
        )

        self.assertEqual(decision["action"], "buy")
        self.assertIsNone(decision["block_reason"])

    def test_check_hard_blocks_blocks_countertrend_in_strong_regime_without_controlled_reversal(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="VENDA",
            regime_evaluation={
                "has_minimum_history": True,
                "regime": "trend_bull",
                "regime_score": 7.5,
                "volatility_state": "normal_volatility",
                "parabolic": False,
                "notes": ["mercado em trend_bull"],
            },
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "continuation",
                "price_location": "trend_zone",
                "structure_quality": 6.8,
            },
            confirmation_evaluation={
                "has_minimum_history": True,
                "confirmation_state": "confirmed",
                "conflicts": [],
            },
            entry_quality_evaluation={
                "has_minimum_history": True,
                "entry_quality": "acceptable",
                "rr_estimate": 1.2,
            },
            atr_pct=0.8,
            min_atr_pct=0.12,
        )

        self.assertTrue(evaluation["hard_block"])
        self.assertEqual(evaluation["block_source"], "market_regime")

    def test_check_hard_blocks_allows_controlled_reversal_in_strong_regime(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="VENDA",
            regime_evaluation={
                "has_minimum_history": True,
                "regime": "trend_bull",
                "regime_score": 7.5,
                "volatility_state": "normal_volatility",
                "parabolic": False,
                "notes": ["mercado em trend_bull"],
            },
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "reversal_risk",
                "price_location": "resistance",
                "structure_quality": 6.7,
                "reversal_risk": True,
                "against_market_bias": False,
            },
            confirmation_evaluation={
                "has_minimum_history": True,
                "confirmation_state": "confirmed",
                "conflicts": [],
            },
            entry_quality_evaluation={
                "has_minimum_history": True,
                "entry_quality": "acceptable",
                "rr_estimate": 1.3,
            },
            atr_pct=0.8,
            min_atr_pct=0.12,
        )

        self.assertFalse(evaluation["hard_block"])

    def test_evaluate_signal_pipeline_exposes_candidate_and_blocked_signal(self):
        bot = TradingBot.__new__(TradingBot)
        bot._last_context_evaluation = {"market_bias": "neutral", "is_tradeable": False}
        bot._last_price_structure_evaluation = {"structure_state": "pullback"}
        bot._last_confirmation_evaluation = {"confirmation_state": "confirmed"}
        bot._last_entry_quality_evaluation = {"entry_quality": "good"}
        bot._last_scenario_evaluation = {"scenario_score": 6.2, "scenario_grade": "C"}
        bot._last_trade_decision = {"action": "wait", "block_reason": "Contexto superior neutro."}
        bot._last_hard_block_evaluation = {
            "hard_block": True,
            "block_reason": "Contexto superior neutro.",
            "block_source": "higher_timeframe_context",
        }
        bot._last_candidate_signal = "COMPRA"
        bot._last_signal_pipeline = None
        bot.check_signal = lambda *args, **kwargs: "NEUTRO"

        pipeline = TradingBot.evaluate_signal_pipeline(bot, pd.DataFrame([{"close": 100.0}]), timeframe="1h")

        self.assertEqual(pipeline["candidate_signal"], "COMPRA")
        self.assertIsNone(pipeline["approved_signal"])
        self.assertEqual(pipeline["blocked_signal"], "COMPRA")
        self.assertEqual(pipeline["block_reason"], "Contexto superior neutro.")

    def test_check_signal_keeps_structure_confirmation_entry_and_scenario_when_context_is_neutral(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.rsi_period = 14
        bot.timeframe = "1h"
        bot._last_context_evaluation = None
        bot._last_price_structure_evaluation = None
        bot._last_confirmation_evaluation = None
        bot._last_entry_quality_evaluation = None
        bot._last_scenario_evaluation = None
        bot._last_trade_decision = None
        bot._last_hard_block_evaluation = None
        bot._last_candidate_signal = "NEUTRO"
        bot._last_signal_pipeline = None
        bot._generate_advanced_signal = lambda row: "COMPRA"
        bot._calculate_signal_confidence = lambda row: 95.0
        bot.calculate_advanced_score = lambda row, signal=None: 0.9
        bot._passes_signal_structure_guardrail = lambda row, signal, timeframe, structure_evaluation=None: True
        def _context_eval(*args, **kwargs):
            bot._last_context_evaluation = {
                "market_bias": "neutral",
                "bias": "neutral",
                "is_tradeable": False,
                "reason": "Timeframe maior sem vies direcional claro.",
                "context_strength": 4.6,
                "regime": "range_low_vol",
            }
            return bot._last_context_evaluation

        def _structure_eval(*args, **kwargs):
            bot._last_price_structure_evaluation = {
                "has_minimum_history": True,
                "structure_state": "pullback",
                "price_location": "trend_zone",
                "structure_quality": 7.0,
                "reversal_risk": False,
                "against_market_bias": False,
                "notes": ["pullback controlado"],
                "reason": "estrutura valida",
            }
            return bot._last_price_structure_evaluation

        def _confirmation_eval(*args, **kwargs):
            bot._last_confirmation_evaluation = {
                "has_minimum_history": True,
                "confirmation_state": "confirmed",
                "confirmation_score": 7.2,
                "conflicts": [],
                "reason": "confirmacao alinhada",
            }
            return bot._last_confirmation_evaluation

        def _entry_eval(*args, **kwargs):
            bot._last_entry_quality_evaluation = {
                "has_minimum_history": True,
                "entry_quality": "good",
                "rr_estimate": 2.1,
                "late_entry": False,
                "stretched_price": False,
                "reason": "entrada boa",
            }
            return bot._last_entry_quality_evaluation

        def _scenario_eval(*args, **kwargs):
            bot._last_scenario_evaluation = {
                "has_minimum_history": True,
                "scenario_score": 7.0,
                "scenario_grade": "B",
            }
            return bot._last_scenario_evaluation

        bot.get_context_evaluation = _context_eval
        bot.get_price_structure_evaluation = _structure_eval
        bot.get_confirmation_evaluation = _confirmation_eval
        bot.get_entry_quality_evaluation = _entry_eval
        bot.build_scenario_score = _scenario_eval

        candle = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.5,
                    "close": 100.8,
                    "rsi": 38.0,
                    "macd": 0.3,
                    "macd_signal": 0.2,
                    "macd_histogram": 0.1,
                    "adx": 28.0,
                    "volume_ratio": 1.5,
                    "atr": 1.0,
                    "stoch_rsi_k": 40.0,
                    "williams_r": -45.0,
                    "bb_width": 0.04,
                    "market_regime": "trending",
                    "is_closed": True,
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )
        context_df = pd.DataFrame(
            [{"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "is_closed": True}],
            index=[pd.Timestamp("2026-01-01 08:00:00")],
        )

        signal = TradingBot.check_signal(
            bot,
            candle,
            timeframe="1h",
            context_df=context_df,
            context_timeframe="4h",
        )

        self.assertIn(signal, {"COMPRA", "COMPRA_FRACA"})
        self.assertIsNotNone(bot._last_context_evaluation)
        self.assertIsNotNone(bot._last_price_structure_evaluation)
        self.assertIsNotNone(bot._last_confirmation_evaluation)
        self.assertIsNotNone(bot._last_entry_quality_evaluation)
        self.assertIsNotNone(bot._last_scenario_evaluation)
        self.assertEqual(bot._last_trade_decision["action"], "buy")
        self.assertIsNone(bot._last_trade_decision["block_reason"])

    def test_hard_block_evaluation_blocks_countertrend_signal(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.get_hard_block_evaluation(
            bot,
            signal="COMPRA",
            context_evaluation={
                "is_tradeable": True,
                "market_bias": "bearish",
                "bias": "bearish",
                "reason": "contexto de baixa",
            },
            structure_evaluation={"has_minimum_history": True, "structure_state": "continuation", "structure_quality": 7.0},
            confirmation_evaluation={"has_minimum_history": True, "confirmation_state": "confirmed", "conflicts": []},
            entry_quality_evaluation={"has_minimum_history": True, "entry_quality": "good", "rr_estimate": 2.0},
        )

        self.assertTrue(evaluation["hard_block"])
        self.assertEqual(evaluation["block_source"], "higher_timeframe_conflict")
        self.assertIn("timeframe maior", evaluation["block_reason"])

    def test_hard_block_evaluation_uses_bad_entry_reason(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.get_hard_block_evaluation(
            bot,
            signal="COMPRA",
            structure_evaluation={"has_minimum_history": True, "structure_state": "continuation", "structure_quality": 7.0},
            confirmation_evaluation={"has_minimum_history": True, "confirmation_state": "confirmed", "conflicts": []},
            entry_quality_evaluation={
                "has_minimum_history": True,
                "entry_quality": "bad",
                "rr_estimate": 0.9,
                "conflicts": ["Risco retorno insuficiente"],
            },
        )

        self.assertTrue(evaluation["hard_block"])
        self.assertEqual(evaluation["block_source"], "entry_quality")
        self.assertEqual(evaluation["block_reason"], "Risco retorno insuficiente")

    def test_check_hard_blocks_blocks_runtime_governance_without_active_profile(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="NEUTRO",
            runtime_allowed=False,
            runtime_block_reason="Nenhum setup ativo promovido para este mercado/timeframe. Runtime bloqueado ate existir perfil ativo.",
            active_profile=None,
        )

        self.assertTrue(evaluation["hard_block"])
        self.assertEqual(evaluation["block_source"], "runtime_governance")
        self.assertIn("Nenhum setup ativo", evaluation["block_reason"])
        self.assertTrue(any("setup ativo" in note for note in evaluation["notes"]))

    def test_check_hard_blocks_blocks_weak_structure(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="COMPRA",
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "weak_structure",
                "structure_quality": 3.4,
                "reason": "Estrutura ruim para entrada.",
                "notes": ["estrutura fraca"],
            },
            confirmation_evaluation={"has_minimum_history": True, "confirmation_state": "confirmed", "conflicts": []},
            entry_quality_evaluation={"has_minimum_history": True, "entry_quality": "good", "rr_estimate": 2.0},
            atr_pct=0.8,
            min_atr_pct=0.12,
        )

        self.assertTrue(evaluation["hard_block"])
        self.assertEqual(evaluation["block_source"], "price_structure")
        self.assertIn("Estrutura ruim", evaluation["block_reason"])

    def test_check_hard_blocks_blocks_reversal_risk_against_bias(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="COMPRA",
            context_evaluation={"is_tradeable": True, "market_bias": "bullish", "bias": "bullish"},
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "reversal_risk",
                "structure_quality": 6.2,
                "reversal_risk": True,
                "against_market_bias": True,
                "reason": "Estrutura mostra risco de reversao contra o vies.",
                "notes": ["contra o vies bullish"],
            },
            confirmation_evaluation={"has_minimum_history": True, "confirmation_state": "confirmed", "conflicts": []},
            entry_quality_evaluation={"has_minimum_history": True, "entry_quality": "good", "rr_estimate": 2.0},
            atr_pct=0.8,
            min_atr_pct=0.12,
        )

        self.assertTrue(evaluation["hard_block"])
        self.assertEqual(evaluation["block_source"], "price_structure")
        self.assertIn("reversao", evaluation["block_reason"])

    def test_check_hard_blocks_blocks_bad_entry_quality(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="COMPRA",
            structure_evaluation={"has_minimum_history": True, "structure_state": "continuation", "structure_quality": 7.0},
            confirmation_evaluation={"has_minimum_history": True, "confirmation_state": "confirmed", "conflicts": []},
            entry_quality_evaluation={
                "has_minimum_history": True,
                "entry_quality": "bad",
                "rr_estimate": 0.95,
                "conflicts": ["Risco retorno insuficiente"],
                "notes": ["entrada ruim"],
            },
            atr_pct=0.8,
            min_atr_pct=0.12,
        )

        self.assertTrue(evaluation["hard_block"])
        self.assertEqual(evaluation["block_source"], "entry_quality")
        self.assertEqual(evaluation["block_reason"], "Risco retorno insuficiente")

    def test_check_hard_blocks_blocks_simple_reversal_against_strong_bull_regime(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="VENDA",
            regime_evaluation={
                "has_minimum_history": True,
                "regime": "trend_bull",
                "regime_score": 7.4,
                "volatility_state": "high_volatility",
                "parabolic": True,
                "notes": ["mercado em trend_bull", "movimento acelerado/parabolico"],
            },
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "continuation",
                "structure_quality": 6.8,
                "reversal_risk": False,
            },
            confirmation_evaluation={
                "has_minimum_history": True,
                "confirmation_state": "mixed",
                "conflicts": [],
            },
            entry_quality_evaluation={
                "has_minimum_history": True,
                "entry_quality": "acceptable",
                "rr_estimate": 1.5,
            },
            atr_pct=0.8,
            min_atr_pct=0.12,
        )

        self.assertTrue(evaluation["hard_block"])
        self.assertEqual(evaluation["block_source"], "market_regime")
        self.assertIn("regime bull", evaluation["block_reason"].lower())

    def test_check_hard_blocks_returns_clear_when_no_block_exists(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="COMPRA",
            context_evaluation={"is_tradeable": True, "market_bias": "bullish", "bias": "bullish"},
            structure_evaluation={"has_minimum_history": True, "structure_state": "continuation", "structure_quality": 7.4},
            confirmation_evaluation={"has_minimum_history": True, "confirmation_state": "confirmed", "conflicts": []},
            entry_quality_evaluation={"has_minimum_history": True, "entry_quality": "good", "rr_estimate": 2.1},
            require_volume=True,
            volume_ratio=1.8,
            min_volume_ratio=1.2,
            require_trend=True,
            adx=31.0,
            min_adx_threshold=22.0,
            atr_pct=0.8,
            min_atr_pct=0.12,
            runtime_allowed=True,
        )

        self.assertFalse(evaluation["hard_block"])
        self.assertIsNone(evaluation["block_reason"])

    def test_check_hard_blocks_keeps_neutral_context_as_penalty_not_block(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="COMPRA",
            context_evaluation={
                "is_tradeable": False,
                "market_bias": "neutral",
                "bias": "neutral",
                "context_strength": 4.6,
                "reason": "Timeframe maior sem vies direcional claro.",
            },
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "pullback",
                "price_location": "trend_zone",
                "structure_quality": 6.8,
            },
            confirmation_evaluation={"has_minimum_history": True, "confirmation_state": "confirmed", "conflicts": []},
            entry_quality_evaluation={"has_minimum_history": True, "entry_quality": "good", "rr_estimate": 2.0},
            market_regime="ranging",
            atr_pct=0.8,
            min_atr_pct=0.12,
        )

        self.assertFalse(evaluation["hard_block"])
        self.assertIsNone(evaluation["block_reason"])

    def test_check_hard_blocks_relaxes_volume_and_adx_for_strong_structure(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="COMPRA",
            context_evaluation={"is_tradeable": True, "market_bias": "bullish", "bias": "bullish"},
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "continuation",
                "price_location": "trend_zone",
                "structure_quality": 6.4,
            },
            confirmation_evaluation={"has_minimum_history": True, "confirmation_state": "confirmed", "conflicts": []},
            entry_quality_evaluation={"has_minimum_history": True, "entry_quality": "acceptable", "rr_estimate": 1.4},
            require_volume=True,
            volume_ratio=1.0,
            min_volume_ratio=1.2,
            require_trend=True,
            adx=20.0,
            min_adx_threshold=24.0,
            atr_pct=0.8,
            min_atr_pct=0.12,
        )

        self.assertFalse(evaluation["hard_block"])
        self.assertIsNone(evaluation["block_reason"])
        self.assertEqual(evaluation["notes"], [])

    def test_check_hard_blocks_blocks_pullback_setup_filter_when_contra_structure(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="VENDA",
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "breakout",
                "price_location": "trend_zone",
                "structure_quality": 6.8,
            },
            confirmation_evaluation={"has_minimum_history": True, "confirmation_state": "confirmed", "conflicts": []},
            entry_quality_evaluation={
                "has_minimum_history": True,
                "entry_quality": "acceptable",
                "setup_type": "pullback_trend",
                "rr_estimate": 1.4,
            },
            atr_pct=0.8,
            min_atr_pct=0.12,
        )

        self.assertTrue(evaluation["hard_block"])
        self.assertEqual(evaluation["block_source"], "setup_filter")
        self.assertIn("pullback_trend", evaluation["block_reason"])

    def test_check_hard_blocks_allows_short_pullback_setup_filter_in_bearish_regime(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="VENDA",
            context_evaluation={"is_tradeable": True, "market_bias": "bearish", "bias": "bearish", "context_strength": 6.7},
            regime_evaluation={
                "has_minimum_history": True,
                "regime": "trend_bear",
                "regime_score": 6.8,
                "volatility_state": "normal_volatility",
            },
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "pullback",
                "price_location": "resistance",
                "structure_quality": 6.1,
            },
            confirmation_evaluation={"has_minimum_history": True, "confirmation_state": "confirmed", "conflicts": []},
            entry_quality_evaluation={
                "has_minimum_history": True,
                "entry_quality": "acceptable",
                "setup_type": "pullback_trend",
                "rr_estimate": 1.4,
            },
            atr_pct=0.8,
            min_atr_pct=0.12,
        )

        self.assertFalse(evaluation["hard_block"])

    def test_check_hard_blocks_allows_short_pullback_with_mixed_confirmation_when_structure_is_valid(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="VENDA",
            context_evaluation={"is_tradeable": True, "market_bias": "bearish", "bias": "bearish", "context_strength": 6.9},
            regime_evaluation={
                "has_minimum_history": True,
                "regime": "trend_bear",
                "regime_score": 7.1,
                "volatility_state": "normal_volatility",
            },
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "pullback",
                "price_location": "resistance",
                "structure_quality": 6.3,
            },
            confirmation_evaluation={"has_minimum_history": True, "confirmation_state": "mixed", "conflicts": []},
            entry_quality_evaluation={
                "has_minimum_history": True,
                "entry_quality": "strong",
                "entry_score": 7.6,
                "rr_estimate": 1.3,
                "setup_type": "pullback_trend",
            },
            atr_pct=0.8,
            min_atr_pct=0.12,
        )

        self.assertFalse(evaluation["hard_block"])

    def test_check_hard_blocks_allows_short_pullback_with_strict_mixed_override(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="VENDA",
            context_evaluation={"is_tradeable": True, "market_bias": "bearish", "bias": "bearish", "context_strength": 7.4},
            regime_evaluation={
                "has_minimum_history": True,
                "regime": "trend_bear",
                "regime_score": 7.3,
                "volatility_state": "normal_volatility",
            },
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "pullback",
                "price_location": "resistance",
                "structure_quality": 6.1,
            },
            confirmation_evaluation={
                "has_minimum_history": True,
                "confirmation_state": "mixed",
                "confirmation_score": 7.1,
                "conflicts": [],
            },
            entry_quality_evaluation={
                "has_minimum_history": True,
                "entry_quality": "strong",
                "entry_score": 8.3,
                "rr_estimate": 1.35,
                "setup_type": "pullback_trend",
            },
            atr_pct=0.8,
            min_atr_pct=0.12,
        )

        self.assertFalse(evaluation["hard_block"])

    def test_check_hard_blocks_keeps_short_pullback_allowed_with_mixed_conflict_when_not_contra_structure(self):
        bot = TradingBot.__new__(TradingBot)

        evaluation = TradingBot.check_hard_blocks(
            bot,
            signal="VENDA",
            context_evaluation={"is_tradeable": True, "market_bias": "bearish", "bias": "bearish", "context_strength": 7.4},
            regime_evaluation={
                "has_minimum_history": True,
                "regime": "trend_bear",
                "regime_score": 7.3,
                "volatility_state": "normal_volatility",
            },
            structure_evaluation={
                "has_minimum_history": True,
                "structure_state": "pullback",
                "price_location": "resistance",
                "structure_quality": 6.1,
            },
            confirmation_evaluation={
                "has_minimum_history": True,
                "confirmation_state": "mixed",
                "confirmation_score": 7.2,
                "conflicts": ["MACD conflita com o vies bearish"],
            },
            entry_quality_evaluation={
                "has_minimum_history": True,
                "entry_quality": "strong",
                "entry_score": 8.4,
                "rr_estimate": 1.4,
                "setup_type": "pullback_trend",
            },
            atr_pct=0.8,
            min_atr_pct=0.12,
        )

        self.assertFalse(evaluation["hard_block"])

    def test_check_signal_records_hard_block_reason_for_ranging_market(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.rsi_period = 14
        bot.timeframe = "15m"
        bot._last_context_evaluation = None
        bot._last_confirmation_evaluation = None
        bot._last_entry_quality_evaluation = None
        bot._last_hard_block_evaluation = None

        candle = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 100.6,
                    "low": 99.5,
                    "close": 100.1,
                    "rsi": 49.0,
                    "macd": 0.1,
                    "macd_signal": 0.08,
                    "macd_histogram": 0.02,
                    "adx": 16.0,
                    "volume_ratio": 0.95,
                    "atr": 1.0,
                    "stoch_rsi_k": 48.0,
                    "williams_r": -50.0,
                    "bb_width": 0.03,
                    "market_regime": "ranging",
                    "is_closed": True,
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="15m", avoid_ranging=True)

        self.assertEqual(signal, "NEUTRO")
        self.assertTrue(bot._last_hard_block_evaluation["hard_block"])
        self.assertEqual(bot._last_hard_block_evaluation["block_source"], "market_regime")
        self.assertIn("lateral", bot._last_hard_block_evaluation["block_reason"])

    def test_check_signal_clears_previous_confirmation_state_on_early_return(self):
        bot = TradingBot.__new__(TradingBot)
        bot.rsi_min = 30
        bot.rsi_max = 70
        bot.rsi_period = 14
        bot.timeframe = "15m"
        bot._last_context_evaluation = {"market_bias": "bullish"}
        bot._last_confirmation_evaluation = {"confirmation_state": "confirmed"}
        bot._last_entry_quality_evaluation = {"entry_quality": "good"}
        bot._last_scenario_evaluation = {"scenario_grade": "A"}
        bot._last_trade_decision = {"action": "buy"}
        bot._last_hard_block_evaluation = {"hard_block": True, "block_reason": "antigo", "block_source": "old"}

        candle = pd.DataFrame(
            [
                {
                    "open": 100.0,
                    "high": 100.8,
                    "low": 99.4,
                    "close": 100.1,
                    "rsi": 48.0,
                    "macd": 0.1,
                    "macd_signal": 0.08,
                    "macd_histogram": 0.02,
                    "adx": 17.0,
                    "volume_ratio": 0.9,
                    "atr": 1.0,
                    "stoch_rsi_k": 48.0,
                    "williams_r": -50.0,
                    "bb_width": 0.03,
                    "market_regime": "ranging",
                    "is_closed": True,
                }
            ],
            index=[pd.Timestamp("2026-01-01 10:00:00")],
        )

        signal = TradingBot.check_signal(bot, candle, timeframe="15m", avoid_ranging=True)

        self.assertEqual(signal, "NEUTRO")
        self.assertIsNone(bot._last_context_evaluation)
        self.assertIsNone(bot._last_confirmation_evaluation)
        self.assertIsNone(bot._last_entry_quality_evaluation)
        self.assertIsNone(bot._last_scenario_evaluation)
        self.assertEqual(bot._last_trade_decision["action"], "wait")
        self.assertTrue(bot._last_hard_block_evaluation["hard_block"])
if __name__ == "__main__":
    unittest.main()
