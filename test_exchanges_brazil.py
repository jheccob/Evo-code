
#!/usr/bin/env python3
"""
Teste de exchanges que funcionam no Brasil
"""

import asyncio
from config.exchange_config import ExchangeConfig

async def test_all_exchanges():
    """Testar todos os exchanges suportados"""
    print("🇧🇷 Testando exchanges disponíveis no Brasil...\n")
    
    results = {}
    
    for exchange_name, info in ExchangeConfig.SUPPORTED_EXCHANGES.items():
        print(f"🧪 Testando {info['name']} ({exchange_name})...")
        
        try:
            success, message = ExchangeConfig.test_connection(exchange_name)
            results[exchange_name] = {
                'success': success,
                'message': message,
                'info': info
            }
            
            if success:
                print(f"  ✅ {message}")
                
                # Testar pares USDT
                pairs = ExchangeConfig.get_usdt_pairs(exchange_name)
                print(f"  📊 {len(pairs)} pares USDT disponíveis")
                print(f"  💰 Exemplos: {', '.join(pairs[:5])}")
                
            else:
                print(f"  ❌ {message}")
                
        except Exception as e:
            print(f"  💥 Erro: {str(e)}")
            results[exchange_name] = {
                'success': False,
                'message': f"Erro: {str(e)}",
                'info': info
            }
        
        print()
    
    # Resumo
    print("=" * 60)
    print("📋 RESUMO DOS TESTES")
    print("=" * 60)
    
    working_exchanges = []
    failed_exchanges = []
    
    for exchange_name, result in results.items():
        if result['success']:
            working_exchanges.append(exchange_name)
            print(f"✅ {result['info']['name']}: FUNCIONANDO")
        else:
            failed_exchanges.append(exchange_name)
            print(f"❌ {result['info']['name']}: FALHOU")
    
    print(f"\n🎯 RECOMENDAÇÃO PARA O BRASIL:")
    if working_exchanges:
        recommended = working_exchanges[0]
        print(f"   Use: {ExchangeConfig.SUPPORTED_EXCHANGES[recommended]['name']} ({recommended})")
        print(f"   Motivo: {ExchangeConfig.SUPPORTED_EXCHANGES[recommended]['description']}")
    else:
        print("   ⚠️ Nenhum exchange funcionando. Verifique sua conexão.")
    
    print(f"\n📈 {len(working_exchanges)} de {len(results)} exchanges funcionando")
    
    return results

if __name__ == "__main__":
    asyncio.run(test_all_exchanges())
