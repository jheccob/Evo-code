#!/usr/bin/env python3
"""
Script para inicializar o bot do Telegram em background
"""

import asyncio
import logging
import os
import sys
import threading
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def start_telegram_bot():
    """Inicia o bot do Telegram em background"""
    try:
        # Verificar se token está disponível
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            logger.warning("❌ TELEGRAM_BOT_TOKEN não encontrado - bot não será iniciado")
            return False
            
        logger.info("🚀 Iniciando bot Telegram...")
        
        # Importar e inicializar bot
        from telegram_bot import TelegramTradingBot
        bot = TelegramTradingBot()
        
        if not bot.is_configured():
            logger.error("❌ Bot não configurado corretamente")
            return False
            
        logger.info("✅ Bot Telegram configurado com sucesso!")
        logger.info("💡 Bot pronto para receber comandos /start")
        
        # Usar método síncrono para evitar problemas com loops
        bot.start_polling()
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Erro ao iniciar bot Telegram: {e}")
        return False

def run_in_background():
    """Executa bot em thread separada"""
    try:
        start_telegram_bot()
    except KeyboardInterrupt:
        logger.info("🛑 Bot Telegram interrompido")
    except Exception as e:
        logger.error(f"❌ Erro fatal no bot Telegram: {e}")

if __name__ == "__main__":
    # Se executado diretamente, roda o bot
    start_telegram_bot()
else:
    # Se importado, inicia em background thread
    logger.info("🔄 Iniciando bot Telegram em background thread...")
    telegram_thread = threading.Thread(target=run_in_background, daemon=True)
    telegram_thread.start()
    logger.info("✅ Thread do bot Telegram iniciada")