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

    def test_display_signal_translates_known_signals_to_english(self):
        self.assertEqual(TelegramTradingBot._display_signal("COMPRA", locale="en"), "BUY")
        self.assertEqual(TelegramTradingBot._display_signal("VENDA_FRACA", locale="en"), "WEAK SELL")
        self.assertEqual(TelegramTradingBot._display_signal("NEUTRO", locale="en"), "WAIT")

    def test_build_strategy_runtime_note_marks_runtime_as_blocked_without_active_profile(self):
        note = TelegramTradingBot._build_strategy_runtime_note(
            {
                "strategy_version": "BTCUSDT-1h-rsi14-30-70-sl2.00-tp4.00-v1-t0-r1-ctx4h",
                "active_profile": None,
                "runtime_allowed": False,
                "runtime_block_reason": "Nenhum setup ativo promovido para este mercado/timeframe.",
            }
        )

        self.assertIn("Perfil ativo: nenhum", note)
        self.assertIn("Estrategia configurada:", note)
        self.assertIn("bloqueado por governanca", note)

    def test_build_strategy_runtime_note_supports_english(self):
        note = TelegramTradingBot._build_strategy_runtime_note(
            {
                "strategy_version": "BTCUSDT-1h-rsi14-30-70-sl2.00-tp4.00-v1-t0-r1-ctx4h",
                "active_profile": None,
                "runtime_allowed": False,
                "runtime_block_reason": "No promoted setup is active for this market/timeframe.",
            },
            locale="en",
        )

        self.assertIn("Active profile: none", note)
        self.assertIn("Configured strategy:", note)
        self.assertIn("blocked by governance", note)

    def test_build_strategy_runtime_note_prefers_active_profile_when_present(self):
        note = TelegramTradingBot._build_strategy_runtime_note(
            {
                "strategy_version": "fallback-version",
                "active_profile": {"strategy_version": "BTCUSDT-4h-rsi14-30-70-sl1.50-tp4.00-v1-t1-r1"},
                "runtime_allowed": True,
            }
        )

        self.assertEqual(note, "Perfil ativo: BTCUSDT-4h-rsi14-30-70-sl1.50-tp4.00-v1-t1-r1")

    def test_build_structure_note_uses_standardized_structure_fields(self):
        note = TelegramTradingBot._build_structure_note(
            {
                "structure_state": "breakout",
                "price_location": "resistance",
                "structure_quality": 6.8,
                "breakout": True,
                "reversal_risk": False,
                "distance_from_ema_pct": 1.37,
                "notes": ["rompimento confirmado", "preco acima da EMA 21"],
            }
        )

        self.assertIn("breakout True", note)
        self.assertIn("reversal_risk False", note)
        self.assertIn("dist EMA 1.37%", note)
        self.assertIn("rompimento confirmado", note)

    def test_build_structure_note_supports_english(self):
        note = TelegramTradingBot._build_structure_note(
            {
                "structure_state": "breakout",
                "price_location": "resistance",
                "structure_quality": 6.8,
                "breakout": True,
                "reversal_risk": False,
                "distance_from_ema_pct": 1.37,
                "notes": ["breakout confirmed", "price above EMA 21"],
            },
            locale="en",
        )

        self.assertIn("Structure:", note)
        self.assertIn("quality 6.80/10", note)
        self.assertIn("notes: breakout confirmed", note)

    def test_build_confirmation_note_uses_standardized_confirmation_fields(self):
        note = TelegramTradingBot._build_confirmation_note(
            {
                "confirmation_state": "mixed",
                "confirmation_score": 5.4,
                "conflicts": ["MACD conflita com o vies bullish"],
                "notes": ["RSI em faixa favoravel para compra", "Volume em linha com a media"],
            }
        )

        self.assertIn("mixed", note)
        self.assertIn("5.40/10", note)
        self.assertIn("MACD conflita com o vies bullish", note)
        self.assertIn("RSI em faixa favoravel para compra", note)

    def test_build_entry_quality_note_uses_standardized_entry_fields(self):
        note = TelegramTradingBot._build_entry_quality_note(
            {
                "entry_quality": "acceptable",
                "rr_estimate": 1.34,
                "late_entry": False,
                "stretched_price": True,
                "notes": ["risco retorno aceitavel", "preco esta esticado em relacao a ema 21"],
            }
        )

        self.assertIn("acceptable", note)
        self.assertIn("RR 1.34", note)
        self.assertIn("stretched True", note)
        self.assertIn("risco retorno aceitavel", note)

    def test_build_scenario_note_uses_standardized_score_fields(self):
        note = TelegramTradingBot._build_scenario_note(
            {
                "scenario_score": 7.45,
                "scenario_grade": "B",
                "score_breakdown": {
                    "context": 8.0,
                    "structure": 7.2,
                    "confirmation": 6.8,
                    "entry": 6.0,
                },
                "notes": ["context forte", "confirmation consistente"],
            }
        )

        self.assertIn("Cenario:", note)
        self.assertIn("7.45/10", note)
        self.assertIn("grade B", note)
        self.assertIn("ctx 8.0", note)
        self.assertIn("context forte", note)

    def test_build_trade_decision_note_uses_standardized_decision_fields(self):
        note = TelegramTradingBot._build_trade_decision_note(
            {
                "action": "buy",
                "confidence": 7.6,
                "entry_reason": "bullish pullback | confirmacao confirmed | entrada good | score 7.40",
                "block_reason": None,
            }
        )

        self.assertIn("Decisao:", note)
        self.assertIn("buy", note)
        self.assertIn("7.60/10", note)
        self.assertIn("bullish pullback", note)
        self.assertIn("nenhum", note)


if __name__ == "__main__":
    unittest.main()
