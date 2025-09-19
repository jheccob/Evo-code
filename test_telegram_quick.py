
#!/usr/bin/env python3
import asyncio
import os
from services.telegram_service import SecureTelegramService

async def test_now():
    telegram = SecureTelegramService()
    
    if telegram.is_configured():
        print("✅ Telegram configurado!")
        
        # Teste de conexão
        success, msg = await telegram.test_connection()
        print(f"Teste de conexão: {msg}")
        
        # Teste de mensagem customizada
        success, msg = await telegram.send_custom_message("🧪 Teste da função send_custom_message - funcionando!")
        print(f"Mensagem customizada: {msg}")
        
    else:
        print("❌ Telegram não configurado. Configure os Secrets:")
        print("- TELEGRAM_BOT_TOKEN")
        print("- TELEGRAM_CHAT_ID")

if __name__ == "__main__":
    asyncio.run(test_now())
