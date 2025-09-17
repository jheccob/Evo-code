import os
import asyncio
import logging
from telegram import Bot
from telegram.error import TelegramError
import pandas as pd

class TelegramNotifier:
    def __init__(self):
        self.bot_token = None
        self.chat_id = None
        self.bot = None
        self.enabled = False
        
    def configure(self, bot_token, chat_id):
        """Configure Telegram bot credentials"""
        try:
            self.bot_token = bot_token
            self.chat_id = chat_id
            self.bot = Bot(token=bot_token)
            self.enabled = True
            return True
        except Exception as e:
            print(f"Error configuring Telegram bot: {e}")
            self.enabled = False
            return False
    
    async def test_connection(self):
        """Test if the bot can send messages"""
        if not self.enabled:
            return False, "Bot not configured"
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text="🤖 Bot de Trading conectado com sucesso! Teste de conectividade."
            )
            return True, "Connection successful"
        except TelegramError as e:
            return False, f"Telegram error: {str(e)}"
        except Exception as e:
            return False, f"General error: {str(e)}"
    
    async def send_signal_alert(self, symbol, signal, price, rsi, macd, macd_signal):
        """Send trading signal alert to Telegram"""
        if not self.enabled:
            return False, "Bot not configured"
        
        try:
            # Choose emoji based on signal type
            signal_emojis = {
                "COMPRA": "🟢",
                "VENDA": "🔴", 
                "COMPRA_FRACA": "🟡",
                "VENDA_FRACA": "🟠",
                "NEUTRO": "⚪"
            }
            
            emoji = signal_emojis.get(signal, "⚪")
            signal_display = signal.replace('_', ' ')
            
            # Format message
            message = f"""
🚨 **ALERTA DE SINAL**

{emoji} **{signal_display}**
📈 Par: {symbol}
💰 Preço: ${price:.6f}

📊 **Indicadores:**
• RSI: {rsi:.2f}
• MACD: {macd:.4f}
• MACD Signal: {macd_signal:.4f}

⏰ {pd.Timestamp.now().strftime('%d/%m/%Y %H:%M:%S')}
            """
            
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
            return True, "Message sent successfully"
            
        except TelegramError as e:
            return False, f"Telegram error: {str(e)}"
        except Exception as e:
            return False, f"General error: {str(e)}"
    
    async def send_custom_message(self, message):
        """Send custom message to Telegram"""
        if not self.enabled:
            return False, "Bot not configured"
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
            return True, "Message sent successfully"
        except TelegramError as e:
            return False, f"Telegram error: {str(e)}"
        except Exception as e:
            return False, f"General error: {str(e)}"
    
    def is_configured(self):
        """Check if bot is properly configured"""
        return self.enabled and self.bot_token and self.chat_id