
#!/usr/bin/env python3
"""
Script para testar configuração da Binance
"""

import os
import sys

def test_binance_credentials():
    print("🔍 Verificando credenciais da Binance...\n")
    
    # Verificar variáveis de ambiente
    api_key = os.getenv('BINANCE_API_KEY')
    secret = os.getenv('BINANCE_SECRET')
    
    if not api_key:
        print("❌ BINANCE_API_KEY não encontrada")
        print("💡 Configure nos Replit Secrets: BINANCE_API_KEY")
        return False
    else:
        masked_key = api_key[:8] + "..." + api_key[-8:] if len(api_key) > 16 else "***"
        print(f"✅ BINANCE_API_KEY: {masked_key}")
    
    if not secret:
        print("❌ BINANCE_SECRET não encontrada")
        print("💡 Configure nos Replit Secrets: BINANCE_SECRET")
        return False
    else:
        masked_secret = secret[:8] + "..." + secret[-8:] if len(secret) > 16 else "***"
        print(f"✅ BINANCE_SECRET: {masked_secret}")
    
    print()
    return True

def test_binance_connection():
    print("🧪 Testando conexão com a Binance...\n")
    
    try:
        from config.exchange_config import ExchangeConfig
        
        # Testar conexão
        success, message = ExchangeConfig.test_connection('binance')
        
        if success:
            print(f"✅ {message}")
            return True
        else:
            print(f"❌ {message}")
            return False
            
    except Exception as e:
        print(f"❌ Erro ao testar conexão: {e}")
        return False

def test_data_access():
    print("\n📊 Testando acesso aos dados...\n")
    
    try:
        from config.exchange_config import ExchangeConfig
        
        # Criar instância
        exchange = ExchangeConfig.get_exchange_instance('binance')
        
        # Testar mercados
        print("📈 Carregando mercados...")
        markets = exchange.load_markets()
        print(f"✅ {len(markets)} mercados carregados")
        
        # Testar dados de preço
        print("💰 Testando dados de preço BTC/USDT...")
        ticker = exchange.fetch_ticker('BTC/USDT')
        print(f"✅ BTC/USDT: ${ticker['last']:.2f}")
        
        # Testar saldo (se tiver credenciais)
        if exchange.apiKey and exchange.secret:
            print("💼 Testando acesso ao saldo...")
            try:
                balance = exchange.fetch_balance()
                usdt_balance = balance.get('USDT', {}).get('total', 0)
                print(f"✅ Saldo USDT: ${usdt_balance:.2f}")
            except Exception as e:
                print(f"⚠️  Saldo não disponível: {str(e)[:50]}...")
        
        return True
        
    except Exception as e:
        print(f"❌ Erro ao acessar dados: {e}")
        return False

def show_next_steps():
    print("\n" + "="*60)
    print("🚀 PRÓXIMOS PASSOS")
    print("="*60)
    print()
    print("1. ✅ Execute o dashboard: streamlit run app.py")
    print("2. 📊 Selecione 'Binance' na barra lateral")
    print("3. 🧪 Clique em 'Testar Conexão'")
    print("4. 📈 Configure seus pares favoritos")
    print("5. ⚡ Ative notificações Telegram (opcional)")
    print()
    print("🎯 Tudo configurado para usar seus dados reais da Binance!")

if __name__ == "__main__":
    print("🔐 Teste de Configuração da Binance")
    print("="*60)
    
    # Teste 1: Credenciais
    if not test_binance_credentials():
        print("\n❌ Configure suas credenciais primeiro!")
        print("📖 Leia o arquivo BINANCE_SETUP.md para instruções")
        sys.exit(1)
    
    # Teste 2: Conexão
    if not test_binance_connection():
        print("\n❌ Problema na conexão com a Binance")
        sys.exit(1)
    
    # Teste 3: Dados
    if not test_data_access():
        print("\n❌ Problema ao acessar dados")
        sys.exit(1)
    
    # Sucesso!
    show_next_steps()
