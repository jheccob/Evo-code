
#!/usr/bin/env python3
"""
Teste completo do bot Telegram após configurar os Secrets
"""

import asyncio
import logging
import os
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """Função principal de teste"""
    print("🧪 Teste Completo do Bot Telegram")
    print("=" * 50)
    
    # 1. Verificar Secrets
    print("\n1️⃣ Verificando Secrets...")
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if token:
        masked_token = token[:10] + "..." + token[-10:] if len(token) > 20 else "***"
        print(f"✅ TELEGRAM_BOT_TOKEN: {masked_token}")
    else:
        print("❌ TELEGRAM_BOT_TOKEN: Não configurado")
        return False
    
    if chat_id:
        print(f"✅ TELEGRAM_CHAT_ID: {chat_id}")
    else:
        print("❌ TELEGRAM_CHAT_ID: Não configurado")
        return False
    
    # 2. Verificar biblioteca
    print("\n2️⃣ Verificando biblioteca...")
    try:
        from telegram import Bot
        print("✅ python-telegram-bot: Importado com sucesso")
    except ImportError as e:
        print(f"❌ Erro ao importar: {e}")
        return False
    
    # 3. Testar conexão do bot
    print("\n3️⃣ Testando conexão...")
    try:
        bot = Bot(token=token)
        me = await bot.get_me()
        print(f"✅ Bot conectado: @{me.username} ({me.first_name})")
    except Exception as e:
        print(f"❌ Erro na conexão: {e}")
        return False
    
    # 4. Enviar mensagem de teste
    print("\n4️⃣ Enviando mensagem de teste...")
    try:
        test_message = f"""🧪 *Teste do Bot - {datetime.now().strftime('%H:%M:%S')}*

✅ *Status:* Bot funcionando perfeitamente!
🤖 *Bot:* @{me.username}
💬 *Chat:* {chat_id}
📅 *Data:* {datetime.now().strftime('%d/%m/%Y')}

🎯 *Próximos passos:*
• Use /start para começar
• Use /help para ver comandos
• Use /analise BTC/USDT para análise

🚀 *Bot está pronto para uso!*"""
        
        await bot.send_message(
            chat_id=chat_id,
            text=test_message,
            parse_mode='Markdown'
        )
        
        print("✅ Mensagem de teste enviada com sucesso!")
        print("📱 Verifique seu Telegram!")
        
    except Exception as e:
        print(f"❌ Erro ao enviar mensagem: {e}")
        return False
    
    # 5. Testar bot integrado
    print("\n5️⃣ Testando bot integrado...")
    try:
        from telegram_bot import TelegramTradingBot
        
        trading_bot = TelegramTradingBot()
        
        if trading_bot.is_configured():
            print("✅ TelegramTradingBot configurado corretamente")
            
            # Teste de conexão
            success, message = await trading_bot.test_connection()
            if success:
                print(f"✅ Teste de conexão: {message}")
            else:
                print(f"❌ Erro no teste: {message}")
                
        else:
            print("❌ TelegramTradingBot não configurado")
            
    except Exception as e:
        print(f"❌ Erro no bot integrado: {e}")
    
    print("\n🎉 Teste concluído!")
    print("💡 Se tudo funcionou, o bot está pronto para uso!")
    
    return True

if __name__ == "__main__":
    asyncio.run(main())
