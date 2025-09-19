#!/usr/bin/env python3
"""
Trading Bot - Versão Profissional Simplificada
Usando telegram_bot.py atualizado
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime

# Configuração de logging profissional
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Verificar dependências primeiro
try:
    from telegram import Bot
    logger.info("✅ python-telegram-bot importado com sucesso")
except ImportError as e:
    logger.error(f"❌ Erro ao importar python-telegram-bot: {e}")
    logger.error("💡 Execute: pip install python-telegram-bot")
    sys.exit(1)

# Imports dos serviços
try:
    from telegram_bot import TelegramTradingBot
    from config.production_config import ProductionConfig
    logger.info("✅ Serviços importados com sucesso")
except ImportError as e:
    logger.error(f"❌ Erro ao importar serviços: {e}")
    sys.exit(1)

# Variável global
telegram_bot = None

async def main():
    """Função principal"""
    global telegram_bot
    
    try:
        logger.info("🚀 Iniciando Trading Bot Professional")

        # Validar configuração
        ProductionConfig.validate_config()

        # Inicializar bot Telegram
        telegram_bot = TelegramTradingBot()

        # Verificar se bot está configurado
        if not telegram_bot.is_configured():
            raise Exception("Bot Telegram não está configurado corretamente")

        logger.info("✅ Bot Telegram inicializado com sucesso!")
        logger.info("🎯 Trading Bot Professional - Modo Produção")
        logger.info("📱 Bot pronto para receber comandos!")
        logger.info("💡 Digite /start no Telegram para começar")

        # Iniciar bot em modo polling assíncrono
        # run_polling handles SIGINT/SIGTERM gracefully by default
        await telegram_bot.start_polling_async()

    except KeyboardInterrupt:
        logger.info("🛑 Bot interrompido pelo usuário")
    except Exception as e:
        logger.error(f"❌ Erro fatal: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())