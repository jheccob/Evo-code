#!/usr/bin/env python3
"""
Bot Telegram para Trading - Versão Consolidada e Atualizada
Python-telegram-bot v20+
"""

import asyncio
import logging
import os
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
    print("💡 Install with: pip install python-telegram-bot==20.7")
    
    # Se não tiver telegram, não prosseguir
    Bot = None
    Update = None
    ContextTypes = None
    Application = None
    CommandHandler = None

from user_manager import UserManager
from trading_bot import TradingBot
from config.telegram_bot_config import TelegramBotConfig

logger = logging.getLogger(__name__)

class TelegramTradingBot:
    """Bot Telegram para Trading - Versão Consolidada"""
    
    def __init__(self):
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
                ("admin", self.admin_command),
                ("stats", self.stats_command),
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
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        try:
            user_id = update.effective_user.id
            username = update.effective_user.username or "sem_username"
            first_name = update.effective_user.first_name or "Usuário"
            
            self.logger.info(f"📥 Comando /start recebido de {user_id} ({first_name})")
            
            # Add user to database if user_manager is available
            if self.user_manager:
                try:
                    self.user_manager.add_user(user_id, username, first_name)
                    self.logger.info(f"✅ Usuário {user_id} adicionado ao banco")
                except Exception as e:
                    self.logger.warning(f"⚠️ Erro ao adicionar usuário: {e}")
            
            # Importar configuração
            try:
                from config.telegram_bot_config import TelegramBotConfig
                supported_pairs = TelegramBotConfig.SUPPORTED_PAIRS[:6]
            except ImportError:
                supported_pairs = ["BTC/USDT", "ETH/USDT", "XLM/USDT"]
            
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
            
            await update.message.reply_text(welcome_message, parse_mode='Markdown')
            self.logger.info(f"✅ Usuário {user_id} - comando /start processado com sucesso")
            
        except Exception as e:
            self.logger.error(f"❌ Erro no comando /start: {e}")
            try:
                await update.message.reply_text(
                    "❌ Erro interno no comando /start. Tente novamente em alguns minutos."
                )
            except Exception as reply_error:
                self.logger.error(f"❌ Erro ao enviar resposta de erro: {reply_error}")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        try:
            user_id = update.effective_user.id
            is_admin = self.user_manager.is_admin(user_id)
            is_premium = self.user_manager.is_premium(user_id)
            
            help_text = f"Comandos Disponiveis:\n\nAnalises:\n- /analise BTC/USDT - Analisar criptomoeda\n- /status - Ver seu status e limites\n\nPremium:\n- /premium - Informacoes sobre Premium\n{'- Voce e Premium!' if is_premium else '- Plano Free (1 analise/dia)'}\n\nPares suportados:\n{', '.join(TelegramBotConfig.SUPPORTED_PAIRS)}"
            
            if is_admin:
                help_text += "\n\nComandos de Admin:\n- /admin - Painel administrativo\n- /stats - Estatisticas do bot\n- /users - Listar usuarios\n- /upgrade [ID] - Fazer upgrade de usuario\n- /broadcast [MSG] - Enviar mensagem para todos"
            
            await update.message.reply_text(help_text)
            
        except Exception as e:
            self.logger.error(f"❌ Erro no comando /help: {e}")
            await update.message.reply_text("❌ Erro interno. Tente novamente.")
    
    async def analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /analise command"""
        try:
            user_id = update.effective_user.id
            user = self.user_manager.get_user(user_id)
            
            if not user:
                self.user_manager.add_user(user_id, update.effective_user.username, 
                                         update.effective_user.first_name)
                user = self.user_manager.get_user(user_id)
            
            # Check if user can perform analysis
            if not self.user_manager.can_analyze(user_id):
                await update.message.reply_text(
                    "Limite atingido!\n\nUsuarios Free tem direito a 1 analise por dia.\n\nUpgrade para Premium e tenha:\n- Analises ilimitadas\n- Alerts em tempo real\n- Analises mais detalhadas\n\nUse /premium para mais informacoes!"
                )
                return
            
            # Get symbol from command
            if not context.args:
                await update.message.reply_text(
                    "Formato incorreto!\n\nUso correto:\n/analise BTC/USDT\n\nPares disponiveis:\n" + ', '.join(TelegramBotConfig.SUPPORTED_PAIRS[:6]) + "..."
                )
                return
            
            symbol = context.args[0].upper()
            
            # Validate symbol
            if not TelegramBotConfig.is_valid_pair(symbol):
                await update.message.reply_text(
                    f"Par nao suportado: {symbol}\n\nPares disponiveis:\n{', '.join(TelegramBotConfig.SUPPORTED_PAIRS)}"
                )
                return
            
            # Send loading message
            loading_msg = await update.message.reply_text("Analisando...\nPor favor aguarde...")
            
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
                await loading_msg.edit_text("Erro: Nao foi possivel obter dados do mercado")
                return
            
            # Get analysis
            last_candle = data.iloc[-1]
            signal = self.trading_bot.check_signal(data)
            emoji = TelegramBotConfig.get_signal_emoji(signal)
            
            analysis_message = f"Analise Tecnica - {symbol}\n\n{emoji} Sinal: {signal.replace('_', ' ')}\n\nPreco Atual: ${last_candle['close']:.6f}\nVariacao: {((last_candle['close'] - last_candle['open']) / last_candle['open'] * 100):+.2f}%\n\nIndicadores:\n- RSI: {last_candle['rsi']:.2f}\n- MACD: {last_candle['macd']:.4f}\n- MACD Signal: {last_candle['macd_signal']:.4f}\n\nAtualizado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\nLembre-se: Esta e uma analise tecnica automatizada. Sempre faca sua propria pesquisa!"
            
            await loading_msg.edit_text(analysis_message)
            
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

📅 **Membro desde:** {user['joined_date'][:10]}

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
    
    # Admin commands (simplified)
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /admin command"""
        user_id = update.effective_user.id
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text("❌ Acesso negado")
            return
        
        stats = self.user_manager.get_stats()
        admin_msg = f"""
👑 **Admin Panel**

📊 **Estatísticas:**
• Usuários: {stats['total_users']}
• Premium: {stats['premium_users']}
• Free: {stats['free_users']}
• Análises hoje: {stats.get('analyses_today', 0)}
"""
        await update.message.reply_text(admin_msg, parse_mode='Markdown')
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        await update.message.reply_text("📊 Estatísticas - em desenvolvimento")
    
    async def users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /users command"""
        await update.message.reply_text("👥 Lista de usuários - em desenvolvimento")
    
    async def upgrade_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /upgrade command"""
        await update.message.reply_text("💎 Upgrade de usuário - em desenvolvimento")
    
    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /broadcast command"""
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
    
    async def start_polling_async(self):
        """Start the bot polling - async method for integration (PTB v22.4)"""
        if not TELEGRAM_AVAILABLE:
            self.logger.error("❌ Cannot start polling: Telegram library not available")
            return False
        
        if not self.application:
            self.logger.error("❌ Cannot start polling: Bot not configured")
            return False
        
        try:
            self.logger.info("🚀 Starting Telegram bot polling (async)...")
            
            # Use the run_polling method which handles initialization and cleanup properly
            await self.application.run_polling(drop_pending_updates=True)
            
            return True
        except Exception as e:
            self.logger.error(f"❌ Erro ao iniciar polling: {e}")
            return False
    
    def is_configured(self):
        """Check if bot is configured"""
        return self.enabled and self.bot_token and TELEGRAM_AVAILABLE