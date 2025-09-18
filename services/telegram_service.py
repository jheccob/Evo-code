"""
Serviço de notificações do Telegram - Versão segura
"""
import asyncio
import logging
from typing import Optional, Tuple, Dict, Any
from datetime import datetime
import json

try:
    import telegram
    from telegram import Bot
    from telegram.error import TelegramError, RetryAfter, TimedOut
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    
from utils.timezone_utils import format_brazil_time
from database.database import db

logger = logging.getLogger(__name__)

class SecureTelegramService:
    """
    Serviço seguro para notificações do Telegram
    Não armazena tokens no código - usa configuração via interface
    """
    
    def __init__(self):
        self.bot = None
        self.bot_token = None
        self.chat_id = None
        self.enabled = False
        
    def configure(self, token: str, chat_id: str) -> Tuple[bool, str]:
        """
        Configurar o serviço Telegram de forma segura
        
        Args:
            token: Token do bot do Telegram
            chat_id: ID do chat para enviar mensagens
            
        Returns:
            Tuple[bool, str]: (sucesso, mensagem)
        """
        if not TELEGRAM_AVAILABLE:
            return False, "❌ Biblioteca python-telegram-bot não está disponível"
        
        if not token or not chat_id:
            return False, "❌ Token e Chat ID são obrigatórios"
            
        try:
            # Limpar e validar entradas
            self.bot_token = token.strip()
            self.chat_id = chat_id.strip()
            
            # Validações básicas
            if not self.bot_token.count(':') == 1:
                return False, "❌ Formato do token inválido. Deve ser como: 123456789:ABCDEF..."
            
            # Tentar criar o bot
            self.bot = Bot(token=self.bot_token)
            
            # Teste de conexão antes de salvar
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Testar autenticação
                me = loop.run_until_complete(self.bot.get_me())
                logger.info(f"Bot autenticado: @{me.username}")
                
                # Testar envio de mensagem
                test_msg = f"🤖 Teste de configuração\n✅ Bot @{me.username} conectado!"
                loop.run_until_complete(
                    self.bot.send_message(chat_id=self.chat_id, text=test_msg)
                )
                
                # Salvar apenas se tudo funcionou
                db.save_setting("telegram_token", self.bot_token)
                db.save_setting("telegram_chat_id", self.chat_id)
                db.save_setting("telegram_enabled", True)
                
                self.enabled = True
                return True, f"✅ Telegram configurado! Bot: @{me.username}"
                
            except TelegramError as te:
                if "Unauthorized" in str(te):
                    return False, "❌ Token inválido ou bot desabilitado"
                elif "Chat not found" in str(te):
                    return False, "❌ Chat ID não encontrado. Verifique se enviou /start para o bot"
                elif "Forbidden" in str(te):
                    return False, "❌ Bot foi bloqueado. Desbloqueie e envie /start"
                else:
                    return False, f"❌ Erro do Telegram: {str(te)}"
            
        except Exception as e:
            logger.error(f"Erro ao configurar Telegram: {e}")
            self.enabled = False
            return False, f"❌ Erro de configuração: {str(e)}"
    
    def load_config(self) -> bool:
        """Carregar configuração salva do banco de dados"""
        try:
            if not TELEGRAM_AVAILABLE:
                return False
                
            token = db.get_setting("telegram_token")
            chat_id = db.get_setting("telegram_chat_id")
            enabled = db.get_setting("telegram_enabled", False)
            
            if token and chat_id and enabled:
                # Validar se não são strings vazias
                token = str(token).strip()
                chat_id = str(chat_id).strip()
                
                if token and chat_id and token != 'None' and chat_id != 'None':
                    self.bot_token = token
                    self.chat_id = chat_id
                    self.bot = Bot(token=self.bot_token)
                    self.enabled = True
                    logger.info("✅ Configuração Telegram carregada do banco de dados")
                    return True
                
        except Exception as e:
            logger.error(f"Erro ao carregar configuração do Telegram: {e}")
        
        return False
    
    def is_configured(self) -> bool:
        """Verificar se o serviço está configurado"""
        if not self.enabled:
            self.load_config()
        return self.enabled and self.bot is not None
    
    async def test_connection(self) -> Tuple[bool, str]:
        """
        Testar conexão com o Telegram
        
        Returns:
            Tuple[bool, str]: (sucesso, mensagem)
        """
        if not self.is_configured():
            return False, "❌ Telegram não configurado"
            
        try:
            # Enviar mensagem de teste
            test_message = f"🤖 **Teste de Conexão**\\n\\n✅ Bot funcionando corretamente!\\n🕒 {format_brazil_time()}"
            
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=test_message,
                parse_mode='Markdown'
            )
            
            return True, "✅ Conexão testada com sucesso! Mensagem enviada."
            
        except TelegramError as e:
            error_msg = f"❌ Erro do Telegram: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
            
        except Exception as e:
            error_msg = f"❌ Erro inesperado: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
    
    async def send_signal_alert(self, symbol: str = None, signal: str = None, price: float = None, 
                              rsi: float = None, macd: float = None, macd_signal: float = None, 
                              timeframe: str = '1h', **kwargs) -> Tuple[bool, str]:
        """
        Enviar alerta de sinal de trading
        
        Args:
            symbol: Par de trading
            signal: Tipo do sinal
            price: Preço atual
            rsi: Valor do RSI
            macd: Valor do MACD
            macd_signal: Valor do MACD Signal
            timeframe: Timeframe
            
        Returns:
            Tuple[bool, str]: (sucesso, mensagem)
        """
        if not self.is_configured():
            return False, "❌ Telegram não configurado"
            
        try:
            # Se foi passado um dict como primeiro parâmetro
            if isinstance(symbol, dict):
                signal_data = symbol
                symbol = signal_data.get('symbol', 'N/A')
                signal = signal_data.get('signal', 'NEUTRO')
                price = signal_data.get('price', 0)
                rsi = signal_data.get('rsi', 0)
                timeframe = signal_data.get('timeframe', '1h')
            
            # Emoji baseado no sinal
            emoji_map = {
                'COMPRA': '🟢',
                'COMPRA_FORTE': '💚', 
                'COMPRA_FRACA': '🟡',
                'VENDA': '🔴',
                'VENDA_FORTE': '💔',
                'VENDA_FRACA': '🟠',
                'NEUTRO': '⚪'
            }
            
            emoji = emoji_map.get(signal, '⚪')
            
            message = f"""
{emoji} **SINAL DE TRADING**

📊 **Par:** {symbol}
⏰ **Timeframe:** {timeframe}
💰 **Preço:** ${price:.6f}
📈 **RSI:** {rsi:.2f}

🎯 **Sinal:** {signal}

⏰ **Horário:** {format_brazil_time()}
🤖 **Bot de Trading Automatizado**
            """.strip()
            
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
            
            return True, "✅ Sinal enviado com sucesso!"
            
        except Exception as e:
            error_msg = f"❌ Erro ao enviar sinal: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
    
    async def send_custom_message(self, message: str) -> Tuple[bool, str]:
        """
        Enviar mensagem personalizada
        
        Args:
            message: Mensagem a ser enviada
            
        Returns:
            Tuple[bool, str]: (sucesso, mensagem de resultado)
        """
        if not self.is_configured():
            return False, "❌ Telegram não configurado"
            
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
            
            return True, "✅ Mensagem enviada com sucesso!"
            
        except Exception as e:
            error_msg = f"❌ Erro ao enviar mensagem: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
    
    def disable(self):
        """Desabilitar o serviço Telegram"""
        try:
            db.save_setting("telegram_enabled", False)
            self.enabled = False
            self.bot = None
            self.bot_token = None
            self.chat_id = None
        except Exception as e:
            logger.error(f"Erro ao desabilitar Telegram: {e}")
    
    def get_config_status(self) -> Dict[str, Any]:
        """Obter status da configuração"""
        return {
            'available': TELEGRAM_AVAILABLE,
            'configured': self.is_configured(),
            'enabled': self.enabled,
            'has_token': bool(self.bot_token),
            'has_chat_id': bool(self.chat_id)
        }