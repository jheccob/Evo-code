import os
import tempfile
import unittest

from database.database import TradingDatabase
from services.credential_vault import CredentialVault


class DashboardUserAccessTests(unittest.TestCase):
    def setUp(self):
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()
        if os.path.exists(temp_db.name):
            os.remove(temp_db.name)

        self.db_path = temp_db.name
        self.database = TradingDatabase(db_path=self.db_path)
        self.vault = CredentialVault(encryption_key=CredentialVault.generate_key(), strict=True)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_dashboard_user_access_authenticate_and_rotate_password(self):
        self.database.upsert_dashboard_user_access(
            {
                "user_id": 101,
                "login_name": "alice.portal",
                "password": "SenhaSuperSegura123",
                "is_active": True,
                "require_password_change": True,
            }
        )

        wrong_auth = self.database.authenticate_dashboard_user("alice.portal", "senha-errada")
        valid_auth = self.database.authenticate_dashboard_user("alice.portal", "SenhaSuperSegura123")

        self.assertIsNone(wrong_auth)
        self.assertIsNotNone(valid_auth)
        self.assertEqual(valid_auth["user_id"], 101)
        self.assertTrue(valid_auth["require_password_change"])

        changed = self.database.change_dashboard_user_password(
            user_id=101,
            current_password="SenhaSuperSegura123",
            new_password="OutraSenhaSuperSegura456",
        )
        old_auth = self.database.authenticate_dashboard_user("alice.portal", "SenhaSuperSegura123")
        new_auth = self.database.authenticate_dashboard_user("alice.portal", "OutraSenhaSuperSegura456")

        self.assertTrue(changed)
        self.assertIsNone(old_auth)
        self.assertIsNotNone(new_auth)
        self.assertFalse(new_auth["require_password_change"])

    def test_get_user_workspace_accounts_isolates_user_accounts_and_status_refs(self):
        self.database.upsert_user_account(
            {
                "user_id": 7,
                "account_id": "A7",
                "account_alias": "Conta A7",
                "exchange": "bybit",
                "status": "active",
                "live_enabled": True,
                "paper_enabled": True,
                "capital_base": 15000.0,
                "risk_mode": "normal",
                "allowed_symbols": ["BTC/USDT", "ETH/USDT"],
                "allowed_timeframes": ["15m", "1h"],
            }
        )
        self.database.upsert_user_account(
            {
                "user_id": 8,
                "account_id": "B8",
                "account_alias": "Conta B8",
                "exchange": "bybit",
                "status": "active",
                "live_enabled": True,
                "paper_enabled": False,
                "capital_base": 9000.0,
                "risk_mode": "normal",
                "allowed_symbols": ["BTC/USDT"],
                "allowed_timeframes": ["1h"],
            }
        )
        self.database.upsert_user_risk_profile(
            {
                "user_id": 7,
                "account_id": "A7",
                "max_risk_per_trade": 0.5,
                "max_daily_loss": 2.0,
                "max_drawdown": 10.0,
                "max_portfolio_open_risk_pct": 2.0,
                "allowed_position_count": 3,
                "preferred_symbols": ["BTC/USDT"],
                "leverage_cap": 5.0,
                "risk_mode": "normal",
                "is_valid": True,
                "live_enabled": True,
                "paper_enabled": True,
            }
        )
        self.vault.store_exchange_credentials(
            self.database,
            user_id=7,
            account_id="A7",
            exchange="bybit",
            api_key="APIKEY-TEST-7",
            api_secret="SECRET-TEST-7",
            permission_status="valid",
            token_status="valid",
            reconciliation_status="ok",
        )
        self.database.create_user_live_order(
            {
                "user_id": 7,
                "account_id": "A7",
                "exchange": "bybit",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategy_version": "v1",
                "status": "pending",
            }
        )
        self.database.create_user_live_position(
            {
                "user_id": 7,
                "account_id": "A7",
                "exchange": "bybit",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategy_version": "v1",
                "side": "long",
                "quantity": 1.0,
                "status": "open",
            }
        )

        user7_accounts = self.database.get_user_workspace_accounts(user_id=7, limit=20)
        user8_accounts = self.database.get_user_workspace_accounts(user_id=8, limit=20)

        self.assertEqual(len(user7_accounts), 1)
        self.assertEqual(len(user8_accounts), 1)
        self.assertEqual(user7_accounts[0]["account_id"], "A7")
        self.assertEqual(user8_accounts[0]["account_id"], "B8")
        self.assertEqual(user7_accounts[0]["open_positions"], 1)
        self.assertEqual(user7_accounts[0]["pending_orders"], 1)
        self.assertEqual(user7_accounts[0]["permission_status"], "valid")
        self.assertEqual(user7_accounts[0]["token_status"], "valid")
        self.assertNotIn("APIKEY-TEST-7", str(user7_accounts[0]))
        self.assertIn("api_key_ref", user7_accounts[0])


if __name__ == "__main__":
    unittest.main()
