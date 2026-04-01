from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from config import ProductionConfig
from database.database import TradingDatabase
from services.paper_trade_service import PaperTradeService
from services.risk_management_service import RiskManagementService


class RiskManagementServiceTests(unittest.TestCase):
    def setUp(self):
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()
        if os.path.exists(temp_db.name):
            os.remove(temp_db.name)

        self.db_path = temp_db.name
        self.database = TradingDatabase(db_path=self.db_path)
        self.paper_trade_service = PaperTradeService(database=self.database)
        self.risk_service = RiskManagementService(database=self.database)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_build_trade_plan_calculates_position_size_from_stop_loss(self):
        with mock.patch.object(ProductionConfig, "PAPER_ACCOUNT_BALANCE", 10000.0), \
             mock.patch.object(ProductionConfig, "RISK_PER_TRADE_PCT", 0.5), \
             mock.patch.object(ProductionConfig, "MAX_OPEN_PAPER_TRADES", 3), \
             mock.patch.object(ProductionConfig, "MAX_PORTFOLIO_OPEN_RISK_PCT", 2.0):
            plan = self.risk_service.build_trade_plan(
                entry_price=100.0,
                stop_loss_pct=2.0,
                symbol="BTC/USDT",
                timeframe="5m",
            )

        self.assertTrue(plan["allowed"])
        self.assertEqual(plan["risk_mode"], "normal")
        self.assertEqual(plan["risk_amount"], 50.0)
        self.assertEqual(plan["position_notional"], 2500.0)
        self.assertEqual(plan["quantity"], 25.0)

    def test_build_trade_plan_blocks_when_open_trade_limit_is_reached(self):
        self.database.create_paper_trade(
            {
                "symbol": "BTC/USDT",
                "timeframe": "5m",
                "signal": "COMPRA",
                "side": "long",
                "source": "test",
                "entry_timestamp": "2026-01-01T10:00:00",
                "entry_price": 100.0,
                "planned_risk_pct": 0.5,
                "planned_risk_amount": 50.0,
                "planned_position_notional": 2500.0,
                "planned_quantity": 25.0,
                "account_reference_balance": 10000.0,
                "status": "OPEN",
            }
        )

        with mock.patch.object(ProductionConfig, "MAX_OPEN_PAPER_TRADES", 1):
            plan = self.risk_service.build_trade_plan(
                entry_price=100.0,
                stop_loss_pct=2.0,
                symbol="ETH/USDT",
                timeframe="15m",
            )

        self.assertFalse(plan["allowed"])
        self.assertIn("Limite de trades abertos", plan["reason"])

    def test_register_signal_persists_risk_plan_fields(self):
        risk_plan = {
            "risk_per_trade_pct": 0.5,
            "risk_amount": 50.0,
            "position_notional": 2500.0,
            "quantity": 25.0,
            "account_reference_balance": 10000.0,
            "risk_mode": "reduced",
            "size_reduced": True,
            "risk_reason": "Losing streak de 3 trades.",
        }

        trade_id = self.paper_trade_service.register_signal(
            symbol="BTC/USDT",
            timeframe="5m",
            signal="COMPRA",
            entry_price=100.0,
            entry_timestamp=datetime(2026, 1, 1, 10, 0),
            source="test",
            stop_loss_pct=2.0,
            take_profit_pct=4.0,
            risk_plan=risk_plan,
        )

        open_trades = self.database.get_open_paper_trades(symbol="BTC/USDT", timeframe="5m")

        self.assertEqual(len(open_trades), 1)
        self.assertEqual(open_trades[0]["id"], trade_id)
        self.assertEqual(open_trades[0]["planned_risk_amount"], 50.0)
        self.assertEqual(open_trades[0]["planned_position_notional"], 2500.0)
        self.assertEqual(open_trades[0]["planned_quantity"], 25.0)
        self.assertEqual(open_trades[0]["risk_mode"], "reduced")
        self.assertEqual(open_trades[0]["size_reduced"], 1)
        self.assertEqual(open_trades[0]["risk_reason"], "Losing streak de 3 trades.")

    def test_build_trade_plan_blocks_when_daily_loss_breaker_is_hit(self):
        self.database.create_paper_trade(
            {
                "symbol": "BTC/USDT",
                "timeframe": "5m",
                "signal": "COMPRA",
                "side": "long",
                "source": "test",
                "entry_timestamp": "2026-01-01T10:00:00",
                "entry_price": 100.0,
                "planned_position_notional": 5000.0,
                "account_reference_balance": 10000.0,
                "status": "CLOSED",
                "outcome": "LOSS",
                "close_reason": "STOP_LOSS",
                "exit_timestamp": datetime.now().replace(hour=10, minute=5, second=0, microsecond=0).isoformat(),
                "exit_price": 95.0,
                "result_pct": -5.0,
            }
        )

        with mock.patch.object(ProductionConfig, "ENABLE_RISK_CIRCUIT_BREAKER", True), \
             mock.patch.object(ProductionConfig, "MAX_DAILY_PAPER_LOSS_PCT", 2.0), \
             mock.patch.object(ProductionConfig, "MAX_CONSECUTIVE_PAPER_LOSSES", 10):
            plan = self.risk_service.build_trade_plan(
                entry_price=100.0,
                stop_loss_pct=2.0,
                symbol="BTC/USDT",
                timeframe="5m",
            )

        self.assertFalse(plan["allowed"])
        self.assertIn("perda diaria", plan["reason"])

    def test_build_trade_plan_blocks_when_loss_streak_breaker_is_hit(self):
        now = datetime.now().replace(hour=11, minute=0, second=0, microsecond=0)
        for offset in range(3):
            self.database.create_paper_trade(
                {
                    "symbol": "ETH/USDT",
                    "timeframe": "15m",
                    "signal": "COMPRA",
                    "side": "long",
                    "source": "test",
                    "entry_timestamp": now.isoformat(),
                    "entry_price": 100.0,
                    "planned_position_notional": 1000.0,
                    "account_reference_balance": 10000.0,
                    "status": "CLOSED",
                    "outcome": "LOSS",
                    "close_reason": "STOP_LOSS",
                    "exit_timestamp": now.replace(minute=offset).isoformat(),
                    "exit_price": 99.5,
                    "result_pct": -0.5,
                }
            )

        with mock.patch.object(ProductionConfig, "ENABLE_RISK_CIRCUIT_BREAKER", True), \
             mock.patch.object(ProductionConfig, "MAX_DAILY_PAPER_LOSS_PCT", 10.0), \
             mock.patch.object(ProductionConfig, "MAX_CONSECUTIVE_PAPER_LOSSES", 3):
            plan = self.risk_service.build_trade_plan(
                entry_price=100.0,
                stop_loss_pct=2.0,
                symbol="ETH/USDT",
                timeframe="15m",
            )

        self.assertFalse(plan["allowed"])
        self.assertIn("losses consecutivos", plan["reason"])

    def test_evaluate_risk_engine_blocks_when_drawdown_limit_is_hit(self):
        with mock.patch.object(ProductionConfig, "RISK_DRAWDOWN_BLOCK_PCT", 10.0):
            plan = self.risk_service.evaluate_risk_engine(
                entry_price=100.0,
                stop_loss_pct=2.0,
                account_balance=10000.0,
                portfolio_summary={"open_trades": 0, "total_open_risk_pct": 0.0},
                symbol_portfolio_summary={"open_trades": 0, "total_open_risk_pct": 0.0},
                circuit_breaker={"allowed": True, "daily_realized_pnl_pct": 0.0, "consecutive_losses": 0},
                drawdown_summary={"current_drawdown_pct": 12.5, "max_drawdown_pct": 12.5},
            )

        self.assertFalse(plan["allowed"])
        self.assertEqual(plan["risk_mode"], "blocked")
        self.assertEqual(plan["drawdown_guard"]["status"], "blocked")
        self.assertIn("Drawdown corrente", plan["reason"])

    def test_evaluate_risk_engine_reduces_position_size_in_warning_mode(self):
        with mock.patch.object(ProductionConfig, "RISK_PER_TRADE_PCT", 0.5), \
             mock.patch.object(ProductionConfig, "RISK_DRAWDOWN_WARNING_PCT", 5.0), \
             mock.patch.object(ProductionConfig, "RISK_DRAWDOWN_BLOCK_PCT", 10.0), \
             mock.patch.object(ProductionConfig, "RISK_REDUCED_MODE_MULTIPLIER", 0.5):
            plan = self.risk_service.evaluate_risk_engine(
                entry_price=100.0,
                stop_loss_pct=2.0,
                account_balance=10000.0,
                portfolio_summary={"open_trades": 0, "total_open_risk_pct": 0.0},
                symbol_portfolio_summary={"open_trades": 0, "total_open_risk_pct": 0.0},
                circuit_breaker={"allowed": True, "daily_realized_pnl_pct": 0.0, "consecutive_losses": 0},
                drawdown_summary={"current_drawdown_pct": 6.0, "max_drawdown_pct": 6.0},
            )

        self.assertTrue(plan["allowed"])
        self.assertEqual(plan["risk_mode"], "reduced")
        self.assertTrue(plan["size_reduced"])
        self.assertAlmostEqual(plan["risk_per_trade_pct"], 0.25, places=4)
        self.assertEqual(plan["risk_amount"], 25.0)
        self.assertEqual(plan["position_notional"], 1250.0)


if __name__ == "__main__":
    unittest.main()
