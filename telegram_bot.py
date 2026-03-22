#!/usr/bin/env python3
"""
Bot Telegram para Trading - Versão Consolidada e Atualizada
Python-telegram-bot v20+
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Verificar se telegram está disponível
try:
    from telegram import Bot, Update
    from telegram.ext import Application, CommandHandler, ContextTypes
    from telegram.error import TelegramError
    import telegram

    TELEGRAM_AVAILABLE = True
    logger.info("python-telegram-bot v%s importado com sucesso", telegram.__version__)

except ImportError as e:
    TELEGRAM_AVAILABLE = False
    logger.warning("Telegram library not available: %s", e)
    logger.warning("Install with: pip install python-telegram-bot==22.6")

    Bot = None
    Update = None
    ContextTypes = None
    Application = None
    CommandHandler = None
    TelegramError = Exception

from user_manager import UserManager
from trading_bot import TradingBot
from ai_model import AIModel
from config import AppConfig, TelegramBotConfig, ProductionConfig
from database.database import build_strategy_version, db as runtime_db
from position_management import build_position_management_preview
from services.paper_trade_service import PaperTradeService
from services.risk_management_service import RiskManagementService

class TelegramTradingBot:
    """Bot Telegram para Trading - Versão Consolidada"""
    
    def __init__(self, allow_simulated_data=False, auto_configure_from_env=True):
        self.allow_simulated_data = allow_simulated_data
        self.auto_configure_from_env = auto_configure_from_env
        self.ai_model = AIModel()
        self.paper_trade_service = PaperTradeService()
        self.risk_management_service = RiskManagementService()
        self.logger = logging.getLogger(self.__class__.__name__)
        
        if not TELEGRAM_AVAILABLE:
            self.logger.error("❌ Telegram library not available")
            self.enabled = False
            self.bot_token = None
            self.bot = None
            self.application = None
            return
            
        self.bot_token = None
        self.bot = None
        self.application = None
        self.enabled = False
        
        # Core services
        try:
            from user_manager import UserManager
            from trading_bot import TradingBot
            self.user_manager = UserManager()
            self.trading_bot = TradingBot(allow_simulated_data=self.allow_simulated_data)
        except ImportError as e:
            self.logger.warning(f"⚠️ Erro ao importar dependências: {e}")
            self.user_manager = None
            self.trading_bot = None
        
        # Auto-configure from environment only when explicitly requested.
        if self.auto_configure_from_env:
            self._auto_configure()
        
    def _auto_configure(self):
        """Auto configure from environment variables"""
        try:
            token = TelegramBotConfig.get_bot_token()
            if token and TELEGRAM_AVAILABLE:
                if self.configure(token):
                    self.logger.info("✅ Bot configurado automaticamente via secrets")
                else:
                    self.logger.error("❌ Erro na configuração automática")
            else:
                if not token:
                    self.logger.debug("TELEGRAM_BOT_TOKEN nao encontrado para auto-configuracao")
                    
        except Exception as e:
            self.logger.error(f"❌ Erro na configuração automática: {e}")
    
    def configure(self, bot_token: str) -> bool:
        """Configure the bot with token"""
        if not TELEGRAM_AVAILABLE:
            self.logger.error("❌ Cannot configure: Telegram library not available")
            return False
            
        if not bot_token or not bot_token.strip():
            self.logger.error("❌ Token do bot está vazio")
            return False
            
        try:
            self.logger.info("🔧 Configurando bot Telegram...")
            
            self.bot_token = bot_token.strip()
            self.bot = Bot(token=self.bot_token)
            
            # Create application
            self.application = Application.builder().token(self.bot_token).build()
            
            # Setup handlers
            self._setup_handlers()
            
            self.enabled = True
            self.logger.info("✅ Bot configurado com sucesso")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Erro ao configurar bot: {e}")
            self.enabled = False
            return False

    def is_configured(self) -> bool:
        return bool(self.enabled and self.application is not None and self.bot_token and TELEGRAM_AVAILABLE)
    
    def _setup_handlers(self):
        """Setup command handlers"""
        if not self.application:
            self.logger.error("❌ Application não inicializada")
            return

        try:
            handlers = [
                ("start", self.start_command),
                ("help", self.help_command),
                ("analise", self.analyze_command),
                ("status", self.status_command),
                ("stats", self.stats_command),
                ("premium", self.premium_command),
                ("users", self.users_command),
                ("upgrade", self.upgrade_command),
                ("broadcast", self.broadcast_command),
            ]

            for command, handler in handlers:
                self.application.add_handler(CommandHandler(command, handler))
                self.logger.debug(f"✅ Handler /{command} adicionado")

            self.logger.info("✅ Todos os handlers configurados")

        except Exception as e:
            self.logger.error(f"❌ Erro ao configurar handlers: {e}")

    async def _safe_reply(self, update: Update, text: str, parse_mode: Optional[str] = None):
        try:
            return await update.message.reply_text(text, parse_mode=parse_mode)
        except TelegramError as telerr:
            self.logger.warning(f"⚠️ Falha ao enviar resposta de Telegram: {telerr}")
            return None
        except Exception as err:
            self.logger.error(f"❌ Erro inesperado ao responder Telegram: {err}")
            return None
    
    @staticmethod
    def _resolve_locale(update: Optional[Update] = None, language_code: Optional[str] = None) -> str:
        resolved_code = language_code
        if not resolved_code and update is not None and getattr(update, "effective_user", None):
            resolved_code = getattr(update.effective_user, "language_code", None)
        resolved_code = str(resolved_code or "pt").lower()
        return "en" if resolved_code.startswith("en") else "pt"

    @staticmethod
    def _display_signal(signal: str, locale: str = "pt") -> str:
        if locale != "en":
            return str(signal or "").replace("_", " ")

        mapping = {
            "COMPRA": "BUY",
            "COMPRA_FRACA": "WEAK BUY",
            "VENDA": "SELL",
            "VENDA_FRACA": "WEAK SELL",
            "NEUTRO": "WAIT",
            "BUY": "BUY",
            "SELL": "SELL",
            "WAIT": "WAIT",
        }
        return mapping.get(str(signal or "").upper(), str(signal or "").replace("_", " "))

    def _apply_edge_guardrail(self, signal: str, symbol: str, timeframe: str, strategy_version: Optional[str] = None):
        if signal not in {"COMPRA", "VENDA", "COMPRA_FRACA", "VENDA_FRACA"}:
            return signal, None
        if not ProductionConfig.ENABLE_EDGE_GUARDRAIL:
            return signal, None

        if strategy_version is None:
            strategy_version = self._build_runtime_strategy_version(symbol, timeframe)

        try:
            edge_summary = runtime_db.get_edge_monitor_summary(
                symbol=symbol,
                timeframe=timeframe,
                strategy_version=strategy_version,
            )
        except Exception as exc:
            self.logger.warning("Falha ao consultar edge monitor: %s", exc)
            return signal, None

        if (
            edge_summary.get("status") == "degraded"
            and edge_summary.get("paper_closed_trades", 0) >= ProductionConfig.MIN_PAPER_TRADES_FOR_EDGE_GUARDRAIL
        ):
            return "NEUTRO", edge_summary

        return signal, edge_summary

    def _build_runtime_strategy_version(
        self,
        symbol: str,
        timeframe: str,
        strategy_settings: Optional[dict] = None,
    ) -> str:
        strategy_settings = strategy_settings or {}
        return build_strategy_version(
            symbol=symbol,
            timeframe=timeframe,
            context_timeframe=strategy_settings.get("context_timeframe"),
            rsi_period=strategy_settings.get("rsi_period", getattr(self.trading_bot, "rsi_period", 14)),
            rsi_min=strategy_settings.get("rsi_min", getattr(self.trading_bot, "rsi_min", 20)),
            rsi_max=strategy_settings.get("rsi_max", getattr(self.trading_bot, "rsi_max", 80)),
            stop_loss_pct=strategy_settings.get("stop_loss_pct", 0.0) or 0.0,
            take_profit_pct=strategy_settings.get("take_profit_pct", 0.0) or 0.0,
            require_volume=strategy_settings.get("require_volume", True),
            require_trend=strategy_settings.get("require_trend", False),
            avoid_ranging=strategy_settings.get("avoid_ranging", True),
        )

    @staticmethod
    def _build_regime_note(regime_evaluation: Optional[dict], locale: str = "pt") -> str:
        if not regime_evaluation:
            return "Regime: unavailable" if locale == "en" else "Regime: indisponivel"

        notes_preview = ", ".join((regime_evaluation.get("notes") or [])[:2]) or (
            "no relevant notes" if locale == "en" else "sem notas relevantes"
        )
        return (
            f"{'Regime' if locale == 'en' else 'Regime'}: {regime_evaluation.get('regime', 'range')} | "
            f"{regime_evaluation.get('volatility_state', 'normal_volatility')} | "
            f"{'strength' if locale == 'en' else 'forca'} {float(regime_evaluation.get('regime_score', 0) or 0):.2f}/10 | "
            f"ADX {float(regime_evaluation.get('adx', 0) or 0):.2f} | "
            f"ATR% {float(regime_evaluation.get('atr_pct', 0) or 0):.2f} | "
            f"trend {regime_evaluation.get('trend_state', 'range')} | "
            f"parabolic {bool(regime_evaluation.get('parabolic', False))} | "
            f"{'notes' if locale == 'en' else 'notas'}: {notes_preview}"
        )

    @staticmethod
    def _build_governance_note(governance_summary: Optional[dict], locale: str = "pt") -> str:
        if not governance_summary:
            return "Governance: unavailable" if locale == "en" else "Governanca: indisponivel"

        allowed_regimes = ", ".join(governance_summary.get("allowed_regimes", [])[:3]) or "-"
        blocked_regimes = ", ".join(governance_summary.get("blocked_regimes", [])[:3]) or "-"
        return (
            f"{'Governance' if locale == 'en' else 'Governanca'}: {governance_summary.get('governance_status', 'research')} | "
            f"{'mode' if locale == 'en' else 'modo'} {governance_summary.get('governance_mode', 'blocked')} | "
            f"alignment {governance_summary.get('alignment_status', 'insufficient')} | "
            f"{'current regime' if locale == 'en' else 'regime atual'} {governance_summary.get('current_regime') or '-'} "
            f"({governance_summary.get('current_regime_status', 'unknown')}) | "
            f"{'allowed' if locale == 'en' else 'aprovados'} {allowed_regimes} | "
            f"{'blocked' if locale == 'en' else 'bloqueados'} {blocked_regimes} | "
            f"{'reason' if locale == 'en' else 'motivo'}: {governance_summary.get('action_reason') or '-'}"
        )

    @staticmethod
    def _build_structure_note(structure_evaluation: Optional[dict], locale: str = "pt") -> str:
        if not structure_evaluation:
            return "Structure: unavailable" if locale == "en" else "Estrutura: indisponivel"

        distance_from_ema_pct = structure_evaluation.get("distance_from_ema_pct")
        if isinstance(distance_from_ema_pct, (int, float)):
            distance_text = f"{float(distance_from_ema_pct):.2f}%"
        else:
            distance_text = "-"

        notes = structure_evaluation.get("notes") or []
        notes_preview = ", ".join(str(note) for note in notes[:2]) or (
            "no relevant notes" if locale == "en" else "sem observacoes relevantes"
        )

        return (
            f"{'Structure' if locale == 'en' else 'Estrutura'}: {structure_evaluation.get('structure_state', 'weak_structure')} | "
            f"{structure_evaluation.get('price_location', 'mid_range')} | "
            f"{'quality' if locale == 'en' else 'qualidade'} {structure_evaluation.get('structure_quality', 0):.2f}/10 | "
            f"breakout {bool(structure_evaluation.get('breakout', False))} | "
            f"reversal_risk {bool(structure_evaluation.get('reversal_risk', False))} | "
            f"dist EMA {distance_text} | "
            f"{'notes' if locale == 'en' else 'notas'}: {notes_preview}"
        )

    @staticmethod
    def _build_confirmation_note(confirmation_evaluation: Optional[dict], locale: str = "pt") -> str:
        if not confirmation_evaluation:
            return "Confirmation: unavailable" if locale == "en" else "Confirmacao: indisponivel"

        conflicts_preview = ", ".join(confirmation_evaluation.get("conflicts", [])[:2]) or (
            "no relevant conflicts" if locale == "en" else "sem conflitos relevantes"
        )
        notes_preview = ", ".join(confirmation_evaluation.get("notes", [])[:2]) or (
            "no relevant notes" if locale == "en" else "sem notas relevantes"
        )

        return (
            f"{'Confirmation' if locale == 'en' else 'Confirmacao'}: {confirmation_evaluation.get('confirmation_state', 'weak')} | "
            f"score {confirmation_evaluation.get('confirmation_score', 0):.2f}/10 | "
            f"{'conflicts' if locale == 'en' else 'conflitos'}: {conflicts_preview} | "
            f"{'notes' if locale == 'en' else 'notas'}: {notes_preview}"
        )

    @staticmethod
    def _build_entry_quality_note(entry_quality_evaluation: Optional[dict], locale: str = "pt") -> str:
        if not entry_quality_evaluation:
            return "Entry: unavailable" if locale == "en" else "Entrada: indisponivel"

        notes_preview = ", ".join(entry_quality_evaluation.get("notes", [])[:2]) or (
            "no relevant notes" if locale == "en" else "sem notas relevantes"
        )
        rejection_reason = entry_quality_evaluation.get("rejection_reason") or (
            "none" if locale == "en" else "nenhum"
        )
        return (
            f"{'Entry' if locale == 'en' else 'Entrada'}: {entry_quality_evaluation.get('entry_quality', 'bad')} | "
            f"score {float(entry_quality_evaluation.get('entry_score', 0) or 0):.2f}/10 | "
            f"setup {entry_quality_evaluation.get('setup_type') or '-'} | "
            f"RSI {entry_quality_evaluation.get('rsi_state', 'neutral')} | "
            f"candle {entry_quality_evaluation.get('candle_quality', 'bad')} | "
            f"momentum {entry_quality_evaluation.get('momentum_state', 'weak')} | "
            f"RR {entry_quality_evaluation.get('rr_estimate', 0):.2f} | "
            f"reject {rejection_reason} | "
            f"{'notes' if locale == 'en' else 'notas'}: {notes_preview}"
        )

    @staticmethod
    def _build_position_management_note(
        strategy_settings: Optional[dict],
        regime_evaluation: Optional[dict],
        locale: str = "pt",
    ) -> str:
        if not strategy_settings:
            return "Position management: unavailable" if locale == "en" else "Gestao da posicao: indisponivel"

        preview = build_position_management_preview(
            stop_loss_pct=float(strategy_settings.get("stop_loss_pct", 0.0) or 0.0),
            take_profit_pct=float(strategy_settings.get("take_profit_pct", 0.0) or 0.0),
            regime_evaluation=regime_evaluation,
        )
        return (
            f"{'Position management' if locale == 'en' else 'Gestao da posicao'}: "
            f"{'stop' if locale == 'en' else 'stop'} {preview.get('initial_stop_pct', 0.0):.2f}% | "
            f"{'take' if locale == 'en' else 'take'} {preview.get('initial_take_pct', 0.0):.2f}% | "
            f"BE {preview.get('break_even_trigger_r', 1.0):.2f}R | "
            f"trail {preview.get('trailing_trigger_r', 2.0):.2f}R/{preview.get('trailing_atr_multiplier', 1.8):.2f} ATR | "
            f"{'mode' if locale == 'en' else 'modo'} {preview.get('protection_mode', 'normal')}"
        )

    @staticmethod
    def _build_risk_plan_note(risk_plan: Optional[dict], locale: str = "pt") -> str:
        if not risk_plan:
            return ""
        if risk_plan.get("allowed"):
            label = "Risk mode" if locale == "en" else "Modo de risco"
            risk_label = "Risk/trade" if locale == "en" else "Risco/trade"
            position_label = "Position" if locale == "en" else "Posicao"
            quantity_label = "Qty" if locale == "en" else "Qtd"
            reason_note = risk_plan.get("risk_reason") or ""
            suffix = f" | reason {reason_note}" if locale == "en" and reason_note else f" | motivo {reason_note}" if reason_note else ""
            return (
                f"\n{label}: {risk_plan.get('risk_mode', 'normal')} | "
                f"{risk_label}: {risk_plan.get('risk_per_trade_pct', 0):.2f}% "
                f"(${risk_plan.get('risk_amount', 0):.2f}) | "
                f"{position_label} ${risk_plan.get('position_notional', 0):.2f} | "
                f"{quantity_label} {risk_plan.get('quantity', 0):.6f}{suffix}"
            )
        reason = risk_plan.get("risk_reason") or risk_plan.get("reason")
        return (
            f"\nRisk guardrail: {reason}"
            if locale == "en"
            else
            f"\nGuardrail de risco: {reason}"
        )

    @staticmethod
    def _build_scenario_note(scenario_evaluation: Optional[dict], locale: str = "pt") -> str:
        if not scenario_evaluation:
            return "Scenario: unavailable" if locale == "en" else "Cenario: indisponivel"

        breakdown = scenario_evaluation.get("score_breakdown", {}) or {}
        notes_preview = ", ".join((scenario_evaluation.get("notes") or [])[:2]) or (
            "no relevant notes" if locale == "en" else "sem notas relevantes"
        )
        return (
            f"{'Scenario' if locale == 'en' else 'Cenario'}: "
            f"score {scenario_evaluation.get('scenario_score', 0):.2f}/10 | "
            f"grade {scenario_evaluation.get('scenario_grade', 'D')} | "
            f"ctx {float(breakdown.get('context', 0) or 0):.1f} | "
            f"struct {float(breakdown.get('structure', 0) or 0):.1f} | "
            f"confirm {float(breakdown.get('confirmation', 0) or 0):.1f} | "
            f"entry {float(breakdown.get('entry', 0) or 0):.1f} | "
            f"{'notes' if locale == 'en' else 'notas'}: {notes_preview}"
        )

    @staticmethod
    def _build_trade_decision_note(trade_decision: Optional[dict], locale: str = "pt") -> str:
        if not trade_decision:
            return "Analytical decision: unavailable" if locale == "en" else "Decisao analitica: indisponivel"

        action = str(trade_decision.get("action") or "wait")
        entry_reason = trade_decision.get("entry_reason") or (
            "no valid entry" if locale == "en" else "sem entrada valida"
        )
        block_reason = trade_decision.get("block_reason") or (
            "none" if locale == "en" else "nenhum"
        )
        return (
            f"{'Analytical decision' if locale == 'en' else 'Decisao analitica'}: {action} | "
            f"{'confidence' if locale == 'en' else 'confianca'} {float(trade_decision.get('confidence', 0) or 0):.2f}/10 | "
            f"{'reason' if locale == 'en' else 'motivo'}: {entry_reason} | "
            f"{'block' if locale == 'en' else 'bloqueio'}: {block_reason}"
        )

    @staticmethod
    def _build_operational_status_note(
        final_signal: str,
        runtime_allowed: bool,
        block_reason: Optional[str] = None,
        block_source: Optional[str] = None,
        locale: str = "pt",
    ) -> str:
        status_label = "allowed" if runtime_allowed and not block_reason else "blocked"
        reason_text = block_reason or ("none" if locale == "en" else "nenhum")
        source_text = f" ({block_source})" if block_source else ""
        return (
            f"{'Operational status' if locale == 'en' else 'Status operacional'}: {status_label} | "
            f"{'final action' if locale == 'en' else 'acao final'} {TelegramTradingBot._display_signal(final_signal, locale)} | "
            f"{'reason' if locale == 'en' else 'motivo'}: {reason_text}{source_text}"
        )

    @staticmethod
    def _build_strategy_runtime_note(strategy_settings: Optional[dict], locale: str = "pt") -> str:
        strategy_settings = strategy_settings or {}
        active_profile = strategy_settings.get("active_profile")
        runtime_strategy_version = strategy_settings.get("strategy_version", "-")
        runtime_allowed = bool(strategy_settings.get("runtime_allowed", True))
        runtime_block_reason = strategy_settings.get("runtime_block_reason", "")

        if active_profile:
            return (
                f"Active profile: {active_profile.get('strategy_version', runtime_strategy_version)}"
                if locale == "en"
                else f"Perfil ativo: {active_profile.get('strategy_version', runtime_strategy_version)}"
            )

        if not runtime_allowed:
            if locale == "en":
                return (
                    "Active profile: none\n"
                    f"Configured strategy: {runtime_strategy_version}\n"
                    f"Runtime status: blocked by governance ({runtime_block_reason})"
                )
            return (
                "Perfil ativo: nenhum\n"
                f"Estrategia configurada: {runtime_strategy_version}\n"
                f"Status do runtime: bloqueado por governanca ({runtime_block_reason})"
            )

        if locale == "en":
            return (
                "Active profile: none\n"
                f"Configured strategy: {runtime_strategy_version}\n"
                "Runtime status: no active profile, but allowed by configuration"
            )
        return (
            "Perfil ativo: nenhum\n"
            f"Estrategia configurada: {runtime_strategy_version}\n"
            "Status do runtime: sem perfil ativo, mas liberado por configuracao"
        )

    def _resolve_runtime_strategy_settings(self, symbol: str, timeframe: str) -> dict:
        default_context_timeframe = AppConfig.get_context_timeframe(timeframe)
        if not self.trading_bot:
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "context_timeframe": default_context_timeframe,
                "rsi_period": 14,
                "rsi_min": 20,
                "rsi_max": 80,
                "stop_loss_pct": ProductionConfig.DEFAULT_LIVE_STOP_LOSS_PCT,
                "take_profit_pct": ProductionConfig.DEFAULT_LIVE_TAKE_PROFIT_PCT,
                "require_volume": True,
                "require_trend": False,
                "active_profile": None,
                "runtime_allowed": False,
                "runtime_block_reason": "Trading bot indisponivel para resolver setup ativo.",
            }

        active_profile = runtime_db.get_active_strategy_profile(symbol=symbol, timeframe=timeframe)
        if active_profile:
            self.trading_bot.update_config(
                symbol=symbol,
                timeframe=timeframe,
                rsi_period=active_profile.get("rsi_period"),
                rsi_min=active_profile.get("rsi_min"),
                rsi_max=active_profile.get("rsi_max"),
            )
            settings = {
                "symbol": symbol,
                "timeframe": timeframe,
                "context_timeframe": active_profile.get("context_timeframe"),
                "rsi_period": active_profile.get("rsi_period"),
                "rsi_min": active_profile.get("rsi_min"),
                "rsi_max": active_profile.get("rsi_max"),
                "stop_loss_pct": active_profile.get("stop_loss_pct") or ProductionConfig.DEFAULT_LIVE_STOP_LOSS_PCT,
                "take_profit_pct": active_profile.get("take_profit_pct") or ProductionConfig.DEFAULT_LIVE_TAKE_PROFIT_PCT,
                "require_volume": bool(active_profile.get("require_volume", False)),
                "require_trend": bool(active_profile.get("require_trend", False)),
                "avoid_ranging": bool(active_profile.get("avoid_ranging", False)),
                "active_profile": active_profile,
                "runtime_allowed": True,
                "runtime_block_reason": "",
            }
        else:
            self.trading_bot.update_config(symbol=symbol, timeframe=timeframe)
            runtime_block_reason = ""
            runtime_allowed = True
            if ProductionConfig.REQUIRE_ACTIVE_PROFILE_FOR_RUNTIME:
                runtime_allowed = False
                runtime_block_reason = (
                    "Nenhum setup ativo promovido para este mercado/timeframe. "
                    "Runtime bloqueado ate existir perfil ativo."
                )
            settings = {
                "symbol": symbol,
                "timeframe": timeframe,
                "context_timeframe": default_context_timeframe,
                "rsi_period": getattr(self.trading_bot, "rsi_period", 14),
                "rsi_min": getattr(self.trading_bot, "rsi_min", 20),
                "rsi_max": getattr(self.trading_bot, "rsi_max", 80),
                "stop_loss_pct": ProductionConfig.DEFAULT_LIVE_STOP_LOSS_PCT,
                "take_profit_pct": ProductionConfig.DEFAULT_LIVE_TAKE_PROFIT_PCT,
                "require_volume": True,
                "require_trend": False,
                "avoid_ranging": True,
                "active_profile": None,
                "runtime_allowed": runtime_allowed,
                "runtime_block_reason": runtime_block_reason,
            }

        settings["strategy_version"] = self._build_runtime_strategy_version(symbol, timeframe, settings)
        return settings

    def _merge_rule_and_ai_signal(self, signal: str, ai_signal: str) -> str:
        if not ProductionConfig.ENABLE_AI_SIGNAL_INFLUENCE:
            return signal

        final_signal = signal
        if ai_signal in ["BUY", "SELL"] and signal in ["COMPRA", "VENDA"]:
            final_signal = signal
        elif ai_signal == "BUY" and signal in ["NEUTRO", "VENDA", "VENDA_FRACA"]:
            final_signal = "COMPRA_FRACA"
        elif ai_signal == "SELL" and signal in ["NEUTRO", "COMPRA", "COMPRA_FRACA"]:
            final_signal = "VENDA_FRACA"
        return final_signal

    def _apply_risk_guardrail(
        self,
        signal: str,
        entry_price: float,
        strategy_settings: dict,
        runtime_allowed: bool = True,
        runtime_block_reason: str = None,
        system_health_ok: bool = True,
        system_health_reason: str = None,
    ):
        if signal not in {"COMPRA", "VENDA", "COMPRA_FRACA", "VENDA_FRACA"}:
            return signal, None

        risk_plan = self.risk_management_service.evaluate_risk_engine(
            entry_price=float(entry_price),
            stop_loss_pct=strategy_settings.get("stop_loss_pct", 0.0) or 0.0,
            symbol=strategy_settings.get("symbol"),
            timeframe=strategy_settings.get("timeframe"),
            strategy_version=strategy_settings.get("strategy_version"),
            runtime_allowed=runtime_allowed,
            runtime_block_reason=runtime_block_reason,
            system_health_ok=system_health_ok,
            system_health_reason=system_health_reason,
        )
        if not risk_plan.get("allowed"):
            return "NEUTRO", risk_plan
        return signal, risk_plan

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        try:
            user_id = update.effective_user.id
            username = update.effective_user.username or "sem_username"
            first_name = update.effective_user.first_name or "Usuário"

            self.logger.info(f"📥 Comando /start recebido de {user_id} ({first_name})")

            if self.user_manager:
                self.user_manager.get_or_create_user(user_id, username, first_name)

            supported_pairs = TelegramBotConfig.SUPPORTED_PAIRS[:6]

            welcome_message = f"""🤖 **Bem-vindo ao Trading Bot!**

    Olá {first_name}! 👋

    **Sobre o bot:**
    • Análises técnicas de criptomoedas em tempo real
    • Sinais baseados em RSI e MACD
    • Suporte a múltiplos pares de trading

    **Comandos principais:**
    • /analise BTC/USDT - Analisar criptomoeda
    • /status - Ver seu status e limites
    • /help - Ver todos os comandos
    • /premium - Informações sobre Premium

    **Pares suportados:**
    {', '.join(supported_pairs)}

    **Tipos de Usuário:**
    • Free: 1 análise por dia
    • Premium: Análises ilimitadas

    **Exemplo de uso:**
    /analise BTC/USDT

    Vamos começar a analisar o mercado! 📈"""

            await self._safe_reply(update, welcome_message, parse_mode="Markdown")
            self.logger.info(f"✅ Usuário {user_id} - comando /start processado com sucesso")

        except Exception as e:
            self.logger.exception(e)
            await self._safe_reply(update, "❌ Erro interno no comando /start. Tente novamente em alguns minutos.")
        
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        try:
            user_id = update.effective_user.id

            self.user_manager.get_or_create_user(
                user_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name
            )

            is_admin = self.user_manager.is_admin(user_id)
            is_premium = self.user_manager.is_premium(user_id)

            help_text = (
                "Comandos Disponiveis:\n\n"
                "Analises:\n"
                "- /analise BTC/USDT - Analisar criptomoeda\n"
                "- /status - Ver seu status e limites\n\n"
                "Premium:\n"
                "- /premium - Informacoes sobre Premium\n"
                f"{'- Voce e Premium!' if is_premium else '- Plano Free (1 analise/dia)'}\n\n"
                "Pares suportados:\n"
                + ", ".join(TelegramBotConfig.SUPPORTED_PAIRS)
            )

            if is_admin:
                help_text += (
                    "\n\nComandos de Admin:\n"
                    "- /stats\n"
                    "- /users\n"
                    "- /upgrade [ID]\n"
                    "- /broadcast [MSG]"
                )

            await self._safe_reply(update, help_text)

        except Exception as e:
            self.logger.exception(e)
            await self._safe_reply(update, f"Erro no /help: {e}")
    
    async def analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /analise command"""
        try:
            locale = self._resolve_locale(update)
            user_id = update.effective_user.id

            self.user_manager.get_or_create_user(
                user_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name
            )

            if not self.user_manager.can_analyze(user_id):
                await self._safe_reply(
                    update,
                    (
                        "Limit reached!\n\n"
                        "Free users can request 1 analysis per day.\n\n"
                        "Upgrade to Premium and get:\n"
                        "- Unlimited analyses\n"
                        "- Real-time alerts\n"
                        "- More detailed analyses\n\n"
                        "Use /premium for more details!"
                    )
                    if locale == "en"
                    else
                    "Limite atingido!\n\n"
                    "Usuarios Free tem direito a 1 analise por dia.\n\n"
                    "Upgrade para Premium e tenha:\n"
                    "- Analises ilimitadas\n"
                    "- Alerts em tempo real\n"
                    "- Analises mais detalhadas\n\n"
                    "Use /premium para mais informacoes!"
                )
                return

            if not context.args:
                await self._safe_reply(
                    update,
                    (
                        "Invalid format!\n\n"
                        "Correct usage:\n"
                        "/analise BTC/USDT\n\n"
                        "Available pairs:\n"
                        if locale == "en"
                        else
                        "Formato incorreto!\n\n"
                        "Uso correto:\n"
                        "/analise BTC/USDT\n\n"
                        "Pares disponiveis:\n"
                    )
                    + ", ".join(TelegramBotConfig.SUPPORTED_PAIRS[:6]) + "..."
                )
                return

            symbol = context.args[0].upper()

            if not TelegramBotConfig.is_valid_pair(symbol):
                await self._safe_reply(
                    update,
                    (
                        f"Unsupported pair: {symbol}\n\n"
                        f"Available pairs:\n{', '.join(TelegramBotConfig.SUPPORTED_PAIRS)}"
                    )
                    if locale == "en"
                    else
                    f"Par nao suportado: {symbol}\n\n"
                    f"Pares disponiveis:\n{', '.join(TelegramBotConfig.SUPPORTED_PAIRS)}"
                )
                return

            loading_msg = await self._safe_reply(
                update,
                "Analyzing...\nPlease wait..." if locale == "en" else "Analisando...\nPor favor aguarde...",
            )

            if loading_msg is None:
                return

            if not self.trading_bot:
                await loading_msg.edit_text("Error: TradingBot not initialized" if locale == "en" else "Erro: TradingBot não inicializado")
                return

            initial_timeframe = getattr(self.trading_bot, "timeframe", "5m")
            strategy_settings = self._resolve_runtime_strategy_settings(symbol, initial_timeframe)
            active_profile = strategy_settings.get("active_profile")

            data = None
            market_data_error = None
            for attempt in range(3):
                try:
                    data = self.trading_bot.get_market_data(
                        symbol=symbol,
                        timeframe=strategy_settings["timeframe"],
                    )
                    if data is not None and not data.empty:
                        break
                except Exception as e:
                    market_data_error = e
                    self.logger.warning(f"Tentativa {attempt + 1} falhou: {e}")
                    if attempt < 2:
                        await asyncio.sleep(1)

            if data is None or data.empty:
                error_suffix = (
                    f"\nDetail: {market_data_error}" if locale == "en" and market_data_error else
                    f"\nDetalhe: {market_data_error}" if market_data_error else ""
                )
                await loading_msg.edit_text(
                    ("Error: Could not obtain real market data right now." if locale == "en" else "Erro: Nao foi possivel obter dados reais do mercado no momento.")
                    + error_suffix
                )
                return

            last_candle = data.iloc[-1]
            timeframe = strategy_settings["timeframe"]
            runtime_block_reason = strategy_settings.get("runtime_block_reason", "")
            context_evaluation = None
            regime_evaluation = None
            structure_evaluation = None
            confirmation_evaluation = None
            entry_quality_evaluation = None
            scenario_evaluation = None
            trade_decision = None
            hard_block_evaluation = None
            governance_summary = None
            signal_pipeline = self.trading_bot.evaluate_signal_pipeline(
                data,
                timeframe=timeframe,
                require_volume=strategy_settings.get("require_volume", True),
                require_trend=strategy_settings.get("require_trend", False),
                avoid_ranging=strategy_settings.get("avoid_ranging", True),
                context_timeframe=strategy_settings.get("context_timeframe"),
                stop_loss_pct=strategy_settings.get("stop_loss_pct"),
                take_profit_pct=strategy_settings.get("take_profit_pct"),
            )
            signal = signal_pipeline["analytical_signal"]
            context_evaluation = signal_pipeline.get("context_evaluation")
            regime_evaluation = signal_pipeline.get("regime_evaluation")
            structure_evaluation = signal_pipeline.get("structure_evaluation")
            confirmation_evaluation = signal_pipeline.get("confirmation_evaluation")
            entry_quality_evaluation = signal_pipeline.get("entry_quality_evaluation")
            scenario_evaluation = signal_pipeline.get("scenario_evaluation")
            trade_decision = signal_pipeline.get("trade_decision")
            hard_block_evaluation = signal_pipeline.get("hard_block_evaluation")
            current_governance_regime = (regime_evaluation or {}).get("regime")
            if (regime_evaluation or {}).get("parabolic"):
                current_governance_regime = "parabolic"
            try:
                governance_summary = runtime_db.evaluate_strategy_governance(
                    symbol=symbol,
                    timeframe=timeframe,
                    strategy_version=strategy_settings.get("strategy_version"),
                    current_regime=current_governance_regime,
                    persist=False,
                )
            except Exception as governance_exc:
                self.logger.warning("Falha na governanca adaptativa: %s", governance_exc)
            emoji = TelegramBotConfig.get_signal_emoji(signal)

            ai_signal = "NEUTRO"
            ai_confidence = 0.0

            try:
                ai_pred = self.ai_model.predict(data)
                ai_signal = ai_pred.get("signal", "NEUTRO")
                ai_confidence = ai_pred.get("confidence", 0.0)
            except Exception as e:
                self.logger.warning(f"Falha na IA: {e}")

            runtime_strategy_version = strategy_settings["strategy_version"]
            final_signal = signal
            edge_summary = None
            risk_plan = None
            operational_runtime_allowed = bool(strategy_settings.get("runtime_allowed", True))
            operational_block_reason = None
            operational_block_source = None
            edge_allowed = True
            edge_block_reason = None
            if operational_runtime_allowed:
                final_signal = self._merge_rule_and_ai_signal(signal, ai_signal)
                edge_signal, edge_summary = self._apply_edge_guardrail(
                    final_signal,
                    symbol,
                    timeframe,
                    strategy_version=runtime_strategy_version,
                )
                edge_allowed = edge_signal in {"COMPRA", "VENDA", "COMPRA_FRACA", "VENDA_FRACA"} or final_signal == "NEUTRO"
                if edge_summary and edge_signal == "NEUTRO" and final_signal != "NEUTRO":
                    edge_block_reason = edge_summary.get("status_message") or "Edge monitor bloqueou o setup."
                final_signal, risk_plan = self._apply_risk_guardrail(
                    final_signal,
                    float(last_candle["close"]),
                    strategy_settings,
                    runtime_allowed=True,
                    system_health_ok=edge_allowed,
                    system_health_reason=edge_block_reason,
                )
                if edge_summary and not edge_allowed:
                    operational_block_reason = edge_block_reason
                    operational_block_source = "edge_guardrail"
                    operational_runtime_allowed = False
                elif risk_plan and not risk_plan.get("allowed"):
                    operational_block_reason = (
                        risk_plan.get("risk_reason") or risk_plan.get("reason") or "Risco operacional bloqueou a entrada."
                    )
                    operational_block_source = "risk_guardrail"
                    operational_runtime_allowed = False
                elif governance_summary and not operational_block_reason and governance_summary.get("governance_mode") == "blocked":
                    final_signal = "NEUTRO"
                    operational_block_reason = governance_summary.get("action_reason") or "Governanca adaptativa bloqueou o setup."
                    operational_block_source = "adaptive_governance"
                    operational_runtime_allowed = False
                elif governance_summary and governance_summary.get("governance_mode") == "reduced" and risk_plan and risk_plan.get("allowed"):
                    risk_plan["governance_mode"] = "reduced"
                    risk_plan["governance_reduction_multiplier"] = governance_summary.get("governance_reduction_multiplier", 1.0)
                    risk_plan["risk_reason"] = risk_plan.get("risk_reason") or governance_summary.get("action_reason")
                emoji = TelegramBotConfig.get_signal_emoji(final_signal)
            else:
                final_signal = "NEUTRO"
                runtime_block_reason = strategy_settings.get("runtime_block_reason", "Runtime bloqueado")
                _, risk_plan = self._apply_risk_guardrail(
                    signal,
                    float(last_candle["close"]),
                    strategy_settings,
                    runtime_allowed=False,
                    runtime_block_reason=runtime_block_reason,
                )
                operational_block_reason = (
                    (risk_plan or {}).get("risk_reason")
                    or (risk_plan or {}).get("reason")
                    or runtime_block_reason
                )
                operational_block_source = "runtime_governance"
                emoji = TelegramBotConfig.get_signal_emoji(final_signal)
            edge_guardrail_note = ""
            if edge_summary and edge_summary.get("status") == "degraded" and final_signal == "NEUTRO":
                edge_guardrail_note = (
                    f"\nGuardrail: setup blocked by paper-trade degradation "
                    f"({edge_summary.get('paper_closed_trades', 0)} closed trades)."
                    if locale == "en"
                    else
                    f"\nGuardrail: setup bloqueado por degradacao no paper trade "
                    f"({edge_summary.get('paper_closed_trades', 0)} trades fechados)."
                )
            risk_guardrail_note = ""
            risk_plan_note = ""
            if risk_plan:
                rendered_risk_note = self._build_risk_plan_note(risk_plan, locale=locale)
                if risk_plan.get("allowed"):
                    risk_plan_note = rendered_risk_note
                else:
                    risk_guardrail_note = rendered_risk_note
            ai_mode_note = "comparative" if locale == "en" and not ProductionConfig.ENABLE_AI_SIGNAL_INFLUENCE else "comparativo" if not ProductionConfig.ENABLE_AI_SIGNAL_INFLUENCE else "influence" if locale == "en" else "influencia"
            context_note = "Higher timeframe: no filter" if locale == "en" else "Contexto superior: sem filtro"
            if context_evaluation:
                context_note = (
                    f"Higher timeframe: {context_evaluation.get('market_bias', 'neutral')} | "
                    f"{context_evaluation.get('regime', '-')} | "
                    f"strength {context_evaluation.get('context_strength', 0):.2f}/10"
                    if locale == "en"
                    else
                    f"Contexto superior: {context_evaluation.get('market_bias', 'neutral')} | "
                    f"{context_evaluation.get('regime', '-')} | "
                    f"forca {context_evaluation.get('context_strength', 0):.2f}/10"
                )
            regime_note = self._build_regime_note(regime_evaluation, locale=locale)
            governance_note = self._build_governance_note(governance_summary, locale=locale)
            structure_note = "Structure: unavailable" if locale == "en" else "Estrutura: indisponivel"
            if structure_evaluation:
                structure_note = self._build_structure_note(structure_evaluation, locale=locale)
            confirmation_note = "Confirmation: unavailable" if locale == "en" else "Confirmacao: indisponivel"
            if confirmation_evaluation:
                confirmation_note = self._build_confirmation_note(confirmation_evaluation, locale=locale)
            entry_quality_note = "Entry: unavailable" if locale == "en" else "Entrada: indisponivel"
            if entry_quality_evaluation:
                entry_quality_note = self._build_entry_quality_note(entry_quality_evaluation, locale=locale)
            management_note = self._build_position_management_note(
                strategy_settings,
                regime_evaluation,
                locale=locale,
            )
            scenario_note = "Scenario: unavailable" if locale == "en" else "Cenario: indisponivel"
            if scenario_evaluation:
                scenario_note = self._build_scenario_note(scenario_evaluation, locale=locale)
            decision_note = "Analytical decision: unavailable" if locale == "en" else "Decisao analitica: indisponivel"
            if trade_decision:
                decision_note = self._build_trade_decision_note(trade_decision, locale=locale)
            operational_note = self._build_operational_status_note(
                final_signal=final_signal,
                runtime_allowed=operational_runtime_allowed,
                block_reason=operational_block_reason,
                block_source=operational_block_source,
                locale=locale,
            )
            hard_block_note = ""
            if hard_block_evaluation and hard_block_evaluation.get("hard_block"):
                hard_block_note = (
                    f"{'Analytical hard block' if locale == 'en' else 'Hard block analitico'}: {hard_block_evaluation.get('block_reason')} "
                    f"({hard_block_evaluation.get('block_source', 'signal_engine')})\n"
                )
            entry_reason = final_signal
            if final_signal != "NEUTRO":
                reason_parts = [final_signal]
                if context_evaluation:
                    reason_parts.append(
                        f"ctx:{context_evaluation.get('market_bias', 'neutral')}/{context_evaluation.get('regime', '-')}"
                    )
                if regime_evaluation:
                    reason_parts.append(
                        f"regime:{regime_evaluation.get('regime', '-')}/{regime_evaluation.get('volatility_state', '-')}"
                    )
                if structure_evaluation:
                    reason_parts.append(
                        f"struct:{structure_evaluation.get('structure_state', '-')}/{structure_evaluation.get('price_location', '-')}"
                    )
                if confirmation_evaluation:
                    reason_parts.append(
                        f"confirm:{confirmation_evaluation.get('confirmation_state', '-')}/{confirmation_evaluation.get('confirmation_score', 0):.1f}"
                    )
                if entry_quality_evaluation:
                    reason_parts.append(
                        f"entry:{entry_quality_evaluation.get('setup_type') or '-'}"
                        f"/{entry_quality_evaluation.get('entry_quality', '-')}"
                        f"/s{float(entry_quality_evaluation.get('entry_score', 0) or 0):.1f}"
                    )
                entry_reason = " | ".join(reason_parts)

            analysis_message = (
                f"{'Technical Analysis' if locale == 'en' else 'Analise Tecnica'} - {symbol}\n\n"
                f"{emoji} {'Signal (rules)' if locale == 'en' else 'Sinal (regras)'}: {self._display_signal(signal, locale)}\n"
                f"{'Signal (AI - ' if locale == 'en' else 'Sinal (IA - '}{ai_mode_note}): {self._display_signal(ai_signal, locale)} (conf: {ai_confidence:.2f})\n"
                f"{'Signal (operational)' if locale == 'en' else 'Sinal (operacional)'}: {self._display_signal(final_signal, locale)}\n\n"
                f"{self._build_strategy_runtime_note(strategy_settings, locale=locale)}\n"
                f"{'Context' if locale == 'en' else 'Contexto'}: {strategy_settings.get('context_timeframe') or ('no higher filter' if locale == 'en' else 'sem filtro superior')}\n"
                f"{context_note}\n"
                f"{regime_note}\n"
                f"{governance_note}\n"
                f"{structure_note}\n"
                f"{confirmation_note}\n"
                f"{entry_quality_note}\n"
                f"{management_note}\n"
                f"{scenario_note}\n"
                f"{decision_note}\n"
                f"{operational_note}\n"
                f"{hard_block_note}"
                f"{'Current Price' if locale == 'en' else 'Preco Atual'}: ${last_candle['close']:.6f}\n"
                f"{'Change' if locale == 'en' else 'Variacao'}: {((last_candle['close'] - last_candle['open']) / last_candle['open'] * 100):+.2f}%\n\n"
                f"{'Indicators' if locale == 'en' else 'Indicadores'}:\n"
                f"- RSI: {last_candle['rsi']:.2f}\n"
                f"- MACD: {last_candle['macd']:.4f}\n"
                f"- MACD Signal: {last_candle['macd_signal']:.4f}\n\n"
                f"{'Updated' if locale == 'en' else 'Atualizado'}: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
                f"{edge_guardrail_note}"
                f"{risk_guardrail_note}"
                f"{risk_plan_note}\n\n"
                f"{'Remember: This is an automated technical analysis. Always do your own research!' if locale == 'en' else 'Lembre-se: Esta e uma analise tecnica automatizada. Sempre faca sua propria pesquisa!'}"
            )

            signal_timestamp = datetime.now()

            try:
                self.paper_trade_service.evaluate_open_trades(symbol=symbol, timeframe=timeframe, market_data=data)
                runtime_db.save_trading_signal(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "context_timeframe": strategy_settings.get("context_timeframe"),
                        "strategy_version": runtime_strategy_version,
                        "regime": (regime_evaluation or {}).get("regime"),
                        "signal": final_signal,
                        "price": last_candle["close"],
                        "rsi": last_candle["rsi"],
                        "macd_signal": last_candle["macd_signal"],
                        "macd_value": last_candle["macd"],
                        "signal_strength": abs(last_candle["rsi"] - 50) / 50,
                        "volume": last_candle.get("volume", 0),
                    }
                )
                if risk_plan and risk_plan.get("allowed"):
                    self.paper_trade_service.register_signal(
                        symbol=symbol,
                        timeframe=timeframe,
                        signal=final_signal,
                        entry_price=float(last_candle["close"]),
                        entry_timestamp=signal_timestamp,
                        context_timeframe=strategy_settings.get("context_timeframe"),
                        source="telegram",
                        strategy_version=runtime_strategy_version,
                        stop_loss_pct=strategy_settings.get("stop_loss_pct"),
                        take_profit_pct=strategy_settings.get("take_profit_pct"),
                          risk_plan=risk_plan,
                          setup_name=(entry_quality_evaluation or {}).get("setup_type") or runtime_strategy_version,
                          regime=(regime_evaluation or {}).get("regime") or last_candle.get("market_regime"),
                          signal_score=(entry_quality_evaluation or {}).get("entry_score", last_candle.get("signal_confidence", 0.0)),
                          atr=last_candle.get("atr", 0.0),
                          entry_reason=entry_reason,
                          entry_quality=(entry_quality_evaluation or {}).get("entry_quality"),
                          rejection_reason=(entry_quality_evaluation or {}).get("rejection_reason"),
                          sample_type="paper",
                      )
            except Exception as e:
                self.logger.warning("Falha ao registrar outcome de paper trade: %s", e)

            await loading_msg.edit_text(analysis_message)
            self.user_manager.record_analysis(user_id)

        except Exception as e:
            self.logger.exception(e)
            await self._safe_reply(update, f"{'Error in /analise' if self._resolve_locale(update) == 'en' else 'Erro no /analise'}: {e}")

    # Admin commands (simplified)
    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /premium command"""
        try:
            user_id = update.effective_user.id

            self.user_manager.get_or_create_user(
                user_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name
            )

            premium_message = (
                "💎 Trading Signals Premium\n\n"
                "🆓 Plano Free:\n"
                "• 1 análise por dia\n"
                "• Suporte básico\n"
                "• Pares principais\n\n"
                "✨ Plano Premium:\n"
                "• Análises ilimitadas\n"
                "• Alerts em tempo real\n"
                "• Análises mais detalhadas\n"
                "• Suporte prioritário\n"
                "• Todos os pares disponíveis\n\n"
                "💰 Preço: R$ 19,90/mês\n\n"
                "🔗 Para upgrade:\n"
                "Entre em contato: @trading_support\n\n"
                "💡 Pagamentos aceitos:\n"
                "• PIX\n"
                "• Cartão de crédito\n"
                "• Mercado Pago"
            )

            await self._safe_reply(update, premium_message)

        except Exception as e:
            self.logger.exception(e)
            await self._safe_reply(update, f"Erro no /premium: {e}")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        try:
            user_id = update.effective_user.id

            if not self.user_manager:
                await self._safe_reply(update, "❌ UserManager não disponível")
                return

            user = self.user_manager.get_or_create_user(
                user_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name
            )

            analyses_today = user.get("analysis_count_today", 0)
            is_premium = user.get("plan") == "premium"
            daily_limit = self.user_manager.get_free_daily_limit()
            remaining = "Ilimitado" if is_premium else max(daily_limit - analyses_today, 0)
            last_analysis = user.get("last_analysis") or "Nenhuma"

            msg = (
                f"📊 Seu status\n"
                f"• Plano: {user.get('plan', 'free')}\n"
                f"• Análises hoje: {analyses_today}\n"
                f"• Limite diário: {'Ilimitado' if is_premium else daily_limit}\n"
                f"• Restante hoje: {remaining}\n"
                f"• Última análise: {last_analysis}"
            )

            if self.user_manager.is_admin(user_id):
                msg += "\n• Perfil: admin"

            await self._safe_reply(update, msg)

        except Exception as e:
            self.logger.exception(e)
            await self._safe_reply(update, f"Erro no /status: {e}")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        user_id = update.effective_user.id
        if not self.user_manager or not self.user_manager.is_admin(user_id):
            await self._safe_reply(update, "❌ Acesso negado")
            return

        stats = self.user_manager.get_stats()
        paper_summary = self.paper_trade_service.get_summary()
        edge_summary = runtime_db.get_edge_monitor_summary()
        governance_summary = runtime_db.get_strategy_governance_summary(active_only=True, limit=20)
        governance_counts = governance_summary.get("counts", {})
        evaluation_overview = runtime_db.get_strategy_evaluation_overview(limit=10)
        evaluation_counts = evaluation_overview.get("governance_counts", {})
        recent_evaluations = evaluation_overview.get("rows", [])[:3]
        risk_summary = self.risk_management_service.get_portfolio_risk_summary()
        msg = (
            f"📊 Status do Sistema:\n"
            f"• Usuários: {stats['total_users']}\n"
            f"• Free: {stats['free_users']}\n"
            f"• Premium: {stats['premium_users']}\n"
            f"• Análises hoje: {stats.get('analyses_today', 0)}"
        )
        msg += (
            f"\n• Paper trades fechados: {paper_summary.get('closed_trades', 0)}"
            f"\n• Win rate paper: {paper_summary.get('win_rate', 0):.1f}%"
            f"\n• Resultado paper acumulado: {paper_summary.get('total_result_pct', 0):.2f}%"
        )
        msg += (
            f"\n• Edge monitor: {edge_summary.get('status')}"
            f"\n• Baseline PF: {edge_summary.get('baseline_profit_factor', 0):.2f}"
            f"\n• Paper PF: {edge_summary.get('paper_profit_factor', 0):.2f}"
        )
        msg += (
            f"\n• Setups aprovados: {governance_counts.get('approved', 0)}"
            f"\n• Setups observando: {governance_counts.get('observing', 0)}"
            f"\n• Setups bloqueados: {governance_counts.get('blocked', 0)}"
        )
        msg += (
            f"\n• Trades abertos: {risk_summary.get('open_trades', 0)}"
            f"\n• Risco aberto: {risk_summary.get('total_open_risk_pct', 0):.2f}%"
            f"\n• Notional aberto: ${risk_summary.get('total_open_position_notional', 0):.2f}"
        )
        msg += (
            f"\n- Breaker risco: {'ok' if risk_summary.get('circuit_breaker_allowed', True) else 'ativo'}"
            f"\n- PnL diario paper: {risk_summary.get('daily_realized_pnl_pct', 0):.2f}%"
            f"\n- Losses consecutivos: {risk_summary.get('consecutive_losses', 0)}"
        )
        msg += (
            f"\n- Strategy evaluations: {evaluation_overview.get('total_strategies', 0)}"
            f"\n- Snapshots aprovados: {evaluation_counts.get('approved', 0)}"
            f"\n- Snapshots bloqueados: {evaluation_counts.get('blocked', 0)}"
        )
        if recent_evaluations:
            msg += "\n\nUltimas strategy evaluations:"
            for evaluation in recent_evaluations:
                msg += (
                    f"\n- {evaluation.get('symbol')} {evaluation.get('timeframe')}"
                    f" | score {evaluation.get('quality_score', 0):.1f}"
                    f" | {evaluation.get('governance_status', 'unknown')}"
                    f" | edge {evaluation.get('edge_status', 'unknown')}"
                )
        await self._safe_reply(update, msg)
    
    async def users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /users command"""
        user_id = update.effective_user.id
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado")
            return

        users = self.user_manager.list_users(limit=100)
        text = "👥 Usuários:\n"
        for u in users:
            text += f"• {u['id']} - {u.get('username','N/A')} - {u['plan']} - análises hoje: {u['analyses_today']}\n"
        await update.message.reply_text(text)
    
    async def upgrade_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /upgrade command"""
        user_id = update.effective_user.id
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado")
            return

        if not context.args or len(context.args) != 1:
            await update.message.reply_text("Uso: /upgrade <user_id>")
            return

        try:
            target_id = int(context.args[0])
            self.user_manager.upgrade_to_premium(target_id)
            await update.message.reply_text(f"💎 Usuário {target_id} atualizado para Premium")
        except Exception as e:
            await update.message.reply_text(f"❌ Erro ao atualizar usuário: {e}")
    
    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /broadcast command"""
        user_id = update.effective_user.id
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado")
            return

        if not context.args:
            await update.message.reply_text("Uso: /broadcast <mensagem>")
            return

        message = ' '.join(context.args)
        recipients = self.user_manager.get_all_user_ids()
        success = 0
        failed = 0
        for uid in recipients:
            try:
                await self.bot.send_message(chat_id=uid, text=f"📢 Broadcast do Admin:\n{message}")
                success += 1
            except Exception:
                failed += 1

        await update.message.reply_text(f"✅ Broadcast enviado: {success} sucesso, {failed} falha")
    
    async def test_connection(self):
        """Test bot connection"""
        if not self.enabled or not TELEGRAM_AVAILABLE:
            return False, "Bot not configured or library not available"
        
        try:
            me = await self.bot.get_me()
            return True, f"Connected as @{me.username}"
        except Exception as e:
            return False, str(e)
    
    def start_polling(self):
        """Start the bot polling - synchronous method for direct use"""
        if not TELEGRAM_AVAILABLE:
            self.logger.error("❌ Cannot start polling: Telegram library not available")
            return False
        
        if not self.application:
            self.logger.error("❌ Cannot start polling: Bot not configured")
            return False
        
        try:
            self.logger.info("🚀 Starting Telegram bot polling...")
            self.application.run_polling(drop_pending_updates=True)
            return True
        except Exception as e:
            self.logger.error(f"❌ Erro ao iniciar polling: {e}")
            return False
