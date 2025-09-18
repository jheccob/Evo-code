
#!/usr/bin/env python3
"""
Bot Telegram Trading - Versão Simplificada
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any

try:
    from telegram import Bot, Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    from telegram.error import TelegramError, RetryAfter, TimedOut, NetworkError
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

from user_manager import UserManager
from trading_bot import TradingBot

logger = logging.getLogger(__name__)

class SimpleTelegramBot:
    """Bot Telegram simplificado"""
    
    def __init__(self):
        if not TELEGRAM_AVAILABLE:
            logger.error("❌ Biblioteca Telegram não disponível")
            return
            
        self.bot_token = None
        self.bot = None
        self.application = None
        self.enabled = False
        self.user_manager = UserManager()
        self.trading_bot = TradingBot()
        
    def configure(self, bot_token: str) -> bool:
        """Configurar o bot"""
        try:
            self.bot_token = bot_token
            self.bot = Bot(token=bot_token)
            self.application = Application.builder().token(bot_token).build()
            
            # Adicionar handlers
            self.application.add_handler(CommandHandler("start", self.start_command))
            self.application.add_handler(CommandHandler("help", self.help_command))
            self.application.add_handler(CommandHandler("analise", self.analyze_command))
            self.application.add_handler(CommandHandler("status", self.status_command))
            
            self.enabled = True
            logger.info("✅ Bot configurado com sucesso")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro ao configurar bot: {e}")
            return False
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /start"""
        user_id = update.effective_user.id
        username = update.effective_user.username
        first_name = update.effective_user.first_name
        
        self.user_manager.add_user(user_id, username, first_name)
        
        welcome_msg = f"""
🎯 **Bem-vindo ao Trading Bot!**

Olá {first_name}! 👋

🔧 **Comandos:**
• `/analise BTC/USDT` - Analisar par
• `/status` - Seu status
• `/help` - Ajuda

✨ Vamos começar!
"""
        await update.message.reply_text(welcome_msg, parse_mode='Markdown')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /help"""
        help_msg = """
📖 **Comandos Disponíveis**

📊 `/analise BTC/USDT` - Analisar par
📊 `/status` - Ver status
📊 `/help` - Esta ajuda

🔧 **Pares:** BTC/USDT, ETH/USDT, XLM/USDT
"""
        await update.message.reply_text(help_msg, parse_mode='Markdown')
    
    async def analyze_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /analise"""
        user_id = update.effective_user.id
        
        if not self.user_manager.can_analyze(user_id):
            await update.message.reply_text(
                "⚠️ **Limite atingido!**\n\nUsuários Free: 1 análise/dia"
            )
            return
        
        if not context.args:
            await update.message.reply_text(
                "❌ **Uso:** `/analise BTC/USDT`"
            )
            return
        
        symbol = context.args[0].upper()
        loading_msg = await update.message.reply_text("🔄 **Analisando...**")
        
        try:
            self.trading_bot.update_config(symbol=symbol)
            data = self.trading_bot.get_market_data()
            
            if data is None or data.empty:
                await loading_msg.edit_text("❌ **Erro:** Sem dados")
                return
            
            last_candle = data.iloc[-1]
            signal = self.trading_bot.check_signal(data)
            
            analysis_msg = f"""
📊 **Análise - {symbol}**

🎯 **Sinal:** {signal}
💰 **Preço:** ${last_candle['close']:.6f}
📊 **RSI:** {last_candle['rsi']:.2f}

⏰ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
            
            await loading_msg.edit_text(analysis_msg, parse_mode='Markdown')
            self.user_manager.record_analysis(user_id)
            
        except Exception as e:
            logger.error(f"Erro na análise: {e}")
            await loading_msg.edit_text("❌ **Erro na análise**")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /status"""
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
📊 **Análises hoje:** {analyses_today}/1
🔄 **Status:** {'Disponível ✅' if self.user_manager.can_analyze(user_id) else 'Limite atingido ❌'}
"""
        
        await update.message.reply_text(status_msg, parse_mode='Markdown')
    
    async def test_connection(self):
        """Testar conexão"""
        if not self.enabled:
            return False, "Bot não configurado"
        
        try:
            me = await self.bot.get_me()
            return True, f"Conectado como @{me.username}"
        except Exception as e:
            return False, str(e)
    
    def start_polling(self):
        """Iniciar polling"""
        if self.application:
            logger.info("🚀 Iniciando bot...")
            self.application.run_polling()
    
    def is_configured(self):
        """Verificar se está configurado"""
        return self.enabled and self.bot_token

def main():
    """Função principal para teste"""
    # Suas credenciais
    BOT_TOKEN = "8454268048:AAFSiHU963ch55L5EhLSrpwdRtKBtPSO_0A"
    
    bot = SimpleTelegramBot()
    if bot.configure(BOT_TOKEN):
        print("✅ Bot configurado! Iniciando...")
        bot.start_polling()
    else:
        print("❌ Erro na configuração")

if __name__ == "__main__":
    main()
