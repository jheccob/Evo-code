
"""
Serviço Seguro do Telegram
Versão segura que não expõe tokens no código
"""

import os
import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)

# Verificar se telegram está disponível
try:
    from telegram import Bot
    from telegram.error import TelegramError
    import telegram
    TELEGRAM_AVAILABLE = True
    logger.info("Telegram service usando v%s", telegram.__version__)
except ImportError as e:
    TELEGRAM_AVAILABLE = False
    Bot = None
    TelegramError = None
    logger.warning("Telegram nao disponivel no service: %s", e)

class SecureTelegramService:
    def __init__(self):
        self.bot = None
        self.chat_id = None
        self._configured = False
        
        # Tentar carregar configuração dos Replit Secrets automaticamente
        self._load_from_secrets()
    
    def _load_from_secrets(self):
        """Carrega configuração dos Replit Secrets se disponível"""
        if not TELEGRAM_AVAILABLE:
            return
            
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        if token and chat_id:
            try:
                self.bot = Bot(token=token)
                self.chat_id = chat_id
                self._configured = True
                logger.info("✅ Telegram configurado via Replit Secrets")
            except Exception as e:
                logger.error(f"❌ Erro ao configurar Telegram via Secrets: {e}")
                self._configured = False
    
    def configure(self, bot_token: str, chat_id: str) -> Tuple[bool, str]:
        """Configura o bot do Telegram de forma segura"""
        if not TELEGRAM_AVAILABLE:
            return False, "❌ Biblioteca python-telegram-bot não disponível"
        
        try:
            # Validar formato básico
            if not bot_token or not chat_id:
                return False, "❌ Token e Chat ID são obrigatórios"
            
            if ":" not in bot_token:
                return False, "❌ Formato de token inválido"
            
            # Configurar bot
            self.bot = Bot(token=bot_token)
            self.chat_id = chat_id
            self._configured = True
            
            logger.info("✅ Telegram configurado com sucesso")
            return True, "✅ Configuração salva com sucesso!"
            
        except Exception as e:
            logger.error(f"❌ Erro na configuração: {e}")
            return False, f"❌ Erro na configuração: {str(e)}"
    
    def is_configured(self) -> bool:
        """Verifica se o serviço está configurado"""
        return self._configured and self.bot is not None and self.chat_id is not None
    
    def get_config_status(self) -> Dict[str, Any]:
        """Retorna status da configuração"""
        return {
            'configured': self.is_configured(),
            'has_bot': self.bot is not None,
            'has_chat_id': self.chat_id is not None,
            'telegram_available': TELEGRAM_AVAILABLE
        }
    
    def disable(self):
        """Desabilita o serviço"""
        self.bot = None
        self.chat_id = None
        self._configured = False
        logger.info("🔴 Telegram desabilitado")
    
    async def test_connection(self) -> Tuple[bool, str]:
        """Testa a conexão com o Telegram"""
        if not self.is_configured():
            return False, "❌ Telegram não configurado"
        
        try:
            # Tentar obter informações do bot
            bot_info = await self.bot.get_me()
            
            # Tentar enviar mensagem de teste
            test_message = f"🧪 Teste de conexão - {datetime.now().strftime('%H:%M:%S')}"
            await self.bot.send_message(chat_id=self.chat_id, text=test_message)
            
            return True, f"✅ Conectado como @{bot_info.username}"
            
        except Exception as e:
            logger.error(f"❌ Erro no teste: {e}")
            return False, f"❌ Erro na conexão: {str(e)}"
    
    async def send_signal_alert(self, symbol: str, signal: str, price: float, 
                              rsi: float, macd: float, macd_signal: float) -> bool:
        """Envia alerta de sinal"""
        if not self.is_configured():
            return False
        
        try:
            # Emojis para sinais
            signal_emojis = {
                "COMPRA": "🟢📈",
                "VENDA": "🔴📉", 
                "COMPRA_FRACA": "🟡📊",
                "VENDA_FRACA": "🟠📊",
                "NEUTRO": "⚪📊"
            }
            
            emoji = signal_emojis.get(signal, "📊")
            
            message = f"{emoji} SINAL DE {signal.replace('_', ' ')}\n\nPar: {symbol}\nPreco: ${price:.6f}\nRSI: {rsi:.2f}\nMACD: {macd:.4f}\nSignal: {macd_signal:.4f}\n\n{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
            
            await self.bot.send_message(
                chat_id=self.chat_id, 
                text=message
            )
            
            logger.info(f"📤 Sinal enviado: {signal} para {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erro ao enviar sinal: {e}")
            return False
    
    async def send_custom_message(self, message: str) -> Tuple[bool, str]:
        """Envia mensagem personalizada"""
        if not self.is_configured():
            return False, "❌ Telegram não configurado"
        
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=message)
            return True, "✅ Mensagem enviada!"
            
        except Exception as e:
            logger.error(f"❌ Erro ao enviar mensagem: {e}")
            return False, f"❌ Erro: {str(e)}"
