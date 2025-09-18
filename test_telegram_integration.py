
#!/usr/bin/env python3
"""
Teste de integração do Telegram Bot
"""
import os
import sys
import asyncio
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_environment():
    """Testar variáveis de ambiente"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token:
        logger.error("❌ TELEGRAM_BOT_TOKEN não configurado")
        return False
    
    if not chat_id:
        logger.error("❌ TELEGRAM_CHAT_ID não configurado") 
        return False
    
    logger.info("✅ Variáveis de ambiente OK")
    return True

async def test_telegram_connection():
    """Testar conexão com Telegram"""
    try:
        from telegram import Bot
        
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        bot = Bot(token=token)
        
        # Teste básico
        me = await bot.get_me()
        logger.info(f"✅ Bot conectado: @{me.username}")
        
        # Teste de envio
        await bot.send_message(
            chat_id=chat_id,
            text="🧪 Teste de integração realizado com sucesso!"
        )
        
        logger.info("✅ Mensagem de teste enviada")
        return True
        
    except Exception as e:
        logger.error(f"❌ Erro na conexão: {e}")
        return False

async def main():
    """Função principal"""
    print("🧪 Testando integração do Telegram Bot...")
    
    # Teste 1: Variáveis de ambiente
    if not test_environment():
        sys.exit(1)
    
    # Teste 2: Conexão
    if not await test_telegram_connection():
        sys.exit(1)
    
    print("✅ Todos os testes passaram!")

if __name__ == "__main__":
    asyncio.run(main())
