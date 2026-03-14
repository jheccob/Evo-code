#!/usr/bin/env python3
"""
Bot Telegram para Trading - Versão Consolidada e Atualizada
Python-telegram-bot v20+
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

# Verificar se telegram está disponível
try:
    from telegram import Bot, Update
    from telegram.ext import Application, CommandHandler, ContextTypes
    from telegram.error import TelegramError
    import telegram

    TELEGRAM_AVAILABLE = True
    print(f"✅ python-telegram-bot v{telegram.__version__} importado com sucesso")

except ImportError as e:
    TELEGRAM_AVAILABLE = False
    print(f"❌ Telegram library not available: {e}")
    print("💡 Install with: pip install python-telegram-bot==22.6")

    Bot = None
    Update = None
    ContextTypes = None
    Application = None
    CommandHandler = None
    TelegramError = Exception

from user_manager import UserManager
from trading_bot import TradingBot
from ai_model import AIModel
from config import TelegramBotConfig, ProductionConfig

logger = logging.getLogger(__name__)

class TelegramTradingBot:
    """Bot Telegram para Trading - Versão Consolidada"""
    
    def __init__(self):
        self.ai_model = AIModel()
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
            self.trading_bot = TradingBot()
        except ImportError as e:
            self.logger.warning(f"⚠️ Erro ao importar dependências: {e}")
            self.user_manager = None
            self.trading_bot = None
        
        # Auto-configure from environment
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
                    self.logger.warning("⚠️ TELEGRAM_BOT_TOKEN não encontrado")
                    
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
        return self.enabled and self.application is not None
    
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

            self.trading_bot.update_config(symbol=symbol)

            data = None
            for attempt in range(3):
                try:
                    data = self.trading_bot.get_market_data()
                    if data is not None and not data.empty:
                        break
                except Exception as e:
                    self.logger.warning(f"Tentativa {attempt + 1} falhou: {e}")
                    if attempt < 2:
                        await asyncio.sleep(1)

            if data is None or data.empty:
                await loading_msg.edit_text("Erro: Nao foi possivel obter dados do mercado")
                return

            last_candle = data.iloc[-1]
            signal = self.trading_bot.check_signal(data)
            emoji = TelegramBotConfig.get_signal_emoji(signal)

            ai_signal = "NEUTRO"
            ai_confidence = 0.0

            try:
                ai_pred = self.ai_model.predict(data)
                ai_signal = ai_pred.get("signal", "NEUTRO")
                ai_confidence = ai_pred.get("confidence", 0.0)
            except Exception as e:
                self.logger.warning(f"Falha na IA: {e}")

            final_signal = signal
            if ai_signal in ["BUY", "SELL"] and signal in ["COMPRA", "VENDA"]:
                final_signal = signal
            elif ai_signal == "BUY" and signal in ["NEUTRO", "VENDA", "VENDA_FRACA"]:
                final_signal = "COMPRA_FRACA"
            elif ai_signal == "SELL" and signal in ["NEUTRO", "COMPRA", "COMPRA_FRACA"]:
                final_signal = "VENDA_FRACA"

            analysis_message = (
                f"Analise Tecnica - {symbol}\n\n"
                f"{emoji} Sinal (regras): {signal.replace('_', ' ')}\n"
                f"Sinal (IA): {ai_signal} (conf: {ai_confidence:.2f})\n"
                f"Sinal (final): {final_signal}\n\n"
                f"Preco Atual: ${last_candle['close']:.6f}\n"
                f"Variacao: {((last_candle['close'] - last_candle['open']) / last_candle['open'] * 100):+.2f}%\n\n"
                f"Indicadores:\n"
                f"- RSI: {last_candle['rsi']:.2f}\n"
                f"- MACD: {last_candle['macd']:.4f}\n"
                f"- MACD Signal: {last_candle['macd_signal']:.4f}\n\n"
                f"Atualizado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
                f"Lembre-se: Esta e uma analise tecnica automatizada. Sempre faca sua propria pesquisa!"
            )

            await loading_msg.edit_text(analysis_message)
            self.user_manager.record_analysis(user_id)

        except Exception as e:
            self.logger.exception(e)
            await self._safe_reply(update, f"Erro no /analise: {e}")
    
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

            self.trading_bot.update_config(symbol=symbol)

            data = None
            for attempt in range(3):
                try:
                    data = self.trading_bot.get_market_data()
                    if data is not None and not data.empty:
                        break
                except Exception as e:
                    self.logger.warning(f"Tentativa {attempt + 1} falhou: {e}")
                    if attempt < 2:
                        await asyncio.sleep(1)

            if data is None or data.empty:
                await loading_msg.edit_text("Erro: Nao foi possivel obter dados do mercado")
                return

            last_candle = data.iloc[-1]
            signal = self.trading_bot.check_signal(data)
            emoji = TelegramBotConfig.get_signal_emoji(signal)

            ai_signal = "NEUTRO"
            ai_confidence = 0.0

            try:
                ai_pred = self.ai_model.predict(data)
                ai_signal = ai_pred.get("signal", "NEUTRO")
                ai_confidence = ai_pred.get("confidence", 0.0)
            except Exception as e:
                self.logger.warning(f"Falha na IA: {e}")

            final_signal = signal
            if ai_signal in ["BUY", "SELL"] and signal in ["COMPRA", "VENDA"]:
                final_signal = signal
            elif ai_signal == "BUY" and signal in ["NEUTRO", "VENDA", "VENDA_FRACA"]:
                final_signal = "COMPRA_FRACA"
            elif ai_signal == "SELL" and signal in ["NEUTRO", "COMPRA", "COMPRA_FRACA"]:
                final_signal = "VENDA_FRACA"

            analysis_message = (
                f"Analise Tecnica - {symbol}\n\n"
                f"{emoji} Sinal (regras): {signal.replace('_', ' ')}\n"
                f"Sinal (IA): {ai_signal} (conf: {ai_confidence:.2f})\n"
                f"Sinal (final): {final_signal}\n\n"
                f"Preco Atual: ${last_candle['close']:.6f}\n"
                f"Variacao: {((last_candle['close'] - last_candle['open']) / last_candle['open'] * 100):+.2f}%\n\n"
                f"Indicadores:\n"
                f"- RSI: {last_candle['rsi']:.2f}\n"
                f"- MACD: {last_candle['macd']:.4f}\n"
                f"- MACD Signal: {last_candle['macd_signal']:.4f}\n\n"
                f"Atualizado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
                f"Lembre-se: Esta e uma analise tecnica automatizada. Sempre faca sua propria pesquisa!"
            )

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
        user_id = update.effective_user.id
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado")
            return

        stats = self.user_manager.get_stats()
        msg = (
            f"📊 Status do Sistema:\n"
            f"• Usuários: {status['total_users']}\n"
            f"• Free: {status['free_users']}\n"
            f"• Premium: {status['premium_users']}\n"
            f"• Análises hoje: {status.get('analyses_today', 0)}"
        )
        await update.message.reply_text(msg)
    
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
    
    def is_configured(self):
        """Check if bot is configured"""
        return self.enabled and self.bot_token and TELEGRAM_AVAILABLE