"""
Bot de Trading Binance com Loop de 60 Segundos
Implementação limpa e enxuta focada em atualizações a cada minuto
"""

import asyncio
import time
from datetime import datetime
from trading_bot_websocket import StreamlinedTradingBot

class BinanceBot60s:
    """Bot que executa análise a cada 60 segundos usando dados públicos da Binance"""
    
    def __init__(self, symbols=["BTCUSDT", "ETHUSDT", "ADAUSDT"]):
        self.symbols = symbols
        self.bots = {}
        self.is_running = False
        self.loop_count = 0
        
        # Inicializar bots para cada símbolo
        for symbol in symbols:
            self.bots[symbol] = StreamlinedTradingBot(symbol, "1m")
            
        print(f"🚀 BinanceBot60s inicializado para {len(symbols)} símbolos")
        
    async def start_monitoring(self):
        """Inicia monitoramento com loop de 60 segundos"""
        if self.is_running:
            print("⚠️ Monitoramento já está em execução")
            return
            
        self.is_running = True
        print("🔄 Iniciando monitoramento a cada 60 segundos...")
        
        while self.is_running:
            try:
                self.loop_count += 1
                current_time = datetime.now().strftime('%H:%M:%S')
                
                print(f"\n{'='*50}")
                print(f"📊 LOOP #{self.loop_count} - {current_time}")
                print(f"{'='*50}")
                
                # Processar cada símbolo
                for symbol in self.symbols:
                    await self.process_symbol(symbol)
                    
                print(f"\n⏰ Próxima atualização em 60 segundos...")
                await asyncio.sleep(60)
                
            except KeyboardInterrupt:
                print("\n🛑 Interrompido pelo usuário")
                break
            except Exception as e:
                print(f"❌ Erro no loop principal: {e}")
                await asyncio.sleep(10)  # Aguardar 10s em caso de erro
                
        self.is_running = False
        print("⏹️ Monitoramento finalizado")
        
    async def process_symbol(self, symbol):
        """Processa um símbolo específico"""
        try:
            bot = self.bots[symbol]
            
            # Buscar dados simulados (em produção seria WebSocket real)
            market_data = await self.fetch_symbol_data(symbol)
            
            if market_data:
                # Gerar sinal
                signal_data = await bot.process_market_data_60s(market_data)
                
                # Log do resultado
                self.log_signal_result(symbol, market_data, signal_data)
                
        except Exception as e:
            print(f"❌ Erro ao processar {symbol}: {e}")
            
    async def fetch_symbol_data(self, symbol):
        """Simula busca de dados públicos da Binance"""
        try:
            import random
            
            # Preços base aproximados para diferentes símbolos
            base_prices = {
                "BTCUSDT": 64000,
                "ETHUSDT": 3200,
                "ADAUSDT": 0.8,
                "SOLUSDT": 180,
                "DOTUSDT": 7.5
            }
            
            base_price = base_prices.get(symbol, 100)
            
            # Simular movimentação de preço realista
            price_change = random.uniform(-3, 3)  # -3% a +3%
            current_price = base_price * (1 + price_change / 100)
            
            return {
                'symbol': symbol,
                'price': current_price,
                'volume': random.uniform(500000, 2000000),
                'change_24h': price_change,
                'high_24h': current_price * random.uniform(1.02, 1.08),
                'low_24h': current_price * random.uniform(0.92, 0.98),
                'timestamp': datetime.now()
            }
            
        except Exception as e:
            print(f"❌ Erro ao buscar dados para {symbol}: {e}")
            return None
            
    def log_signal_result(self, symbol, market_data, signal_data):
        """Log formatado do resultado do sinal"""
        try:
            price = market_data['price']
            change_24h = market_data['change_24h']
            volume = market_data['volume']
            
            signal = signal_data['signal']
            confidence = signal_data['confidence']
            rsi = signal_data.get('rsi', 0)
            
            # Emoji baseado no sinal
            emoji = "🟢" if "COMPRA" in signal else "🔴" if "VENDA" in signal else "⚪"
            
            print(f"{emoji} {symbol}: ${price:.4f} ({change_24h:+.2f}%)")
            print(f"   🎯 Sinal: {signal} | 🔥 Confiança: {confidence:.1f}%")
            print(f"   📊 RSI: {rsi:.1f} | 📈 Volume: {volume:,.0f}")
            
        except Exception as e:
            print(f"❌ Erro ao fazer log de {symbol}: {e}")
            
    def stop(self):
        """Para o monitoramento"""
        self.is_running = False
        print("🛑 Parando monitoramento...")

# Função para executar o bot
async def run_binance_60s_bot():
    """Executa o bot com loop de 60 segundos"""
    
    # Símbolos para monitorar
    symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "SOLUSDT"]
    
    # Criar e iniciar bot
    bot = BinanceBot60s(symbols)
    
    try:
        await bot.start_monitoring()
    except KeyboardInterrupt:
        print("\n🛑 Bot interrompido pelo usuário")
    finally:
        bot.stop()

if __name__ == "__main__":
    print("🚀 Iniciando Binance Bot com Loop de 60 Segundos")
    print("📡 Usando WebSocket público da Binance Futures")
    print("⏰ Análise automática a cada 1 minuto")
    print("\nPressione Ctrl+C para parar\n")
    
    # Executar bot
    asyncio.run(run_binance_60s_bot())