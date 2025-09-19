import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any
import time

try:
    from telegram import Bot, Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    from telegram.error import TelegramError, RetryAfter, TimedOut, NetworkError
    TELEGRAM_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("✅ python-telegram-bot imported successfully")
except ImportError as e:
    TELEGRAM_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.error(f"❌ Telegram library not available: {e}")
    logger.error("💡 Install with: pip install python-telegram-bot")

    # Complete dummy classes when Telegram is not available
    class Update:
        def __init__(self):
            self.effective_user = self.EffectiveUser()
            self.message = self.Message()

        class EffectiveUser:
            def __init__(self):
                self.id = None
                self.username = None
                self.first_name = None

        class Message:
            async def reply_text(self, text, **kwargs):
                pass
            async def edit_text(self, text, **kwargs):
                pass

    class ContextTypes:
        DEFAULT_TYPE = None

    class Bot:
        def __init__(self, token):
            self.token = token
        async def get_me(self):
            pass
        async def send_message(self, chat_id, text, **kwargs):
            pass

    class Application:
        @staticmethod
        def builder():
            return ApplicationBuilder()

    class ApplicationBuilder:
        def token(self, token):
            return self
        def build(self):
            return MockApplication()

    class MockApplication:
        def add_handler(self, handler):
            pass
        def run_polling(self):
            pass

    class CommandHandler:
        def __init__(self, command, callback):
            pass

from user_manager import UserManager
from trading_bot import TradingBot

class TelegramTradingBot:
    """Trading bot for Telegram"""

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

        if not TELEGRAM_AVAILABLE:
            self.logger.error("❌ Telegram library not available. Install with: pip install python-telegram-bot")

        self.bot_token = None
        self.bot = None
        self.application = None
        self.enabled = False
        self.user_manager = UserManager()
        self.trading_bot = TradingBot()
        self.last_error_time = 0
        self.error_count = 0

        # Automatically configure from environment variables
        self._auto_configure()

    def _auto_configure(self):
        """Auto configure from Replit Secrets"""
        try:
            token = os.getenv("TELEGRAM_BOT_TOKEN")
            if token and TELEGRAM_AVAILABLE:
                if self.configure(token):
                    self.logger.info("✅ Telegram bot configurado automaticamente via Replit Secrets")
                else:
                    self.logger.error("❌ Erro na configuração automática do bot")
            else:
                if not token:
                    self.logger.warning("⚠️ TELEGRAM_BOT_TOKEN não encontrado nos secrets")
                if not TELEGRAM_AVAILABLE:
                    self.logger.error("❌ Biblioteca do Telegram não disponível")
        except Exception as e:
            self.logger.error(f"❌ Erro na configuração automática: {e}")

    def configure(self, bot_token):
        """Configure the Telegram bot"""
        if not TELEGRAM_AVAILABLE:
            self.logger.error("❌ Cannot configure: Telegram library not available")
            return False

        try:
            self.bot_token = bot_token
            self.bot = Bot(token=bot_token)
            self.application = Application.builder().token(bot_token).build()

            # Add command handlers
            self.application.add_handler(CommandHandler("start", self.start_command))
            self.application.add_handler(CommandHandler("help", self.help_command))
            self.application.add_handler(CommandHandler("analise", self.analyze_command))
            self.application.add_handler(CommandHandler("status", self.status_command))
            self.application.add_handler(CommandHandler("premium", self.premium_command))
            self.application.add_handler(CommandHandler("admin", self.admin_command))
            self.application.add_handler(CommandHandler("stats", self.stats_command))
            self.application.add_handler(CommandHandler("users", self.users_command))
            self.application.add_handler(CommandHandler("upgrade", self.upgrade_command))
            self.application.add_handler(CommandHandler("broadcast", self.broadcast_command))

            self.enabled = True
            self.logger.info("✅ Bot configurado com sucesso")
            return True

        except Exception as e:
            self.logger.error(f"❌ Erro ao configurar bot: {e}")
            return False

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        try:
            user_id = update.effective_user.id
            username = update.effective_user.username
            first_name = update.effective_user.first_name

            # Add user to database
            self.user_manager.add_user(user_id, username, first_name)

            welcome_message = f"""
🎯 **Bem-vindo ao Trading Signals Bot!**

Olá {first_name}! 👋

🤖 **Sobre o bot:**
• Análises técnicas de criptomoedas em tempo real
• Sinais baseados em RSI e MACD
• Suporte a múltiplos pares de trading

📖 **Comandos principais:**
• /analise [PAR] - Analisar criptomoeda
• /status - Ver seu status e limites
• /help - Ver todos os comandos
• /premium - Informações sobre Premium

🔧 **Pares suportados:**
• BTC/USDT, ETH/USDT, XLM/USDT
• ADA/USDT, DOT/USDT, MATIC/USDT

💎 **Tipos de Usuário:**
• 🆓 **Free:** 1 análise por dia
• 💎 **Premium:** Análises ilimitadas + alertas em tempo real

💡 **Exemplo de uso:**
`/analise BTC/USDT`

✨ Vamos começar a analisar o mercado!
"""

            await update.message.reply_text(welcome_message, parse_mode='Markdown')
            self.logger.info(f"✅ Usuário {user_id} executou /start")

        except Exception as e:
            self.logger.error(f"❌ Erro no comando /start: {e}")
            await update.message.reply_text("❌ Erro interno. Tente novamente em alguns minutos.")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        try:
            user_id = update.effective_user.id
            is_admin = self.user_manager.is_admin(user_id)
            is_premium = self.user_manager.is_premium(user_id)

            help_text = f"""
📖 **Comandos Disponíveis:**

📊 **Análises:**
• /analise [PAR] - Analisar criptomoeda
  Exemplo: /analise BTC/USDT
• /status - Ver seu status e limites

💎 **Premium:**
• /premium - Informações sobre Premium
{'• ✅ Você é Premium!' if is_premium else '• 🆓 Plano Free (1 análise/dia)'}

🔧 **Pares suportados:**
• BTC/USDT, ETH/USDT, XLM/USDT
• ADA/USDT, DOT/USDT, MATIC/USDT
• LINK/USDT, UNI/USDT, SOL/USDT
"""

            if is_admin:
                help_text += """
👑 **Comandos de Admin:**
• /admin - Painel administrativo
• /stats - Estatísticas do bot
• /users - Listar usuários
• /upgrade [ID] - Fazer upgrade de usuário
• /broadcast [MSG] - Enviar mensagem para todos
"""

            await update.message.reply_text(help_text, parse_mode='Markdown')

        except Exception as e:
            self.logger.error(f"❌ Erro no comando /help: {e}")
            await update.message.reply_text("❌ Erro interno. Tente novamente.")

    async def analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /analise command"""
        try:
            user_id = update.effective_user.id
            user = self.user_manager.get_user(user_id)

            if not user:
                self.user_manager.add_user(user_id, update.effective_user.username, update.effective_user.first_name)
                user = self.user_manager.get_user(user_id)

            # Check if user can perform analysis
            if not self.user_manager.can_analyze(user_id):
                await update.message.reply_text(
                    "⚠️ **Limite atingido!**\n\n"
                    "Usuários **Free** têm direito a **1 análise por dia**.\n\n"
                    "💎 Upgrade para **Premium** e tenha:\n"
                    "• ✅ Análises ilimitadas\n"
                    "• 🚀 Alerts em tempo real\n"
                    "• 📊 Análises mais detalhadas\n\n"
                    "Use `/premium` para mais informações!",
                    parse_mode='Markdown'
                )
                return

            # Get symbol from command
            if not context.args:
                await update.message.reply_text(
                    "❌ **Formato incorreto!**\n\n"
                    "📖 **Uso correto:**\n"
                    "`/analise BTC/USDT`\n\n"
                    "💡 **Pares disponíveis:**\n"
                    "• BTC/USDT, ETH/USDT, XLM/USDT\n"
                    "• ADA/USDT, DOT/USDT, MATIC/USDT",
                    parse_mode='Markdown'
                )
                return

            symbol = context.args[0].upper()

            # Validate symbol
            valid_pairs = ["BTC/USDT", "ETH/USDT", "XLM/USDT", "ADA/USDT", "DOT/USDT", "MATIC/USDT", "LINK/USDT", "UNI/USDT", "SOL/USDT"]
            if symbol not in valid_pairs:
                await update.message.reply_text(
                    f"❌ **Par não suportado:** `{symbol}`\n\n"
                    "💡 **Pares disponíveis:**\n"
                    "• " + "\n• ".join(valid_pairs),
                    parse_mode='Markdown'
                )
                return

            # Send loading message
            loading_msg = await update.message.reply_text("🔄 **Analisando...**\nPor favor aguarde...")

            # Configure trading bot
            self.trading_bot.update_config(symbol=symbol)

            # Get market data with retry logic
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
                await loading_msg.edit_text("❌ **Erro:** Não foi possível obter dados do mercado após 3 tentativas")
                return

            # Get analysis
            last_candle = data.iloc[-1]
            signal = self.trading_bot.check_signal(data)

            # Create analysis message
            signal_emojis = {
                "COMPRA": "🟢",
                "VENDA": "🔴",
                "COMPRA_FRACA": "🟡",
                "VENDA_FRACA": "🟠",
                "NEUTRO": "⚪"
            }

            emoji = signal_emojis.get(signal, "⚪")

            analysis_message = f"""
📊 **Análise Técnica - {symbol}**

{emoji} **Sinal: {signal.replace('_', ' ')}**

💰 **Preço Atual:** ${last_candle['close']:.6f}
📈 **Variação:** {((last_candle['close'] - last_candle['open']) / last_candle['open'] * 100):+.2f}%

📊 **Indicadores:**
• **RSI:** {last_candle['rsi']:.2f}
• **MACD:** {last_candle['macd']:.4f}
• **MACD Signal:** {last_candle['macd_signal']:.4f}

⏰ **Atualizado:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

💡 **Lembre-se:** Esta é uma análise técnica automatizada. Sempre faça sua própria pesquisa antes de investir!
"""

            await loading_msg.edit_text(analysis_message, parse_mode='Markdown')

            # Record analysis
            self.user_manager.record_analysis(user_id)

        except Exception as e:
            self.logger.error(f"❌ Erro no comando /analise: {e}")
            try:
                await update.message.reply_text("❌ Erro interno. Tente novamente em alguns minutos.")
            except:
                pass

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        try:
            user_id = update.effective_user.id
            user = self.user_manager.get_user(user_id)

            if not user:
                await update.message.reply_text("❌ Usuário não encontrado. Use /start primeiro.")
                return

            is_premium = self.user_manager.is_premium(user_id)
            analyses_today = self.user_manager.get_analyses_today(user_id)
            can_analyze = self.user_manager.can_analyze(user_id)

            status_message = f"""
👤 **Seu Status**

📱 **ID:** `{user_id}`
💎 **Plano:** {'Premium ✨' if is_premium else 'Free 🆓'}

📊 **Análises hoje:** {analyses_today}{'/' + str(self.user_manager.max_analyses_per_day) if not is_premium else ' (ilimitadas)'}
🔄 **Próxima análise:** {'Disponível ✅' if can_analyze else 'Limite atingido ❌'}

📅 **Membro desde:** {user['created_at'].strftime('%d/%m/%Y')}

{'💡 Use /premium para upgrade!' if not is_premium else '🎉 Obrigado por ser Premium!'}
"""

            await update.message.reply_text(status_message, parse_mode='Markdown')

        except Exception as e:
            self.logger.error(f"❌ Erro no comando /status: {e}")
            await update.message.reply_text("❌ Erro interno. Tente novamente.")

    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /premium command"""
        premium_message = """
💎 **Trading Signals Premium**

🆓 **Plano Free:**
• 1 análise por dia
• Suporte básico
• Pares principais

✨ **Plano Premium:**
• ✅ Análises ilimitadas
• 🚀 Alerts em tempo real
• 📊 Análises mais detalhadas
• 🎯 Suporte prioritário
• 📈 Todos os pares disponíveis

💰 **Preço:** R$ 19,90/mês

🔗 **Para upgradar:**
Entre em contato: @trading_support

💡 **Pagamentos aceitos:**
• PIX
• Cartão de crédito
• Mercado Pago
"""

        await update.message.reply_text(premium_message, parse_mode='Markdown')

    # Add other command methods here (admin, stats, etc.)
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /admin command - placeholder"""
        await update.message.reply_text("👑 Comando de administrador - em desenvolvimento")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command - placeholder"""
        await update.message.reply_text("📊 Estatísticas - em desenvolvimento")

    async def users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /users command - placeholder"""
        await update.message.reply_text("👥 Lista de usuários - em desenvolvimento")

    async def upgrade_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /upgrade command - placeholder"""
        await update.message.reply_text("💎 Upgrade de usuário - em desenvolvimento")

    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /broadcast command - placeholder"""
        await update.message.reply_text("📢 Broadcast - em desenvolvimento")

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
        """Start the bot polling"""
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

# Legacy class for compatibility
class TelegramNotifier(TelegramTradingBot):
    """Legacy compatibility class"""

    def __init__(self):
        super().__init__()
        self.chat_id = None

    def configure(self, bot_token, chat_id=None):
        """Configure with legacy method"""
        if chat_id:
            self.chat_id = chat_id
        return super().configure(bot_token)

    async def send_signal_alert(self, symbol, signal, price, rsi, macd, macd_signal, chat_id=None):
        """Send signal alert to specific chat"""
        if not TELEGRAM_AVAILABLE:
            return False, "Telegram library not available"

        try:
            target_chat_id = chat_id or self.chat_id
            if not target_chat_id:
                return False, "No chat ID configured"

            signal_emojis = {
                "COMPRA": "🟢",
                "VENDA": "🔴",
                "COMPRA_FRACA": "🟡",
                "VENDA_FRACA": "🟠",
                "NEUTRO": "⚪"
            }

            emoji = signal_emojis.get(signal, "⚪")

            message = f"""
🚨 **ALERTA DE SINAL**

{emoji} **{signal.replace('_', ' ')}**
📈 **Par:** {symbol}
💰 **Preço:** ${price:.6f}

📊 **Indicadores:**
• **RSI:** {rsi:.2f}
• **MACD:** {macd:.4f}
• **MACD Signal:** {macd_signal:.4f}

⏰ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""

            await self.bot.send_message(
                chat_id=target_chat_id,
                text=message,
                parse_mode='Markdown'
            )

            return True, "Alert sent successfully"

        except Exception as e:
            self.logger.error(f"Error sending signal alert: {e}")
            return False, str(e)

    async def send_custom_message(self, message, chat_id=None):
        """Send custom message"""
        if not TELEGRAM_AVAILABLE:
            return False, "Telegram library not available"

        try:
            target_chat_id = chat_id or self.chat_id
            if not target_chat_id:
                return False, "No chat ID configured"

            await self.bot.send_message(
                chat_id=target_chat_id,
                text=message,
                parse_mode='Markdown'
            )

            return True, "Message sent successfully"

        except Exception as e:
            self.logger.error(f"Error sending custom message: {e}")
            return False, str(e)