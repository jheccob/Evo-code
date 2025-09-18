#!/usr/bin/env python3
"""
Script para iniciar o bot do Telegram
Agora lê o token e o chat_id das variáveis de ambiente (Replit Secrets)
"""

import os
import logging
from telegram_bot import TelegramTradingBot, TelegramNotifier

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    """Main function to start the telegram bot"""
    try:
        # Pegando variáveis de ambiente do Replit
        TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
        TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

        if not TELEGRAM_BOT_TOKEN:
            logger.error("❌ Token do Telegram não configurado no Replit (Secret TELEGRAM_BOT_TOKEN)")
            return

        if TELEGRAM_CHAT_ID:
            bot = TelegramNotifier()
            bot.configure(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
        else:
            bot = TelegramTradingBot()
            bot.configure(TELEGRAM_BOT_TOKEN)

        logger.info("✅ Bot Telegram iniciado com sucesso no Replit!")
        logger.info("📡 Pressione Ctrl+C para parar")

        bot.start_polling()

    except KeyboardInterrupt:
        logger.info("🛑 Bot parado pelo usuário")
    except Exception as e:
        logger.error(f"💥 Erro ao iniciar bot: {e}")


if __name__ == '__main__':
    main()