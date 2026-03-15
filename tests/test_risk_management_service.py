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


if __name__ == "__main__":
    unittest.main()
