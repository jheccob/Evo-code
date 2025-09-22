
#!/usr/bin/env python3
"""
Script de teste de conexão com exchanges
"""

import ccxt
import asyncio
from config.exchange_config import ExchangeConfig

def test_exchange_connection():
    """Testar conexão básica com exchanges"""
    print("🔍 Testando conexão com exchanges...")
    
    for exchange_name in ['bybit', 'okx', 'kucoin']:
        try:
            print(f"\n📊 Testando {exchange_name}...")
            
            # Configurar exchange
            exchange = ExchangeConfig.get_exchange_instance(exchange_name, testnet=False)
            
            # Teste básico de conectividade
            print(f"   ⏳ Carregando mercados...")
            markets = exchange.load_markets()
            print(f"   ✅ {len(markets)} mercados carregados")
            
            # Teste de ticker
            print(f"   ⏳ Buscando ticker BTC/USDT...")
            ticker = exchange.fetch_ticker('BTC/USDT')
            print(f"   ✅ BTC/USDT: ${ticker['last']:.2f}")
            
            # Teste de dados OHLCV
            print(f"   ⏳ Buscando dados OHLCV...")
            ohlcv = exchange.fetch_ohlcv('BTC/USDT', '5m', limit=10)
            print(f"   ✅ {len(ohlcv)} candles recebidos")
            
            print(f"   🎉 {exchange_name} funcionando perfeitamente!")
            
        except ccxt.NetworkError as e:
            print(f"   ❌ Erro de rede com {exchange_name}: {str(e)}")
        except ccxt.ExchangeError as e:
            print(f"   ❌ Erro do exchange {exchange_name}: {str(e)}")
        except Exception as e:
            print(f"   💥 Erro inesperado com {exchange_name}: {str(e)}")
    
    print(f"\n🏁 Teste de conexão concluído!")

if __name__ == "__main__":
    test_exchange_connection()
