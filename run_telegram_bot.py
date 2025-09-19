#!/usr/bin/env python3
"""
Script para executar o bot Telegram
"""

import asyncio
import logging
import sys
import os
from telegram_bot import TelegramTradingBot

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Função principal para iniciar o bot"""
    try:
        logger.info("🚀 Iniciando Trading Bot Telegram...")
        
        # Verificar se token está configurado
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            logger.error("❌ TELEGRAM_BOT_TOKEN não configurado nos Replit Secrets")
            logger.info("💡 Configure o token do bot nos Secrets do Replit")
            logger.info("📖 Veja TELEGRAM_SETUP.md para instruções")
            return
        
        # Inicializar bot
        bot = TelegramTradingBot()
        
        if not bot.is_configured():
            logger.error("❌ Bot não configurado corretamente")
            return
        
        logger.info("✅ Bot configurado com sucesso!")
        logger.info("💡 Digite /start no Telegram para começar")
        logger.info("🛑 Pressione Ctrl+C para parar")
        
        # Iniciar polling
        bot.start_polling()
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot parado pelo usuário")
    except Exception as e:
        logger.error(f"❌ Erro fatal: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()