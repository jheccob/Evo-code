from __future__ import annotations

import asyncio
import unittest
from unittest import mock

import pandas as pd

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

    def test_build_regime_note_uses_standardized_regime_fields(self):
        note = TelegramTradingBot._build_regime_note(
            {
                "regime": "trend_bull",
                "volatility_state": "high_volatility",
                "regime_score": 8.2,
                "adx": 31.4,
                "atr_pct": 1.86,
                "trend_state": "trend_bull",
                "parabolic": True,
                "notes": ["mercado em trend_bull", "movimento acelerado/parabolico"],
            }
        )

        self.assertIn("Regime: trend_bull", note)
        self.assertIn("high_volatility", note)
        self.assertIn("forca 8.20/10", note)
        self.assertIn("ADX 31.40", note)
        self.assertIn("Parabolic".lower(), note.lower())

    def test_build_governance_note_uses_adaptive_fields(self):
        note = TelegramTradingBot._build_governance_note(
            {
                "governance_status": "reduced",
                "governance_mode": "reduced",
                "alignment_status": "warning",
                "current_regime": "trend_bull",
                "current_regime_status": "approved",
                "allowed_regimes": ["trend_bull"],
                "blocked_regimes": ["range"],
                "action_reason": "paper_alignment_warning",
            }
        )

        self.assertIn("Governanca: reduced", note)
        self.assertIn("alignment warning", note)
        self.assertIn("trend_bull", note)
        self.assertIn("range", note)
        self.assertIn("paper_alignment_warning", note)

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
                "entry_score": 6.8,
                "setup_type": "pullback_trend",
                "rsi_state": "pullback_recovery",
                "candle_quality": "acceptable",
                "momentum_state": "acceptable",
                "rr_estimate": 1.34,
                "rejection_reason": None,
                "notes": ["risco retorno aceitavel", "preco esta esticado em relacao a ema 21"],
            }
        )

        self.assertIn("acceptable", note)
        self.assertIn("6.80/10", note)
        self.assertIn("pullback_trend", note)
        self.assertIn("RR 1.34", note)
        self.assertIn("pullback_recovery", note)
        self.assertIn("risco retorno aceitavel", note)

    def test_build_position_management_note_uses_preview_rules(self):
        note = TelegramTradingBot._build_position_management_note(
            {
                "stop_loss_pct": 2.0,
                "take_profit_pct": 4.0,
            },
            {
                "volatility_state": "high_volatility",
                "parabolic": True,
            },
        )

        self.assertIn("stop 2.00%", note)
        self.assertIn("take 4.00%", note)
        self.assertIn("BE 1.00R", note)
        self.assertIn("modo aggressive", note)

    def test_build_risk_plan_note_uses_risk_mode_and_quantity(self):
        note = TelegramTradingBot._build_risk_plan_note(
            {
                "allowed": True,
                "risk_mode": "reduced",
                "risk_per_trade_pct": 0.25,
                "risk_amount": 25.0,
                "position_notional": 1250.0,
                "quantity": 12.5,
                "risk_reason": "Losing streak de 3 trades.",
            }
        )

        self.assertIn("Modo de risco: reduced", note)
        self.assertIn("Risco/trade: 0.25%", note)
        self.assertIn("Qtd 12.500000", note)
        self.assertIn("Losing streak de 3 trades.", note)

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

        self.assertIn("Decisao analitica:", note)
        self.assertIn("buy", note)
        self.assertIn("7.60/10", note)
        self.assertIn("bullish pullback", note)
        self.assertIn("nenhum", note)

    def test_build_operational_status_note_marks_blocked_runtime(self):
        note = TelegramTradingBot._build_operational_status_note(
            final_signal="NEUTRO",
            runtime_allowed=False,
            block_reason="Nenhum setup ativo promovido para este mercado/timeframe.",
            block_source="runtime_governance",
            locale="en",
        )

        self.assertIn("Operational status:", note)
        self.assertIn("blocked", note.lower())
        self.assertIn("WAIT", note)
        self.assertIn("runtime_governance", note)

    def test_analyze_command_keeps_analytical_blocks_visible_when_runtime_is_blocked(self):
        bot = TelegramTradingBot.__new__(TelegramTradingBot)
        bot.logger = mock.Mock()
        bot.ai_model = mock.Mock()
        bot.ai_model.predict.return_value = {"signal": "NEUTRO", "confidence": 0.0}
        bot.user_manager = mock.Mock()
        bot.paper_trade_service = mock.Mock()
        bot.paper_trade_service.evaluate_open_trades = mock.Mock()
        bot.paper_trade_service.register_signal = mock.Mock()
        bot.risk_management_service = mock.Mock()

        loading_msg = mock.Mock()
        loading_msg.edit_text = mock.AsyncMock()
        bot._safe_reply = mock.AsyncMock(return_value=loading_msg)

        market_data = pd.DataFrame(
            [
                {
                    "open": 70000.0,
                    "high": 71500.0,
                    "low": 69850.0,
                    "close": 71365.06,
                    "volume": 1250.0,
                    "rsi": 56.2,
                    "macd": 120.55,
                    "macd_signal": 101.12,
                    "market_regime": "trending",
                    "signal_confidence": 7.4,
                    "atr": 850.0,
                }
            ]
        )

        trading_bot = mock.Mock()
        trading_bot.timeframe = "1h"
        trading_bot.get_market_data.return_value = market_data

        trading_bot.evaluate_signal_pipeline.return_value = {
            "candidate_signal": "COMPRA",
            "approved_signal": "COMPRA",
            "blocked_signal": None,
            "analytical_signal": "COMPRA",
            "block_reason": None,
            "block_source": None,
            "context_evaluation": {
                "market_bias": "bullish",
                "regime": "trend_low_vol",
                "context_strength": 7.8,
                "is_tradeable": True,
            },
            "regime_evaluation": {
                "regime": "trend_bull",
                "volatility_state": "high_volatility",
                "regime_score": 8.2,
                "adx": 31.4,
                "atr_pct": 1.86,
                "trend_state": "trend_bull",
                "parabolic": True,
                "notes": ["mercado em trend_bull"],
            },
            "structure_evaluation": {
                "structure_state": "pullback",
                "price_location": "trend_zone",
                "structure_quality": 7.1,
                "breakout": False,
                "reversal_risk": False,
                "distance_from_ema_pct": 0.82,
                "notes": ["pullback controlado", "preco respeitando a EMA 21"],
                "is_tradeable": True,
            },
            "confirmation_evaluation": {
                "confirmation_state": "confirmed",
                "confirmation_score": 7.3,
                "conflicts": [],
                "notes": ["RSI favoravel", "MACD acima do sinal"],
            },
            "entry_quality_evaluation": {
                "entry_quality": "strong",
                "entry_score": 7.4,
                "setup_type": "pullback_trend",
                "rsi_state": "pullback_recovery",
                "candle_quality": "acceptable",
                "momentum_state": "strong",
                "rr_estimate": 2.15,
                "late_entry": False,
                "stretched_price": False,
                "rejection_reason": None,
                "notes": ["entrada proxima da EMA 21", "RR minimo atendido"],
            },
            "scenario_evaluation": {
                "scenario_score": 7.45,
                "scenario_grade": "B",
                "score_breakdown": {
                    "context": 7.8,
                    "structure": 7.1,
                    "confirmation": 7.3,
                    "entry": 7.0,
                },
                "notes": ["cenario favoravel"],
            },
            "trade_decision": {
                "action": "buy",
                "confidence": 7.45,
                "market_bias": "bullish",
                "setup_type": "pullback",
                "entry_reason": "bullish pullback | confirmacao confirmed | entrada good | score 7.45",
                "block_reason": None,
                "invalid_if": "perder a EMA 21",
            },
            "hard_block_evaluation": {
                "hard_block": False,
                "block_reason": None,
                "block_source": "signal_engine",
                "notes": [],
            },
        }
        bot.trading_bot = trading_bot
        bot._resolve_runtime_strategy_settings = mock.Mock(
            return_value={
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "context_timeframe": "4h",
                "strategy_version": "BTCUSDT-1h-rsi14-30-70-sl2.00-tp4.00-v1-t0-r1-ctx4h",
                "runtime_allowed": False,
                "runtime_block_reason": "Nenhum setup ativo promovido para este mercado/timeframe. Runtime bloqueado ate existir perfil ativo.",
                "active_profile": None,
                "require_volume": True,
                "require_trend": False,
                "avoid_ranging": True,
                "stop_loss_pct": 2.0,
                "take_profit_pct": 4.0,
            }
        )

        update = mock.Mock()
        update.effective_user = mock.Mock(id=123, username="tester", language_code="pt-BR")
        update.message = mock.Mock()
        context = mock.Mock(args=["btc/usdt"])

        with mock.patch("telegram_bot.runtime_db.save_trading_signal"), \
             mock.patch.object(TelegramTradingBot, "_apply_edge_guardrail", return_value=("COMPRA", None)), \
             mock.patch.object(TelegramTradingBot, "_apply_risk_guardrail", return_value=("COMPRA", {"allowed": True})):
            asyncio.run(bot.analyze_command(update, context))

        loading_msg.edit_text.assert_awaited_once()
        message = loading_msg.edit_text.await_args.args[0]
        self.assertIn("Sinal (regras): COMPRA", message)
        self.assertIn("Sinal (operacional): NEUTRO", message)
        self.assertIn("Contexto superior: bullish | trend_low_vol | forca 7.80/10", message)
        self.assertIn("Regime: trend_bull | high_volatility | forca 8.20/10", message)
        self.assertIn("Estrutura: pullback", message)
        self.assertIn("Confirmacao: confirmed", message)
        self.assertIn("Entrada: strong", message)
        self.assertIn("setup pullback_trend", message)
        self.assertIn("Cenario: score 7.45/10", message)
        self.assertIn("Decisao analitica: buy", message)
        self.assertIn("Status operacional: blocked", message)
        self.assertIn("runtime_governance", message)
        self.assertNotIn("Estrutura: indisponivel", message)
        self.assertNotIn("Confirmacao: indisponivel", message)
        self.assertNotIn("Entrada: indisponivel", message)
        self.assertNotIn("Cenario: indisponivel", message)
        self.assertNotIn("Risk guardrail:", message)


if __name__ == "__main__":
    unittest.main()
