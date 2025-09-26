"""
Demo ao vivo do WebSocket Binance Futures
Exemplo simples de uso do WebSocket público para sinais em tempo real
"""

import asyncio
import streamlit as st
from binance_websocket import BinanceFuturesWebSocket, RealTimeDataManager
from trading_bot_websocket import StreamlinedTradingBot
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

async def demo_websocket_live():
    """Demo ao vivo do WebSocket Binance Futures"""
    
    # Configuração
    symbol = "BTCUSDT"
    timeframe = "1m"  # 1 minuto para demo rápido
    
    # Inicializar WebSocket e bot
    ws_client = BinanceFuturesWebSocket()
    bot = StreamlinedTradingBot(symbol, timeframe)
    
    print(f"🚀 Iniciando demo WebSocket para {symbol} ({timeframe})")
    
    # Callback para processar dados
    async def process_live_data(kline_data):
        print(f"📊 {kline_data['symbol']}: ${kline_data['close']:.4f} "
              f"({kline_data['price_change_percent']:+.2f}%) "
              f"Vol: {kline_data['volume']:.2f}")
        
        # Se o candle estiver fechado, gerar sinal
        if kline_data['is_closed']:
            # Simular dados históricos para análise (em produção seria do data_manager)
            fake_data = pd.DataFrame([{
                'timestamp': kline_data['timestamp'],
                'open': kline_data['open'],
                'high': kline_data['high'],
                'low': kline_data['low'],
                'close': kline_data['close'],
                'volume': kline_data['volume']
            }])
            
            # Gerar sinal básico
            price = kline_data['close']
            change_pct = kline_data['price_change_percent']
            
            if change_pct > 0.5:
                signal = "COMPRA_FRACA"
                confidence = min(abs(change_pct) * 10, 75)
            elif change_pct < -0.5:
                signal = "VENDA_FRACA"  
                confidence = min(abs(change_pct) * 10, 75)
            else:
                signal = "NEUTRO"
                confidence = 30
                
            print(f"🎯 SINAL: {signal} (Confiança: {confidence:.1f}%)")
    
    try:
        # Conectar ao WebSocket
        await ws_client.connect_kline_stream(symbol, timeframe, process_live_data)
    except KeyboardInterrupt:
        print("\n🛑 Demo interrompida pelo usuário")
    except Exception as e:
        print(f"❌ Erro no demo: {e}")

if __name__ == "__main__":
    # Executar demo
    asyncio.run(demo_websocket_live())