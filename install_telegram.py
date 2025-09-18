
#!/usr/bin/env python3
"""
Script para instalar e configurar dependências do Telegram
"""

import subprocess
import sys
import importlib

def install_package(package):
    """Instalar pacote usando pip"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        return True
    except subprocess.CalledProcessError:
        return False

def check_telegram_availability():
    """Verificar se o Telegram está disponível"""
    try:
        import telegram
        print("✅ Biblioteca telegram encontrada")
        return True
    except ImportError:
        print("❌ Biblioteca telegram não encontrada")
        return False

def main():
    print("🔧 INSTALADOR DO TELEGRAM BOT")
    print("=" * 40)
    
    # Verificar se já está instalado
    if check_telegram_availability():
        print("✅ Telegram já está configurado!")
        return
    
    # Tentar instalar
    print("📦 Instalando python-telegram-bot...")
    
    packages = ["python-telegram-bot[all]"]
    
    for package in packages:
        print(f"Installing {package}...")
        if install_package(package):
            print(f"✅ {package} instalado com sucesso!")
        else:
            print(f"❌ Erro ao instalar {package}")
            return False
    
    # Verificar instalação
    print("\n🔍 Verificando instalação...")
    if check_telegram_availability():
        print("🎉 Telegram instalado com sucesso!")
        print("\n💡 Agora você pode:")
        print("   1. Executar: python test_telegram_simple.py")
        print("   2. Configurar seu bot no app principal")
        return True
    else:
        print("❌ Erro na verificação da instalação")
        return False

if __name__ == "__main__":
    main()
