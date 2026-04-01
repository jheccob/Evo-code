from __future__ import annotations

from datetime import UTC, datetime
import os
import tempfile
import unittest
from unittest import mock

import pandas as pd

from backtest import BacktestEngine
from config import AppConfig, ProductionConfig
from database.database import TradingDatabase


class DeterministicTradingBot:
    def __init__(self):
        self.updated_config = {}
        self.check_calls = []

    def update_config(self, symbol=None, timeframe=None, rsi_period=None, rsi_min=None, rsi_max=None):
        self.updated_config = {
            "symbol": symbol,
            "timeframe": timeframe,
            "rsi_period": rsi_period,
            "rsi_min": rsi_min,
            "rsi_max": rsi_max,
        }

    def calculate_indicators(self, df):
        return df

    def check_signal(self, df, timeframe="5m", require_volume=False, require_trend=False, avoid_ranging=False):
        self.check_calls.append(
            {
                "length": len(df),
                "timeframe": timeframe,
                "require_volume": require_volume,
                "require_trend": require_trend,
                "avoid_ranging": avoid_ranging,
            }
        )
        if len(df) == 211:
            return "COMPRA"
        return "NEUTRO"


class TemporalSignalTradingBot(DeterministicTradingBot):
    def __init__(self, signal_times):
        super().__init__()
        self.signal_times = {pd.Timestamp(ts) for ts in signal_times}

    def check_signal(self, df, timeframe="5m", require_volume=False, require_trend=False, avoid_ranging=False):
        result = super().check_signal(
            df,
            timeframe=timeframe,
            require_volume=require_volume,
            require_trend=require_trend,
            avoid_ranging=avoid_ranging,
        )
        if result != "NEUTRO":
            return result

        if pd.Timestamp(df.index[-1]) in self.signal_times:
            return "COMPRA"
        return "NEUTRO"


class RegimeAwareTradingBot(DeterministicTradingBot):
    def calculate_indicators(self, df):
        return df

    def check_signal(self, df, timeframe="5m", require_volume=False, require_trend=False, avoid_ranging=False):
        last_row = df.iloc[-1]
        self.check_calls.append(
            {
                "length": len(df),
                "timeframe": timeframe,
                "require_volume": require_volume,
                "require_trend": require_trend,
                "avoid_ranging": avoid_ranging,
                "market_regime": last_row.get("market_regime", "trending"),
            }
        )
        if avoid_ranging and last_row.get("market_regime") == "ranging":
            return "NEUTRO"
        if len(df) == 211:
            return "COMPRA"
        return "NEUTRO"


class ContextAwareTradingBot(DeterministicTradingBot):
    def calculate_indicators(self, df):
        return df

    def check_signal(
        self,
        df,
        timeframe="5m",
        require_volume=False,
        require_trend=False,
        avoid_ranging=False,
        context_df=None,
        context_timeframe=None,
    ):
        self.check_calls.append(
            {
                "length": len(df),
                "timeframe": timeframe,
                "context_timeframe": context_timeframe,
                "has_context_df": context_df is not None,
            }
        )
        if len(df) == 211 and context_timeframe == "4h" and context_df is not None:
            return "COMPRA"
        return "NEUTRO"


class DecisionAwareTradingBot(DeterministicTradingBot):
    def check_signal(self, df, timeframe="5m", require_volume=False, require_trend=False, avoid_ranging=False):
        result = super().check_signal(
            df,
            timeframe=timeframe,
            require_volume=require_volume,
            require_trend=require_trend,
            avoid_ranging=avoid_ranging,
        )
        if result == "COMPRA":
            self._last_trade_decision = {
                "action": "buy",
                "confidence": 7.4,
                "market_bias": "bullish",
                "setup_type": "pullback",
                "entry_reason": "bullish pullback | confirmacao confirmed | entrada good | score 7.40",
                "block_reason": None,
                "invalid_if": "perder vies bullish ou invalidar a estrutura pullback",
            }
        else:
            self._last_trade_decision = {
                "action": "wait",
                "confidence": 0.0,
                "market_bias": "neutral",
                "setup_type": None,
                "entry_reason": None,
                "block_reason": "Sem setup valido",
                "invalid_if": None,
            }
        return result


class PipelineAwareTradingBot(DeterministicTradingBot):
    def evaluate_signal_pipeline(
        self,
        df,
        timeframe="5m",
        require_volume=False,
        require_trend=False,
        avoid_ranging=False,
        **kwargs,
    ):
        self.check_calls.append(
            {
                "length": len(df),
                "timeframe": timeframe,
                "require_volume": require_volume,
                "require_trend": require_trend,
                "avoid_ranging": avoid_ranging,
            }
        )
        sequence = {
            211: {
                "candidate_signal": "COMPRA",
                "approved_signal": "COMPRA",
                "blocked_signal": None,
                "analytical_signal": "COMPRA",
                "block_reason": None,
                "regime_evaluation": {"regime": "trend_bull"},
                "structure_evaluation": {"structure_state": "breakout"},
                "confirmation_evaluation": {"confirmation_state": "confirmed"},
                "entry_quality_evaluation": {"entry_quality": "strong", "setup_type": "continuation_breakout", "entry_score": 7.8},
                "market_state_evaluation": {"market_state": "breakout_expansion", "execution_mode": "momentum_follow"},
                "trade_decision": {
                    "action": "buy",
                    "market_state": "breakout_expansion",
                    "execution_mode": "momentum_follow",
                    "confidence": 7.8,
                    "setup_type": "continuation_breakout",
                },
            },
            212: {
                "candidate_signal": "COMPRA",
                "approved_signal": None,
                "blocked_signal": "COMPRA",
                "analytical_signal": "NEUTRO",
                "block_reason": "Estrutura fraca",
                "regime_evaluation": {"regime": "range"},
                "structure_evaluation": {"structure_state": "weak_structure"},
                "confirmation_evaluation": {"confirmation_state": "confirmed"},
                "entry_quality_evaluation": {"entry_quality": "strong", "setup_type": "continuation_breakout", "entry_score": 7.2},
                "market_state_evaluation": {"market_state": "transition", "execution_mode": "standby"},
                "trade_decision": {
                    "action": "wait",
                    "market_state": "transition",
                    "execution_mode": "standby",
                    "confidence": 4.6,
                    "setup_type": "continuation_breakout",
                },
            },
            213: {
                "candidate_signal": "VENDA",
                "approved_signal": None,
                "blocked_signal": "VENDA",
                "analytical_signal": "NEUTRO",
                "block_reason": "Volume fraco",
                "regime_evaluation": {"regime": "trend_bear"},
                "structure_evaluation": {"structure_state": "pullback"},
                "confirmation_evaluation": {"confirmation_state": "weak"},
                "entry_quality_evaluation": {"entry_quality": "bad", "setup_type": "pullback_trend", "entry_score": 3.4},
                "market_state_evaluation": {"market_state": "blocked", "execution_mode": "standby"},
                "trade_decision": {
                    "action": "wait",
                    "market_state": "blocked",
                    "execution_mode": "standby",
                    "confidence": 1.8,
                    "setup_type": "pullback_trend",
                },
            },
        }
        return sequence.get(
            len(df),
            {
                "candidate_signal": "NEUTRO",
                "approved_signal": None,
                "blocked_signal": None,
                "analytical_signal": "NEUTRO",
                "block_reason": None,
                "regime_evaluation": {"regime": "range"},
                "structure_evaluation": {"structure_state": "mid_range"},
                "confirmation_evaluation": {"confirmation_state": "mixed"},
                "entry_quality_evaluation": {"entry_quality": "acceptable", "setup_type": "reversal_controlled", "entry_score": 5.2},
                "market_state_evaluation": {"market_state": "neutral_chop", "execution_mode": "standby"},
                "trade_decision": {
                    "action": "wait",
                    "market_state": "neutral_chop",
                    "execution_mode": "standby",
                    "confidence": 0.0,
                    "setup_type": "reversal_controlled",
                },
            },
        )


class EvoResumePipelineTradingBot(DeterministicTradingBot):
    def __init__(self, signal_map):
        super().__init__()
        self.signal_map = signal_map

    def calculate_indicators(self, df):
        return df

    def evaluate_signal_pipeline(
        self,
        df,
        timeframe="5m",
        require_volume=False,
        require_trend=False,
        avoid_ranging=False,
        **kwargs,
    ):
        signal = self.signal_map.get(len(df), "NEUTRO")
        if signal == "COMPRA":
            setup_type = "ema_rsi_resume_long"
            market_state = "ema_rsi_resume_bull"
        elif signal == "VENDA":
            setup_type = "ema_rsi_resume_short"
            market_state = "ema_rsi_resume_bear"
        else:
            return {
                "candidate_signal": "NEUTRO",
                "approved_signal": None,
                "blocked_signal": None,
                "analytical_signal": "NEUTRO",
                "block_reason": None,
                "regime_evaluation": {"regime": "range"},
                "structure_evaluation": {"structure_state": "mid_range"},
                "confirmation_evaluation": {"confirmation_state": "mixed"},
                "entry_quality_evaluation": {"entry_quality": "acceptable", "setup_type": None, "entry_score": 0.0},
                "market_state_evaluation": {"market_state": "neutral", "execution_mode": "standby"},
                "trade_decision": {
                    "action": "wait",
                    "market_state": "neutral",
                    "execution_mode": "standby",
                    "confidence": 0.0,
                    "setup_type": None,
                },
            }

        action = "buy" if signal == "COMPRA" else "sell"
        return {
            "candidate_signal": signal,
            "approved_signal": signal,
            "blocked_signal": None,
            "analytical_signal": signal,
            "block_reason": None,
            "regime_evaluation": {"regime": "trend_bull" if signal == "COMPRA" else "trend_bear"},
            "structure_evaluation": {"structure_state": "resume"},
            "confirmation_evaluation": {"confirmation_state": "confirmed"},
            "entry_quality_evaluation": {"entry_quality": "strong", "setup_type": setup_type, "entry_score": 8.4},
            "market_state_evaluation": {"market_state": market_state, "execution_mode": "ema_rsi_resume"},
            "trade_decision": {
                "action": action,
                "market_state": market_state,
                "execution_mode": "ema_rsi_resume",
                "confidence": 8.4,
                "setup_type": setup_type,
                "entry_reason": signal,
            },
        }


class FixedDataBacktestEngine(BacktestEngine):
    def __init__(self, data_frame, trading_bot):
        super().__init__(trading_bot=trading_bot)
        self._data_frame = data_frame

    def _fetch_historical_ohlcv(self, symbol, timeframe, start_date, end_date):
        return self._data_frame.copy()


class ComparisonBacktestEngine(BacktestEngine):
    def __init__(self, result_map):
        super().__init__(trading_bot=DeterministicTradingBot())
        self.result_map = result_map

    def run_backtest(self, symbol, timeframe, **kwargs):
        scenario = self.result_map[(symbol, timeframe)]
        if isinstance(scenario, Exception):
            raise scenario

        return {
            "meta": {
                "symbol": symbol,
                "timeframe": timeframe,
                "start_date": "2026-01-01T00:00:00",
                "end_date": "2026-01-10T00:00:00",
            },
            "stats": scenario["stats"],
            "validation": scenario.get("validation"),
            "walk_forward": scenario.get("walk_forward"),
            "saved_run_id": scenario.get("saved_run_id"),
            "trades": [],
            "portfolio_values": [],
        }


class RobustnessMatrixBacktestEngine(BacktestEngine):
    def __init__(self, result_map):
        super().__init__(trading_bot=DeterministicTradingBot())
        self.result_map = result_map
        self.calls = []

    def run_backtest(self, symbol, timeframe, start_date, end_date, **kwargs):
        horizon_days = int(round((pd.Timestamp(end_date) - pd.Timestamp(start_date)).total_seconds() / 86400.0))
        self.calls.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "horizon_days": horizon_days,
                "kwargs": dict(kwargs),
            }
        )
        scenario = self.result_map[(symbol, horizon_days)]
        if isinstance(scenario, Exception):
            raise scenario

        return {
            "meta": {
                "symbol": symbol,
                "timeframe": timeframe,
                "start_date": pd.Timestamp(start_date).isoformat(),
                "end_date": pd.Timestamp(end_date).isoformat(),
            },
            "stats": scenario["stats"],
            "validation": scenario.get("validation"),
            "walk_forward": scenario.get("walk_forward"),
            "saved_run_id": scenario.get("saved_run_id"),
            "trades": [],
            "portfolio_values": [],
        }


class OptimizationBacktestEngine(BacktestEngine):
    def __init__(self, result_map):
        super().__init__(trading_bot=DeterministicTradingBot())
        self.result_map = result_map

    def run_backtest(self, symbol, timeframe, rsi_min, rsi_max, **kwargs):
        scenario = self.result_map[(rsi_min, rsi_max)]
        if isinstance(scenario, Exception):
            raise scenario

        return {
            "meta": {
                "symbol": symbol,
                "timeframe": timeframe,
                "start_date": "2026-01-01T00:00:00",
                "end_date": "2026-01-10T00:00:00",
                "rsi_min": rsi_min,
                "rsi_max": rsi_max,
            },
            "stats": scenario["stats"],
            "validation": scenario.get("validation"),
            "walk_forward": scenario.get("walk_forward"),
            "saved_run_id": scenario.get("saved_run_id"),
            "trades": [],
            "portfolio_values": [],
        }


class BacktestEngineTests(unittest.TestCase):
    def _build_market_data(self):
        timestamps = pd.date_range("2026-01-01", periods=260, freq="5min")
        data = pd.DataFrame(
            {
                "open": [100.0] * len(timestamps),
                "high": [100.1] * len(timestamps),
                "low": [99.9] * len(timestamps),
                "close": [100.0] * len(timestamps),
                "volume": [1_000.0] * len(timestamps),
            },
            index=timestamps,
        )
        data.iloc[211, data.columns.get_loc("high")] = 100.7
        return data

    def _build_validation_market_data(self):
        timestamps = pd.date_range("2026-01-01", periods=520, freq="5min")
        data = pd.DataFrame(
            {
                "open": [100.0] * len(timestamps),
                "high": [100.1] * len(timestamps),
                "low": [99.9] * len(timestamps),
                "close": [100.0] * len(timestamps),
                "volume": [1_000.0] * len(timestamps),
            },
            index=timestamps,
        )
        data.loc[pd.Timestamp("2026-01-01 18:25:00"), "high"] = 100.7
        data.loc[pd.Timestamp("2026-01-02 15:05:00"), "high"] = 100.7
        return data

    def _build_walk_forward_market_data(self):
        timestamps = pd.date_range("2026-01-01", periods=900, freq="5min")
        data = pd.DataFrame(
            {
                "open": [100.0] * len(timestamps),
                "high": [100.1] * len(timestamps),
                "low": [99.9] * len(timestamps),
                "close": [100.0] * len(timestamps),
                "volume": [1_000.0] * len(timestamps),
            },
            index=timestamps,
        )
        data.loc[pd.Timestamp("2026-01-02 06:05:00"), "high"] = 100.7
        data.loc[pd.Timestamp("2026-01-03 12:05:00"), "high"] = 100.7
        return data

    def _build_management_market_data(self):
        timestamps = pd.date_range("2026-01-01", periods=260, freq="5min")
        data = pd.DataFrame(
            {
                "open": [100.0] * len(timestamps),
                "high": [100.2] * len(timestamps),
                "low": [99.8] * len(timestamps),
                "close": [100.0] * len(timestamps),
                "volume": [1_000.0] * len(timestamps),
                "atr": [1.0] * len(timestamps),
                "ema_21": [100.0] * len(timestamps),
                "market_regime": ["trend_bull"] * len(timestamps),
                "volatility_state": ["normal_volatility"] * len(timestamps),
                "regime_score": [8.0] * len(timestamps),
                "parabolic": [False] * len(timestamps),
            },
            index=timestamps,
        )
        data.iloc[212, data.columns.get_loc("high")] = 102.4
        data.iloc[212, data.columns.get_loc("low")] = 100.2
        data.iloc[212, data.columns.get_loc("close")] = 102.1
        data.iloc[212, data.columns.get_loc("ema_21")] = 101.1
        data.iloc[213, data.columns.get_loc("open")] = 102.2
        data.iloc[213, data.columns.get_loc("high")] = 104.8
        data.iloc[213, data.columns.get_loc("low")] = 102.1
        data.iloc[213, data.columns.get_loc("close")] = 104.3
        data.iloc[213, data.columns.get_loc("ema_21")] = 102.2
        data.iloc[214, data.columns.get_loc("open")] = 104.2
        data.iloc[214, data.columns.get_loc("high")] = 106.2
        data.iloc[214, data.columns.get_loc("low")] = 103.8
        data.iloc[214, data.columns.get_loc("close")] = 106.0
        data.iloc[214, data.columns.get_loc("ema_21")] = 103.2
        return data

    def _build_evo_resume_take_market_data(self):
        timestamps = pd.date_range("2026-01-01", periods=260, freq="5min")
        data = pd.DataFrame(
            {
                "open": [100.0] * len(timestamps),
                "high": [100.2] * len(timestamps),
                "low": [99.8] * len(timestamps),
                "close": [100.0] * len(timestamps),
                "volume": [1_000.0] * len(timestamps),
            },
            index=timestamps,
        )
        data.iloc[211, data.columns.get_loc("open")] = 110.0
        data.iloc[211, data.columns.get_loc("high")] = 120.0
        data.iloc[211, data.columns.get_loc("low")] = 95.0
        data.iloc[211, data.columns.get_loc("close")] = 101.0
        data.iloc[212, data.columns.get_loc("open")] = 101.0
        data.iloc[212, data.columns.get_loc("high")] = 105.0
        data.iloc[212, data.columns.get_loc("low")] = 100.0
        data.iloc[212, data.columns.get_loc("close")] = 104.2
        return data

    def _build_evo_resume_reversal_market_data(self):
        timestamps = pd.date_range("2026-01-01", periods=260, freq="5min")
        data = pd.DataFrame(
            {
                "open": [100.0] * len(timestamps),
                "high": [100.2] * len(timestamps),
                "low": [99.8] * len(timestamps),
                "close": [100.0] * len(timestamps),
                "volume": [1_000.0] * len(timestamps),
            },
            index=timestamps,
        )
        data.iloc[211, data.columns.get_loc("open")] = 110.0
        data.iloc[211, data.columns.get_loc("high")] = 115.0
        data.iloc[211, data.columns.get_loc("low")] = 95.0
        data.iloc[211, data.columns.get_loc("close")] = 101.0
        data.iloc[212, data.columns.get_loc("open")] = 101.0
        data.iloc[212, data.columns.get_loc("high")] = 102.0
        data.iloc[212, data.columns.get_loc("low")] = 100.0
        data.iloc[212, data.columns.get_loc("close")] = 101.0
        data.iloc[213, data.columns.get_loc("open")] = 90.0
        data.iloc[213, data.columns.get_loc("high")] = 101.0
        data.iloc[213, data.columns.get_loc("low")] = 89.0
        data.iloc[213, data.columns.get_loc("close")] = 100.0
        return data

    def test_apply_setup_execution_policy_blocks_disallowed_setup(self):
        engine = BacktestEngine(trading_bot=DeterministicTradingBot())
        pipeline = {
            "candidate_signal": "COMPRA",
            "approved_signal": "COMPRA",
            "blocked_signal": None,
            "analytical_signal": "COMPRA",
            "block_reason": None,
            "block_source": None,
            "entry_quality_evaluation": {"setup_type": "pullback_trend"},
            "trade_decision": {"action": "buy", "setup_type": "pullback_trend"},
            "hard_block_evaluation": {"hard_block": False},
        }

        updated = engine._apply_setup_execution_policy(
            pipeline,
            allowed_execution_setups={"continuation_breakout"},
        )

        self.assertEqual(updated["approved_signal"], None)
        self.assertEqual(updated["blocked_signal"], "COMPRA")
        self.assertEqual(updated["analytical_signal"], "NEUTRO")
        self.assertEqual(updated["block_source"], "setup_execution_policy")
        self.assertIn("modo pesquisa", str(updated["block_reason"]))
        self.assertEqual(updated["trade_decision"]["action"], "wait")
        self.assertTrue(updated["hard_block_evaluation"]["hard_block"])

    def test_apply_setup_execution_policy_keeps_allowed_setup(self):
        engine = BacktestEngine(trading_bot=DeterministicTradingBot())
        pipeline = {
            "candidate_signal": "VENDA",
            "approved_signal": "VENDA",
            "blocked_signal": None,
            "analytical_signal": "VENDA",
            "entry_quality_evaluation": {"setup_type": "continuation_breakout"},
            "trade_decision": {"action": "sell", "setup_type": "continuation_breakout"},
        }

        updated = engine._apply_setup_execution_policy(
            pipeline,
            allowed_execution_setups={"continuation_breakout"},
        )

        self.assertEqual(updated["approved_signal"], "VENDA")
        self.assertEqual(updated["blocked_signal"], None)
        self.assertEqual(updated["analytical_signal"], "VENDA")

    def test_run_backtest_returns_dashboard_contract_and_respects_small_take_profit_pct(self):
        bot = DeterministicTradingBot()
        engine = FixedDataBacktestEngine(self._build_market_data(), bot)

        results = engine.run_backtest(
            symbol="BTC/USDT",
            timeframe="5m",
            start_date=datetime(2026, 1, 1, 0, 0),
            end_date=datetime(2026, 1, 1, 21, 35),
            initial_balance=1_000,
            rsi_period=14,
            rsi_min=20,
            rsi_max=80,
            take_profit_pct=0.5,
            fee_rate=0.0,
            slippage=0.0,
        )

        self.assertEqual(results["stats"]["total_trades"], 1)
        self.assertEqual(results["trades"][0]["reason"], "TAKE_PROFIT")
        self.assertEqual(results["stats"]["winning_trades"], 1)
        self.assertIn("profit_factor", results["stats"])
        self.assertTrue(results["portfolio_values"])
        self.assertTrue(results["benchmark_values"])
        self.assertEqual(results["benchmark_values"][0]["benchmark_value"], 1000.0)
        self.assertIn("objective_check", results)
        self.assertIn("status", results["objective_check"])
        self.assertIn("objective_score", results["objective_check"])
        self.assertEqual(results["candidate_count"], 1)
        self.assertEqual(results["approved_count"], 1)
        self.assertEqual(results["blocked_count"], 0)
        self.assertEqual(results["approval_rate_pct"], 100.0)
        self.assertEqual(results["signal_pipeline_stats"]["candidate_count"], 1)
        self.assertEqual(
            list(engine.get_trade_summary_df().columns),
            ["timestamp", "entry_price", "price", "profit_loss_pct", "profit_loss", "signal"],
        )
        self.assertEqual(bot.updated_config["symbol"], "BTC/USDT")

    def test_run_backtest_accepts_timezone_aware_dates_with_naive_market_index(self):
        bot = DeterministicTradingBot()
        engine = FixedDataBacktestEngine(self._build_market_data(), bot)

        results = engine.run_backtest(
            symbol="BTC/USDT",
            timeframe="5m",
            start_date=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            end_date=datetime(2026, 1, 1, 21, 35, tzinfo=UTC),
            initial_balance=1_000,
            rsi_period=14,
            rsi_min=20,
            rsi_max=80,
            take_profit_pct=0.5,
            fee_rate=0.0,
            slippage=0.0,
        )

        self.assertEqual(results["stats"]["total_trades"], 1)
        self.assertTrue(results["benchmark_values"])
        self.assertEqual(results["candidate_count"], 1)

    def test_run_backtest_collects_signal_pipeline_counters(self):
        bot = PipelineAwareTradingBot()
        engine = FixedDataBacktestEngine(self._build_market_data(), bot)

        results = engine.run_backtest(
            symbol="BTC/USDT",
            timeframe="5m",
            start_date=datetime(2026, 1, 1, 0, 0),
            end_date=datetime(2026, 1, 1, 21, 35),
            initial_balance=1_000,
            take_profit_pct=0.5,
            fee_rate=0.0,
            slippage=0.0,
        )

        self.assertEqual(results["candidate_count"], 3)
        self.assertEqual(results["approved_count"], 1)
        self.assertEqual(results["blocked_count"], 2)
        self.assertAlmostEqual(results["approval_rate_pct"], 33.33, places=2)
        self.assertEqual(results["block_reason_counts"]["Estrutura fraca"], 1)
        self.assertEqual(results["block_reason_counts"]["Volume fraco"], 1)
        self.assertEqual(results["regime_counts"]["trend_bull"], 1)
        self.assertEqual(results["regime_counts"]["range"], 1)
        self.assertEqual(results["regime_counts"]["trend_bear"], 1)
        self.assertEqual(results["structure_state_counts"]["breakout"], 1)
        self.assertEqual(results["structure_state_counts"]["weak_structure"], 1)
        self.assertEqual(results["structure_state_counts"]["pullback"], 1)
        self.assertEqual(results["confirmation_state_counts"]["confirmed"], 2)
        self.assertEqual(results["confirmation_state_counts"]["weak"], 1)
        self.assertEqual(results["entry_quality_counts"]["strong"], 2)
        self.assertEqual(results["entry_quality_counts"]["bad"], 1)
        self.assertEqual(results["setup_type_counts"]["continuation_breakout"], 2)
        self.assertEqual(results["setup_type_counts"]["pullback_trend"], 1)
        self.assertEqual(results["setup_type_approved_counts"]["continuation_breakout"], 1)
        self.assertEqual(results["setup_type_blocked_counts"]["continuation_breakout"], 1)
        self.assertEqual(results["setup_type_blocked_counts"]["pullback_trend"], 1)
        self.assertEqual(results["setup_type_block_rates"]["continuation_breakout"], 50.0)
        self.assertEqual(results["setup_type_block_rates"]["pullback_trend"], 100.0)
        self.assertEqual(results["signal_pipeline_stats"]["candidate_count"], 3)
        self.assertEqual(results["signal_audit_summary"]["candidate_count"], 3)
        self.assertEqual(results["signal_audit_summary"]["blocked_count"], 2)
        self.assertIn("approval_by_regime", results["signal_audit_summary"])
        self.assertIn("approval_by_market_state", results["signal_audit_summary"])
        self.assertEqual(results["signal_pipeline_stats"]["regime_counts"]["trend_bull"], 1)
        self.assertEqual(results["signal_pipeline_stats"]["market_state_counts"]["breakout_expansion"], 1)
        self.assertEqual(results["signal_pipeline_stats"]["market_state_approved_counts"]["breakout_expansion"], 1)
        self.assertEqual(results["signal_pipeline_stats"]["market_state_blocked_counts"]["blocked"], 1)
        self.assertEqual(results["signal_pipeline_stats"]["execution_mode_counts"]["standby"], 2)
        self.assertEqual(len(results["regime_summary"]), 1)
        self.assertEqual(results["regime_summary"][0]["regime"], "trend_bull")
        self.assertEqual(results["regime_summary"][0]["total_trades"], 1)
        self.assertEqual(results["setup_type_summary"][0]["setup_type"], "continuation_breakout")
        self.assertEqual(results["market_state_summary"][0]["market_state"], "breakout_expansion")
        self.assertEqual(results["execution_mode_summary"][0]["execution_mode"], "momentum_follow")

    def test_run_backtest_executes_evo_resume_on_signal_close_and_ignores_intrabar_take(self):
        bot = EvoResumePipelineTradingBot({211: "COMPRA"})
        engine = FixedDataBacktestEngine(self._build_evo_resume_take_market_data(), bot)

        results = engine.run_backtest(
            symbol="BTC/USDT",
            timeframe="5m",
            start_date=datetime(2026, 1, 1, 0, 0),
            end_date=datetime(2026, 1, 1, 21, 35),
            initial_balance=1_000,
            take_profit_pct=4.0,
            fee_rate=0.0,
            slippage=0.0,
        )

        self.assertEqual(results["stats"]["total_trades"], 1)
        self.assertEqual(results["trades"][0]["setup_name"], "ema_rsi_resume_long")
        self.assertEqual(results["trades"][0]["entry_price"], 100.0)
        self.assertEqual(results["trades"][0]["price"], 104.2)
        self.assertEqual(results["trades"][0]["reason"], "TAKE_PROFIT")

    def test_run_backtest_reverses_evo_resume_position_on_same_candle_close(self):
        bot = EvoResumePipelineTradingBot({211: "COMPRA", 213: "VENDA"})
        engine = FixedDataBacktestEngine(self._build_evo_resume_reversal_market_data(), bot)

        results = engine.run_backtest(
            symbol="BTC/USDT",
            timeframe="5m",
            start_date=datetime(2026, 1, 1, 0, 0),
            end_date=datetime(2026, 1, 1, 21, 35),
            initial_balance=1_000,
            fee_rate=0.0,
            slippage=0.0,
        )

        self.assertEqual(results["stats"]["total_trades"], 2)
        self.assertEqual(results["trades"][0]["reason"], "OPPOSITE_SIGNAL")
        self.assertEqual(results["trades"][0]["entry_price"], 100.0)
        self.assertEqual(results["trades"][0]["price"], 101.0)
        self.assertEqual(results["trades"][1]["side"], "short")
        self.assertEqual(results["trades"][1]["entry_price"], 101.0)

    def test_run_backtest_persists_run_and_trade_metrics_in_sqlite(self):
        bot = PipelineAwareTradingBot()
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        try:
            if os.path.exists(temp_db.name):
                os.remove(temp_db.name)

            database = TradingDatabase(db_path=temp_db.name)
            engine = FixedDataBacktestEngine(self._build_market_data(), bot)
            engine.database = database

            results = engine.run_backtest(
                symbol="BTC/USDT",
                timeframe="5m",
                start_date=datetime(2026, 1, 1, 0, 0),
                end_date=datetime(2026, 1, 1, 21, 35),
                initial_balance=1_000,
                take_profit_pct=0.5,
                fee_rate=0.0,
                slippage=0.0,
            )

            self.assertIsInstance(results.get("saved_run_id"), int)

            runs = database.get_backtest_runs()
            trades = database.get_backtest_trades(results["saved_run_id"])
            trade_analytics = database.get_trade_analytics(run_id=results["saved_run_id"])
            signal_audit = database.get_signal_audit(run_id=results["saved_run_id"])
            summary = database.get_backtest_performance_summary(symbol="BTC/USDT", timeframe="5m")

            self.assertEqual(len(runs), 1)
            self.assertEqual(len(trades), 1)
            self.assertEqual(len(trade_analytics), 1)
            self.assertGreaterEqual(len(signal_audit), 1)
            self.assertEqual(summary["total_runs"], 1)
            self.assertEqual(summary["total_trades"], 1)
            self.assertEqual(summary["breakdown_by_market"][0]["symbol"], "BTC/USDT")
            self.assertIn("avg_expectancy_pct", summary)
            self.assertEqual(runs[0]["net_profit"], results["stats"]["net_profit"])
            self.assertEqual(trades[0]["setup_name"], "continuation_breakout")
            self.assertEqual(trades[0]["strategy_version"], results["meta"]["strategy_version"])
            self.assertEqual(trades[0]["entry_reason"], "COMPRA")
            self.assertEqual(trades[0]["exit_reason"], trades[0]["reason"])
            self.assertEqual(trades[0]["sample_type"], "backtest")
            self.assertGreaterEqual(float(trades[0]["signal_score"]), 0.0)
            self.assertIn("break_even_active", trades[0])
            self.assertIn("mfe_pct", trades[0])
            self.assertIn("risk_mode", trades[0])
            self.assertIn("risk_amount", trades[0])
            self.assertIn("size_reduced", trades[0])
            self.assertEqual(trades[0]["market_state"], "breakout_expansion")
            self.assertEqual(trades[0]["execution_mode"], "momentum_follow")
            self.assertEqual(trade_analytics[0]["setup_type"], results["trades"][0]["setup_name"])
            self.assertIn("mfe_pct", trade_analytics[0])
            self.assertIn("mae_pct", trade_analytics[0])
            self.assertIn("profit_given_back_pct", trade_analytics[0])
            self.assertIn("notes", trade_analytics[0])
            self.assertIsInstance(trade_analytics[0]["notes"], list)
            self.assertIn("candidate_signal", signal_audit[0])
            self.assertIn("scenario_score", signal_audit[0])
            self.assertIn("risk_mode", signal_audit[0])
            self.assertIn("market_state", signal_audit[0])
            self.assertIn("execution_mode", signal_audit[0])
            self.assertEqual(signal_audit[0]["market_state"], "blocked")
            self.assertEqual(signal_audit[-1]["execution_mode"], "momentum_follow")
            self.assertIsInstance(signal_audit[0]["notes"], list)
        finally:
            if os.path.exists(temp_db.name):
                os.remove(temp_db.name)

    def test_run_backtest_uses_trade_decision_entry_reason_when_available(self):
        bot = DecisionAwareTradingBot()
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        try:
            if os.path.exists(temp_db.name):
                os.remove(temp_db.name)

            database = TradingDatabase(db_path=temp_db.name)
            engine = FixedDataBacktestEngine(self._build_market_data(), bot)
            engine.database = database

            results = engine.run_backtest(
                symbol="BTC/USDT",
                timeframe="5m",
                start_date=datetime(2026, 1, 1, 0, 0),
                end_date=datetime(2026, 1, 1, 21, 35),
                initial_balance=1_000,
                take_profit_pct=0.5,
                fee_rate=0.0,
                slippage=0.0,
            )

            trades = database.get_backtest_trades(results["saved_run_id"])

            self.assertEqual(
                trades[0]["entry_reason"],
                "bullish pullback | confirmacao confirmed | entrada good | score 7.40",
            )
            self.assertAlmostEqual(float(trades[0]["signal_score"]), 7.4, places=2)
        finally:
            if os.path.exists(temp_db.name):
                os.remove(temp_db.name)

    def test_run_backtest_tracks_position_management_counters_and_trade_fields(self):
        bot = DeterministicTradingBot()
        engine = FixedDataBacktestEngine(self._build_management_market_data(), bot)

        results = engine.run_backtest(
            symbol="BTC/USDT",
            timeframe="5m",
            start_date=datetime(2026, 1, 1, 0, 0),
            end_date=datetime(2026, 1, 1, 21, 35),
            initial_balance=1_000,
            stop_loss_pct=2.0,
            take_profit_pct=6.0,
            fee_rate=0.0,
            slippage=0.0,
        )

        self.assertEqual(results["stats"]["total_trades"], 1)
        self.assertEqual(results["stats"]["break_even_activated_count"], 1)
        self.assertEqual(results["stats"]["trailing_activated_count"], 1)
        self.assertEqual(results["stats"]["exit_reason_counts"]["TAKE_PROFIT"], 1)
        self.assertIn("position_management_summary", results)
        self.assertGreaterEqual(results["trades"][0]["mfe_pct"], 4.0)
        self.assertTrue(results["trades"][0]["break_even_active"])
        self.assertTrue(results["trades"][0]["trailing_active"])
        self.assertIn("trade_autopsy", results)
        self.assertIn("equity_diagnostics", results)
        self.assertGreaterEqual(results["trade_autopsy"][0]["profit_given_back_pct"], 0.0)
        self.assertIn("timestamp_exit", results["trade_autopsy"][0])
        self.assertIn("setup_type", results["trade_autopsy"][0])
        self.assertIn("pnl_pct", results["trade_autopsy"][0])
        self.assertIn("stop_initial", results["trade_autopsy"][0])
        self.assertIn("average_drawdown_pct", results["equity_diagnostics"])
        self.assertIn("profit_giveback_pct", results["equity_diagnostics"])

    def test_build_equity_diagnostics_measures_profit_giveback_after_peak(self):
        engine = BacktestEngine(trading_bot=DeterministicTradingBot())
        portfolio_df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=7, freq="1h"),
                "portfolio_value": [1000.0, 1100.0, 1080.0, 1150.0, 1120.0, 1180.0, 1140.0],
            }
        )

        diagnostics = engine._build_equity_diagnostics(portfolio_df, initial_balance=1000.0)

        self.assertAlmostEqual(diagnostics["profit_giveback_pct"], 22.22, places=2)
        self.assertGreater(diagnostics["max_drawdown_pct"], 0.0)
        self.assertGreaterEqual(diagnostics["max_recovery_periods"], 0)

    def test_run_backtest_blocks_trade_when_risk_engine_disallows_entry(self):
        from config import ProductionConfig

        bot = DeterministicTradingBot()
        engine = FixedDataBacktestEngine(self._build_market_data(), bot)

        with mock.patch.object(ProductionConfig, "RISK_DRAWDOWN_BLOCK_PCT", 0.0):
            results = engine.run_backtest(
                symbol="BTC/USDT",
                timeframe="5m",
                start_date=datetime(2026, 1, 1, 0, 0),
                end_date=datetime(2026, 1, 1, 21, 35),
                initial_balance=1_000,
                stop_loss_pct=2.0,
                take_profit_pct=0.5,
                fee_rate=0.0,
                slippage=0.0,
            )

        self.assertEqual(results["stats"]["total_trades"], 0)
        self.assertEqual(results["risk_engine_summary"]["risk_blocked_count"], 1)
        self.assertGreaterEqual(
            results["risk_engine_summary"]["risk_block_reason_counts"].get(
                "Drawdown corrente de 0.00% acima do limite de 0.00%.", 0
            ),
            1,
        )

    def test_run_backtest_tracks_reduced_risk_mode_on_trade(self):
        from config import ProductionConfig

        bot = DeterministicTradingBot()
        engine = FixedDataBacktestEngine(self._build_market_data(), bot)

        with mock.patch.object(ProductionConfig, "RISK_DRAWDOWN_WARNING_PCT", 0.0), \
             mock.patch.object(ProductionConfig, "RISK_DRAWDOWN_BLOCK_PCT", 100.0), \
             mock.patch.object(ProductionConfig, "RISK_REDUCED_MODE_MULTIPLIER", 0.5):
            results = engine.run_backtest(
                symbol="BTC/USDT",
                timeframe="5m",
                start_date=datetime(2026, 1, 1, 0, 0),
                end_date=datetime(2026, 1, 1, 21, 35),
                initial_balance=1_000,
                stop_loss_pct=2.0,
                take_profit_pct=0.5,
                fee_rate=0.0,
                slippage=0.0,
            )

        self.assertEqual(results["risk_engine_summary"]["reduced_size_count"], 1)
        self.assertEqual(results["trades"][0]["risk_mode"], "reduced")
        self.assertTrue(results["trades"][0]["size_reduced"])

    def test_run_backtest_forwards_existing_signal_filter_flags(self):
        bot = DeterministicTradingBot()
        engine = FixedDataBacktestEngine(self._build_market_data(), bot)

        engine.run_backtest(
            symbol="BTC/USDT",
            timeframe="5m",
            start_date=datetime(2026, 1, 1, 0, 0),
            end_date=datetime(2026, 1, 1, 21, 35),
            initial_balance=1_000,
            require_volume=True,
            require_trend=True,
            take_profit_pct=0.5,
            fee_rate=0.0,
            slippage=0.0,
        )

        self.assertTrue(bot.check_calls)
        self.assertTrue(any(call["require_volume"] for call in bot.check_calls))
        self.assertTrue(any(call["require_trend"] for call in bot.check_calls))

    def test_run_backtest_from_dataframe_can_block_range_entries_with_avoid_ranging(self):
        timestamps = pd.date_range("2026-01-01", periods=260, freq="5min")
        data = pd.DataFrame(
            {
                "open": [100.0] * len(timestamps),
                "high": [100.1] * len(timestamps),
                "low": [99.9] * len(timestamps),
                "close": [100.0] * len(timestamps),
                "volume": [1_000.0] * len(timestamps),
                "market_regime": ["ranging"] * len(timestamps),
            },
            index=timestamps,
        )
        data.iloc[211, data.columns.get_loc("high")] = 100.7

        engine = BacktestEngine(trading_bot=RegimeAwareTradingBot())

        without_filter = engine.run_backtest_from_dataframe(
            df=data,
            symbol="BTC/USDT",
            timeframe="5m",
            start_date=datetime(2026, 1, 1, 0, 0),
            end_date=datetime(2026, 1, 1, 21, 35),
            initial_balance=1_000,
            take_profit_pct=0.5,
            fee_rate=0.0,
            slippage=0.0,
            avoid_ranging=False,
        )
        with_filter = engine.run_backtest_from_dataframe(
            df=data,
            symbol="BTC/USDT",
            timeframe="5m",
            start_date=datetime(2026, 1, 1, 0, 0),
            end_date=datetime(2026, 1, 1, 21, 35),
            initial_balance=1_000,
            take_profit_pct=0.5,
            fee_rate=0.0,
            slippage=0.0,
            avoid_ranging=True,
        )

        self.assertEqual(without_filter["stats"]["total_trades"], 1)
        self.assertEqual(with_filter["stats"]["total_trades"], 0)

    def test_run_backtest_from_dataframe_persists_context_timeframe_for_multi_timeframe_setup(self):
        timestamps = pd.date_range("2026-01-01", periods=260, freq="1h")
        entry_df = pd.DataFrame(
            {
                "open": [100.0] * len(timestamps),
                "high": [100.1] * len(timestamps),
                "low": [99.9] * len(timestamps),
                "close": [100.0] * len(timestamps),
                "volume": [1_000.0] * len(timestamps),
            },
            index=timestamps,
        )
        entry_df.iloc[211, entry_df.columns.get_loc("high")] = 100.7

        context_timestamps = pd.date_range("2025-12-01", periods=120, freq="4h")
        context_df = pd.DataFrame(
            {
                "open": [100.0] * len(context_timestamps),
                "high": [101.0] * len(context_timestamps),
                "low": [99.0] * len(context_timestamps),
                "close": [100.5] * len(context_timestamps),
                "volume": [5_000.0] * len(context_timestamps),
            },
            index=context_timestamps,
        )

        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        try:
            if os.path.exists(temp_db.name):
                os.remove(temp_db.name)

            database = TradingDatabase(db_path=temp_db.name)
            engine = BacktestEngine(trading_bot=ContextAwareTradingBot(), database=database)

            results = engine.run_backtest_from_dataframe(
                df=entry_df,
                context_df=context_df,
                symbol="BTC/USDT",
                timeframe="1h",
                context_timeframe="4h",
                start_date=datetime(2026, 1, 1, 0, 0),
                end_date=datetime(2026, 1, 11, 19, 0),
                initial_balance=1_000,
                take_profit_pct=0.5,
                fee_rate=0.0,
                slippage=0.0,
                persist_result=True,
            )

            run = database.get_backtest_runs(limit=1)[0]
            trade = database.get_backtest_trades(results["saved_run_id"])[0]

            self.assertEqual(results["meta"]["context_timeframe"], "4h")
            self.assertEqual(run["context_timeframe"], "4h")
            self.assertEqual(trade["context_timeframe"], "4h")
            self.assertIn("-ctx4h", run["strategy_version"])
            self.assertTrue(engine.trading_bot.check_calls)
            self.assertEqual(engine.trading_bot.check_calls[0]["context_timeframe"], "4h")
        finally:
            if os.path.exists(temp_db.name):
                os.remove(temp_db.name)

    def test_run_backtest_builds_in_sample_and_out_of_sample_validation(self):
        bot = TemporalSignalTradingBot(
            signal_times=[
                "2026-01-01 18:20:00",
                "2026-01-02 15:00:00",
            ]
        )
        engine = FixedDataBacktestEngine(self._build_validation_market_data(), bot)

        results = engine.run_backtest(
            symbol="BTC/USDT",
            timeframe="5m",
            start_date=datetime(2026, 1, 1, 0, 0),
            end_date=datetime(2026, 1, 2, 19, 15),
            initial_balance=1_000,
            take_profit_pct=0.5,
            fee_rate=0.0,
            slippage=0.0,
            validation_split_pct=30,
            persist_result=False,
        )

        self.assertIn("validation", results)
        self.assertEqual(results["validation"]["split_pct"], 30.0)
        self.assertGreaterEqual(results["validation"]["in_sample"]["stats"]["total_trades"], 1)
        self.assertGreaterEqual(results["validation"]["out_of_sample"]["stats"]["total_trades"], 1)
        self.assertGreater(results["validation"]["out_of_sample"]["stats"]["total_return_pct"], 0)

    def test_run_backtest_persists_out_of_sample_metrics(self):
        bot = TemporalSignalTradingBot(
            signal_times=[
                "2026-01-01 18:20:00",
                "2026-01-02 15:00:00",
            ]
        )
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        try:
            if os.path.exists(temp_db.name):
                os.remove(temp_db.name)

            database = TradingDatabase(db_path=temp_db.name)
            engine = FixedDataBacktestEngine(self._build_validation_market_data(), bot)
            engine.database = database

            results = engine.run_backtest(
                symbol="BTC/USDT",
                timeframe="5m",
                start_date=datetime(2026, 1, 1, 0, 0),
                end_date=datetime(2026, 1, 2, 19, 15),
                initial_balance=1_000,
                take_profit_pct=0.5,
                fee_rate=0.0,
                slippage=0.0,
                validation_split_pct=30,
            )

            run = database.get_backtest_runs(limit=1)[0]
            summary = database.get_backtest_performance_summary(symbol="BTC/USDT", timeframe="5m")

            self.assertEqual(run["validation_split_pct"], 30.0)
            self.assertGreater(run["out_of_sample_return_pct"], 0)
            self.assertGreaterEqual(run["out_of_sample_total_trades"], 1)
            self.assertIn("avg_out_of_sample_return_pct", summary)
            self.assertGreater(summary["avg_out_of_sample_return_pct"], 0)
            self.assertEqual(results["saved_run_id"], run["id"])
        finally:
            if os.path.exists(temp_db.name):
                os.remove(temp_db.name)

    def test_run_backtest_builds_walk_forward_summary(self):
        bot = TemporalSignalTradingBot(
            signal_times=[
                "2026-01-02 06:00:00",
                "2026-01-03 12:00:00",
            ]
        )
        engine = FixedDataBacktestEngine(self._build_walk_forward_market_data(), bot)

        with mock.patch.object(ProductionConfig, "MIN_PROMOTION_OOS_TRADES", 1):
            results = engine.run_backtest(
                symbol="BTC/USDT",
                timeframe="5m",
                start_date=datetime(2026, 1, 1, 0, 0),
                end_date=datetime(2026, 1, 4, 3, 0),
                initial_balance=1_000,
                take_profit_pct=0.5,
                fee_rate=0.0,
                slippage=0.0,
                walk_forward_windows=2,
                persist_result=False,
            )

        self.assertIn("walk_forward", results)
        self.assertEqual(results["walk_forward"]["total_windows"], 2)
        self.assertEqual(results["walk_forward"]["passed_windows"], 2)
        self.assertGreater(results["walk_forward"]["avg_oos_return_pct"], 0)

    def test_run_backtest_persists_walk_forward_summary(self):
        bot = TemporalSignalTradingBot(
            signal_times=[
                "2026-01-02 06:00:00",
                "2026-01-03 12:00:00",
            ]
        )
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        try:
            if os.path.exists(temp_db.name):
                os.remove(temp_db.name)

            database = TradingDatabase(db_path=temp_db.name)
            engine = FixedDataBacktestEngine(self._build_walk_forward_market_data(), bot)
            engine.database = database

            with mock.patch.object(ProductionConfig, "MIN_PROMOTION_OOS_TRADES", 1):
                results = engine.run_backtest(
                    symbol="BTC/USDT",
                    timeframe="5m",
                    start_date=datetime(2026, 1, 1, 0, 0),
                    end_date=datetime(2026, 1, 4, 3, 0),
                    initial_balance=1_000,
                    take_profit_pct=0.5,
                    fee_rate=0.0,
                    slippage=0.0,
                    walk_forward_windows=2,
                )

            run = database.get_backtest_runs(limit=1)[0]
            summary = database.get_backtest_performance_summary(symbol="BTC/USDT", timeframe="5m")

            self.assertEqual(run["walk_forward_windows"], 2)
            self.assertGreater(run["walk_forward_pass_rate_pct"], 0)
            self.assertGreater(run["walk_forward_avg_oos_return_pct"], 0)
            self.assertIn("avg_walk_forward_pass_rate_pct", summary)
            self.assertGreater(summary["avg_walk_forward_pass_rate_pct"], 0)
            self.assertEqual(results["saved_run_id"], run["id"])
        finally:
            if os.path.exists(temp_db.name):
                os.remove(temp_db.name)

    def test_run_market_scan_ranks_best_market_by_quality_score(self):
        engine = ComparisonBacktestEngine(
            {
                ("BTC/USDT", "5m"): {
                    "stats": {
                        "total_return_pct": 8.0,
                        "profit_factor": 1.45,
                        "expectancy_pct": 0.9,
                        "win_rate": 56.0,
                        "total_trades": 18,
                        "max_drawdown": 10.0,
                    },
                    "validation": {
                        "oos_passed": True,
                        "out_of_sample": {
                            "stats": {
                                "total_return_pct": 4.0,
                                "profit_factor": 1.35,
                                "expectancy_pct": 0.6,
                                "total_trades": 6,
                            }
                        },
                    },
                    "walk_forward": {
                        "overall_passed": True,
                        "pass_rate_pct": 100.0,
                        "avg_oos_return_pct": 3.2,
                        "avg_oos_profit_factor": 1.3,
                    },
                    "saved_run_id": 11,
                },
                ("BTC/USDT", "15m"): {
                    "stats": {
                        "total_return_pct": 2.0,
                        "profit_factor": 1.05,
                        "expectancy_pct": 0.2,
                        "win_rate": 51.0,
                        "total_trades": 12,
                        "max_drawdown": 14.0,
                    },
                    "validation": {
                        "oos_passed": False,
                        "out_of_sample": {
                            "stats": {
                                "total_return_pct": -1.0,
                                "profit_factor": 0.9,
                                "expectancy_pct": -0.1,
                                "total_trades": 4,
                            }
                        },
                    },
                    "walk_forward": {
                        "overall_passed": False,
                        "pass_rate_pct": 33.3,
                        "avg_oos_return_pct": -0.5,
                        "avg_oos_profit_factor": 0.95,
                    },
                    "saved_run_id": 12,
                },
                ("ETH/USDT", "5m"): RuntimeError("Dados insuficientes"),
            }
        )

        scan_results = engine.run_market_scan(
            symbols=["BTC/USDT", "ETH/USDT"],
            timeframes=["5m", "15m"],
            start_date=datetime(2026, 1, 1, 0, 0),
            end_date=datetime(2026, 1, 10, 0, 0),
        )

        self.assertEqual(scan_results["summary"]["requested_runs"], 4)
        self.assertEqual(scan_results["summary"]["completed_runs"], 2)
        self.assertEqual(scan_results["summary"]["failed_runs"], 2)
        self.assertEqual(scan_results["best"]["symbol"], "BTC/USDT")
        self.assertEqual(scan_results["best"]["timeframe"], "5m")
        self.assertGreater(scan_results["best"]["quality_score"], scan_results["rows"][1]["quality_score"])
        self.assertEqual(scan_results["best_result"]["saved_run_id"], 11)
        failed_pairs = {(row["symbol"], row["timeframe"]) for row in scan_results["failed_runs"]}
        self.assertEqual(failed_pairs, {("ETH/USDT", "5m"), ("ETH/USDT", "15m")})

    def test_run_market_scan_requires_non_empty_symbols_and_timeframes(self):
        engine = ComparisonBacktestEngine({})

        with self.assertRaises(ValueError):
            engine.run_market_scan(
                symbols=[],
                timeframes=["5m"],
                start_date=datetime(2026, 1, 1, 0, 0),
                end_date=datetime(2026, 1, 2, 0, 0),
            )

        with self.assertRaises(ValueError):
            engine.run_market_scan(
                symbols=["BTC/USDT"],
                timeframes=[],
                start_date=datetime(2026, 1, 1, 0, 0),
                end_date=datetime(2026, 1, 2, 0, 0),
            )

    def test_run_global_robustness_matrix_aggregates_by_family_and_horizon(self):
        engine = RobustnessMatrixBacktestEngine(
            {
                ("BTC/USDT", 30): {
                    "stats": {
                        "total_return_pct": 8.5,
                        "profit_factor": 1.42,
                        "expectancy_pct": 0.6,
                        "win_rate": 57.0,
                        "total_trades": 18,
                        "max_drawdown": 7.5,
                    },
                    "validation": {
                        "oos_passed": True,
                        "out_of_sample": {
                            "stats": {
                                "total_return_pct": 2.8,
                                "profit_factor": 1.21,
                                "expectancy_pct": 0.22,
                                "total_trades": 6,
                            }
                        },
                    },
                    "walk_forward": {
                        "overall_passed": True,
                        "pass_rate_pct": 100.0,
                        "avg_oos_return_pct": 2.0,
                        "avg_oos_profit_factor": 1.18,
                    },
                    "saved_run_id": 31,
                },
                ("BTC/USDT", 90): {
                    "stats": {
                        "total_return_pct": -1.2,
                        "profit_factor": 0.96,
                        "expectancy_pct": -0.08,
                        "win_rate": 48.0,
                        "total_trades": 20,
                        "max_drawdown": 9.4,
                    },
                    "validation": {
                        "oos_passed": False,
                        "out_of_sample": {
                            "stats": {
                                "total_return_pct": -0.7,
                                "profit_factor": 0.93,
                                "expectancy_pct": -0.05,
                                "total_trades": 7,
                            }
                        },
                    },
                    "walk_forward": {
                        "overall_passed": False,
                        "pass_rate_pct": 33.3,
                        "avg_oos_return_pct": -0.4,
                        "avg_oos_profit_factor": 0.92,
                    },
                    "saved_run_id": 32,
                },
                ("SOL/USDT", 30): {
                    "stats": {
                        "total_return_pct": 5.4,
                        "profit_factor": 1.28,
                        "expectancy_pct": 0.33,
                        "win_rate": 54.0,
                        "total_trades": 14,
                        "max_drawdown": 8.8,
                    },
                    "validation": {
                        "oos_passed": True,
                        "out_of_sample": {
                            "stats": {
                                "total_return_pct": 1.6,
                                "profit_factor": 1.12,
                                "expectancy_pct": 0.14,
                                "total_trades": 5,
                            }
                        },
                    },
                    "walk_forward": {
                        "overall_passed": True,
                        "pass_rate_pct": 66.7,
                        "avg_oos_return_pct": 1.2,
                        "avg_oos_profit_factor": 1.08,
                    },
                    "saved_run_id": 33,
                },
                ("SOL/USDT", 90): RuntimeError("Dados insuficientes"),
            }
        )

        matrix_results = engine.run_global_robustness_matrix(
            symbols=["BTC/USDT", "SOL/USDT"],
            horizon_days=[30, 90],
            timeframe="15m",
            end_date=datetime(2026, 3, 29, 23, 59),
            family_overlay_mode="recommended",
            initial_balance=1_000,
            stop_loss_pct=0.8,
            take_profit_pct=1.8,
            require_volume=False,
            require_trend=False,
            avoid_ranging=False,
        )

        self.assertEqual(matrix_results["summary"]["requested_runs"], 4)
        self.assertEqual(matrix_results["summary"]["completed_runs"], 3)
        self.assertEqual(matrix_results["summary"]["failed_runs"], 1)
        self.assertEqual(matrix_results["summary"]["families_covered"], 2)
        self.assertEqual(matrix_results["summary"]["horizons_covered"], 2)
        self.assertEqual(matrix_results["summary"]["family_overlay_mode_label"], "Overlay por Familia")
        self.assertGreater(matrix_results["summary"]["robustness_score"], 0.0)
        self.assertEqual(matrix_results["best"]["symbol"], "BTC/USDT")
        self.assertEqual(matrix_results["best"]["horizon_days"], 30)

        family_labels = {row["label"] for row in matrix_results["family_breakdown"]}
        self.assertIn("Majors", family_labels)
        self.assertIn("Trend Alts", family_labels)
        horizon_labels = {row["label"] for row in matrix_results["horizon_breakdown"]}
        self.assertEqual(horizon_labels, {"30d", "90d"})

        btc_call = next(call for call in engine.calls if call["symbol"] == "BTC/USDT" and call["horizon_days"] == 30)
        self.assertEqual(btc_call["kwargs"]["stop_loss_pct"], 0.8)
        self.assertEqual(btc_call["kwargs"]["take_profit_pct"], 1.8)
        self.assertFalse(btc_call["kwargs"]["require_trend"])
        self.assertFalse(btc_call["kwargs"]["avoid_ranging"])

        sol_call = next(call for call in engine.calls if call["symbol"] == "SOL/USDT" and call["horizon_days"] == 30)
        self.assertEqual(sol_call["kwargs"]["stop_loss_pct"], AppConfig.get_backtest_family_runtime_overrides("SOL/USDT")["stop_loss_pct"])
        self.assertEqual(sol_call["kwargs"]["take_profit_pct"], AppConfig.get_backtest_family_runtime_overrides("SOL/USDT")["take_profit_pct"])
        self.assertTrue(sol_call["kwargs"]["require_trend"])
        self.assertTrue(sol_call["kwargs"]["avoid_ranging"])

    def test_run_global_robustness_matrix_requires_symbols_horizons_and_timeframe(self):
        engine = RobustnessMatrixBacktestEngine({})

        with self.assertRaises(ValueError):
            engine.run_global_robustness_matrix(
                symbols=[],
                horizon_days=[30],
                timeframe="15m",
                end_date=datetime(2026, 3, 29, 23, 59),
            )

        with self.assertRaises(ValueError):
            engine.run_global_robustness_matrix(
                symbols=["BTC/USDT"],
                horizon_days=[],
                timeframe="15m",
                end_date=datetime(2026, 3, 29, 23, 59),
            )

        with self.assertRaises(ValueError):
            engine.run_global_robustness_matrix(
                symbols=["BTC/USDT"],
                horizon_days=[30],
                timeframe="",
                end_date=datetime(2026, 3, 29, 23, 59),
            )

    def test_optimize_rsi_parameters_prioritizes_robust_candidate(self):
        engine = OptimizationBacktestEngine(
            {
                (20, 70): {
                    "stats": {
                        "total_return_pct": 12.0,
                        "profit_factor": 1.5,
                        "expectancy_pct": 0.8,
                        "win_rate": 55.0,
                        "total_trades": 16,
                        "max_drawdown": 11.0,
                        "sharpe_ratio": 1.2,
                    },
                    "validation": {
                        "oos_passed": True,
                        "out_of_sample": {
                            "stats": {
                                "total_return_pct": 4.0,
                                "profit_factor": 1.3,
                                "expectancy_pct": 0.5,
                                "total_trades": 5,
                            }
                        },
                    },
                    "walk_forward": {
                        "overall_passed": True,
                        "pass_rate_pct": 100.0,
                        "avg_oos_return_pct": 3.0,
                        "avg_oos_profit_factor": 1.25,
                    },
                    "saved_run_id": 21,
                },
                (20, 80): {
                    "stats": {
                        "total_return_pct": 15.0,
                        "profit_factor": 1.6,
                        "expectancy_pct": 0.9,
                        "win_rate": 58.0,
                        "total_trades": 18,
                        "max_drawdown": 13.0,
                        "sharpe_ratio": 1.4,
                    },
                    "validation": {
                        "oos_passed": False,
                        "out_of_sample": {
                            "stats": {
                                "total_return_pct": -2.0,
                                "profit_factor": 0.9,
                                "expectancy_pct": -0.2,
                                "total_trades": 5,
                            }
                        },
                    },
                    "walk_forward": {
                        "overall_passed": False,
                        "pass_rate_pct": 33.3,
                        "avg_oos_return_pct": -0.4,
                        "avg_oos_profit_factor": 0.95,
                    },
                    "saved_run_id": 22,
                },
                (30, 80): RuntimeError("Dados insuficientes"),
            }
        )

        optimization_results = engine.optimize_rsi_parameters(
            symbol="BTC/USDT",
            timeframe="5m",
            rsi_min_range=(20, 30),
            rsi_max_range=(70, 80),
            max_tests=4,
            optimization_metric="Total Return",
            start_date=datetime(2026, 1, 1, 0, 0),
            end_date=datetime(2026, 1, 10, 0, 0),
            initial_balance=1_000,
        )

        self.assertEqual(optimization_results["best"]["rsi_min"], 20)
        self.assertEqual(optimization_results["best"]["rsi_max"], 70)
        self.assertTrue(optimization_results["best"]["robust_candidate"])
        self.assertEqual(optimization_results["best_result"]["saved_run_id"], 21)
        self.assertEqual(optimization_results["summary"]["completed_tests"], 2)
        self.assertEqual(optimization_results["summary"]["failed_tests"], 2)

    def test_should_force_opposite_exit_requires_strong_opposite_context(self):
        engine = BacktestEngine(trading_bot=DeterministicTradingBot())
        should_exit = engine._should_force_opposite_exit(
            position_side="long",
            analytical_signal="VENDA",
            signal_pipeline={
                "trade_decision": {"confidence": 6.4},
                "scenario_evaluation": {"scenario_score": 6.1},
                "confirmation_evaluation": {"confirmation_state": "confirmed"},
                "structure_evaluation": {"structure_state": "continuation"},
            },
        )
        self.assertTrue(should_exit)

    def test_should_force_opposite_exit_ignores_neutral_or_low_quality_reversal(self):
        engine = BacktestEngine(trading_bot=DeterministicTradingBot())
        weak_signal_exit = engine._should_force_opposite_exit(
            position_side="long",
            analytical_signal="NEUTRO",
            signal_pipeline={
                "trade_decision": {"confidence": 8.0},
                "scenario_evaluation": {"scenario_score": 8.0},
                "confirmation_evaluation": {"confirmation_state": "confirmed"},
                "structure_evaluation": {"structure_state": "breakout"},
            },
        )
        weak_context_exit = engine._should_force_opposite_exit(
            position_side="long",
            analytical_signal="VENDA",
            signal_pipeline={
                "trade_decision": {"confidence": 5.0},
                "scenario_evaluation": {"scenario_score": 4.9},
                "confirmation_evaluation": {"confirmation_state": "mixed"},
                "structure_evaluation": {"structure_state": "weak_structure"},
            },
        )
        self.assertFalse(weak_signal_exit)
        self.assertFalse(weak_context_exit)

    def test_build_objective_setup_check_marks_approved_on_robust_metrics(self):
        engine = BacktestEngine(trading_bot=DeterministicTradingBot())

        objective_check = engine._build_objective_setup_check(
            stats={
                "total_trades": 240,
                "total_return_pct": 18.5,
                "profit_factor": 1.42,
                "expectancy_pct": 0.18,
                "max_drawdown": 11.2,
            },
            validation={
                "oos_passed": True,
                "out_of_sample": {
                    "stats": {
                        "total_trades": 72,
                        "total_return_pct": 5.6,
                        "profit_factor": 1.16,
                        "expectancy_pct": 0.07,
                    }
                },
            },
            walk_forward={
                "total_windows": 5,
                "overall_passed": True,
                "pass_rate_pct": 80.0,
                "avg_oos_return_pct": 2.3,
                "avg_oos_profit_factor": 1.08,
            },
            signal_pipeline_stats={
                "candidate_count": 980,
                "approval_rate_pct": 19.7,
            },
            risk_engine_summary={
                "risk_blocked_count": 130,
            },
            market_state_summary=[
                {
                    "market_state": "breakout_expansion",
                    "total_trades": 160,
                    "profit_factor": 1.34,
                    "win_rate": 57.2,
                    "net_profit": 1420.0,
                },
                {
                    "market_state": "trend_pullback",
                    "total_trades": 80,
                    "profit_factor": 1.12,
                    "win_rate": 52.5,
                    "net_profit": 460.0,
                },
            ],
            setup_type_summary=[
                {
                    "setup_type": "continuation_breakout",
                    "total_trades": 160,
                    "profit_factor": 1.34,
                    "win_rate": 57.2,
                    "net_profit": 1420.0,
                },
                {
                    "setup_type": "pullback_trend",
                    "total_trades": 80,
                    "profit_factor": 1.12,
                    "win_rate": 52.5,
                    "net_profit": 460.0,
                },
            ],
        )

        self.assertEqual(objective_check["status"], "approved")
        self.assertGreaterEqual(objective_check["objective_score"], 75.0)
        self.assertEqual(objective_check["recommended_market_state"], "breakout_expansion")
        self.assertEqual(objective_check["approved_market_state"], "breakout_expansion")
        self.assertEqual(objective_check["recommended_setup"], "continuation_breakout")
        self.assertTrue(objective_check["checks"])
        self.assertFalse(objective_check["blockers"])

    def test_build_objective_setup_check_blocks_weak_configuration(self):
        engine = BacktestEngine(trading_bot=DeterministicTradingBot())

        objective_check = engine._build_objective_setup_check(
            stats={
                "total_trades": 42,
                "total_return_pct": -8.2,
                "profit_factor": 0.82,
                "expectancy_pct": -0.11,
                "max_drawdown": 26.4,
            },
            validation={
                "oos_passed": False,
                "out_of_sample": {
                    "stats": {
                        "total_trades": 10,
                        "total_return_pct": -3.6,
                        "profit_factor": 0.74,
                        "expectancy_pct": -0.09,
                    }
                },
            },
            walk_forward={
                "total_windows": 3,
                "overall_passed": False,
                "pass_rate_pct": 33.3,
                "avg_oos_return_pct": -1.2,
                "avg_oos_profit_factor": 0.81,
            },
            signal_pipeline_stats={
                "candidate_count": 220,
                "approval_rate_pct": 3.5,
            },
            risk_engine_summary={
                "risk_blocked_count": 190,
            },
            market_state_summary=[
                {
                    "market_state": "breakout_expansion",
                    "total_trades": 32,
                    "profit_factor": 0.88,
                    "win_rate": 41.0,
                    "net_profit": -540.0,
                }
            ],
            setup_type_summary=[
                {
                    "setup_type": "continuation_breakout",
                    "total_trades": 32,
                    "profit_factor": 0.88,
                    "win_rate": 41.0,
                    "net_profit": -540.0,
                }
            ],
        )

        self.assertEqual(objective_check["status"], "blocked")
        self.assertLess(objective_check["objective_score"], 55.0)
        self.assertTrue(objective_check["blockers"])
        self.assertIn("Amostra insuficiente", " | ".join(objective_check["blockers"]))


class DashboardBacktestIntegrationTests(unittest.TestCase):
    def test_dashboard_passes_existing_risk_and_filter_inputs_to_backtest(self):
        with open("app.py", "r", encoding="utf-8") as app_file:
            source = app_file.read()

        self.assertIn("stop_loss_pct=stop_loss_pct", source)
        self.assertIn("take_profit_pct=take_profit_pct", source)
        self.assertIn("require_volume=enable_volume_filter", source)
        self.assertIn("require_trend=enable_trend_filter", source)
        self.assertIn("validation_split_pct=validation_split_pct if enable_oos_validation else 0.0", source)
        self.assertIn("walk_forward_windows=walk_forward_windows if enable_walk_forward else 0", source)
        self.assertIn("run_market_scan(", source)
        self.assertIn("run_global_robustness_matrix(", source)
        self.assertIn("backtest_scan_results", source)
        self.assertIn("optimize_rsi_parameters(", source)
        self.assertIn("backtest_optimization_results", source)
        self.assertIn("backtest_robustness_results", source)
        self.assertIn("Preset Operacional", source)
        self.assertIn("Contexto Operacional:", source)
        self.assertIn("Leitura de Mercado:", source)
        self.assertIn("Perfil de Risco do Usuário", source)
        self.assertIn("Compatibilidade Legada de Execução", source)
        self.assertIn("bt_setup_focus", source)
        self.assertIn("Cesta de Setups", source)
        self.assertIn('allowed_execution_setups = list(dict.fromkeys(bt_setup_focus)) or None', source)
        self.assertIn("context_timeframe=execution_context_timeframe", source)
        self.assertIn("Criterios de Aprovacao Real", source)
        self.assertIn("Meta de throughput", source)
        self.assertIn("trade_autopsy", source)
        self.assertIn("signal_audit", source)
        self.assertIn("time_analytics", source)
        self.assertIn("objective_check", source)
        self.assertIn("Checagem Objetiva de Sobrevivência", source)
        self.assertIn("Matriz de Robustez Global", source)
        self.assertTrue(
            "Linha do Tempo da Execução" in source
            or "Timeline de Sinais (Backtest)" in source
        )
        self.assertIn("Taxa Aprovação %", source)


class ObjectiveCheckBasketTests(unittest.TestCase):
    def test_objective_check_uses_explicit_setup_basket_for_runtime_promotion(self):
        engine = BacktestEngine(trading_bot=mock.Mock())

        objective = engine._build_objective_setup_check(
            stats={
                "total_trades": 60,
                "total_return_pct": 8.2,
                "profit_factor": 1.36,
                "expectancy_pct": 0.11,
                "max_drawdown": 9.5,
            },
            validation={
                "oos_passed": True,
                "out_of_sample": {
                    "stats": {
                        "total_trades": 18,
                        "total_return_pct": 2.4,
                        "profit_factor": 1.22,
                        "expectancy_pct": 0.04,
                    }
                },
            },
            walk_forward={
                "total_windows": 3,
                "overall_passed": True,
                "pass_rate_pct": 66.7,
                "avg_oos_return_pct": 1.1,
                "avg_oos_profit_factor": 1.19,
                "avg_oos_expectancy_pct": 0.03,
            },
            signal_pipeline_stats={
                "approval_rate_pct": 21.0,
                "candidate_count": 140,
            },
            risk_engine_summary={
                "risk_blocked_count": 14,
            },
            market_state_summary=[
                {
                    "market_state": "breakout_expansion",
                    "total_trades": 42,
                    "profit_factor": 1.42,
                    "win_rate": 54.0,
                    "net_profit": 460.0,
                },
                {
                    "market_state": "trend_pullback",
                    "total_trades": 18,
                    "profit_factor": 1.21,
                    "win_rate": 51.0,
                    "net_profit": 140.0,
                },
            ],
            setup_type_summary=[
                {
                    "setup_type": "continuation_breakout",
                    "total_trades": 42,
                    "profit_factor": 1.42,
                    "win_rate": 54.0,
                    "net_profit": 460.0,
                },
                {
                    "setup_type": "pullback_trend",
                    "total_trades": 18,
                    "profit_factor": 1.21,
                    "win_rate": 51.0,
                    "net_profit": 140.0,
                },
            ],
            allowed_execution_setups=["pullback_trend", "continuation_breakout"],
            start_date=datetime(2026, 2, 1, 0, 0),
            end_date=datetime(2026, 3, 5, 0, 0),
        )

        self.assertEqual(objective["approved_market_state_mode"], "basket")
        self.assertEqual(objective["approved_market_states"], ["breakout_expansion", "trend_pullback"])
        self.assertEqual(objective["approved_market_state_trades"], 60)
        self.assertEqual(objective["approved_market_state"], "breakout_expansion")
        self.assertEqual(objective["approved_setup_mode"], "basket")
        self.assertEqual(objective["approved_setup_types"], ["ema_rsi_resume_long", "ema_rsi_resume_short"])
        self.assertEqual(objective["approved_setup_trades"], 60)
        self.assertEqual(objective["approved_setup_type"], "ema_rsi_resume_long")


if __name__ == "__main__":
    unittest.main()
