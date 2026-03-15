import asyncio
import importlib
import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock

from config import ProductionConfig
from services.billing_service import BillingService
from services.rate_limiter import RateLimiter
from user_manager import UserManager


class UserManagerSmokeTests(unittest.TestCase):
    def test_add_admin_updates_permissions_and_stats_shape(self):
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        temp_file.close()

        try:
            os.unlink(temp_file.name)
            manager = UserManager(db_file=temp_file.name)

            manager.add_admin(999)
            stats = manager.get_user_stats()
            users = manager.list_users(10)

            self.assertTrue(manager.is_admin(999))
            self.assertIn("active_today", stats)
            self.assertEqual(users[0]["is_admin"], True)
        finally:
            if os.path.exists(temp_file.name):
                os.remove(temp_file.name)


class BillingServiceSmokeTests(unittest.TestCase):
    def test_billing_service_fails_safe_without_stripe_config(self):
        with mock.patch.object(ProductionConfig, "STRIPE_SECRET_KEY", ""), \
             mock.patch.object(ProductionConfig, "STRIPE_WEBHOOK_SECRET", ""), \
             mock.patch.object(ProductionConfig, "PREMIUM_PRICE_MONTHLY", 19.90):
            service = BillingService()
            result = asyncio.run(service.create_payment_link(123))

        self.assertFalse(service.enabled)
        self.assertIn("Billing indisponivel", result)


class RateLimiterSmokeTests(unittest.TestCase):
    def test_rate_limiter_works_with_memory_fallback(self):
        with mock.patch.object(ProductionConfig, "REDIS_URL", ""):
            limiter = RateLimiter()
            allowed = asyncio.run(limiter.check_rate_limit(1, "free"))
            remaining = asyncio.run(limiter.get_remaining_requests(1, "free"))

        self.assertTrue(allowed)
        self.assertEqual(remaining, 2)


class ImportSmokeTests(unittest.TestCase):
    def test_import_main_production(self):
        module = importlib.import_module("main_production")
        self.assertTrue(hasattr(module, "main"))

    def test_import_start_telegram_bot(self):
        module = importlib.import_module("start_telegram_bot")
        self.assertTrue(hasattr(module, "main"))

    def test_import_telegram_bot(self):
        module = importlib.import_module("telegram_bot")
        self.assertTrue(hasattr(module, "TelegramTradingBot"))

    def test_app_source_has_no_known_broken_imports_or_hardcoded_admin_password(self):
        with open("app.py", "r", encoding="utf-8") as app_file:
            source = app_file.read()

        self.assertNotIn("config.exchange_config", source)
        self.assertNotIn("config.app_config", source)
        self.assertNotIn("admin123", source)
        self.assertNotIn("use_container_width", source)


class ProductionConfigSmokeTests(unittest.TestCase):
    def test_polling_runtime_config_only_requires_bot_token(self):
        with mock.patch.object(ProductionConfig, "TELEGRAM_BOT_TOKEN", "123456:ABCDEF"), \
             mock.patch.object(ProductionConfig, "TELEGRAM_CHAT_ID", ""):
            self.assertTrue(ProductionConfig.validate_polling_runtime_config())
            self.assertFalse(ProductionConfig.validate_config())


class RailwayConfigSmokeTests(unittest.TestCase):
    def test_railway_json_targets_the_worker_entrypoint(self):
        with open("railway.json", "r", encoding="utf-8") as railway_file:
            config = json.load(railway_file)

        self.assertEqual(config["build"]["builder"], "RAILPACK")
        self.assertIn("requirements_railway.txt", config["build"]["buildCommand"])
        self.assertEqual(config["deploy"]["startCommand"], "python start_telegram_bot.py")
        self.assertEqual(config["deploy"]["restartPolicyType"], "ON_FAILURE")

    def test_railway_requirements_are_worker_scoped(self):
        with open("requirements_railway.txt", "r", encoding="utf-8") as req_file:
            content = req_file.read()

        self.assertIn("python-telegram-bot==22.6", content)
        self.assertIn("ccxt==4.5.5", content)
        self.assertIn("streamlit==1.49.1", content)

    def test_default_requirements_entrypoint_points_to_production(self):
        with open("requirements.txt", "r", encoding="utf-8") as req_file:
            content = req_file.read()

        self.assertIn("python-telegram-bot==22.6", content)
        self.assertIn("ccxt==4.5.5", content)
        self.assertIn("streamlit==1.49.1", content)


class GcpDeploySmokeTests(unittest.TestCase):
    def test_gcp_setup_script_and_unit_file_exist(self):
        self.assertTrue(os.path.exists("deploy/gcp/setup_vm.sh"))
        self.assertTrue(os.path.exists("deploy/gcp/trading-bot.service"))
        self.assertTrue(os.path.exists("deploy/gcp/trading-bot.env.example"))

    def test_gcp_service_targets_start_telegram_bot(self):
        with open("deploy/gcp/trading-bot.service", "r", encoding="utf-8") as service_file:
            service_content = service_file.read()

        with open("deploy/gcp/setup_vm.sh", "r", encoding="utf-8") as setup_file:
            setup_content = setup_file.read()

        self.assertIn("ExecStart=__PYTHON_BIN__ __APP_DIR__/start_telegram_bot.py", service_content)
        self.assertIn("requirements_railway.txt", setup_content)
        self.assertIn("/etc/trading-bot.env", setup_content)


class MainProductionSmokeTests(unittest.TestCase):
    def test_main_returns_nonzero_after_repeated_polling_failure(self):
        module = importlib.import_module("main_production")

        with mock.patch.object(module.ProductionConfig, "validate_polling_runtime_config", return_value=True), \
             mock.patch.object(module.ProductionConfig, "TELEGRAM_CHAT_ID", ""), \
             mock.patch.object(module.time, "sleep", return_value=None), \
             mock.patch.object(module, "TelegramTradingBot") as bot_cls:
            bot = bot_cls.return_value
            bot.is_configured.return_value = True
            bot.start_polling.return_value = False

            self.assertEqual(module.main(), 1)


if __name__ == "__main__":
    unittest.main()
