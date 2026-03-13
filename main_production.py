#!/usr/bin/env python3
"""
Trading Bot - Versão Profissional Simplificada
Compatível com config.py unificado
Sem async loop bug
"""

import logging
import sys
import time

# =========================
# LOG CONFIG
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("trading_bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


# =========================
# TEST TELEGRAM LIB
# =========================

try:

    logger.info("python-telegram-bot importado com sucesso")

except ImportError as e:
    logger.error(f"Erro ao importar python-telegram-bot: {e}")
    logger.error("Execute: pip install python-telegram-bot")
    sys.exit(1)


# =========================
# IMPORTS DO PROJETO
# =========================

try:
    from telegram_bot import TelegramTradingBot
    from config import ProductionConfig

    logger.info("Serviços importados com sucesso")

except ImportError as e:
    logger.error(f"Erro ao importar serviços: {e}")
    sys.exit(1)


telegram_bot = None


# =========================
# MAIN
# =========================

def main():

    global telegram_bot

    logger.info("Iniciando Trading Bot Professional")

    for attempt in range(1, 4):
        try:
            # validar config
            if not ProductionConfig.validate_config():
                raise Exception("Config inválida")

            # iniciar bot
            telegram_bot = TelegramTradingBot()

            if not telegram_bot.is_configured():
                raise Exception("Bot Telegram não está configurado corretamente")

            logger.info("Bot Telegram inicializado com sucesso")
            logger.info("Trading Bot Professional - Modo Produção")
            logger.info("Bot pronto para receber comandos")
            logger.info("Digite /start no Telegram")

            # START NORMAL (sem async)
            telegram_bot.start_polling()
            return

        except KeyboardInterrupt:
            logger.info("Bot interrompido pelo usuário")
            return

        except Exception as e:
            logger.error(f"Erro fatal (tentativa {attempt}/3): {e}")
            if attempt < 3:
                logger.info("Tentando reiniciar em 5 segundos...")
                time.sleep(5)
                continue
            else:
                logger.critical("Falha após 3 tentativas. Verificar logs e configuração.")
                return


# =========================

if __name__ == "__main__":
    main()