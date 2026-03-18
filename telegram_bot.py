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
    def _build_structure_note(structure_evaluation: Optional[dict]) -> str:
        if not structure_evaluation:
            return "Estrutura: indisponivel"

        distance_from_ema_pct = structure_evaluation.get("distance_from_ema_pct")
        if isinstance(distance_from_ema_pct, (int, float)):
            distance_text = f"{float(distance_from_ema_pct):.2f}%"
        else:
            distance_text = "-"

        notes = structure_evaluation.get("notes") or []
        notes_preview = ", ".join(str(note) for note in notes[:2]) or "sem observacoes relevantes"

        return (
            f"Estrutura: {structure_evaluation.get('structure_state', 'weak_structure')} | "
            f"{structure_evaluation.get('price_location', 'mid_range')} | "
            f"qualidade {structure_evaluation.get('structure_quality', 0):.2f}/10 | "
            f"breakout {bool(structure_evaluation.get('breakout', False))} | "
            f"reversal_risk {bool(structure_evaluation.get('reversal_risk', False))} | "
            f"dist EMA {distance_text} | "
            f"notas: {notes_preview}"
        )

    @staticmethod
    def _build_confirmation_note(confirmation_evaluation: Optional[dict]) -> str:
        if not confirmation_evaluation:
            return "Confirmacao: indisponivel"

        conflicts_preview = ", ".join(confirmation_evaluation.get("conflicts", [])[:2]) or "sem conflitos relevantes"
        notes_preview = ", ".join(confirmation_evaluation.get("notes", [])[:2]) or "sem notas relevantes"

        return (
            f"Confirmacao: {confirmation_evaluation.get('confirmation_state', 'weak')} | "
            f"score {confirmation_evaluation.get('confirmation_score', 0):.2f}/10 | "
            f"conflitos: {conflicts_preview} | "
            f"notas: {notes_preview}"
        )

    @staticmethod
    def _build_entry_quality_note(entry_quality_evaluation: Optional[dict]) -> str:
        if not entry_quality_evaluation:
            return "Entrada: indisponivel"

        notes_preview = ", ".join(entry_quality_evaluation.get("notes", [])[:2]) or "sem notas relevantes"
        return (
            f"Entrada: {entry_quality_evaluation.get('entry_quality', 'bad')} | "
            f"RR {entry_quality_evaluation.get('rr_estimate', 0):.2f} | "
            f"late {entry_quality_evaluation.get('late_entry', False)} | "
            f"stretched {entry_quality_evaluation.get('stretched_price', False)} | "
            f"notas: {notes_preview}"
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

    def _apply_risk_guardrail(self, signal: str, entry_price: float, strategy_settings: dict):
        if signal not in {"COMPRA", "VENDA", "COMPRA_FRACA", "VENDA_FRACA"}:
            return signal, None

        risk_plan = self.risk_management_service.build_trade_plan(
            entry_price=float(entry_price),
            stop_loss_pct=strategy_settings.get("stop_loss_pct", 0.0) or 0.0,
            symbol=strategy_settings.get("symbol"),
            timeframe=strategy_settings.get("timeframe"),
            strategy_version=strategy_settings.get("strategy_version"),
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
            user_id = update.effective_user.id

            self.user_manager.get_or_create_user(
                user_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name
            )

            if not self.user_manager.can_analyze(user_id):
                await self._safe_reply(
                    update,
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
                    "Formato incorreto!\n\n"
                    "Uso correto:\n"
                    "/analise BTC/USDT\n\n"
                    "Pares disponiveis:\n"
                    + ", ".join(TelegramBotConfig.SUPPORTED_PAIRS[:6]) + "..."
                )
                return

            symbol = context.args[0].upper()

            if not TelegramBotConfig.is_valid_pair(symbol):
                await self._safe_reply(
                    update,
                    f"Par nao suportado: {symbol}\n\n"
                    f"Pares disponiveis:\n{', '.join(TelegramBotConfig.SUPPORTED_PAIRS)}"
                )
                return

            loading_msg = await self._safe_reply(update, "Analisando...\nPor favor aguarde...")

            if loading_msg is None:
                return

            if not self.trading_bot:
                await loading_msg.edit_text("Erro: TradingBot não inicializado")
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
                error_suffix = f"\nDetalhe: {market_data_error}" if market_data_error else ""
                await loading_msg.edit_text(
                    "Erro: Nao foi possivel obter dados reais do mercado no momento."
                    f"{error_suffix}"
                )
                return

            last_candle = data.iloc[-1]
            timeframe = strategy_settings["timeframe"]
            runtime_block_reason = strategy_settings.get("runtime_block_reason", "")
            context_evaluation = None
            structure_evaluation = None
            confirmation_evaluation = None
            entry_quality_evaluation = None
            hard_block_evaluation = None
            if not strategy_settings.get("runtime_allowed", True):
                signal = "NEUTRO"
                final_signal = "NEUTRO"
                edge_summary = None
                risk_plan = {"allowed": False, "reason": runtime_block_reason}
                hard_block_evaluation = {
                    "hard_block": True,
                    "block_reason": runtime_block_reason,
                    "block_source": "runtime_governance",
                }
                emoji = TelegramBotConfig.get_signal_emoji(final_signal)
            else:
                signal = self.trading_bot.check_signal(
                    data,
                    timeframe=timeframe,
                    require_volume=strategy_settings.get("require_volume", True),
                    require_trend=strategy_settings.get("require_trend", False),
                    avoid_ranging=strategy_settings.get("avoid_ranging", True),
                    context_timeframe=strategy_settings.get("context_timeframe"),
                    stop_loss_pct=strategy_settings.get("stop_loss_pct"),
                    take_profit_pct=strategy_settings.get("take_profit_pct"),
                )
                context_evaluation = getattr(self.trading_bot, "_last_context_evaluation", None)
                structure_evaluation = getattr(self.trading_bot, "_last_price_structure_evaluation", None)
                confirmation_evaluation = getattr(self.trading_bot, "_last_confirmation_evaluation", None)
                entry_quality_evaluation = getattr(self.trading_bot, "_last_entry_quality_evaluation", None)
                hard_block_evaluation = getattr(self.trading_bot, "_last_hard_block_evaluation", None)
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
            if strategy_settings.get("runtime_allowed", True):
                final_signal = self._merge_rule_and_ai_signal(signal, ai_signal)
                final_signal, edge_summary = self._apply_edge_guardrail(
                    final_signal,
                    symbol,
                    timeframe,
                    strategy_version=runtime_strategy_version,
                )
                final_signal, risk_plan = self._apply_risk_guardrail(
                    final_signal,
                    float(last_candle["close"]),
                    strategy_settings,
                )
                if edge_summary and final_signal == "NEUTRO":
                    hard_block_evaluation = {
                        "hard_block": True,
                        "block_reason": edge_summary.get("status_message") or "Edge monitor bloqueou o setup.",
                        "block_source": "edge_guardrail",
                    }
                elif risk_plan and not risk_plan.get("allowed"):
                    hard_block_evaluation = {
                        "hard_block": True,
                        "block_reason": risk_plan.get("reason") or "Risco operacional bloqueou a entrada.",
                        "block_source": "risk_guardrail",
                    }
                emoji = TelegramBotConfig.get_signal_emoji(final_signal)
            edge_guardrail_note = ""
            if edge_summary and edge_summary.get("status") == "degraded" and final_signal == "NEUTRO":
                edge_guardrail_note = (
                    f"\nGuardrail: setup bloqueado por degradacao no paper trade "
                    f"({edge_summary.get('paper_closed_trades', 0)} trades fechados)."
                )
            risk_guardrail_note = ""
            risk_plan_note = ""
            if risk_plan:
                if risk_plan.get("allowed"):
                    risk_plan_note = (
                        f"\nPlano de risco: {risk_plan.get('risk_per_trade_pct', 0):.2f}% "
                        f"(${risk_plan.get('risk_amount', 0):.2f}) | "
                        f"Posicao ${risk_plan.get('position_notional', 0):.2f}"
                    )
                else:
                    risk_guardrail_note = f"\nRisk guardrail: {risk_plan.get('reason')}"
            ai_mode_note = "comparativo" if not ProductionConfig.ENABLE_AI_SIGNAL_INFLUENCE else "influencia"
            context_note = "Contexto superior: sem filtro"
            if context_evaluation:
                context_note = (
                    f"Contexto superior: {context_evaluation.get('market_bias', 'neutral')} | "
                    f"{context_evaluation.get('regime', '-')} | "
                    f"forca {context_evaluation.get('context_strength', 0):.2f}/10"
                )
            structure_note = "Estrutura: indisponivel"
            if structure_evaluation:
                structure_note = self._build_structure_note(structure_evaluation)
            confirmation_note = "Confirmacao: indisponivel"
            if confirmation_evaluation:
                confirmation_note = self._build_confirmation_note(confirmation_evaluation)
            entry_quality_note = "Entrada: indisponivel"
            if entry_quality_evaluation:
                entry_quality_note = self._build_entry_quality_note(entry_quality_evaluation)
            hard_block_note = ""
            if hard_block_evaluation and hard_block_evaluation.get("hard_block"):
                hard_block_note = (
                    f"Hard block: {hard_block_evaluation.get('block_reason')} "
                    f"({hard_block_evaluation.get('block_source', 'signal_engine')})\n"
                )
            entry_reason = final_signal
            if final_signal != "NEUTRO":
                reason_parts = [final_signal]
                if context_evaluation:
                    reason_parts.append(
                        f"ctx:{context_evaluation.get('market_bias', 'neutral')}/{context_evaluation.get('regime', '-')}"
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
                        f"entry:{entry_quality_evaluation.get('entry_quality', '-')}/rr{entry_quality_evaluation.get('rr_estimate', 0):.2f}"
                    )
                entry_reason = " | ".join(reason_parts)

            analysis_message = (
                f"Analise Tecnica - {symbol}\n\n"
                f"{emoji} Sinal (regras): {signal.replace('_', ' ')}\n"
                f"Sinal (IA - {ai_mode_note}): {ai_signal} (conf: {ai_confidence:.2f})\n"
                f"Sinal (final): {final_signal}\n\n"
                f"Estrategia ativa: {active_profile.get('strategy_version') if active_profile else runtime_strategy_version}\n"
                f"Contexto: {strategy_settings.get('context_timeframe') or 'sem filtro superior'}\n"
                f"{context_note}\n"
                f"{structure_note}\n"
                f"{confirmation_note}\n"
                f"{entry_quality_note}\n"
                f"{hard_block_note}"
                f"Preco Atual: ${last_candle['close']:.6f}\n"
                f"Variacao: {((last_candle['close'] - last_candle['open']) / last_candle['open'] * 100):+.2f}%\n\n"
                f"Indicadores:\n"
                f"- RSI: {last_candle['rsi']:.2f}\n"
                f"- MACD: {last_candle['macd']:.4f}\n"
                f"- MACD Signal: {last_candle['macd_signal']:.4f}\n\n"
                f"Atualizado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
                f"{edge_guardrail_note}"
                f"{risk_guardrail_note}"
                f"{risk_plan_note}\n\n"
                f"Lembre-se: Esta e uma analise tecnica automatizada. Sempre faca sua propria pesquisa!"
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
                        setup_name=runtime_strategy_version,
                        regime=last_candle.get("market_regime"),
                        signal_score=last_candle.get("signal_confidence", 0.0),
                        atr=last_candle.get("atr", 0.0),
                        entry_reason=entry_reason,
                        sample_type="paper",
                    )
            except Exception as e:
                self.logger.warning("Falha ao registrar outcome de paper trade: %s", e)

            await loading_msg.edit_text(analysis_message)
            self.user_manager.record_analysis(user_id)

        except Exception as e:
            self.logger.exception(e)
            await self._safe_reply(update, f"Erro no /analise: {e}")

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
            f"\nâ€¢ Paper trades fechados: {paper_summary.get('closed_trades', 0)}"
            f"\nâ€¢ Win rate paper: {paper_summary.get('win_rate', 0):.1f}%"
            f"\nâ€¢ Resultado paper acumulado: {paper_summary.get('total_result_pct', 0):.2f}%"
        )
        msg += (
            f"\nâ€¢ Edge monitor: {edge_summary.get('status')}"
            f"\nâ€¢ Baseline PF: {edge_summary.get('baseline_profit_factor', 0):.2f}"
            f"\nâ€¢ Paper PF: {edge_summary.get('paper_profit_factor', 0):.2f}"
        )
        msg += (
            f"\nâ€¢ Setups aprovados: {governance_counts.get('approved', 0)}"
            f"\nâ€¢ Setups observando: {governance_counts.get('observing', 0)}"
            f"\nâ€¢ Setups bloqueados: {governance_counts.get('blocked', 0)}"
        )
        msg += (
            f"\nâ€¢ Trades abertos: {risk_summary.get('open_trades', 0)}"
            f"\nâ€¢ Risco aberto: {risk_summary.get('total_open_risk_pct', 0):.2f}%"
            f"\nâ€¢ Notional aberto: ${risk_summary.get('total_open_position_notional', 0):.2f}"
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
