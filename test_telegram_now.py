#!/usr/bin/env python3
"""
Teste robusto do Bot Telegram - Versão Atualizada
"""

import os
import logging
import asyncio
from telegram_bot import TelegramTradingBot

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def test_bot():
    """Test bot functionality"""
    logger.info("🧪 Iniciando teste do bot...")
    
    # Check environment variables
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    logger.info(f"🔑 Token disponível: {'✅ Sim' if token else '❌ Não'}")
    logger.info(f"💬 Chat ID disponível: {'✅ Sim' if chat_id else '❌ Não'}")
    
    if not token:
        logger.error("❌ TELEGRAM_BOT_TOKEN não encontrado nos Replit Secrets")
        logger.info("💡 Configure o token do bot nos Secrets do Replit")
        return False
    
    # Initialize bot
    bot = TelegramTradingBot()
    
    # Test configuration
    if bot.is_configured():
        logger.info("✅ Bot configurado com sucesso")
    else:
        logger.error("❌ Bot não está configurado corretamente")
        return False
    
    # Test connection
    success, message = await bot.test_connection()
    if success:
        logger.info(f"✅ Conexão OK: {message}")
    else:
        logger.error(f"❌ Erro na conexão: {message}")
        return False
    
    # Send test message if chat_id is available
    if chat_id and bot.bot:
        try:
            await bot.bot.send_message(
                chat_id=chat_id,
                text="🧪 **Teste do Bot - Versão Atualizada**\n\n"
                      "✅ Bot está funcionando corretamente!\n"
                      "💡 Use /start para começar a usar o bot.\n"
                      "🔄 Versão python-telegram-bot v20+ ativa",
                parse_mode='Markdown'
            )
            logger.info("✅ Mensagem de teste enviada com sucesso")
        except Exception as e:
            logger.error(f"❌ Erro ao enviar mensagem de teste: {e}")
    
    logger.info("🎉 Teste concluído com sucesso!")
    return True

def main():
    """Main function"""
    try:
        result = asyncio.run(test_bot())
        if result:
            print("\n" + "="*50)
            print("✅ BOT ESTÁ PRONTO PARA USO!")
            print("💡 O bot agora usa python-telegram-bot v20+")
            print("📱 Digite /start no Telegram para começar")
            print("="*50)
        else:
            print("\n" + "="*50)
            print("❌ BOT NÃO ESTÁ FUNCIONANDO")
            print("🔧 Verifique os Replit Secrets")
            print("="*50)
    except Exception as e:
        logger.error(f"❌ Erro no teste: {e}")

if __name__ == '__main__':
    main()