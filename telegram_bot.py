
import os
import asyncio
import logging
import re
from datetime import datetime
try:
    from telegram import Bot, Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    from telegram.error import TelegramError
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("Warning: python-telegram-bot not installed. Telegram features will be limited.")

import pandas as pd
from trading_bot import TradingBot
from user_manager import UserManager

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

class TelegramTradingBot:
    def __init__(self):
        self.bot_token = None
        self.bot = None
        self.application = None
        self.enabled = False and TELEGRAM_AVAILABLE
        self.trading_bot = TradingBot()
        self.user_manager = UserManager()
        
    def configure(self, bot_token):
        """Configure Telegram bot"""
        if not TELEGRAM_AVAILABLE:
            logger.error("python-telegram-bot not available")
            return False
        
        try:
            self.bot_token = bot_token
            self.bot = Bot(token=bot_token)
            
            # Create application
            self.application = Application.builder().token(bot_token).build()
            
            # Add handlers
            self.application.add_handler(CommandHandler("start", self.start_command))
            self.application.add_handler(CommandHandler("help", self.help_command))
            self.application.add_handler(CommandHandler("analise", self.analyze_command))
            self.application.add_handler(CommandHandler("premium", self.premium_command))
            self.application.add_handler(CommandHandler("status", self.status_command))
            
            # Admin commands
            self.application.add_handler(CommandHandler("admin", self.admin_command))
            self.application.add_handler(CommandHandler("stats", self.stats_command))
            self.application.add_handler(CommandHandler("users", self.users_command))
            self.application.add_handler(CommandHandler("upgrade", self.upgrade_command))
            self.application.add_handler(CommandHandler("broadcast", self.broadcast_command))
            
            # Message handler for analysis requests
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
            
            self.enabled = True
            return True
        except Exception as e:
            logger.error(f"Error configuring bot: {e}")
            self.enabled = False
            return False
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        self.user_manager.add_user(user.id, user.username, user.first_name)
        
        welcome_message = f"""
🤖 **Bem-vindo ao Trading Bot!**

Olá, {user.first_name}! 👋

🔸 **Plano Atual:** {'🟢 Premium' if self.user_manager.is_premium(user.id) else '🆓 Free (1 análise/dia)'}

📊 **Comandos disponíveis:**
• `/analise BTC/USDT` - Analisar uma criptomoeda
• `/premium` - Informações sobre o plano Premium
• `/status` - Ver seu status atual
• `/help` - Ver todos os comandos

💡 **Exemplo de uso:**
`/analise ETH/USDT`

🚀 Vamos começar a analisar o mercado!
        """
        
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        user_id = update.effective_user.id
        is_admin = self.user_manager.is_admin(user_id)
        is_premium = self.user_manager.is_premium(user_id)
        
        help_text = f"""
📖 **Comandos Disponíveis:**

**📊 Análises:**
• `/analise [PAR]` - Analisar criptomoeda
  Exemplo: `/analise BTC/USDT`
• `/status` - Ver seu status e limites

**💎 Premium:**
• `/premium` - Informações sobre Premium
{'• ✅ **Você é Premium!**' if is_premium else '• 🆓 **Plano Free** (1 análise/dia)'}

**🔧 Pares suportados:**
• BTC/USDT, ETH/USDT, XLM/USDT
• ADA/USDT, DOT/USDT, MATIC/USDT
• LINK/USDT, UNI/USDT, SOL/USDT
"""
        
        if is_admin:
            help_text += """
**👑 Comandos de Admin:**
• `/admin` - Painel administrativo
• `/stats` - Estatísticas do bot
• `/users` - Listar usuários
• `/upgrade [ID]` - Fazer upgrade de usuário
• `/broadcast [MSG]` - Enviar mensagem para todos
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
        
        # Validate symbol format
        if not re.match(r'^[A-Z]+/USD[T]?$', symbol):
            await update.message.reply_text(
                f"❌ **Par inválido: {symbol}**\n\n"
                "📖 **Formato correto:** `BTC/USDT`\n\n"
                "💡 **Pares suportados:**\n"
                "• BTC/USDT, ETH/USDT, XLM/USDT\n"
                "• ADA/USDT, DOT/USDT, MATIC/USDT",
                parse_mode='Markdown'
            )
            return
        
        await update.message.reply_text(f"🔄 **Analisando {symbol}...**\n\nPor favor, aguarde...")
        
        try:
            # Perform analysis
            result = await self.perform_analysis(symbol)
            
            # Record the analysis
            self.user_manager.record_analysis(user_id)
            
            await update.message.reply_text(result, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in analysis: {e}")
            await update.message.reply_text(
                "❌ **Erro na análise**\n\n"
                f"Não foi possível analisar {symbol}.\n"
                "Tente novamente em alguns minutos."
            )
    
    async def perform_analysis(self, symbol):
        """Perform technical analysis for a symbol"""
        try:
            # Configure trading bot
            self.trading_bot.update_config(symbol=symbol, timeframe='15m')
            
            # Get market data
            data = self.trading_bot.get_market_data(limit=100)
            
            if data is None or data.empty:
                raise Exception("No data available")
            
            last_candle = data.iloc[-1]
            signal = self.trading_bot.check_signal(data)
            
            # Calculate additional metrics
            price_change_24h = ((last_candle['close'] - data.iloc[-96]['close']) / data.iloc[-96]['close'] * 100) if len(data) >= 96 else 0
            
            # Signal analysis
            signal_analysis = self.get_signal_analysis(signal, last_candle, price_change_24h)
            
            # Format response
            response = f"""
📊 **Análise Técnica - {symbol}**

💰 **Preço Atual:** ${last_candle['close']:.6f}
📈 **Variação 24h:** {price_change_24h:.2f}%

📊 **Indicadores:**
• **RSI:** {last_candle['rsi']:.2f}
• **MACD:** {last_candle['macd']:.4f}
• **MACD Signal:** {last_candle['macd_signal']:.4f}

{signal_analysis}

⏰ **Análise:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

💡 **Aviso:** Esta análise é apenas informativa. Sempre faça sua própria pesquisa antes de investir.
            """
            
            return response
            
        except Exception as e:
            raise Exception(f"Analysis error: {str(e)}")
    
    def get_signal_analysis(self, signal, candle, price_change_24h):
        """Get detailed signal analysis"""
        if signal == "COMPRA":
            return f"""
🟢 **SINAL: COMPRA FORTE**

✅ **Oportunidade detectada!**
• RSI em zona de sobrevenda
• MACD com momentum positivo
• Condições favoráveis para entrada

🎯 **Recomendação:** Considere posição de compra
⚠️ **Stop Loss:** Considere abaixo de ${candle['close'] * 0.95:.6f}
"""
        elif signal == "VENDA":
            return f"""
🔴 **SINAL: VENDA FORTE**

⚠️ **Cuidado - Pressão vendedora!**
• RSI em zona de sobrecompra
• MACD com momentum negativo
• Condições favoráveis para saída

🎯 **Recomendação:** Considere realizar lucros
📉 **Alerta:** Possível correção em curso
"""
        elif signal == "COMPRA_FRACA":
            return f"""
🟡 **SINAL: COMPRA FRACA**

🔍 **Oportunidade em formação**
• Alguns indicadores positivos
• Aguardar confirmação adicional

🎯 **Recomendação:** Observar evolução
⏳ **Status:** Aguardar melhor entrada
"""
        elif signal == "VENDA_FRACA":
            return f"""
🟠 **SINAL: VENDA FRACA**

⚠️ **Atenção - Sinais mistos**
• Alguns indicadores negativos
• Cautela recomendada

🎯 **Recomendação:** Reduzir exposição
📊 **Status:** Monitorar de perto
"""
        else:
            return f"""
⚪ **SINAL: NEUTRO**

📊 **Mercado indeciso**
• Indicadores em equilíbrio
• Sem oportunidade clara

🎯 **Recomendação:** Aguardar melhor momento
⏳ **Status:** Paciência é essencial
"""
    
    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /premium command"""
        user_id = update.effective_user.id
        is_premium = self.user_manager.is_premium(user_id)
        
        if is_premium:
            message = """
💎 **Você já é Premium!**

🎉 **Benefícios ativos:**
• ✅ Análises ilimitadas
• 🚀 Alertas em tempo real
• 📊 Análises detalhadas
• 🎯 Sinais prioritários
• 💬 Suporte prioritário

Aproveite todos os recursos!
"""
        else:
            analyses_left = 1 - self.user_manager.get_user(user_id).get('analysis_count_today', 0)
            message = f"""
🆓 **Plano Free Ativo**

📊 **Status atual:**
• Análises restantes hoje: **{analyses_left}**
• Limite diário: 1 análise

💎 **Upgrade para Premium:**
• ✅ **Análises ilimitadas**
• 🚀 **Alertas em tempo real**
• 📊 **Análises mais detalhadas**
• 🎯 **Sinais prioritários**
• 💬 **Suporte prioritário**

💰 **Preço:** R$ 29,90/mês

Para fazer upgrade, entre em contato:
@seu_usuario_admin
"""
        
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        user_id = update.effective_user.id
        user = self.user_manager.get_user(user_id)
        
        if not user:
            await update.message.reply_text("❌ Usuário não encontrado. Use /start primeiro.")
            return
        
        plan = user.get('plan', 'free')
        analyses_today = user.get('analysis_count_today', 0)
        last_analysis = user.get('last_analysis')
        
        if last_analysis:
            last_analysis_dt = datetime.fromisoformat(last_analysis.replace('Z', '+00:00'))
            last_analysis_str = last_analysis_dt.strftime('%d/%m/%Y %H:%M')
        else:
            last_analysis_str = "Nunca"
        
        status_text = f"""
👤 **Seu Status**

**👑 Plano:** {'💎 Premium' if plan == 'premium' else '🆓 Free'}
**📊 Análises hoje:** {analyses_today}
**🕒 Última análise:** {last_analysis_str}

{'**✅ Acesso ilimitado!**' if plan == 'premium' else f'**⏳ Restantes hoje:** {1 - analyses_today}'}

**📅 Membro desde:** {datetime.fromisoformat(user['joined_date']).strftime('%d/%m/%Y')}
        """
        
        await update.message.reply_text(status_text, parse_mode='Markdown')
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle regular messages looking for analysis requests"""
        text = update.message.text.upper()
        
        # Check for symbol patterns like "BTC/USDT" or "BTC"
        symbol_match = re.search(r'\b([A-Z]{2,6})/?USD[T]?\b', text)
        if symbol_match:
            symbol = symbol_match.group(1) + "/USDT"
            
            await update.message.reply_text(
                f"💡 **Detectei interesse em {symbol}!**\n\n"
                f"Para análise completa, use:\n"
                f"`/analise {symbol}`",
                parse_mode='Markdown'
            )
    
    # Admin commands
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /admin command"""
        user_id = update.effective_user.id
        
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado. Comando apenas para administradores.")
            return
        
        stats = self.user_manager.get_user_stats()
        
        admin_panel = f"""
👑 **Painel Administrativo**

📊 **Estatísticas:**
• 👥 Total de usuários: {stats['total_users']}
• 🆓 Usuários Free: {stats['free_users']}
• 💎 Usuários Premium: {stats['premium_users']}
• 🔥 Ativos hoje: {stats['active_today']}

🔧 **Comandos disponíveis:**
• `/stats` - Estatísticas detalhadas
• `/users` - Listar usuários
• `/upgrade [ID]` - Upgrade usuário
• `/broadcast [MSG]` - Mensagem para todos
        """
        
        await update.message.reply_text(admin_panel, parse_mode='Markdown')
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        user_id = update.effective_user.id
        
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado.")
            return
        
        stats = self.user_manager.get_user_stats()
        
        await update.message.reply_text(f"""
📈 **Estatísticas Detalhadas**

👥 **Usuários:**
• Total: {stats['total_users']}
• Free: {stats['free_users']}
• Premium: {stats['premium_users']}
• Ativos hoje: {stats['active_today']}

💰 **Conversão:**
• Taxa Premium: {(stats['premium_users']/stats['total_users']*100):.1f}%
        """, parse_mode='Markdown')
    
    async def users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /users command"""
        user_id = update.effective_user.id
        
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado.")
            return
        
        users = self.user_manager.list_users(10)
        
        users_text = "👥 **Últimos Usuários:**\n\n"
        for user in users:
            plan_emoji = "💎" if user['plan'] == 'premium' else "🆓"
            users_text += f"{plan_emoji} **{user['first_name']}** (@{user['username']})\n"
            users_text += f"   ID: `{user['id']}` | Análises hoje: {user['analyses_today']}\n\n"
        
        await update.message.reply_text(users_text, parse_mode='Markdown')
    
    async def upgrade_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /upgrade command"""
        user_id = update.effective_user.id
        
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado.")
            return
        
        if not context.args:
            await update.message.reply_text("❌ Use: `/upgrade [USER_ID]`", parse_mode='Markdown')
            return
        
        try:
            target_user_id = int(context.args[0])
            success = self.user_manager.upgrade_to_premium(target_user_id)
            
            if success:
                await update.message.reply_text(f"✅ Usuário {target_user_id} foi promovido para Premium!")
                
                # Notify the user
                try:
                    await self.bot.send_message(
                        target_user_id,
                        "🎉 **Parabéns!**\n\nVocê foi promovido para **Premium**!\n\n"
                        "💎 **Benefícios desbloqueados:**\n"
                        "• ✅ Análises ilimitadas\n"
                        "• 🚀 Alertas em tempo real\n"
                        "• 📊 Análises detalhadas\n\n"
                        "Aproveite! 🚀",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            else:
                await update.message.reply_text("❌ Usuário não encontrado.")
                
        except ValueError:
            await update.message.reply_text("❌ ID inválido.")
    
    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /broadcast command"""
        user_id = update.effective_user.id
        
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado.")
            return
        
        if not context.args:
            await update.message.reply_text("❌ Use: `/broadcast [MENSAGEM]`", parse_mode='Markdown')
            return
        
        message = " ".join(context.args)
        users = self.user_manager.list_users(1000)  # Get more users for broadcast
        
        sent = 0
        failed = 0
        
        await update.message.reply_text(f"📢 Enviando para {len(users)} usuários...")
        
        for user in users:
            try:
                await self.bot.send_message(
                    user['id'],
                    f"📢 **Comunicado Oficial**\n\n{message}",
                    parse_mode='Markdown'
                )
                sent += 1
                await asyncio.sleep(0.1)  # Avoid rate limits
            except:
                failed += 1
        
        await update.message.reply_text(
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
    
    async def send_signal_alert(self, symbol, signal, price, rsi, macd, macd_signal):
        """Send signal alert to specific chat"""
        if not self.chat_id:
            return False, "No chat ID configured"
        
        try:
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
📈 Par: {symbol}
💰 Preço: ${price:.6f}

📊 **Indicadores:**
• RSI: {rsi:.2f}
• MACD: {macd:.4f}
• MACD Signal: {macd_signal:.4f}

⏰ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
            """
            
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
            return True, "Message sent successfully"
            
        except Exception as e:
            return False, str(e)
    
    async def send_custom_message(self, message):
        """Send custom message"""
        if not self.chat_id:
            return False, "No chat ID configured"
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
            return True, "Message sent successfully"
        except Exception as e:
            return False, str(e)
