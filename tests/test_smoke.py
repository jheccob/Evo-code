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
        self.assertIn("requirements_production.txt", config["build"]["buildCommand"])
        self.assertEqual(config["deploy"]["startCommand"], "python start_telegram_bot.py")
        self.assertEqual(config["deploy"]["restartPolicyType"], "ALWAYS")


if __name__ == "__main__":
    unittest.main()
