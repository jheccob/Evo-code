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
except ImportError:
    TELEGRAM_AVAILABLE = False
    # Dummy classes for when Telegram is not available
    class Update: pass
    class ContextTypes: 
        DEFAULT_TYPE = None

from user_manager import UserManager
from trading_bot import TradingBot

logger = logging.getLogger(__name__)

class TelegramTradingBot:
    """Trading bot for Telegram"""
    
    def __init__(self):
        if not TELEGRAM_AVAILABLE:
            logger.error("❌ Telegram library not available. Install with: pip install python-telegram-bot")
            
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
            if token:
                self.configure(token)
                logger.info("✅ Telegram bot configurado automaticamente via Replit Secrets")
            else:
                logger.info("⚠️ TELEGRAM_BOT_TOKEN não encontrado nos secrets")
        except Exception as e:
            logger.error(f"Erro na configuração automática: {e}")
        
    def configure(self, bot_token):
        """Configure the Telegram bot"""
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
            return True
            
        except Exception as e:
            logger.error(f"Error configuring Telegram bot: {e}")
            return False
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user_id = update.effective_user.id
        username = update.effective_user.username
        first_name = update.effective_user.first_name
        
        # Add user to database
        self.user_manager.add_user(user_id, username, first_name)
        
        welcome_message = f"""
🎯 **Bem-vindo ao Trading Signals Bot!**

Olá {first_name}! 👋

🤖 **Sobre o bot:**
• Análises técnicas de criptomoedas
• Sinais baseados em RSI e MACD
• Suporte a múltiplos pares

📖 **Comandos principais:**
• /analise [PAR] - Analisar criptomoeda
• /status - Ver seu status e limites
• /help - Ver todos os comandos
• /premium - Informações sobre Premium

🔧 **Pares suportados:**
• BTC/USDT, ETH/USDT, XLM/USDT
• ADA/USDT, DOT/USDT, MATIC/USDT

💡 **Exemplo de uso:**
`/analise BTC/USDT`

✨ Vamos começar a analisar o mercado!
"""
        
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        user_id = update.effective_user.id
        is_admin = self.user_manager.is_admin(user_id)
        is_premium = self.user_manager.is_premium(user_id)
        
        help_text = f"""
📖 Comandos Disponíveis:

📊 Análises:
• /analise [PAR] - Analisar criptomoeda
Exemplo: /analise BTC/USDT
• /status - Ver seu status e limites

💎 Premium:
• /premium - Informações sobre Premium
{'• ✅ Você é Premium!' if is_premium else '• 🆓 Plano Free (1 análise/dia)'}

🔧 Pares suportados:
• BTC/USDT, ETH/USDT, XLM/USDT
• ADA/USDT, DOT/USDT, MATIC/USDT
• LINK/USDT, UNI/USDT, SOL/USDT
"""
        
        if is_admin:
            help_text += """
👑 Comandos de Admin:
• /admin - Painel administrativo
• /stats - Estatísticas do bot
• /users - Listar usuários
• /upgrade [ID] - Fazer upgrade de usuário
• /broadcast [MSG] - Enviar mensagem para todos
"""
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /analise command"""
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
        
        # Validate symbol - usar configuração centralizada
        from config.telegram_bot_config import TelegramBotConfig
        if not TelegramBotConfig.is_valid_pair(symbol):
            await update.message.reply_text(
                f"❌ **Par não suportado:** `{symbol}`\n\n"
                "💡 **Pares disponíveis:**\n"
                "• " + "\n• ".join(TelegramBotConfig.SUPPORTED_PAIRS),
                parse_mode='Markdown'
            )
            return
        
        # Send loading message
        loading_msg = await update.message.reply_text("🔄 **Analisando...**\nPor favor aguarde...")
        
        try:
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
                    logger.warning(f"Attempt {attempt + 1} failed: {e}")
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
            
        except RetryAfter as e:
            logger.warning(f"Rate limited by Telegram: {e.retry_after}s")
            await loading_msg.edit_text(f"⏱️ **Rate limit:** Aguarde {e.retry_after} segundos")
        except NetworkError as e:
            logger.error(f"Network error: {e}")
            await loading_msg.edit_text("🌐 **Erro de rede:** Tente novamente em alguns minutos")
        except Exception as e:
            logger.error(f"Error in analyze command: {e}")
            self.error_count += 1
            self.last_error_time = time.time()
            
            # Rate limiting mais inteligente
            if self.error_count > 5 and time.time() - self.last_error_time < 300:  # 5 erros em 5 min
                await loading_msg.edit_text("🛑 **Sistema temporariamente indisponível**\nTente novamente em alguns minutos.")
            elif "Network" in str(e) or "timeout" in str(e).lower():
                await loading_msg.edit_text("🌐 **Erro de conexão**\nVerifique sua internet e tente novamente.")
            else:
                error_msg = str(e)[:100] + "..." if len(str(e)) > 100 else str(e)
                await loading_msg.edit_text(f"❌ **Erro:** {error_msg}")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
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
    
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /admin command"""
        user_id = update.effective_user.id
        
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado. Comando apenas para administradores.")
            return
        
        stats = self.user_manager.get_stats()
        
        admin_message = f"""
👑 **Painel Administrativo**

📊 **Estatísticas:**
• Total de usuários: {stats['total_users']}
• Usuários Premium: {stats['premium_users']}
• Análises hoje: {stats['analyses_today']}
• Análises total: {stats['total_analyses']}

🔧 **Comandos disponíveis:**
• /stats - Ver estatísticas detalhadas
• /users - Listar usuários recentes
• /upgrade [ID] - Fazer upgrade de usuário
• /broadcast [MSG] - Enviar mensagem para todos
"""
        
        await update.message.reply_text(admin_message, parse_mode='Markdown')
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        user_id = update.effective_user.id
        
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado.")
            return
        
        stats = self.user_manager.get_detailed_stats()
        
        stats_message = f"""
📈 **Estatísticas Detalhadas**

👥 **Usuários:**
• Total: {stats['total_users']}
• Premium: {stats['premium_users']}
• Ativos hoje: {stats['active_today']}
• Novos esta semana: {stats['new_this_week']}

📊 **Análises:**
• Hoje: {stats['analyses_today']}
• Esta semana: {stats['analyses_this_week']}
• Total: {stats['total_analyses']}

💎 **Premium:**
• Taxa de conversão: {stats['premium_conversion']:.1f}%
• Receita mensal: R$ {stats['monthly_revenue']:.2f}
"""
        
        await update.message.reply_text(stats_message, parse_mode='Markdown')
    
    async def users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /users command"""
        user_id = update.effective_user.id
        
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado.")
            return
        
        recent_users = self.user_manager.get_recent_users(limit=10)
        
        users_message = "👥 **Usuários Recentes:**\n\n"
        
        for user in recent_users:
            premium_status = "💎" if user['is_premium'] else "🆓"
            users_message += f"{premium_status} {user['first_name']} (@{user['username'] or 'N/A'})\n"
            users_message += f"   ID: `{user['user_id']}` | {user['created_at'].strftime('%d/%m')}\n\n"
        
        await update.message.reply_text(users_message, parse_mode='Markdown')
    
    async def upgrade_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /upgrade command"""
        user_id = update.effective_user.id
        
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado.")
            return
        
        if not context.args:
            await update.message.reply_text(
                "❌ **Formato incorreto!**\n\n"
                "📖 **Uso correto:**\n"
                "`/upgrade 123456789`"
            )
            return
        
        try:
            target_user_id = int(context.args[0])
            
            success = self.user_manager.upgrade_to_premium(target_user_id)
            
            if success:
                await update.message.reply_text(f"✅ Usuário `{target_user_id}` foi upgradado para Premium!")
                
                # Notify the user
                try:
                    await self.bot.send_message(
                        target_user_id,
                        "🎉 **Parabéns!**\n\n"
                        "✨ Sua conta foi upgradada para **Premium**!\n\n"
                        "🚀 Agora você tem acesso a:\n"
                        "• Análises ilimitadas\n"
                        "• Alerts em tempo real\n"
                        "• Suporte prioritário\n\n"
                        "💡 Use /status para verificar seu novo status!"
                    )
                except:
                    pass  # User might have blocked the bot
                    
            else:
                await update.message.reply_text(f"❌ Erro ao upgradar usuário `{target_user_id}`")
                
        except ValueError:
            await update.message.reply_text("❌ ID de usuário inválido")
    
    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /broadcast command"""
        user_id = update.effective_user.id
        
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado.")
            return
        
        if not context.args:
            await update.message.reply_text(
                "❌ **Formato incorreto!**\n\n"
                "📖 **Uso correto:**\n"
                "`/broadcast Sua mensagem aqui`"
            )
            return
        
        message = " ".join(context.args)
        users = self.user_manager.get_all_user_ids()
        
        sent = 0
        failed = 0
        
        progress_msg = await update.message.reply_text(f"📤 Enviando para {len(users)} usuários...")
        
        for target_user_id in users:
            try:
                await self.bot.send_message(target_user_id, message, parse_mode='Markdown')
                sent += 1
            except:
                failed += 1
        
        await progress_msg.edit_text(
            f"📊 **Resultado do broadcast:**\n"
            f"✅ Enviados: {sent}\n"
            f"❌ Falharam: {failed}"
        )
    
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
            self.application.run_polling()
    
    def is_configured(self):
        """Check if bot is configured"""
        return self.enabled and self.bot_token

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
🚨 ALERTA DE SINAL

{emoji} {signal.replace('_', ' ')}
📈 Par: {symbol}
💰 Preço: ${price:.6f}

📊 Indicadores:
• RSI: {rsi:.2f}
• MACD: {macd:.4f}
• MACD Signal: {macd_signal:.4f}

⏰ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
            
            await self.bot.send_message(
                chat_id=target_chat_id,
                text=message
            )
            
            return True, "Alert sent successfully"
            
        except Exception as e:
            logger.error(f"Error sending signal alert: {e}")
            return False, str(e)
    
    async def send_custom_message(self, message, chat_id=None):
        """Send custom message"""
        try:
            target_chat_id = chat_id or self.chat_id
            if not target_chat_id:
                return False, "No chat ID configured"
            
            await self.bot.send_message(
                chat_id=target_chat_id,
                text=message
            )
            
            return True, "Message sent successfully"
            
        except Exception as e:
            logger.error(f"Error sending custom message: {e}")
            return False, str(e)