
#!/usr/bin/env python3
"""
Teste simples do Telegram para debug
"""

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_telegram_credentials():
    """Teste direto das credenciais do Telegram"""
    
    # Solicitar credenciais diretamente
    print("🔧 TESTE DE CONEXÃO TELEGRAM")
    print("=" * 40)
    
    bot_token = input("📱 Cole seu Bot Token: ").strip()
    chat_id = input("💬 Cole seu Chat ID: ").strip()
    
    if not bot_token or not chat_id:
        print("❌ Erro: Token e Chat ID são obrigatórios!")
        return False
    
    print("\n🔄 Testando conexão...")
    
    try:
        from telegram import Bot
        
        # Criar bot
        bot = Bot(token=bot_token)
        
        # Testar conexão básica
        print("1️⃣ Testando autenticação do bot...")
        me = await bot.get_me()
        print(f"✅ Bot conectado: @{me.username}")
        print(f"📝 Nome: {me.first_name}")
        print(f"🆔 ID: {me.id}")
        
        # Testar envio de mensagem
        print("\n2️⃣ Testando envio de mensagem...")
        
        test_message = f"""
🤖 **TESTE DE CONEXÃO**

✅ Bot funcionando perfeitamente!
🕒 Teste realizado com sucesso!

**Detalhes do Bot:**
• Nome: {me.first_name}
• Username: @{me.username}
• ID: {me.id}

**Chat ID de destino:** `{chat_id}`
"""
        
        await bot.send_message(
            chat_id=chat_id,
            text=test_message,
            parse_mode='Markdown'
        )
        
        print("✅ Mensagem enviada com sucesso!")
        print(f"📱 Verifique seu Telegram (Chat ID: {chat_id})")
        
        # Salvar configuração funcionando
        print("\n3️⃣ Salvando configuração...")
        
        try:
            from database.database import db
            db.save_setting("telegram_token", bot_token)
            db.save_setting("telegram_chat_id", chat_id)
            db.save_setting("telegram_enabled", True)
            print("✅ Configuração salva no banco de dados!")
        except Exception as e:
            print(f"⚠️ Aviso: Erro ao salvar no banco: {e}")
        
        print("\n🎉 TESTE CONCLUÍDO COM SUCESSO!")
        print("=" * 40)
        print("💡 Agora você pode usar o Telegram no app principal!")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERRO NO TESTE:")
        print(f"   {str(e)}")
        print("\n🔍 POSSÍVEIS CAUSAS:")
        print("   1. Token do bot incorreto")
        print("   2. Chat ID incorreto")
        print("   3. Bot não foi iniciado com /start")
        print("   4. Bot foi bloqueado ou removido")
        print("\n📖 COMO CORRIGIR:")
        print("   1. Verifique o token no @BotFather")
        print("   2. Confirme o Chat ID com @userinfobot")
        print("   3. Envie /start para seu bot")
        
        return False

if __name__ == '__main__':
    try:
        result = asyncio.run(test_telegram_credentials())
        if not result:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⏹️ Teste cancelado pelo usuário")
    except Exception as e:
        print(f"\n💥 Erro inesperado: {e}")
        sys.exit(1)
