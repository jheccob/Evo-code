from __future__ import annotations

from datetime import datetime
import os
import tempfile
import unittest

import pandas as pd

from backtest import BacktestEngine
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
        self.assertEqual(
            list(engine.get_trade_summary_df().columns),
            ["timestamp", "entry_price", "price", "profit_loss_pct", "profit_loss", "signal"],
        )
        self.assertEqual(bot.updated_config["symbol"], "BTC/USDT")

    def test_run_backtest_persists_run_and_trade_metrics_in_sqlite(self):
        bot = DeterministicTradingBot()
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
            summary = database.get_backtest_performance_summary(symbol="BTC/USDT", timeframe="5m")

            self.assertEqual(len(runs), 1)
            self.assertEqual(len(trades), 1)
            self.assertEqual(summary["total_runs"], 1)
            self.assertEqual(summary["total_trades"], 1)
            self.assertEqual(summary["breakdown_by_market"][0]["symbol"], "BTC/USDT")
            self.assertIn("avg_expectancy_pct", summary)
            self.assertEqual(runs[0]["net_profit"], results["stats"]["net_profit"])
            self.assertEqual(trades[0]["setup_name"], results["meta"]["strategy_version"])
            self.assertEqual(trades[0]["strategy_version"], results["meta"]["strategy_version"])
            self.assertEqual(trades[0]["entry_reason"], trades[0]["signal"])
            self.assertEqual(trades[0]["exit_reason"], trades[0]["reason"])
            self.assertEqual(trades[0]["sample_type"], "backtest")
            self.assertGreaterEqual(float(trades[0]["signal_score"]), 0.0)
        finally:
            if os.path.exists(temp_db.name):
                os.remove(temp_db.name)

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
        self.assertIn("backtest_scan_results", source)
        self.assertIn("optimize_rsi_parameters(", source)
        self.assertIn("backtest_optimization_results", source)


if __name__ == "__main__":
    unittest.main()
