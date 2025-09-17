
#!/usr/bin/env python3
"""
Trading Bot - Versão Profissional Simplificada
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
    from services.telegram_service import ProfessionalTelegramService
    from config.production_config import ProductionConfig
    logger.info("✅ Serviços importados com sucesso")
except ImportError as e:
    logger.error(f"❌ Erro ao importar serviços: {e}")
    sys.exit(1)

# Variável global
telegram_service = None

async def signal_handler(signum, frame):
    """Handler para sinais do sistema"""
    logger.info(f"Recebido sinal {signum}, encerrando...")

    # Cleanup
    if telegram_service and telegram_service.application:
        await telegram_service.application.stop()

    sys.exit(0)

async def main():
    """Função principal"""
    global telegram_service
    
    try:
        logger.info("🚀 Iniciando Trading Bot Professional")

        # Validar configuração
        ProductionConfig.validate_config()

        # Inicializar serviços
        telegram_service = ProfessionalTelegramService()

        # Inicializar Telegram service
        success = await telegram_service.initialize()
        if not success:
            raise Exception("Falha ao inicializar serviço Telegram")

        logger.info("✅ Bot Telegram inicializado com sucesso!")
        logger.info("🎯 Trading Bot Professional - Modo Produção")
        logger.info("📱 Bot pronto para receber comandos!")
        logger.info("💡 Digite /start no Telegram para começar")

        # Configurar handlers de sinal
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Iniciar bot em modo polling
        await telegram_service.start_production_service()

    except KeyboardInterrupt:
        logger.info("🛑 Bot interrompido pelo usuário")
        if telegram_service and telegram_service.application:
            await telegram_service.application.stop()
    except Exception as e:
        logger.error(f"❌ Erro fatal: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
