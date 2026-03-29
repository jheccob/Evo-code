from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from database.database import TradingDatabase
from services.credential_vault import CredentialVault
from services.multiuser_runtime_service import MultiUserRuntimeService
from services.paper_trade_service import PaperTradeService
from services.risk_management_service import RiskManagementService


class MultiUserRuntimeTests(unittest.TestCase):
    def setUp(self):
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()
        if os.path.exists(temp_db.name):
            os.remove(temp_db.name)

        self.db_path = temp_db.name
        self.database = TradingDatabase(db_path=self.db_path)
        self.vault = CredentialVault(encryption_key=CredentialVault.generate_key(), strict=True)
        self.risk_service = RiskManagementService(database=self.database)
        self.runtime_service = MultiUserRuntimeService(
            database=self.database,
            risk_management_service=self.risk_service,
        )
        self.paper_service = PaperTradeService(database=self.database)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _seed_account(
        self,
        *,
        user_id: int,
        account_id: str,
        exchange: str = "binance",
        live_enabled: bool = True,
        paper_enabled: bool = True,
        with_risk_profile: bool = True,
        token_status: str = "valid",
        permission_status: str = "valid",
        reconciliation_status: str = "ok",
    ):
        self.database.upsert_user_account(
            {
                "user_id": user_id,
                "account_id": account_id,
                "account_alias": f"acc-{account_id}",
                "exchange": exchange,
                "status": "active",
                "live_enabled": live_enabled,
                "paper_enabled": paper_enabled,
                "capital_base": 10_000.0,
                "risk_mode": "normal",
                "allowed_symbols": ["BTC/USDT"],
                "allowed_timeframes": ["1h"],
            }
        )

        if with_risk_profile:
            self.database.upsert_user_risk_profile(
                {
                    "user_id": user_id,
                    "account_id": account_id,
                    "max_risk_per_trade": 0.5,
                    "max_daily_loss": 2.0,
                    "max_drawdown": 10.0,
                    "max_portfolio_open_risk_pct": 2.0,
                    "allowed_position_count": 3,
                    "preferred_symbols": ["BTC/USDT"],
                    "leverage_cap": 5.0,
                    "risk_mode": "normal",
                    "is_valid": True,
                    "live_enabled": live_enabled,
                    "paper_enabled": paper_enabled,
                }
            )

        self.vault.store_exchange_credentials(
            self.database,
            user_id=user_id,
            account_id=account_id,
            exchange=exchange,
            api_key="TEST_API_KEY_SHOULD_NOT_LEAK",
            api_secret="TEST_API_SECRET_SHOULD_NOT_LEAK",
            token_status=token_status,
            permission_status=permission_status,
            reconciliation_status=reconciliation_status,
            permissions_read=True,
            permissions_trade=True,
            permissions_withdraw=False,
        )

        self.database.upsert_user_governance_state(
            {
                "user_id": user_id,
                "account_id": account_id,
                "exchange": exchange,
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategy_version": "v1",
                "governance_status": "approved",
                "governance_mode": "normal",
                "blocked": False,
            }
        )

    def test_segregacao_de_ordens_por_usuario(self):
        self._seed_account(user_id=1, account_id="A1")
        self._seed_account(user_id=2, account_id="B1")

        self.database.create_user_live_order(
            {
                "user_id": 1,
                "account_id": "A1",
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategy_version": "v1",
                "status": "pending",
            }
        )
        self.database.create_user_live_order(
            {
                "user_id": 2,
                "account_id": "B1",
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategy_version": "v1",
                "status": "pending",
            }
        )

        user1_orders = self.database.get_user_live_orders(user_id=1)
        user2_orders = self.database.get_user_live_orders(user_id=2)
        self.assertEqual(len(user1_orders), 1)
        self.assertEqual(len(user2_orders), 1)
        self.assertEqual(user1_orders[0]["account_id"], "A1")
        self.assertEqual(user2_orders[0]["account_id"], "B1")

    def test_segregacao_de_posicoes_por_usuario(self):
        self._seed_account(user_id=10, account_id="X1")
        self._seed_account(user_id=20, account_id="Y1")

        self.database.create_user_live_position(
            {
                "user_id": 10,
                "account_id": "X1",
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategy_version": "v1",
                "side": "long",
                "quantity": 1.0,
                "status": "open",
            }
        )
        self.database.create_user_live_position(
            {
                "user_id": 20,
                "account_id": "Y1",
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategy_version": "v1",
                "side": "short",
                "quantity": 2.0,
                "status": "open",
            }
        )

        user10_positions = self.database.get_user_live_positions(user_id=10)
        user20_positions = self.database.get_user_live_positions(user_id=20)
        self.assertEqual(len(user10_positions), 1)
        self.assertEqual(len(user20_positions), 1)
        self.assertEqual(user10_positions[0]["account_id"], "X1")
        self.assertEqual(user20_positions[0]["account_id"], "Y1")

    def test_bloqueia_conta_sem_live_enabled(self):
        self._seed_account(user_id=3, account_id="A3", live_enabled=False, paper_enabled=True)
        context = self.database.build_account_execution_context(
            user_id=3,
            account_id="A3",
            exchange="binance",
            symbol="BTC/USDT",
            timeframe="1h",
            strategy_version="v1",
        )
        with mock.patch("config.ProductionConfig.ENABLE_MULTIUSER_AUTO_ORDER_EXECUTION", False):
            result = self.runtime_service.run_account_cycle(
                context=context,
                symbol="BTC/USDT",
                timeframe="1h",
                strategy_version="v1",
                entry_price=100.0,
                stop_loss_pct=2.0,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertIn("live_enabled", result["reason"])

    def test_bloqueia_conta_sem_risk_profile(self):
        self._seed_account(user_id=4, account_id="A4", with_risk_profile=False)
        context = self.database.build_account_execution_context(
            user_id=4,
            account_id="A4",
            exchange="binance",
            symbol="BTC/USDT",
            timeframe="1h",
            strategy_version="v1",
        )

        with mock.patch("config.ProductionConfig.ENABLE_MULTIUSER_AUTO_ORDER_EXECUTION", False):
            result = self.runtime_service.run_account_cycle(
                context=context,
                symbol="BTC/USDT",
                timeframe="1h",
                strategy_version="v1",
                entry_price=100.0,
                stop_loss_pct=2.0,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertIn("risk profile", result["reason"].lower())

    def test_token_nunca_exposto_no_contexto_ou_eventos(self):
        self._seed_account(user_id=5, account_id="A5")
        context = self.database.build_account_execution_context(
            user_id=5,
            account_id="A5",
            exchange="binance",
            symbol="BTC/USDT",
            timeframe="1h",
            strategy_version="v1",
        )
        rendered = str(context)
        self.assertNotIn("TEST_API_KEY_SHOULD_NOT_LEAK", rendered)
        self.assertNotIn("TEST_API_SECRET_SHOULD_NOT_LEAK", rendered)
        self.assertIn("api_key_ref", context)
        self.assertIn("token_ref", context)

        with mock.patch("config.ProductionConfig.ENABLE_MULTIUSER_AUTO_ORDER_EXECUTION", False):
            self.runtime_service.run_account_cycle(
                context=context,
                symbol="BTC/USDT",
                timeframe="1h",
                strategy_version="v1",
                entry_price=100.0,
                stop_loss_pct=2.0,
            )

        events = self.database.get_user_execution_events(user_id=5, account_id="A5", limit=20)
        serialized = str(events)
        self.assertNotIn("TEST_API_KEY_SHOULD_NOT_LEAK", serialized)
        self.assertNotIn("TEST_API_SECRET_SHOULD_NOT_LEAK", serialized)

    def test_execucao_independente_por_conta(self):
        self._seed_account(user_id=7, account_id="A7")
        self._seed_account(user_id=8, account_id="B8")

        with mock.patch("config.ProductionConfig.ENABLE_MULTIUSER_RUNTIME", True), \
             mock.patch("config.ProductionConfig.ENABLE_MULTIUSER_AUTO_ORDER_EXECUTION", False):
            results = self.runtime_service.run_cycle(
                symbol="BTC/USDT",
                timeframe="1h",
                strategy_version="v1",
                entry_price=100.0,
                stop_loss_pct=2.0,
            )

        self.assertEqual(len(results), 2)
        statuses = {item["status"] for item in results}
        self.assertEqual(statuses, {"ready_no_auto_order"})
        events = self.database.get_user_execution_events(limit=50)
        accounts = {f'{item["user_id"]}:{item["account_id"]}' for item in events if item["event_status"] == "ready_no_auto_order"}
        self.assertIn("7:A7", accounts)
        self.assertIn("8:B8", accounts)

    def test_compatibilidade_com_single_user_existente(self):
        trade_id = self.paper_service.register_signal(
            symbol="BTC/USDT",
            timeframe="1h",
            signal="COMPRA",
            entry_price=100.0,
            entry_timestamp="2026-01-01T10:00:00",
            source="test",
            strategy_version="single-user-v1",
            stop_loss_pct=2.0,
            take_profit_pct=4.0,
            risk_plan={
                "risk_per_trade_pct": 0.5,
                "risk_amount": 50.0,
                "position_notional": 2500.0,
                "quantity": 25.0,
                "account_reference_balance": 10000.0,
                "risk_mode": "normal",
                "size_reduced": False,
                "risk_reason": "",
            },
        )
        open_trades = self.database.get_open_paper_trades(symbol="BTC/USDT", timeframe="1h")
        self.assertEqual(len(open_trades), 1)
        self.assertEqual(open_trades[0]["id"], trade_id)


if __name__ == "__main__":
    unittest.main()
