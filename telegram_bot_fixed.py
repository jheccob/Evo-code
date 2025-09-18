
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any
import time

try:
    from telegram import Bot, Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    from telegram.error import TelegramError, RetryAfter, TimedOut, NetworkError
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

from user_manager import UserManager
from trading_bot import TradingBot
from config.telegram_bot_config import TelegramBotConfig

logger = logging.getLogger(__name__)

class ImprovedTelegramBot:
    """Bot Telegram melhorado com melhor estrutura"""
    
    def __init__(self):
        if not TELEGRAM_AVAILABLE:
            logger.error("❌ Telegram library not available")
            raise ImportError("python-telegram-bot not installed")
            
        self.bot_token = None
        self.bot = None
        self.application = None
        self.enabled = False
        self.user_manager = UserManager()
        self.trading_bot = TradingBot()
        
        # Rate limiting
        self.last_error_time = 0
        self.error_count = 0
        
    def configure(self, bot_token: str) -> bool:
        """Configure the bot with token"""
        try:
            self.bot_token = bot_token
            self.bot = Bot(token=bot_token)
            self.application = Application.builder().token(bot_token).build()
            
            self._setup_handlers()
            self.enabled = True
            
            logger.info("✅ Telegram bot configured successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error configuring bot: {e}")
            return False
    
    def _setup_handlers(self):
        """Setup command handlers"""
        handlers = [
            ("start", self.start_command),
            ("help", self.help_command),
            ("analise", self.analyze_command),
            ("status", self.status_command),
            ("premium", self.premium_command),
        ]
        
        # Add admin commands
        admin_handlers = [
            ("admin", self.admin_command),
            ("stats", self.stats_command),
            ("users", self.users_command),
            ("upgrade", self.upgrade_command),
            ("broadcast", self.broadcast_command),
        ]
        
        for command, handler in handlers + admin_handlers:
            self.application.add_handler(CommandHandler(command, handler))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user_id = update.effective_user.id
        username = update.effective_user.username
        first_name = update.effective_user.first_name
        
        self.user_manager.add_user(user_id, username, first_name)
        
        welcome_msg = f"""
🎯 **Bem-vindo ao Trading Bot!**

Olá {first_name}! 👋

🔧 **Comandos principais:**
• `/analise BTC/USDT` - Analisar par
• `/status` - Seu status atual
• `/help` - Lista completa de comandos

💎 **Pares disponíveis:**
{', '.join(TelegramBotConfig.SUPPORTED_PAIRS)}

✨ Vamos começar!
"""
        await update.message.reply_text(welcome_msg, parse_mode='Markdown')
    
    async def analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /analise command with improved error handling"""
        user_id = update.effective_user.id
        
        # Verificar se pode analisar
        if not self.user_manager.can_analyze(user_id):
            await update.message.reply_text(
                "⚠️ **Limite atingido!**\n\n"
                f"Usuários Free: {self.user_manager.max_analyses_per_day} análise/dia\n"
                "Use `/premium` para upgrade!", 
                parse_mode='Markdown'
            )
            return
        
        # Validar símbolo
        if not context.args:
            await update.message.reply_text(
                "❌ **Uso:** `/analise BTC/USDT`\n\n"
                f"**Pares:** {', '.join(TelegramBotConfig.SUPPORTED_PAIRS[:6])}...",
                parse_mode='Markdown'
            )
            return
        
        symbol = context.args[0].upper()
        if not TelegramBotConfig.is_valid_pair(symbol):
            await update.message.reply_text(
                f"❌ **Par inválido:** `{symbol}`\n\n"
                f"**Válidos:** {', '.join(TelegramBotConfig.SUPPORTED_PAIRS[:6])}...",
                parse_mode='Markdown'
            )
            return
        
        loading_msg = await update.message.reply_text("🔄 **Analisando...**")
        
        try:
            # Configurar e obter dados
            self.trading_bot.update_config(symbol=symbol)
            data = self.trading_bot.get_market_data()
            
            if data is None or data.empty:
                await loading_msg.edit_text("❌ **Erro:** Sem dados disponíveis")
                return
            
            # Análise
            last_candle = data.iloc[-1]
            signal = self.trading_bot.check_signal(data)
            emoji = TelegramBotConfig.get_signal_emoji(signal)
            
            analysis_msg = f"""
📊 **Análise - {symbol}**

{emoji} **{signal.replace('_', ' ')}**

💰 **Preço:** ${last_candle['close']:.6f}
📈 **Variação:** {((last_candle['close'] - last_candle['open']) / last_candle['open'] * 100):+.2f}%
📊 **RSI:** {last_candle['rsi']:.2f}
📊 **MACD:** {last_candle['macd']:.4f}

⏰ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
            
            await loading_msg.edit_text(analysis_msg, parse_mode='Markdown')
            self.user_manager.record_analysis(user_id)
            
        except Exception as e:
            logger.error(f"Analysis error: {e}")
            await loading_msg.edit_text("❌ **Erro na análise**\nTente novamente em alguns minutos.")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user status"""
        user_id = update.effective_user.id
        user = self.user_manager.get_user(user_id)
        
        if not user:
            await update.message.reply_text("❌ Use /start primeiro")
            return
        
        is_premium = self.user_manager.is_premium(user_id)
        analyses_today = self.user_manager.get_analyses_today(user_id)
        
        status_msg = f"""
👤 **Seu Status**

💎 **Plano:** {'Premium ✨' if is_premium else 'Free 🆓'}
📊 **Análises hoje:** {analyses_today}{'/' + str(self.user_manager.max_analyses_per_day) if not is_premium else ' (ilimitadas)'}
🔄 **Status:** {'Disponível ✅' if self.user_manager.can_analyze(user_id) else 'Limite atingido ❌'}

{'💡 Use /premium para upgrade!' if not is_premium else '🎉 Obrigado por ser Premium!'}
"""
        
        await update.message.reply_text(status_msg, parse_mode='Markdown')
    
    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show premium info"""
        premium_msg = """
💎 **Trading Premium**

🆓 **Free:** 1 análise/dia
✨ **Premium:** 
• Análises ilimitadas
• Suporte prioritário  
• Alertas em tempo real

💰 **R$ 19,90/mês**
📞 Contato: @trading_support
"""
        await update.message.reply_text(premium_msg, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help"""
        help_msg = """
📖 **Comandos Disponíveis**

📊 **Análise:**
• `/analise BTC/USDT` - Analisar par
• `/status` - Ver seu status

💎 **Premium:**
• `/premium` - Informações

🔧 **Pares suportados:**
""" + ', '.join(TelegramBotConfig.SUPPORTED_PAIRS[:9])
        
        await update.message.reply_text(help_msg, parse_mode='Markdown')
    
    # Métodos administrativos simplificados
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin panel - simplified"""
        user_id = update.effective_user.id
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado")
            return
        
        stats = self.user_manager.get_stats()
        admin_msg = f"""
👑 **Admin Panel**

📊 **Stats:**
• Usuários: {stats['total_users']}
• Premium: {stats['premium_users']}
• Free: {stats['free_users']}
• Análises hoje: {stats.get('analyses_today', 0)}
"""
        await update.message.reply_text(admin_msg, parse_mode='Markdown')
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Detailed stats for admins"""
        user_id = update.effective_user.id
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado")
            return
        
        stats = self.user_manager.get_detailed_stats()
        stats_msg = f"""
📈 **Estatísticas Detalhadas**

👥 **Usuários:** {stats['total_users']} total
💎 **Premium:** {stats['premium_users']} ({stats['premium_conversion']:.1f}%)
📊 **Análises:** {stats.get('analyses_today', 0)} hoje
💰 **Receita:** R$ {stats['monthly_revenue']:.2f}/mês
"""
        await update.message.reply_text(stats_msg, parse_mode='Markdown')
    
    async def users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List recent users"""
        user_id = update.effective_user.id
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado")
            return
        
        users = self.user_manager.get_recent_users(5)
        users_msg = "👥 **Usuários Recentes:**\n\n"
        
        for user in users:
            premium_icon = "💎" if user['is_premium'] else "🆓"
            users_msg += f"{premium_icon} {user['first_name']} | {user['user_id']}\n"
        
        await update.message.reply_text(users_msg, parse_mode='Markdown')
    
    async def upgrade_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Upgrade user to premium"""
        user_id = update.effective_user.id
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado")
            return
        
        if not context.args:
            await update.message.reply_text("❌ Use: `/upgrade USER_ID`", parse_mode='Markdown')
            return
        
        try:
            target_id = int(context.args[0])
            if self.user_manager.upgrade_to_premium(target_id):
                await update.message.reply_text(f"✅ Usuário {target_id} upgradado!")
                # Notify user
                try:
                    await self.bot.send_message(target_id, "🎉 **Conta upgradada para Premium!**", parse_mode='Markdown')
                except:
                    pass
            else:
                await update.message.reply_text("❌ Usuário não encontrado")
        except ValueError:
            await update.message.reply_text("❌ ID inválido")
    
    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Broadcast message"""
        user_id = update.effective_user.id
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado")
            return
        
        if not context.args:
            await update.message.reply_text("❌ Use: `/broadcast sua mensagem`", parse_mode='Markdown')
            return
        
        message = " ".join(context.args)
        users = self.user_manager.get_all_user_ids()
        
        sent, failed = 0, 0
        progress_msg = await update.message.reply_text(f"📤 Enviando para {len(users)} usuários...")
        
        for target_id in users:
            try:
                await self.bot.send_message(target_id, message, parse_mode='Markdown')
                sent += 1
            except:
                failed += 1
        
        await progress_msg.edit_text(f"📊 **Resultado:**\n✅ {sent} enviados\n❌ {failed} falharam")
    
    async def test_connection(self):
        """Test bot connection"""
        if not self.enabled:
            return False, "Bot not configured"
        
        try:
            me = await self.bot.get_me()
            return True, f"Connected as @{me.username}"
        except Exception as e:
            return False, str(e)
    
    def start_polling(self):
        """Start the bot polling"""
        if self.application:
            logger.info("🚀 Starting Telegram bot polling...")
            self.application.run_polling()
    
    def is_configured(self):
        """Check if bot is configured"""
        return self.enabled and self.bot_token
