from __future__ import annotations

from datetime import datetime
import os
import tempfile
import unittest
from unittest import mock

import pandas as pd

from config import ProductionConfig
from database.database import TradingDatabase, build_strategy_version
from services.paper_trade_service import PaperTradeService


class PaperTradeServiceTests(unittest.TestCase):
    def setUp(self):
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()
        if os.path.exists(temp_db.name):
            os.remove(temp_db.name)

        self.db_path = temp_db.name
        self.database = TradingDatabase(db_path=self.db_path)
        self.service = PaperTradeService(database=self.database, max_hold_candles=3)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_register_signal_deduplicates_same_direction_trade(self):
        first_id = self.service.register_signal(
            symbol="BTC/USDT",
            timeframe="5m",
            signal="COMPRA",
            entry_price=100.0,
            entry_timestamp=datetime(2026, 1, 1, 10, 0),
            source="test",
        )
        second_id = self.service.register_signal(
            symbol="BTC/USDT",
            timeframe="5m",
            signal="COMPRA_FRACA",
            entry_price=101.0,
            entry_timestamp=datetime(2026, 1, 1, 10, 5),
            source="test",
        )

        open_trades = self.database.get_open_paper_trades(symbol="BTC/USDT", timeframe="5m")

        self.assertEqual(first_id, second_id)
        self.assertEqual(len(open_trades), 1)

    def test_evaluate_open_trades_closes_trade_at_take_profit(self):
        self.service.register_signal(
            symbol="BTC/USDT",
            timeframe="5m",
            signal="COMPRA",
            entry_price=100.0,
            entry_timestamp=datetime(2026, 1, 1, 10, 0),
            source="test",
            stop_loss_pct=2.0,
            take_profit_pct=4.0,
        )

        market_data = pd.DataFrame(
            {
                "open": [100.0, 100.0],
                "high": [101.0, 104.5],
                "low": [99.5, 99.9],
                "close": [100.5, 104.0],
                "volume": [1_000.0, 1_000.0],
            },
            index=[
                pd.Timestamp("2026-01-01 10:00:00"),
                pd.Timestamp("2026-01-01 10:05:00"),
            ],
        )

        closed = self.service.evaluate_open_trades("BTC/USDT", "5m", market_data)
        summary = self.service.get_summary(symbol="BTC/USDT", timeframe="5m")

        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["outcome"], "WIN")
        self.assertEqual(summary["open_trades"], 0)
        self.assertEqual(summary["wins"], 1)
        self.assertEqual(summary["win_rate"], 100.0)

    def test_evaluate_open_trades_ignores_entry_candle_range(self):
        self.service.register_signal(
            symbol="BTC/USDT",
            timeframe="5m",
            signal="COMPRA",
            entry_price=100.0,
            entry_timestamp=datetime(2026, 1, 1, 10, 0),
            source="test",
            stop_loss_pct=2.0,
            take_profit_pct=4.0,
        )

        market_data = pd.DataFrame(
            {
                "open": [100.0, 100.0],
                "high": [104.5, 101.0],
                "low": [99.5, 99.4],
                "close": [100.5, 100.4],
                "volume": [1_000.0, 1_000.0],
            },
            index=[
                pd.Timestamp("2026-01-01 10:00:00"),
                pd.Timestamp("2026-01-01 10:05:00"),
            ],
        )

        closed = self.service.evaluate_open_trades("BTC/USDT", "5m", market_data)
        summary = self.service.get_summary(symbol="BTC/USDT", timeframe="5m")

        self.assertEqual(len(closed), 0)
        self.assertEqual(summary["open_trades"], 1)

    def test_evaluate_open_trades_uses_closed_candles_only_when_flag_present(self):
        self.service.register_signal(
            symbol="BTC/USDT",
            timeframe="5m",
            signal="COMPRA",
            entry_price=100.0,
            entry_timestamp=datetime(2026, 1, 1, 10, 0),
            source="test",
            stop_loss_pct=2.0,
            take_profit_pct=4.0,
        )

        market_data = pd.DataFrame(
            {
                "open": [100.0, 100.0],
                "high": [101.0, 104.5],
                "low": [99.5, 99.9],
                "close": [100.5, 104.0],
                "volume": [1_000.0, 1_000.0],
                "is_closed": [True, False],
            },
            index=[
                pd.Timestamp("2026-01-01 10:05:00"),
                pd.Timestamp("2026-01-01 10:10:00"),
            ],
        )

        closed = self.service.evaluate_open_trades("BTC/USDT", "5m", market_data)
        summary = self.service.get_summary(symbol="BTC/USDT", timeframe="5m")

        self.assertEqual(len(closed), 0)
        self.assertEqual(summary["open_trades"], 1)

    def test_paper_trade_result_pct_includes_fee_and_slippage_costs(self):
        service = PaperTradeService(
            database=self.database,
            max_hold_candles=3,
            fee_rate=0.001,
            slippage=0.0005,
        )
        service.register_signal(
            symbol="BTC/USDT",
            timeframe="5m",
            signal="COMPRA",
            entry_price=100.0,
            entry_timestamp=datetime(2026, 1, 1, 10, 0),
            source="test",
            stop_loss_pct=2.0,
            take_profit_pct=4.0,
        )

        market_data = pd.DataFrame(
            {
                "open": [100.0, 100.0],
                "high": [101.0, 104.5],
                "low": [99.5, 99.9],
                "close": [100.5, 104.0],
                "volume": [1_000.0, 1_000.0],
            },
            index=[
                pd.Timestamp("2026-01-01 10:00:00"),
                pd.Timestamp("2026-01-01 10:05:00"),
            ],
        )

        closed = service.evaluate_open_trades("BTC/USDT", "5m", market_data)

        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["outcome"], "WIN")
        self.assertLess(closed[0]["result_pct"], 4.0)
        self.assertGreater(closed[0]["result_pct"], 3.0)

    def test_evaluate_open_trades_persists_break_even_management_state(self):
        service = PaperTradeService(
            database=self.database,
            max_hold_candles=5,
            fee_rate=0.0,
            slippage=0.0,
        )
        service.register_signal(
            symbol="BTC/USDT",
            timeframe="5m",
            signal="COMPRA",
            entry_price=100.0,
            entry_timestamp=datetime(2026, 1, 1, 10, 0),
            source="test",
            stop_loss_pct=2.0,
            take_profit_pct=6.0,
        )

        market_data = pd.DataFrame(
            {
                "open": [100.0],
                "high": [102.4],
                "low": [100.2],
                "close": [102.1],
                "volume": [1_000.0],
                "atr": [1.0],
                "ema_21": [101.0],
                "market_regime": ["trend_bull"],
                "volatility_state": ["normal_volatility"],
                "regime_score": [8.0],
                "parabolic": [False],
            },
            index=[pd.Timestamp("2026-01-01 10:05:00")],
        )

        closed = service.evaluate_open_trades("BTC/USDT", "5m", market_data)
        open_trades = self.database.get_open_paper_trades(symbol="BTC/USDT", timeframe="5m")

        self.assertEqual(len(closed), 0)
        self.assertEqual(len(open_trades), 1)
        self.assertEqual(open_trades[0]["break_even_active"], 1)
        self.assertGreaterEqual(float(open_trades[0]["stop_loss_price"]), float(open_trades[0]["entry_price"]))

    def test_register_signal_flips_existing_trade(self):
        first_id = self.service.register_signal(
            symbol="BTC/USDT",
            timeframe="5m",
            signal="COMPRA",
            entry_price=100.0,
            entry_timestamp=datetime(2026, 1, 1, 10, 0),
            source="test",
        )

        second_id = self.service.register_signal(
            symbol="BTC/USDT",
            timeframe="5m",
            signal="VENDA",
            entry_price=102.0,
            entry_timestamp=datetime(2026, 1, 1, 10, 5),
            source="test",
        )

        recent_trades = self.database.get_recent_paper_trades(symbol="BTC/USDT", timeframe="5m")
        open_trades = self.database.get_open_paper_trades(symbol="BTC/USDT", timeframe="5m")

        self.assertNotEqual(first_id, second_id)
        self.assertEqual(len(open_trades), 1)
        self.assertEqual(open_trades[0]["side"], "short")
        self.assertTrue(any(trade["close_reason"] == "SIGNAL_FLIP" for trade in recent_trades))

    def test_register_signal_persists_setup_and_signal_metadata(self):
        strategy_version = build_strategy_version("BTC/USDT", "5m", 14, 20, 70, 0.0, 0.0, True, False)

        trade_id = self.service.register_signal(
            symbol="BTC/USDT",
            timeframe="5m",
            signal="COMPRA",
            entry_price=100.0,
            entry_timestamp=datetime(2026, 1, 1, 10, 0),
            context_timeframe="1h",
            source="test",
            strategy_version=strategy_version,
            setup_name="setup-btc-5m",
            regime="trending",
            signal_score=74.5,
            atr=1.23,
            entry_reason="COMPRA",
            sample_type="paper",
        )

        open_trades = self.database.get_open_paper_trades(symbol="BTC/USDT", timeframe="5m")

        self.assertEqual(trade_id, open_trades[0]["id"])
        self.assertEqual(open_trades[0]["setup_name"], "setup-btc-5m")
        self.assertEqual(open_trades[0]["strategy_version"], strategy_version)
        self.assertEqual(open_trades[0]["context_timeframe"], "1h")
        self.assertEqual(open_trades[0]["regime"], "trending")
        self.assertEqual(open_trades[0]["signal_score"], 74.5)
        self.assertEqual(open_trades[0]["atr"], 1.23)
        self.assertEqual(open_trades[0]["entry_reason"], "COMPRA")
        self.assertEqual(open_trades[0]["sample_type"], "paper")

    def test_edge_monitor_flags_degraded_live_performance_against_backtest(self):
        self.database.save_backtest_result(
            {
                "symbol": "BTC/USDT",
                "timeframe": "5m",
                "start_date": "2026-01-01T00:00:00",
                "end_date": "2026-01-10T00:00:00",
                "initial_balance": 1000.0,
                "final_balance": 1080.0,
                "net_profit": 80.0,
                "total_return_pct": 8.0,
                "total_trades": 20,
                "winning_trades": 12,
                "losing_trades": 8,
                "win_rate": 60.0,
                "max_drawdown": 9.0,
                "sharpe_ratio": 1.4,
                "profit_factor": 1.5,
                "avg_profit": 1.2,
                "avg_loss": -0.8,
                "expectancy_pct": 0.5,
                "rsi_period": 14,
                "rsi_min": 20,
                "rsi_max": 70,
                "out_of_sample_return_pct": 5.0,
                "out_of_sample_profit_factor": 1.4,
                "out_of_sample_expectancy_pct": 0.4,
                "out_of_sample_passed": True,
                "walk_forward_passed": True,
                "walk_forward_pass_rate_pct": 100.0,
                "walk_forward_avg_oos_profit_factor": 1.3,
            },
            [],
        )

        paper_results = [1.0, -1.2, 0.8, -1.0, -0.9]
        for index, result_pct in enumerate(paper_results):
            outcome = "WIN" if result_pct > 0 else "LOSS"
            self.database.create_paper_trade(
                {
                    "symbol": "BTC/USDT",
                    "timeframe": "5m",
                    "signal": "COMPRA" if index % 2 == 0 else "VENDA",
                    "side": "long" if index % 2 == 0 else "short",
                    "source": "test",
                    "entry_timestamp": f"2026-01-0{index + 1}T10:00:00",
                    "entry_price": 100.0,
                    "status": "CLOSED",
                    "outcome": outcome,
                    "close_reason": "TAKE_PROFIT" if outcome == "WIN" else "STOP_LOSS",
                    "exit_timestamp": f"2026-01-0{index + 1}T10:05:00",
                    "exit_price": 101.0 if outcome == "WIN" else 99.0,
                    "result_pct": result_pct,
                }
            )

        with mock.patch.object(ProductionConfig, "MIN_PAPER_TRADES_FOR_EDGE_VALIDATION", 5):
            edge_summary = self.database.get_edge_monitor_summary(symbol="BTC/USDT", timeframe="5m")

        self.assertEqual(edge_summary["baseline_source"], "OOS")
        self.assertEqual(edge_summary["paper_closed_trades"], 5)
        self.assertLess(edge_summary["paper_profit_factor"], 1.0)
        self.assertEqual(edge_summary["status"], "degraded")

    def test_promoted_strategy_profile_scopes_edge_monitor_to_active_version(self):
        strategy_v1 = build_strategy_version("BTC/USDT", "5m", 14, 20, 70, 0.0, 0.0, True, False)
        strategy_v2 = build_strategy_version("BTC/USDT", "5m", 14, 25, 75, 0.0, 0.0, True, False)

        run_v1 = self.database.save_backtest_result(
            {
                "symbol": "BTC/USDT",
                "timeframe": "5m",
                "strategy_version": strategy_v1,
                "start_date": "2026-01-01T00:00:00",
                "end_date": "2026-01-10T00:00:00",
                "initial_balance": 1000.0,
                "final_balance": 1070.0,
                "net_profit": 70.0,
                "total_return_pct": 7.0,
                "total_trades": 12,
                "winning_trades": 7,
                "losing_trades": 5,
                "win_rate": 58.0,
                "max_drawdown": 8.0,
                "sharpe_ratio": 1.2,
                "profit_factor": 1.4,
                "avg_profit": 1.1,
                "avg_loss": -0.7,
                "expectancy_pct": 0.4,
                "rsi_period": 14,
                "rsi_min": 20,
                "rsi_max": 70,
                "require_volume": True,
                "out_of_sample_return_pct": 4.5,
                "out_of_sample_profit_factor": 1.3,
                "out_of_sample_expectancy_pct": 0.35,
                "out_of_sample_passed": True,
            },
            [],
        )
        self.database.save_backtest_result(
            {
                "symbol": "BTC/USDT",
                "timeframe": "5m",
                "strategy_version": strategy_v2,
                "start_date": "2026-01-01T00:00:00",
                "end_date": "2026-01-10T00:00:00",
                "initial_balance": 1000.0,
                "final_balance": 980.0,
                "net_profit": -20.0,
                "total_return_pct": -2.0,
                "total_trades": 11,
                "winning_trades": 4,
                "losing_trades": 7,
                "win_rate": 36.0,
                "max_drawdown": 14.0,
                "sharpe_ratio": -0.4,
                "profit_factor": 0.8,
                "avg_profit": 0.8,
                "avg_loss": -1.1,
                "expectancy_pct": -0.2,
                "rsi_period": 14,
                "rsi_min": 25,
                "rsi_max": 75,
                "require_volume": True,
                "out_of_sample_return_pct": -1.5,
                "out_of_sample_profit_factor": 0.75,
                "out_of_sample_expectancy_pct": -0.2,
                "out_of_sample_passed": False,
            },
            [],
        )

        for result_pct in [1.0, 0.8, -0.4, 0.7, 0.6]:
            self.database.create_paper_trade(
                {
                    "symbol": "BTC/USDT",
                    "timeframe": "5m",
                    "strategy_version": strategy_v1,
                    "signal": "COMPRA",
                    "side": "long",
                    "source": "test",
                    "entry_timestamp": "2026-01-01T10:00:00",
                    "entry_price": 100.0,
                    "status": "CLOSED",
                    "outcome": "WIN" if result_pct > 0 else "LOSS",
                    "close_reason": "TAKE_PROFIT",
                    "exit_timestamp": "2026-01-01T10:05:00",
                    "exit_price": 101.0,
                    "result_pct": result_pct,
                }
            )
        for result_pct in [-0.8, -1.0, 0.2]:
            self.database.create_paper_trade(
                {
                    "symbol": "BTC/USDT",
                    "timeframe": "5m",
                    "strategy_version": strategy_v2,
                    "signal": "COMPRA",
                    "side": "long",
                    "source": "test",
                    "entry_timestamp": "2026-01-02T10:00:00",
                    "entry_price": 100.0,
                    "status": "CLOSED",
                    "outcome": "WIN" if result_pct > 0 else "LOSS",
                    "close_reason": "TAKE_PROFIT" if result_pct > 0 else "STOP_LOSS",
                    "exit_timestamp": "2026-01-02T10:05:00",
                    "exit_price": 101.0,
                    "result_pct": result_pct,
                }
            )

        with mock.patch.object(ProductionConfig, "MIN_PAPER_TRADES_FOR_EDGE_VALIDATION", 5):
            promoted = self.database.promote_backtest_run(run_v1, notes="Promovido no teste")
            edge_summary = self.database.get_edge_monitor_summary(symbol="BTC/USDT", timeframe="5m")

        self.assertIsNotNone(promoted)
        self.assertEqual(edge_summary["strategy_version"], strategy_v1)
        self.assertEqual(edge_summary["paper_closed_trades"], 5)
        self.assertGreater(edge_summary["paper_profit_factor"], 1.0)
        self.assertEqual(edge_summary["status"], "aligned")

    def test_promotion_readiness_blocks_unrobust_backtest_runs(self):
        run_id = self.database.save_backtest_result(
            {
                "symbol": "BTC/USDT",
                "timeframe": "5m",
                "start_date": "2026-01-01T00:00:00",
                "end_date": "2026-01-10T00:00:00",
                "initial_balance": 1000.0,
                "final_balance": 995.0,
                "net_profit": -5.0,
                "total_return_pct": -0.5,
                "total_trades": 4,
                "winning_trades": 2,
                "losing_trades": 2,
                "win_rate": 50.0,
                "max_drawdown": 25.0,
                "sharpe_ratio": -0.1,
                "profit_factor": 0.9,
                "avg_profit": 0.4,
                "avg_loss": -0.5,
                "expectancy_pct": -0.02,
                "rsi_period": 14,
                "rsi_min": 20,
                "rsi_max": 70,
                "out_of_sample_passed": False,
            },
            [],
        )

        readiness = self.database.get_backtest_run_promotion_readiness(run_id)
        promoted = self.database.promote_backtest_run(run_id, notes="Nao deveria ativar")

        self.assertFalse(readiness["ready"])
        self.assertGreaterEqual(len(readiness["reasons"]), 3)
        self.assertIsNone(promoted)

    def test_backtest_save_creates_strategy_evaluation_snapshot(self):
        strategy_version = build_strategy_version("BTC/USDT", "5m", 14, 20, 70, 0.0, 0.0, True, False)

        run_id = self.database.save_backtest_result(
            {
                "symbol": "BTC/USDT",
                "timeframe": "5m",
                "strategy_version": strategy_version,
                "start_date": "2026-01-01T00:00:00",
                "end_date": "2026-01-10T00:00:00",
                "initial_balance": 1000.0,
                "final_balance": 1080.0,
                "net_profit": 80.0,
                "total_return_pct": 8.0,
                "total_trades": 20,
                "winning_trades": 12,
                "losing_trades": 8,
                "win_rate": 60.0,
                "max_drawdown": 9.0,
                "sharpe_ratio": 1.4,
                "profit_factor": 1.5,
                "avg_profit": 1.2,
                "avg_loss": -0.8,
                "expectancy_pct": 0.5,
                "rsi_period": 14,
                "rsi_min": 20,
                "rsi_max": 70,
                "require_volume": True,
                "out_of_sample_return_pct": 5.0,
                "out_of_sample_profit_factor": 1.4,
                "out_of_sample_expectancy_pct": 0.4,
                "out_of_sample_passed": True,
                "walk_forward_passed": True,
                "walk_forward_pass_rate_pct": 100.0,
                "walk_forward_avg_oos_profit_factor": 1.3,
            },
            [],
        )

        evaluations = self.database.get_strategy_evaluations(
            symbol="BTC/USDT",
            timeframe="5m",
            strategy_version=strategy_version,
            evaluation_type="backtest",
        )

        self.assertIsInstance(run_id, int)
        self.assertEqual(len(evaluations), 1)
        self.assertEqual(evaluations[0]["evaluation_type"], "backtest")
        self.assertEqual(evaluations[0]["edge_status"], "awaiting_live_data")
        self.assertGreater(evaluations[0]["quality_score"], 0)

    def test_backtest_performance_summary_uses_trade_level_aggregates(self):
        self.database.save_backtest_result(
            {
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategy_version": "setup-a",
                "start_date": "2026-01-01T00:00:00",
                "end_date": "2026-01-10T00:00:00",
                "initial_balance": 1000.0,
                "final_balance": 1050.0,
                "net_profit": 50.0,
                "total_return_pct": 5.0,
                "total_trades": 2,
                "winning_trades": 1,
                "losing_trades": 1,
                "win_rate": 100.0,
                "max_drawdown": 4.0,
                "sharpe_ratio": 1.0,
                "profit_factor": 9.9,
                "avg_profit": 10.0,
                "avg_loss": -5.0,
                "expectancy_pct": 9.9,
            },
            [
                {
                    "entry_timestamp": "2026-01-02T10:00:00",
                    "timestamp": "2026-01-02T11:00:00",
                    "entry_price": 100.0,
                    "price": 110.0,
                    "profit_loss_pct": 10.0,
                    "profit_loss": 100.0,
                    "signal": "COMPRA",
                    "side": "long",
                    "reason": "TAKE_PROFIT",
                },
                {
                    "entry_timestamp": "2026-01-03T10:00:00",
                    "timestamp": "2026-01-03T11:00:00",
                    "entry_price": 100.0,
                    "price": 95.0,
                    "profit_loss_pct": -5.0,
                    "profit_loss": -50.0,
                    "signal": "VENDA",
                    "side": "short",
                    "reason": "STOP_LOSS",
                },
            ],
        )
        self.database.save_backtest_result(
            {
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategy_version": "setup-b",
                "start_date": "2026-01-11T00:00:00",
                "end_date": "2026-01-20T00:00:00",
                "initial_balance": 1000.0,
                "final_balance": 1030.0,
                "net_profit": 30.0,
                "total_return_pct": 3.0,
                "total_trades": 1,
                "winning_trades": 1,
                "losing_trades": 0,
                "win_rate": 0.0,
                "max_drawdown": 2.0,
                "sharpe_ratio": 0.5,
                "profit_factor": 0.1,
                "avg_profit": 3.0,
                "avg_loss": 0.0,
                "expectancy_pct": -9.9,
            },
            [
                {
                    "entry_timestamp": "2026-01-12T10:00:00",
                    "timestamp": "2026-01-12T11:00:00",
                    "entry_price": 100.0,
                    "price": 103.0,
                    "profit_loss_pct": 3.0,
                    "profit_loss": 30.0,
                    "signal": "COMPRA",
                    "side": "long",
                    "reason": "TAKE_PROFIT",
                }
            ],
        )

        summary = self.database.get_backtest_performance_summary(symbol="BTC/USDT", timeframe="1h")
        breakdown = summary["breakdown_by_market"][0]

        self.assertEqual(summary["aggregate_total_trades"], 3)
        self.assertEqual(summary["avg_profit_factor"], 2.6)
        self.assertEqual(summary["avg_expectancy_pct"], 2.67)
        self.assertEqual(summary["avg_win_rate"], 66.67)
        self.assertEqual(breakdown["avg_profit_factor"], 2.6)
        self.assertEqual(breakdown["avg_expectancy_pct"], 2.67)
        self.assertEqual(breakdown["avg_win_rate"], 66.67)

    def test_close_paper_trade_creates_strategy_evaluation_snapshot(self):
        strategy_version = build_strategy_version("ETH/USDT", "15m", 14, 25, 75, 0.0, 0.0, True, False)

        trade_id = self.database.create_paper_trade(
            {
                "symbol": "ETH/USDT",
                "timeframe": "15m",
                "strategy_version": strategy_version,
                "signal": "COMPRA",
                "side": "long",
                "source": "test",
                "entry_timestamp": "2026-01-01T10:00:00",
                "entry_price": 100.0,
                "planned_position_notional": 1000.0,
                "account_reference_balance": 10000.0,
                "status": "OPEN",
            }
        )

        self.database.close_paper_trade(
            trade_id=trade_id,
            exit_timestamp="2026-01-01T10:05:00",
            exit_price=104.0,
            outcome="WIN",
            close_reason="TAKE_PROFIT",
            result_pct=4.0,
        )

        evaluations = self.database.get_strategy_evaluations(
            symbol="ETH/USDT",
            timeframe="15m",
            strategy_version=strategy_version,
            evaluation_type="paper",
        )
        recent_trades = self.database.get_recent_paper_trades(symbol="ETH/USDT", timeframe="15m")

        self.assertEqual(len(evaluations), 1)
        self.assertEqual(evaluations[0]["paper_closed_trades"], 1)
        self.assertEqual(evaluations[0]["evaluation_type"], "paper")
        self.assertEqual(recent_trades[0]["exit_reason"], "TAKE_PROFIT")

    def test_strategy_evaluation_overview_returns_latest_snapshot_per_strategy(self):
        strategy_v1 = build_strategy_version("BTC/USDT", "5m", 14, 20, 70, 0.0, 0.0, True, False)
        strategy_v2 = build_strategy_version("ETH/USDT", "15m", 14, 25, 75, 0.0, 0.0, True, False)

        self.database.save_strategy_evaluation(
            {
                "symbol": "BTC/USDT",
                "timeframe": "5m",
                "strategy_version": strategy_v1,
                "evaluation_type": "backtest",
                "avg_profit_factor": 1.4,
                "avg_out_of_sample_profit_factor": 1.3,
                "paper_profit_factor": 0.0,
                "edge_status": "awaiting_live_data",
                "governance_status": "observing",
                "quality_score": 61.0,
            }
        )
        self.database.save_strategy_evaluation(
            {
                "symbol": "BTC/USDT",
                "timeframe": "5m",
                "strategy_version": strategy_v1,
                "evaluation_type": "paper",
                "avg_profit_factor": 1.4,
                "avg_out_of_sample_profit_factor": 1.3,
                "paper_profit_factor": 1.5,
                "edge_status": "aligned",
                "governance_status": "approved",
                "quality_score": 74.0,
            }
        )
        self.database.save_strategy_evaluation(
            {
                "symbol": "ETH/USDT",
                "timeframe": "15m",
                "strategy_version": strategy_v2,
                "evaluation_type": "backtest",
                "avg_profit_factor": 0.9,
                "avg_out_of_sample_profit_factor": 0.8,
                "paper_profit_factor": 0.0,
                "edge_status": "no_backtest",
                "governance_status": "blocked",
                "quality_score": 18.0,
            }
        )

        overview = self.database.get_strategy_evaluation_overview(limit=10)
        by_version = {row["strategy_version"]: row for row in overview["rows"]}

        self.assertEqual(overview["total_strategies"], 2)
        self.assertEqual(by_version[strategy_v1]["evaluation_type"], "paper")
        self.assertEqual(by_version[strategy_v1]["governance_status"], "approved")
        self.assertEqual(by_version[strategy_v2]["governance_status"], "blocked")
        self.assertEqual(overview["governance_counts"]["approved"], 1)
        self.assertEqual(overview["governance_counts"]["blocked"], 1)
        self.assertEqual(overview["edge_counts"]["aligned"], 1)

    def test_strategy_governance_summary_classifies_profiles_objectively(self):
        strategy_ready = build_strategy_version("BTC/USDT", "5m", 14, 20, 70, 0.0, 0.0, True, False)
        strategy_active = build_strategy_version("ETH/USDT", "15m", 14, 25, 75, 0.0, 0.0, True, False)

        ready_run = self.database.save_backtest_result(
            {
                "symbol": "BTC/USDT",
                "timeframe": "5m",
                "strategy_version": strategy_ready,
                "start_date": "2026-01-01T00:00:00",
                "end_date": "2026-01-10T00:00:00",
                "initial_balance": 1000.0,
                "final_balance": 1060.0,
                "net_profit": 60.0,
                "total_return_pct": 6.0,
                "total_trades": 12,
                "winning_trades": 7,
                "losing_trades": 5,
                "win_rate": 58.0,
                "max_drawdown": 8.0,
                "sharpe_ratio": 1.1,
                "profit_factor": 1.4,
                "avg_profit": 1.0,
                "avg_loss": -0.7,
                "expectancy_pct": 0.3,
                "rsi_period": 14,
                "rsi_min": 20,
                "rsi_max": 70,
                "require_volume": True,
                "out_of_sample_return_pct": 3.0,
                "out_of_sample_profit_factor": 1.3,
                "out_of_sample_expectancy_pct": 0.2,
                "out_of_sample_passed": True,
            },
            [],
        )
        self.database.save_strategy_profile(
            {
                "symbol": "BTC/USDT",
                "timeframe": "5m",
                "strategy_version": strategy_ready,
                "status": "draft",
                "rsi_period": 14,
                "rsi_min": 20,
                "rsi_max": 70,
                "require_volume": True,
                "source_run_id": ready_run,
            }
        )

        active_run = self.database.save_backtest_result(
            {
                "symbol": "ETH/USDT",
                "timeframe": "15m",
                "strategy_version": strategy_active,
                "start_date": "2026-01-01T00:00:00",
                "end_date": "2026-01-10T00:00:00",
                "initial_balance": 1000.0,
                "final_balance": 1080.0,
                "net_profit": 80.0,
                "total_return_pct": 8.0,
                "total_trades": 20,
                "winning_trades": 12,
                "losing_trades": 8,
                "win_rate": 60.0,
                "max_drawdown": 9.0,
                "sharpe_ratio": 1.4,
                "profit_factor": 1.5,
                "avg_profit": 1.2,
                "avg_loss": -0.8,
                "expectancy_pct": 0.5,
                "rsi_period": 14,
                "rsi_min": 25,
                "rsi_max": 75,
                "require_volume": True,
                "out_of_sample_return_pct": 5.0,
                "out_of_sample_profit_factor": 1.4,
                "out_of_sample_expectancy_pct": 0.4,
                "out_of_sample_passed": True,
            },
            [],
        )

        for result_pct in [1.0, 0.8, -0.2, 0.7, 0.6]:
            self.database.create_paper_trade(
                {
                    "symbol": "ETH/USDT",
                    "timeframe": "15m",
                    "strategy_version": strategy_active,
                    "signal": "COMPRA",
                    "side": "long",
                    "source": "test",
                    "entry_timestamp": "2026-01-01T10:00:00",
                    "entry_price": 100.0,
                    "status": "CLOSED",
                    "outcome": "WIN" if result_pct > 0 else "LOSS",
                    "close_reason": "TAKE_PROFIT" if result_pct > 0 else "STOP_LOSS",
                    "exit_timestamp": "2026-01-01T10:05:00",
                    "exit_price": 101.0,
                    "result_pct": result_pct,
                }
            )

        with mock.patch.object(ProductionConfig, "MIN_PAPER_TRADES_FOR_EDGE_VALIDATION", 5), \
             mock.patch.object(ProductionConfig, "GOVERNANCE_MIN_ALIGNMENT_TRADES", 5), \
             mock.patch.object(ProductionConfig, "MIN_LIVE_QUALITY_SCORE", 10.0):
            self.database.promote_backtest_run(active_run, notes="Ativo no teste")
            governance = self.database.get_strategy_governance_summary(limit=10)

        governance_by_version = {
            row["strategy_version"]: row["governance_status"]
            for row in governance["profiles"]
        }

        self.assertEqual(governance_by_version[strategy_ready], "candidate")
        self.assertEqual(governance_by_version[strategy_active], "approved")

    def test_live_execution_readiness_is_blocked_when_live_is_disabled(self):
        readiness = self.database.get_live_execution_readiness(symbol="BTC/USDT", timeframe="5m")

        self.assertFalse(readiness["allowed"])
        self.assertIn("Execucao live desabilitada por configuracao.", readiness["reasons"])

    def test_live_execution_readiness_requires_approved_governance(self):
        strategy_active = build_strategy_version("ETH/USDT", "15m", 14, 25, 75, 0.0, 0.0, True, False)
        active_run = self.database.save_backtest_result(
            {
                "symbol": "ETH/USDT",
                "timeframe": "15m",
                "strategy_version": strategy_active,
                "start_date": "2026-01-01T00:00:00",
                "end_date": "2026-01-10T00:00:00",
                "initial_balance": 1000.0,
                "final_balance": 1080.0,
                "net_profit": 80.0,
                "total_return_pct": 8.0,
                "total_trades": 20,
                "winning_trades": 12,
                "losing_trades": 8,
                "win_rate": 60.0,
                "max_drawdown": 9.0,
                "sharpe_ratio": 1.4,
                "profit_factor": 1.5,
                "avg_profit": 1.2,
                "avg_loss": -0.8,
                "expectancy_pct": 0.5,
                "rsi_period": 14,
                "rsi_min": 25,
                "rsi_max": 75,
                "require_volume": True,
                "out_of_sample_return_pct": 5.0,
                "out_of_sample_profit_factor": 1.4,
                "out_of_sample_expectancy_pct": 0.4,
                "out_of_sample_passed": True,
            },
            [],
        )

        for result_pct in [1.0, 0.8, -0.2, 0.7, 0.6]:
            self.database.create_paper_trade(
                {
                    "symbol": "ETH/USDT",
                    "timeframe": "15m",
                    "strategy_version": strategy_active,
                    "signal": "COMPRA",
                    "side": "long",
                    "source": "test",
                    "entry_timestamp": "2026-01-01T10:00:00",
                    "entry_price": 100.0,
                    "status": "CLOSED",
                    "outcome": "WIN" if result_pct > 0 else "LOSS",
                    "close_reason": "TAKE_PROFIT" if result_pct > 0 else "STOP_LOSS",
                    "exit_timestamp": "2026-01-01T10:05:00",
                    "exit_price": 101.0,
                    "result_pct": result_pct,
                }
            )

        with mock.patch.object(ProductionConfig, "ENABLE_LIVE_EXECUTION", True), \
             mock.patch.object(ProductionConfig, "MIN_PAPER_TRADES_FOR_EDGE_VALIDATION", 5), \
             mock.patch.object(ProductionConfig, "GOVERNANCE_MIN_ALIGNMENT_TRADES", 5), \
             mock.patch.object(ProductionConfig, "MIN_LIVE_QUALITY_SCORE", 40.0):
            self.database.promote_backtest_run(active_run, notes="Aprovado para teste")
            readiness = self.database.get_live_execution_readiness(symbol="ETH/USDT", timeframe="15m")

        self.assertTrue(readiness["allowed"])
        self.assertEqual(readiness["governance_status"], "approved")
        self.assertEqual(readiness["edge_status"], "aligned")


class PaperTradeIntegrationSourceTests(unittest.TestCase):
    def test_dashboard_and_telegram_sources_call_paper_trade_service(self):
        with open("app.py", "r", encoding="utf-8") as app_file:
            app_source = app_file.read()

        with open("telegram_bot.py", "r", encoding="utf-8") as bot_file:
            bot_source = bot_file.read()

        self.assertIn("get_paper_trade_service().evaluate_open_trades", app_source)
        self.assertIn("get_paper_trade_service().register_signal", app_source)
        self.assertIn("get_paper_trade_service().get_summary", app_source)
        self.assertIn("get_edge_monitor_summary", app_source)
        self.assertIn("apply_edge_guardrail", app_source)
        self.assertIn("get_risk_management_service().evaluate_risk_engine", app_source)
        self.assertIn("promote_backtest_run", app_source)
        self.assertIn("get_strategy_governance_summary", app_source)
        self.assertIn("evaluate_strategy_governance", app_source)
        self.assertIn("get_setup_regime_baselines", app_source)
        self.assertIn("get_alignment_metrics", app_source)
        self.assertIn("get_governance_history", app_source)
        self.assertIn("get_strategy_evaluation_overview", app_source)
        self.assertIn("build_strategy_evaluation_display_df", app_source)
        self.assertIn("strategy_version", app_source)
        self.assertIn("self.paper_trade_service.evaluate_open_trades", bot_source)
        self.assertIn("self.paper_trade_service.register_signal", bot_source)
        self.assertIn("self.paper_trade_service.get_summary", bot_source)
        self.assertIn("RiskManagementService", bot_source)
        self.assertIn("get_edge_monitor_summary", bot_source)
        self.assertIn("get_strategy_governance_summary", bot_source)
        self.assertIn("evaluate_strategy_governance", bot_source)
        self.assertIn("_build_governance_note", bot_source)
        self.assertIn("get_strategy_evaluation_overview", bot_source)
        self.assertIn("_apply_edge_guardrail", bot_source)
        self.assertIn("_apply_risk_guardrail", bot_source)
        self.assertIn("get_active_strategy_profile", bot_source)
        self.assertIn("_resolve_runtime_strategy_settings", bot_source)
        self.assertIn("strategy_version", bot_source)


if __name__ == "__main__":
    unittest.main()
