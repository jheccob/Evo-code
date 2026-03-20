from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from config import ProductionConfig
from database.database import TradingDatabase


class AdaptiveGovernanceTests(unittest.TestCase):
    def setUp(self):
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()
        if os.path.exists(temp_db.name):
            os.remove(temp_db.name)

        self.db_path = temp_db.name
        self.database = TradingDatabase(db_path=self.db_path)
        self.symbol = "BTC/USDT"
        self.timeframe = "1h"
        self.strategy_version = "BTCUSDT-1h-governance-test"

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _save_backtest_run(self) -> int:
        trade_analytics = []
        bullish_results = [0.7, 0.6, 0.4, 0.3, -0.5, -0.4]
        range_results = [-0.4, -0.3, -0.2, -0.5, -0.1, -0.2]
        all_results = [("trend_bull", value) for value in bullish_results] + [("range", value) for value in range_results]

        for index, (regime, pnl_pct) in enumerate(all_results, start=1):
            trade_analytics.append(
                {
                    "strategy_version": self.strategy_version,
                    "setup_name": "continuation_breakout",
                    "regime": regime,
                    "regime_score": 7.5 if regime == "trend_bull" else 3.0,
                    "trend_state": regime,
                    "volatility_state": "normal_volatility",
                    "context_bias": "bullish" if regime == "trend_bull" else "neutral",
                    "structure_state": "continuation" if regime == "trend_bull" else "weak_structure",
                    "confirmation_state": "confirmed" if regime == "trend_bull" else "mixed",
                    "entry_quality": "strong" if regime == "trend_bull" else "bad",
                    "entry_score": 7.1 if regime == "trend_bull" else 3.2,
                    "risk_mode": "normal",
                    "quantity": 1.0,
                    "position_notional": 1000.0,
                    "risk_amount": 5.0,
                    "initial_stop_price": 98.0,
                    "initial_take_price": 104.0,
                    "final_stop_price": 99.0,
                    "final_take_price": 104.0,
                    "exit_reason": "TAKE_PROFIT" if pnl_pct > 0 else "STOP_LOSS",
                    "entry_timestamp": f"2026-01-{index:02d}T10:00:00",
                    "timestamp": f"2026-01-{index:02d}T12:00:00",
                    "holding_time_minutes": 120,
                    "holding_candles": 2,
                    "profit_loss_pct": pnl_pct,
                    "profit_loss": pnl_pct * 10,
                    "mfe_pct": max(pnl_pct + 0.6, 0.2),
                    "mae_pct": abs(min(pnl_pct - 0.2, -0.1)),
                    "rr_realized": pnl_pct / 0.5,
                    "profit_given_back_pct": 12.0 if regime == "trend_bull" else 5.0,
                    "notes": [regime],
                }
            )

        return self.database.save_backtest_result(
            {
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "strategy_version": self.strategy_version,
                "start_date": "2026-01-01T00:00:00",
                "end_date": "2026-03-01T00:00:00",
                "initial_balance": 10000.0,
                "final_balance": 10550.0,
                "net_profit": 550.0,
                "total_return_pct": 5.5,
                "total_trades": 12,
                "winning_trades": 4,
                "losing_trades": 8,
                "win_rate": 33.3,
                "max_drawdown": 6.0,
                "sharpe_ratio": 1.1,
                "profit_factor": 1.35,
                "avg_profit": 0.5,
                "avg_loss": -0.3,
                "expectancy_pct": 0.15,
                "rsi_period": 14,
                "rsi_min": 30,
                "rsi_max": 70,
                "require_volume": True,
                "require_trend": True,
                "avoid_ranging": True,
                "out_of_sample_return_pct": 2.3,
                "out_of_sample_profit_factor": 1.28,
                "out_of_sample_expectancy_pct": 0.11,
                "out_of_sample_passed": True,
            },
            trades=[],
            trade_analytics=trade_analytics,
        )

    def _create_closed_trades(self, results: list[float], regime: str = "trend_bull"):
        for idx, result_pct in enumerate(results, start=1):
            self.database.create_paper_trade(
                {
                    "symbol": self.symbol,
                    "timeframe": self.timeframe,
                    "strategy_version": self.strategy_version,
                    "regime": regime,
                    "signal": "COMPRA",
                    "side": "long",
                    "source": "test",
                    "sample_type": "paper",
                    "entry_timestamp": f"2026-03-{idx:02d}T10:00:00",
                    "entry_price": 100.0,
                    "status": "CLOSED",
                    "outcome": "WIN" if result_pct > 0 else "LOSS",
                    "close_reason": "TAKE_PROFIT" if result_pct > 0 else "STOP_LOSS",
                    "exit_reason": "TAKE_PROFIT" if result_pct > 0 else "STOP_LOSS",
                    "exit_timestamp": f"2026-03-{idx:02d}T11:00:00",
                    "exit_price": 101.0,
                    "result_pct": result_pct,
                }
            )

    def test_governance_blocks_regime_not_approved(self):
        run_id = self._save_backtest_run()

        with mock.patch.object(ProductionConfig, "MIN_PAPER_TRADES_FOR_EDGE_VALIDATION", 5):
            self.database.promote_backtest_run(run_id, notes="runtime active")
            governance = self.database.evaluate_strategy_governance(
                symbol=self.symbol,
                timeframe=self.timeframe,
                strategy_version=self.strategy_version,
                current_regime="range",
            )

        self.assertEqual(governance["current_regime_status"], "blocked")
        self.assertEqual(governance["governance_mode"], "blocked")
        self.assertEqual(governance["action_reason"], "regime_not_approved")

    def test_governance_reduces_on_alignment_warning(self):
        run_id = self._save_backtest_run()
        self._create_closed_trades([0.35, 0.25, -0.2, 0.15, -0.15, 0.25, 0.1, -0.05])

        with mock.patch.object(ProductionConfig, "MIN_PAPER_TRADES_FOR_EDGE_VALIDATION", 5), \
             mock.patch.object(ProductionConfig, "GOVERNANCE_MIN_ALIGNMENT_TRADES", 5), \
             mock.patch.object(ProductionConfig, "MIN_LIVE_QUALITY_SCORE", 10.0):
            self.database.promote_backtest_run(run_id, notes="runtime active")
            governance = self.database.evaluate_strategy_governance(
                symbol=self.symbol,
                timeframe=self.timeframe,
                strategy_version=self.strategy_version,
                current_regime="trend_bull",
            )

        self.assertEqual(governance["current_regime_status"], "approved")
        self.assertEqual(governance["governance_status"], "reduced")
        self.assertEqual(governance["governance_mode"], "reduced")
        self.assertIn(governance["alignment_status"], {"warning", "degraded"})

    def test_governance_blocks_on_broken_alignment(self):
        run_id = self._save_backtest_run()
        self._create_closed_trades([-0.5, 0.1, -0.6, -0.4, 0.2, -0.3, -0.2, -0.1])

        with mock.patch.object(ProductionConfig, "MIN_PAPER_TRADES_FOR_EDGE_VALIDATION", 5), \
             mock.patch.object(ProductionConfig, "GOVERNANCE_MIN_ALIGNMENT_TRADES", 5), \
             mock.patch.object(ProductionConfig, "MIN_LIVE_QUALITY_SCORE", 10.0):
            self.database.promote_backtest_run(run_id, notes="runtime active")
            governance = self.database.evaluate_strategy_governance(
                symbol=self.symbol,
                timeframe=self.timeframe,
                strategy_version=self.strategy_version,
                current_regime="trend_bull",
            )

        self.assertEqual(governance["governance_mode"], "blocked")
        self.assertIn(governance["governance_status"], {"blocked", "degraded"})
        self.assertIn(governance["action_reason"], {"live_degradation", "setup_degraded"})

    def test_governance_persists_baselines_alignment_and_history(self):
        run_id = self._save_backtest_run()
        self._create_closed_trades([0.6, 0.5, 0.4, -0.2, 0.3, 0.2, 0.1, -0.1])

        with mock.patch.object(ProductionConfig, "MIN_PAPER_TRADES_FOR_EDGE_VALIDATION", 5), \
             mock.patch.object(ProductionConfig, "GOVERNANCE_MIN_ALIGNMENT_TRADES", 5), \
             mock.patch.object(ProductionConfig, "MIN_LIVE_QUALITY_SCORE", 10.0):
            self.database.promote_backtest_run(run_id, notes="runtime active")
            governance = self.database.evaluate_strategy_governance(
                symbol=self.symbol,
                timeframe=self.timeframe,
                strategy_version=self.strategy_version,
                current_regime="trend_bull",
                persist=True,
            )

        baselines = self.database.get_setup_regime_baselines(
            symbol=self.symbol,
            timeframe=self.timeframe,
            strategy_version=self.strategy_version,
        )
        alignment_rows = self.database.get_alignment_metrics(
            symbol=self.symbol,
            timeframe=self.timeframe,
            strategy_version=self.strategy_version,
        )
        history_rows = self.database.get_governance_history(
            symbol=self.symbol,
            timeframe=self.timeframe,
            strategy_version=self.strategy_version,
        )

        self.assertTrue(baselines)
        self.assertTrue(any(row["regime"] == "trend_bull" for row in baselines))
        self.assertTrue(alignment_rows)
        self.assertTrue(history_rows)
        self.assertIn(governance["governance_status"], {"approved", "reduced", "observing"})


if __name__ == "__main__":
    unittest.main()
