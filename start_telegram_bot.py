
#!/usr/bin/env python3
"""
Script para iniciar o bot do Telegram
Execute este arquivo separadamente para manter o bot rodando
"""

import asyncio
import logging
from telegram_bot import TelegramTradingBot

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

async def main():
    """Main function to start the telegram bot"""
    try:
        from config.telegram_config import TELEGRAM_BOT_TOKEN
        
        if TELEGRAM_BOT_TOKEN == "SEU_BOT_TOKEN_AQUI":
            logger.error("Configure o token do bot no arquivo config/telegram_config.py")
            return
        
        # Create and configure bot
        bot = TelegramTradingBot()
        
        if not bot.configure(TELEGRAM_BOT_TOKEN):
            logger.error("Erro ao configurar o bot")
            return
        
        logger.info("Bot Telegram iniciado com sucesso!")
        logger.info("Pressione Ctrl+C para parar")
        
        # Start polling
        bot.start_polling()
        
    except KeyboardInterrupt:
        logger.info("Bot parado pelo usuário")
    except Exception as e:
        logger.error(f"Erro ao iniciar bot: {e}")

if __name__ == '__main__':
    asyncio.run(main())
