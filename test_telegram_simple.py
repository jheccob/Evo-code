
#!/usr/bin/env python3
"""
Teste simples do bot Telegram
"""

import asyncio
import logging
from telegram_bot import TelegramTradingBot
from config.telegram_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_bot():
    """Teste básico do bot"""
    bot = TelegramTradingBot()
    
    # Configurar bot
    success = bot.configure(TELEGRAM_BOT_TOKEN)
    if not success:
        logger.error("❌ Falha na configuração do bot")
        return
    
    # Testar conexão
    connection_ok, message = await bot.test_connection()
    logger.info(f"Conexão: {connection_ok} - {message}")
    
    if connection_ok:
        logger.info("✅ Bot conectado! Enviando mensagem de teste...")
        
        # Enviar mensagem de teste
        success, result = await bot.send_custom_message(
            "🤖 **Bot Online!**\n\n"
            "Seu bot está funcionando perfeitamente!\n\n"
            "📊 **Comandos disponíveis:**\n"
            "• `/start` - Iniciar bot\n"
            "• `/help` - Ver ajuda\n"
            "• `/analise BTC/USDT` - Análise\n"
            "• `/status` - Ver status\n\n"
            "🚀 Digite qualquer comando para testar!"
        )
        
        if success:
            logger.info("✅ Mensagem de teste enviada!")
        else:
            logger.error(f"❌ Erro ao enviar: {result}")
    
    return connection_ok

if __name__ == '__main__':
    asyncio.run(test_bot())
