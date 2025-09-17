import os
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class ProductionConfig:
    """Configurações de produção profissionais"""

    # Telegram Configuration
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "SEU_BOT_TOKEN_AQUI")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "SEU_CHAT_ID_AQUI")

    # Admin Users (Chat IDs)
    ADMIN_USERS: list = [1035830659]  # Adicione seus chat IDs aqui

    @classmethod
    def validate_config(cls) -> bool:
        """Validar configurações essenciais"""
        # Tentar carregar do arquivo de config se não estiver nas env vars
        try:
            from config.telegram_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
            if cls.TELEGRAM_BOT_TOKEN == "SEU_BOT_TOKEN_AQUI" and TELEGRAM_BOT_TOKEN != "SEU_BOT_TOKEN_AQUI":
                cls.TELEGRAM_BOT_TOKEN = TELEGRAM_BOT_TOKEN
                logger.info("✅ Token carregado do arquivo config")

            if cls.TELEGRAM_CHAT_ID == "SEU_CHAT_ID_AQUI" and TELEGRAM_CHAT_ID != "SEU_CHAT_ID_AQUI":
                cls.TELEGRAM_CHAT_ID = TELEGRAM_CHAT_ID
                logger.info("✅ Chat ID carregado do arquivo config")
        except ImportError:
            logger.warning("⚠️ Arquivo config/telegram_config.py não encontrado")

        errors = []

        if cls.TELEGRAM_BOT_TOKEN == "SEU_BOT_TOKEN_AQUI":
            errors.append("❌ TELEGRAM_BOT_TOKEN não configurado")

        if not cls.TELEGRAM_BOT_TOKEN.startswith(("1", "2", "5", "6", "7")):
            errors.append("❌ TELEGRAM_BOT_TOKEN formato inválido")_BOT_TOKEN inválido")

        if errors:
            for error in errors:
                logger.error(error)
            logger.info("💡 Configure o token no arquivo config/telegram_config.py")
            return False

        logger.info("✅ Configurações validadas com sucesso")
        return True

    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        """Verificar se usuário é admin"""
        return user_id in cls.ADMIN_USERS

    @classmethod
    def get_telegram_config(cls) -> dict:
        """Obter configuração do Telegram"""
        return {
            "bot_token": cls.TELEGRAM_BOT_TOKEN,
            "chat_id": cls.TELEGRAM_CHAT_ID
        }