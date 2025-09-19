
#!/usr/bin/env python3
"""
Diagnóstico completo do ambiente Telegram
"""

import sys
import os
import subprocess

print("🔍 DIAGNÓSTICO COMPLETO DO TELEGRAM")
print("=" * 50)

# 1. Verificar Python
print(f"\n1️⃣ Python: {sys.version}")

# 2. Verificar pip
try:
    import pip
    print(f"✅ pip disponível")
except:
    print("❌ pip não disponível")

# 3. Listar pacotes telegram instalados
print("\n2️⃣ Pacotes telegram instalados:")
try:
    result = subprocess.run([sys.executable, "-m", "pip", "list"], 
                          capture_output=True, text=True)
    lines = result.stdout.split('\n')
    telegram_packages = [line for line in lines if 'telegram' in line.lower()]
    
    if telegram_packages:
        for pkg in telegram_packages:
            print(f"📦 {pkg}")
    else:
        print("❌ Nenhum pacote telegram encontrado")
except Exception as e:
    print(f"❌ Erro ao listar pacotes: {e}")

# 4. Tentar importar telegram
print("\n3️⃣ Teste de importação:")
try:
    import telegram
    print(f"✅ telegram v{telegram.__version__} importado")
    
    from telegram import Bot
    print("✅ Bot importado")
    
    from telegram.ext import Application
    print("✅ Application importado")
    
except ImportError as e:
    print(f"❌ Erro ao importar: {e}")

# 5. Verificar secrets
print("\n4️⃣ Secrets do Replit:")
token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

if token:
    masked = token[:10] + "..." + token[-10:] if len(token) > 20 else "***"
    print(f"✅ TELEGRAM_BOT_TOKEN: {masked}")
else:
    print("❌ TELEGRAM_BOT_TOKEN não configurado")

if chat_id:
    print(f"✅ TELEGRAM_CHAT_ID: {chat_id}")
else:
    print("❌ TELEGRAM_CHAT_ID não configurado")

# 6. Sugestões
print("\n5️⃣ Próximos passos:")
if not token or not chat_id:
    print("🔧 Configure os Replit Secrets primeiro")

print("🚀 Execute: python diagnose_telegram.py")
print("📱 Se tudo OK, execute: python test_telegram_complete.py")
