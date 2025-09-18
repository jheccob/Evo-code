
#!/usr/bin/env python3
"""
Teste rápido do Telegram
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.telegram_service import SecureTelegramService
from database.database import db

async def test_telegram():
    print("🧪 TESTE DO TELEGRAM")
    print("=" * 30)
    
    # Verificar configuração no banco
    token = db.get_setting("telegram_token")
    chat_id = db.get_setting("telegram_chat_id") 
    enabled = db.get_setting("telegram_enabled")
    
    print(f"Token configurado: {'✅' if token else '❌'}")
    print(f"Chat ID configurado: {'✅' if chat_id else '❌'}")
    print(f"Telegram habilitado: {'✅' if enabled else '❌'}")
    
    if not token or not chat_id:
        print("\n❌ Configure o Telegram primeiro no dashboard!")
        return
    
    # Testar serviço
    service = SecureTelegramService()
    
    if service.is_configured():
        print("\n✅ Serviço configurado!")
        
        # Teste de conexão
        print("🔄 Testando conexão...")
        try:
            success, msg = await service.test_connection()
            if success:
                print(f"✅ {msg}")
            else:
                print(f"❌ {msg}")
                return
        except Exception as e:
            print(f"❌ Erro na conexão: {e}")
            return
        
        # Teste de sinal
        print("🔄 Testando envio de sinal...")
        try:
            success, msg = await service.send_signal_alert(
                symbol="BTC-USD",
                signal="COMPRA",
                price=50000.00,
                rsi=25.5,
                macd=150.5,
                macd_signal=120.3,
                timeframe="1h"
            )
            if success:
                print(f"✅ Sinal enviado: {msg}")
            else:
                print(f"❌ Erro no sinal: {msg}")
        except Exception as e:
            print(f"❌ Erro ao enviar sinal: {e}")
    
    else:
        print("\n❌ Serviço não configurado!")

if __name__ == '__main__':
    asyncio.run(test_telegram())
