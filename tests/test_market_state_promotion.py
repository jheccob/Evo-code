from __future__ import annotations

import os
import tempfile
import unittest

from database.database import TradingDatabase


class MarketStatePromotionTests(unittest.TestCase):
    def setUp(self):
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()
        if os.path.exists(temp_db.name):
            os.remove(temp_db.name)

        self.db_path = temp_db.name
        self.database = TradingDatabase(db_path=self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_promote_backtest_run_persists_market_state_identity_in_profile(self):
        run_id = self.database.save_backtest_result(
            {
                "symbol": "BTC/USDT",
                "timeframe": "15m",
                "strategy_version": "BTCUSDT-15m-state-profile",
                "start_date": "2026-02-01T00:00:00",
                "end_date": "2026-03-05T00:00:00",
                "initial_balance": 1000.0,
                "final_balance": 1080.0,
                "net_profit": 80.0,
                "total_return_pct": 8.0,
                "total_trades": 60,
                "winning_trades": 36,
                "losing_trades": 24,
                "win_rate": 60.0,
                "max_drawdown": 9.0,
                "sharpe_ratio": 1.4,
                "profit_factor": 1.5,
                "avg_profit": 1.2,
                "avg_loss": -0.8,
                "expectancy_pct": 0.5,
                "rsi_period": 14,
                "rsi_min": 30,
                "rsi_max": 70,
                "approved_market_state": "ema_rsi_resume_bull",
                "approved_market_states": ["ema_rsi_resume_bull"],
                "approved_market_state_trades": 60,
                "approved_market_state_profit_factor": 1.5,
                "approved_setup_type": "ema_rsi_resume_long",
                "approved_setup_types": ["ema_rsi_resume_long"],
                "approved_setup_trades": 60,
                "approved_setup_profit_factor": 1.5,
                "evaluation_period_days": 32.0,
                "out_of_sample_return_pct": 4.0,
                "out_of_sample_profit_factor": 1.3,
                "out_of_sample_expectancy_pct": 0.2,
                "out_of_sample_total_trades": 18,
                "out_of_sample_passed": True,
                "walk_forward_windows": 3,
                "walk_forward_passed": True,
                "walk_forward_pass_rate_pct": 66.7,
                "walk_forward_avg_oos_profit_factor": 1.2,
                "objective_status": "approved",
            },
            [],
        )

        profile = self.database.promote_backtest_run(run_id, notes="phase2 market-state", require_ready=False)

        self.assertIsNotNone(profile)
        self.assertEqual(profile["market_state"], "ema_rsi_resume_bull")
        self.assertEqual(profile["allowed_market_states"], ["ema_rsi_resume_bull"])
        self.assertEqual(profile["setup_type"], "ema_rsi_resume_long")
        self.assertEqual(profile["allowed_setup_types"], ["ema_rsi_resume_long"])

    def test_promotion_readiness_derives_market_state_from_backtest_trades(self):
        trades = []
        for index in range(1, 61):
            trades.append(
                {
                    "timestamp": f"2026-03-{(index % 28) + 1:02d}T10:00:00",
                    "entry_timestamp": f"2026-03-{(index % 28) + 1:02d}T09:00:00",
                    "entry_price": 100.0,
                    "price": 101.0 if index % 3 else 99.4,
                    "profit_loss_pct": 1.0 if index % 3 else -0.6,
                    "profit_loss": 10.0 if index % 3 else -6.0,
                    "signal": "COMPRA",
                    "side": "long",
                    "reason": "TAKE_PROFIT" if index % 3 else "STOP_LOSS",
                    "exit_reason": "TAKE_PROFIT" if index % 3 else "STOP_LOSS",
                    "setup_name": "ema_rsi_resume_long",
                    "market_state": "ema_rsi_resume_bull",
                    "execution_mode": "ema_rsi_resume",
                }
            )

        run_id = self.database.save_backtest_result(
            {
                "symbol": "ETH/USDT",
                "timeframe": "15m",
                "strategy_version": "ETHUSDT-15m-derived-state",
                "start_date": "2026-02-01T00:00:00",
                "end_date": "2026-03-05T00:00:00",
                "initial_balance": 1000.0,
                "final_balance": 1070.0,
                "net_profit": 70.0,
                "total_return_pct": 7.0,
                "total_trades": 60,
                "winning_trades": 40,
                "losing_trades": 20,
                "win_rate": 66.7,
                "max_drawdown": 8.0,
                "sharpe_ratio": 1.2,
                "profit_factor": 1.45,
                "avg_profit": 1.0,
                "avg_loss": -0.6,
                "expectancy_pct": 0.3,
                "evaluation_period_days": 32.0,
                "out_of_sample_return_pct": 3.5,
                "out_of_sample_profit_factor": 1.25,
                "out_of_sample_expectancy_pct": 0.15,
                "out_of_sample_total_trades": 18,
                "out_of_sample_passed": True,
                "walk_forward_windows": 3,
                "walk_forward_passed": True,
                "walk_forward_pass_rate_pct": 66.7,
                "walk_forward_avg_oos_profit_factor": 1.15,
                "objective_status": "approved",
            },
            trades,
        )

        readiness = self.database.get_backtest_run_promotion_readiness(run_id)

        self.assertEqual(readiness["approved_market_state"], "ema_rsi_resume_bull")
        self.assertEqual(readiness["approved_market_states"], ["ema_rsi_resume_bull"])
        self.assertIn("ema_rsi_resume_long", readiness["approved_setup_types"])


if __name__ == "__main__":
    unittest.main()
