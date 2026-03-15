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


if __name__ == "__main__":
    unittest.main()
