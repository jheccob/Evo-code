
#!/usr/bin/env python3
"""
Script para testar envio de mensagem no Telegram
"""

import asyncio
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from telegram import Bot
    from telegram.error import TelegramError
    TELEGRAM_AVAILABLE = True
    print("✅ Biblioteca telegram instalada com sucesso")
except ImportError as e:
    TELEGRAM_AVAILABLE = False
    print(f"❌ Erro ao importar telegram: {e}")

async def test_telegram_message():
    """Teste básico de envio de mensagem"""
    if not TELEGRAM_AVAILABLE:
        print("❌ Biblioteca python-telegram-bot não está disponível")
        return False
    
    # Suas credenciais
    BOT_TOKEN = "8454268048:AAFSiHU963ch55L5EhLSrpwdRtKBtPSO_0A"
    CHAT_ID = "2081890738"
    
    try:
        # Criar bot
        bot = Bot(token=BOT_TOKEN)
        
        # Testar conexão
        print("🔄 Testando conexão com Telegram...")
        me = await bot.get_me()
        print(f"✅ Bot conectado: @{me.username}")
        
        # Enviar mensagem de teste
        test_message = f"""
🤖 **Teste de Conexão**

✅ Bot funcionando perfeitamente!
⏰ {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

🎯 Seu bot está pronto para uso!
"""
        
        print("📤 Enviando mensagem de teste...")
        await bot.send_message(
            chat_id=CHAT_ID,
            text=test_message,
            parse_mode='Markdown'
        )
        
        print("✅ Mensagem enviada com sucesso!")
        return True
        
    except TelegramError as e:
        print(f"❌ Erro do Telegram: {e}")
        return False
    except Exception as e:
        print(f"❌ Erro geral: {e}")
        return False

def main():
    """Função principal"""
    print("🚀 Iniciando teste do Telegram Bot...")
    
    # Executar teste
    try:
        result = asyncio.run(test_telegram_message())
        if result:
            print("\n🎉 SUCESSO! Verificque seu Telegram para ver a mensagem.")
        else:
            print("\n💥 FALHA! Verifique as credenciais e tente novamente.")
    except Exception as e:
        print(f"\n💥 Erro na execução: {e}")

if __name__ == "__main__":
    main()
