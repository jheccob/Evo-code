
#!/usr/bin/env python3
"""
Teste básico do bot Telegram
"""

import asyncio
import logging
from config.telegram_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_basic_bot():
    """Teste básico do bot"""
    try:
        from telegram import Bot
        
        # Criar bot
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        
        # Testar conexão
        me = await bot.get_me()
        logger.info(f"✅ Bot conectado: @{me.username}")
        logger.info(f"📝 Nome: {me.first_name}")
        logger.info(f"🆔 ID: {me.id}")
        
        # Enviar mensagem de teste
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="🤖 **Teste do Bot**\n\n✅ Bot funcionando perfeitamente!\n\nDigite /start para começar!",
            parse_mode='Markdown'
        )
        logger.info("📤 Mensagem de teste enviada!")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Erro no teste: {e}")
        return False

if __name__ == '__main__':
    result = asyncio.run(test_basic_bot())
    if result:
        logger.info("🎉 Teste concluído com sucesso!")
    else:
        logger.error("💥 Teste falhou!")
