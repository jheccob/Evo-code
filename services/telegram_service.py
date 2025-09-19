"""
Serviço de notificações do Telegram - Versão simplificada
"""
import asyncio
import logging
import os
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
        # Carregar configuração dos secrets do Replit
        self._load_config()

    def _load_config(self):
        """Carregar configuração dos environment variables (Replit Secrets)"""
        if not TELEGRAM_AVAILABLE:
            return

        try:
            # Usar os secrets do Replit
            token = os.getenv("TELEGRAM_BOT_TOKEN")
            chat_id = os.getenv("TELEGRAM_CHAT_ID")

            if token and chat_id:
                self.bot_token = token
                self.chat_id = chat_id
                self.bot = Bot(token=self.bot_token)
                self.enabled = True
                logger.info("✅ Telegram configurado automaticamente via Replit Secrets")
            else:
                logger.info("⚠️ Credenciais do Telegram não encontradas nos secrets")
        except Exception as e:
            logger.error(f"Erro ao carregar config Telegram: {e}")

    def configure(self, token: str, chat_id: str) -> Tuple[bool, str]:
        """Configurar Telegram (apenas para teste - credenciais vêm dos Secrets)"""
        if not TELEGRAM_AVAILABLE:
            return False, "❌ Biblioteca não disponível"

        try:
            # Usar as credenciais apenas para teste, não salvar no banco
            test_token = token.strip()
            test_chat_id = chat_id.strip()
            test_bot = Bot(token=test_token)

            # Testar conexão
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            me = loop.run_until_complete(test_bot.get_me())
            test_msg = f"✅ Bot @{me.username} testado com sucesso!"
            loop.run_until_complete(
                test_bot.send_message(chat_id=test_chat_id, text=test_msg)
            )

            # NÃO salvar no banco - as credenciais devem vir dos Replit Secrets
            # Recarregar configuração dos secrets
            self._load_config()
            
            return True, f"✅ Teste ok: @{me.username}. Use os Replit Secrets para configuração permanente."

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

            # Validar dados obrigatórios com valores padrão seguros
            symbol = symbol or "N/A"
            signal = signal or "NEUTRO"
            
            emoji = {'COMPRA': '🟢', 'VENDA': '🔴', 'NEUTRO': '⚪'}.get(signal, '⚪')

            # Formatação segura para preço e RSI
            price_str = f"${price:.6f}" if price is not None else "N/A"
            rsi_str = f"{rsi:.2f}" if rsi is not None else "N/A"

            message = f"""
{emoji} **SINAL DE TRADING**

📊 **Par:** {symbol}
💰 **Preço:** {price_str}
📈 **RSI:** {rsi_str}
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

    async def send_custom_message(self, message: str, chat_id: str = None) -> Tuple[bool, str]:
        """Enviar mensagem customizada"""
        if not self.is_configured():
            return False, "❌ Não configurado"

        try:
            target_chat_id = chat_id or self.chat_id
            
            await self.bot.send_message(
                chat_id=target_chat_id,
                text=message,
                parse_mode='Markdown'
            )
            return True, "✅ Mensagem enviada!"

        except Exception as e:
            return False, f"❌ Erro: {str(e)}"

    def disable(self):
        """Desabilitar"""
        db.save_setting("telegram_enabled", False)
        self.enabled = False
        self.bot = None

    def get_config_status(self) -> Dict[str, Any]:
        # Forçar reload da configuração para garantir que os secrets sejam lidos
        if not self.is_configured():
            self._load_config()
        
        return {
            'available': TELEGRAM_AVAILABLE,
            'configured': self.is_configured(),
            'enabled': self.enabled,
            'auto_configured': bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
        }