
"""
Configuração centralizada do Telegram Bot
"""
import os
from typing import Optional, Dict, Any

class TelegramBotConfig:
    """Configuração do bot Telegram"""
    
    # Configurações básicas
    MAX_ANALYSES_FREE = 1
    MAX_ANALYSES_PREMIUM = float('inf')
    
    # Rate limiting
    MAX_ERRORS_PER_WINDOW = 5
    ERROR_WINDOW_SECONDS = 300
    RETRY_ATTEMPTS = 3
    RETRY_DELAY = 1
    
    # Comandos disponíveis
    AVAILABLE_COMMANDS = [
        "/start", "/help", "/analise", "/status", 
        "/premium", "/admin", "/stats", "/users", 
        "/upgrade", "/broadcast"
    ]
    
    # Pares suportados
    SUPPORTED_PAIRS = [
        "BTC/USDT", "ETH/USDT", "XLM/USDT", 
        "ADA/USDT", "DOT/USDT", "MATIC/USDT",
        "LINK/USDT", "UNI/USDT", "SOL/USDT"
    ]
    
    # Emojis para sinais
    SIGNAL_EMOJIS = {
        "COMPRA": "🟢",
        "VENDA": "🔴", 
        "COMPRA_FRACA": "🟡",
        "VENDA_FRACA": "🟠",
        "NEUTRO": "⚪"
    }
    
    @staticmethod
    def get_bot_token() -> Optional[str]:
        """Obter token do bot das variáveis de ambiente"""
        return os.getenv("TELEGRAM_BOT_TOKEN")
    
    @staticmethod
    def get_chat_id() -> Optional[str]:
        """Obter chat ID das variáveis de ambiente"""
        return os.getenv("TELEGRAM_CHAT_ID")
    
    @staticmethod
    def is_valid_pair(symbol: str) -> bool:
        """Verificar se o par é suportado"""
        return symbol.upper() in TelegramBotConfig.SUPPORTED_PAIRS
    
    @staticmethod
    def get_signal_emoji(signal: str) -> str:
        """Obter emoji para o sinal"""
        return TelegramBotConfig.SIGNAL_EMOJIS.get(signal, "⚪")
