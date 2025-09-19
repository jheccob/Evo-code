
#!/usr/bin/env python3
"""
Script para verificar se os Secrets estão configurados
"""

import os

def check_secrets():
    print("🔍 Verificando Secrets do Replit...\n")
    
    # Verificar TELEGRAM_BOT_TOKEN
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if bot_token:
        # Ocultar a maior parte do token por segurança
        masked_token = bot_token[:10] + "..." + bot_token[-10:] if len(bot_token) > 20 else "***"
        print(f"✅ TELEGRAM_BOT_TOKEN: {masked_token}")
    else:
        print("❌ TELEGRAM_BOT_TOKEN: Não configurado")
    
    # Verificar TELEGRAM_CHAT_ID  
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if chat_id:
        print(f"✅ TELEGRAM_CHAT_ID: {chat_id}")
    else:
        print("❌ TELEGRAM_CHAT_ID: Não configurado")
    
    print(f"\n📊 Total de variáveis de ambiente: {len(os.environ)}")
    
    # Verificar se a biblioteca está instalada
    try:
        import telegram
        print("✅ python-telegram-bot: Instalado")
    except ImportError:
        print("❌ python-telegram-bot: Não instalado")
    
    print("\n💡 Para configurar os Secrets:")
    print("1. Clique no ícone 🔒 na sidebar esquerda (Secrets)")
    print("2. Adicione TELEGRAM_BOT_TOKEN com o token do @BotFather")
    print("3. Adicione TELEGRAM_CHAT_ID com seu ID do chat")

if __name__ == "__main__":
    check_secrets()
