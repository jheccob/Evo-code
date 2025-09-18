"""
Serviço de notificações do Telegram - Versão simplificada
"""
import asyncio
import logging
from typing import Optional, Tuple, Dict, Any
from datetime import datetime

try:
    from telegram import Bot
    from telegram.error import TelegramError
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

from utils.timezone_utils import format_brazil_time
from database.database import db

logger = logging.getLogger(__name__)

class SecureTelegramService:
    def __init__(self):
        self.bot = None
        self.bot_token = None
        self.chat_id = None
        self.enabled = False
        self._load_config()

    def _load_config(self):
        """Carregar configuração do banco"""
        if not TELEGRAM_AVAILABLE:
            return

        try:
            token = db.get_setting("telegram_token")
            chat_id = db.get_setting("telegram_chat_id")
            enabled = db.get_setting("telegram_enabled", False)

            if token and chat_id and enabled:
                self.bot_token = token
                self.chat_id = chat_id
                self.bot = Bot(token=self.bot_token)
                self.enabled = True
        except Exception as e:
            logger.error(f"Erro ao carregar config Telegram: {e}")

    def configure(self, token: str, chat_id: str) -> Tuple[bool, str]:
        """Configurar Telegram"""
        if not TELEGRAM_AVAILABLE:
            return False, "❌ Biblioteca não disponível"

        try:
            self.bot_token = token.strip()
            self.chat_id = chat_id.strip()
            self.bot = Bot(token=self.bot_token)

            # Testar
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            me = loop.run_until_complete(self.bot.get_me())
            test_msg = f"✅ Bot @{me.username} configurado!"
            loop.run_until_complete(
                self.bot.send_message(chat_id=self.chat_id, text=test_msg)
            )

            # Salvar
            db.save_setting("telegram_token", self.bot_token)
            db.save_setting("telegram_chat_id", self.chat_id)
            db.save_setting("telegram_enabled", True)

            self.enabled = True
            return True, f"✅ Configurado: @{me.username}"

        except Exception as e:
            return False, f"❌ Erro: {str(e)}"

    def is_configured(self) -> bool:
        return self.enabled and self.bot is not None

    async def test_connection(self) -> Tuple[bool, str]:
        if not self.is_configured():
            return False, "❌ Não configurado"

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=f"🤖 Teste OK - {format_brazil_time()}"
            )
            return True, "✅ Teste enviado!"
        except Exception as e:
            return False, f"❌ Erro: {str(e)}"

    async def send_signal_alert(self, symbol=None, signal=None, price=None, 
                              rsi=None, **kwargs) -> Tuple[bool, str]:
        if not self.is_configured():
            return False, "❌ Não configurado"

        try:
            # Usar dados do kwargs se disponível
            if 'signal_data' in kwargs:
                data = kwargs['signal_data']
                symbol = data.get('symbol', symbol)
                signal = data.get('signal', signal) 
                price = data.get('price', price)
                rsi = data.get('rsi', rsi)

            emoji = {'COMPRA': '🟢', 'VENDA': '🔴', 'NEUTRO': '⚪'}.get(signal, '⚪')

            message = f"""
{emoji} **SINAL DE TRADING**

📊 **Par:** {symbol}
💰 **Preço:** ${price:.6f}
📈 **RSI:** {rsi:.2f}
🎯 **Sinal:** {signal}

⏰ {format_brazil_time()}
"""

            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
            return True, "✅ Sinal enviado!"

        except Exception as e:
            return False, f"❌ Erro: {str(e)}"

    def disable(self):
        """Desabilitar"""
        db.save_setting("telegram_enabled", False)
        self.enabled = False
        self.bot = None

    def get_config_status(self) -> Dict[str, Any]:
        return {
            'available': TELEGRAM_AVAILABLE,
            'configured': self.is_configured(),
            'enabled': self.enabled
        }