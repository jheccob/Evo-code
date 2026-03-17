from __future__ import annotations

import unittest
from unittest import mock

from config import ProductionConfig
from telegram_bot import TelegramTradingBot


class TelegramTradingBotLogicTests(unittest.TestCase):
    def test_ai_signal_is_comparative_only_by_default(self):
        bot = TelegramTradingBot.__new__(TelegramTradingBot)

        with mock.patch.object(ProductionConfig, "ENABLE_AI_SIGNAL_INFLUENCE", False):
            self.assertEqual(bot._merge_rule_and_ai_signal("VENDA", "BUY"), "VENDA")
            self.assertEqual(bot._merge_rule_and_ai_signal("COMPRA", "SELL"), "COMPRA")

    def test_ai_signal_can_influence_when_feature_flag_is_enabled(self):
        bot = TelegramTradingBot.__new__(TelegramTradingBot)

        with mock.patch.object(ProductionConfig, "ENABLE_AI_SIGNAL_INFLUENCE", True):
            self.assertEqual(bot._merge_rule_and_ai_signal("NEUTRO", "BUY"), "COMPRA_FRACA")
            self.assertEqual(bot._merge_rule_and_ai_signal("NEUTRO", "SELL"), "VENDA_FRACA")

    def test_runtime_settings_block_session_fallback_without_active_profile(self):
        bot = TelegramTradingBot.__new__(TelegramTradingBot)
        bot.trading_bot = mock.Mock()
        bot.trading_bot.rsi_period = 14
        bot.trading_bot.rsi_min = 30
        bot.trading_bot.rsi_max = 70

        with mock.patch("telegram_bot.runtime_db.get_active_strategy_profile", return_value=None), \
             mock.patch.object(ProductionConfig, "REQUIRE_ACTIVE_PROFILE_FOR_RUNTIME", True):
            settings = bot._resolve_runtime_strategy_settings("BTC/USDT", "1h")

        self.assertFalse(settings["runtime_allowed"])
        self.assertIsNone(settings["active_profile"])
        self.assertIn("Nenhum setup ativo", settings["runtime_block_reason"])

    def test_runtime_strategy_version_includes_context_suffix_when_present(self):
        bot = TelegramTradingBot.__new__(TelegramTradingBot)
        bot.trading_bot = mock.Mock()
        bot.trading_bot.rsi_period = 14
        bot.trading_bot.rsi_min = 30
        bot.trading_bot.rsi_max = 70

        strategy_version = bot._build_runtime_strategy_version(
            "BTC/USDT",
            "1h",
            {
                "rsi_period": 14,
                "rsi_min": 30,
                "rsi_max": 70,
                "require_volume": True,
                "require_trend": True,
                "avoid_ranging": True,
                "context_timeframe": "4h",
            },
        )

        self.assertIn("-ctx4h", strategy_version)


if __name__ == "__main__":
    unittest.main()
