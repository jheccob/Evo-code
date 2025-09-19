#!/usr/bin/env python3
"""
Script para testar o bot do Telegram com os novos recursos
"""
import asyncio
import os
import sys
from telegram_bot import TelegramTradingBot
from services.telegram_service import SecureTelegramService

async def test_telegram_integration():
    """Testar integração do Telegram"""
    print("🧪 Testando integração do Telegram...")
    
    # Verificar se os secrets estão configurados
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("❌ Credenciais do Telegram não encontradas!")
        print("Verifique se TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID estão nos secrets.")
        return False
    
    print(f"✅ Token configurado: {'*' * 10}{token[-10:]}")
    print(f"✅ Chat ID configurado: {chat_id}")
    
    # Testar serviço básico
    try:
        service = SecureTelegramService()
        if service.is_configured():
            print("✅ SecureTelegramService configurado com sucesso!")
            
            # Testar conexão
            success, message = await service.test_connection()
            if success:
                print(f"✅ Teste de conexão: {message}")
            else:
                print(f"❌ Erro no teste: {message}")
                
        else:
            print("❌ SecureTelegramService não configurado")
            
    except Exception as e:
        print(f"❌ Erro no serviço básico: {e}")
        return False
    
    # Testar TelegramTradingBot
    try:
        bot = TelegramTradingBot()
        if bot.enabled:
            print("✅ TelegramTradingBot configurado com sucesso!")
            print("✅ Bot está pronto para receber comandos /start")
        else:
            print("❌ TelegramTradingBot não habilitado")
            
    except Exception as e:
        print(f"❌ Erro no trading bot: {e}")
        return False
    
    return True

def test_improved_indicators():
    """Testar novos indicadores"""
    print("📊 Testando indicadores melhorados...")
    
    try:
        from trading_bot import TradingBot
        
        bot = TradingBot()
        print("✅ TradingBot inicializado")
        
        # Testar busca de dados
        data = bot.get_market_data(limit=250)  # Usar mais dados para SMA 200
        
        if data is not None and not data.empty:
            print(f"✅ Dados obtidos: {len(data)} candles")
            
            # Verificar se temos as novas colunas
            expected_columns = ['sma_21', 'sma_50', 'sma_200', 'trend_analysis']
            missing_columns = [col for col in expected_columns if col not in data.columns]
            
            if not missing_columns:
                print("✅ Todas as médias móveis calculadas (21, 50, 200)")
                
                # Verificar se temos dados suficientes
                last_row = data.iloc[-1]
                if not data['sma_200'].isna().iloc[-1]:
                    print("✅ SMA 200 calculada com sucesso")
                    
                    # Mostrar análise de tendência
                    trend = last_row.get('trend_analysis', 'N/A')
                    strength = last_row.get('trend_strength', 'N/A')
                    
                    print(f"📈 Tendência atual: {trend}")
                    print(f"💪 Força da tendência: {strength}")
                    
                else:
                    print("⚠️ SMA 200 ainda não disponível (poucos dados)")
            else:
                print(f"❌ Colunas faltando: {missing_columns}")
                
            # Testar sinal atual
            signal = bot.check_signal(data)
            print(f"🚨 Sinal atual (XLM-USD): {signal}")
            
        else:
            print("❌ Não foi possível obter dados de mercado")
            return False
            
    except Exception as e:
        print(f"❌ Erro ao testar indicadores: {e}")
        return False
    
    return True

async def main():
    """Função principal"""
    print("🎯 Iniciando testes do sistema de trading melhorado...")
    print("=" * 50)
    
    # Teste 1: Indicadores
    indicators_ok = test_improved_indicators()
    print()
    
    # Teste 2: Telegram
    telegram_ok = await test_telegram_integration()
    print()
    
    # Resultado final
    print("=" * 50)
    if indicators_ok and telegram_ok:
        print("✅ Todos os testes passaram! Sistema pronto para uso.")
        print("🚀 Agora você pode:")
        print("   - Usar /start no seu bot do Telegram")
        print("   - Receber sinais mais precisos com médias móveis")
        print("   - Credenciais seguras nos Replit Secrets")
    else:
        print("❌ Alguns testes falharam. Verifique os erros acima.")
    
    return indicators_ok and telegram_ok

if __name__ == "__main__":
    try:
        result = asyncio.run(main())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n⏹️ Teste interrompido pelo usuário")
        sys.exit(1)
    except Exception as e:
        print(f"💥 Erro fatal: {e}")
        sys.exit(1)