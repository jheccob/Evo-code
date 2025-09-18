
#!/usr/bin/env python3
"""
Script para testar se a configuração do Telegram está funcionando
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.telegram_service import SecureTelegramService
from database.database import db

def test_config():
    print("🔧 TESTANDO CONFIGURAÇÃO TELEGRAM")
    print("=" * 40)
    
    # Verificar se existem dados no banco
    token = db.get_setting("telegram_token")
    chat_id = db.get_setting("telegram_chat_id")
    enabled = db.get_setting("telegram_enabled")
    
    print(f"Token salvo: {'✅ Sim' if token else '❌ Não'}")
    print(f"Chat ID salvo: {'✅ Sim' if chat_id else '❌ Não'}")
    print(f"Habilitado: {'✅ Sim' if enabled else '❌ Não'}")
    
    if token:
        print(f"Token (primeiros 10 chars): {str(token)[:10]}...")
    if chat_id:
        print(f"Chat ID: {chat_id}")
    
    # Testar serviço
    print("\n🔄 Testando serviço...")
    service = SecureTelegramService()
    
    print(f"Configurado inicialmente: {'✅ Sim' if service.is_configured() else '❌ Não'}")
    
    # Tentar carregar config
    loaded = service.load_config()
    print(f"Carregou configuração: {'✅ Sim' if loaded else '❌ Não'}")
    print(f"Configurado após carregar: {'✅ Sim' if service.is_configured() else '❌ Não'}")
    
    # Status completo
    status = service.get_config_status()
    print("\n📊 Status completo:")
    for key, value in status.items():
        print(f"  {key}: {value}")

if __name__ == '__main__':
    test_config()
