"""
TradingBot otimizado com integração WebSocket Binance Futures
Versão limpa e enxuta focada em performance e dados em tempo real
"""

import asyncio
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Optional
from binance_websocket import BinanceFuturesWebSocket, RealTimeDataManager
from indicators import TechnicalIndicators
import os

class StreamlinedTradingBot:
    """
    TradingBot otimizado para Binance Futures WebSocket
    Focado em performance e simplicidade
    """
    
    def __init__(self, symbol: str = "BTCUSDT", timeframe: str = "5m"):
        self.symbol = symbol.replace('/', '')  # Formato Binance (BTCUSDT)
        self.timeframe = timeframe
        
        # WebSocket client e data manager
        self.ws_client = BinanceFuturesWebSocket()
        self.data_manager = RealTimeDataManager(max_candles=200)
        
        # Indicadores técnicos
        self.indicators = TechnicalIndicators()
        
        # Configurações de trading
        self.rsi_period = 14
        self.rsi_oversold = 25
        self.rsi_overbought = 75
        
        # Estado atual
        self.current_data = None
        self.current_signal = "NEUTRO"
        self.last_price = 0.0
        self.is_running = False
        self._last_signal = "NEUTRO"  # Para rastreamento de mudanças
        
        print(f"🚀 StreamlinedTradingBot inicializado para {self.symbol} ({self.timeframe})")
        
    async def start_real_time_analysis(self):
        """Inicia análise em tempo real com WebSocket"""
        if self.is_running:
            print("⚠️ Bot já está em execução")
            return
            
        self.is_running = True
        print(f"🔄 Iniciando análise em tempo real para {self.symbol}...")
        
        # Callback para processar dados de kline
        async def process_market_data(kline_data):
            try:
                # Atualizar dados
                await self.data_manager.process_kline_update(kline_data)
                
                # Obter DataFrame atualizado
                df = self.data_manager.get_latest_data(self.symbol)
                
                if df is not None and len(df) >= 20:  # Mínimo para cálculos
                    # Calcular indicadores
                    df_with_indicators = self.calculate_indicators(df.copy())
                    self.current_data = df_with_indicators
                    
                    # Gerar sinal
                    signal_data = self.generate_optimized_signal(df_with_indicators)
                    
                    # Atualizar estado
                    self.current_signal = signal_data['signal']
                    self.last_price = kline_data['close']
                    
                    # Log apenas mudanças de sinal
                    if hasattr(self, '_last_signal') and self._last_signal != self.current_signal:
                        print(f"🎯 {self.symbol}: {self.current_signal} @ ${self.last_price:.4f}")
                        print(f"   RSI: {signal_data.get('rsi', 0):.1f} | Confiança: {signal_data.get('confidence', 0):.1f}%")
                    
                    self._last_signal = self.current_signal
                    
            except Exception as e:
                print(f"❌ Erro ao processar dados: {e}")
        
        try:
            # Conectar ao stream de klines
            await self.ws_client.connect_kline_stream(
                self.symbol, 
                self.timeframe, 
                process_market_data
            )
        except Exception as e:
            print(f"❌ Erro na conexão WebSocket: {e}")
            self.is_running = False
            
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcula indicadores técnicos essenciais"""
        try:
            # RSI
            df['rsi'] = self.indicators.calculate_rsi(df['close'], self.rsi_period)
            
            # MACD
            macd_data = self.indicators.calculate_macd(df['close'])
            df['macd'] = macd_data['macd']
            df['macd_signal'] = macd_data['signal']
            df['macd_histogram'] = macd_data['histogram']
            
            # Médias móveis
            df['sma_20'] = df['close'].rolling(window=20).mean()
            df['ema_12'] = df['close'].ewm(span=12).mean()
            df['ema_26'] = df['close'].ewm(span=26).mean()
            
            # Bollinger Bands
            bb_data = self.indicators.calculate_bollinger_bands(df['close'])
            df['bb_upper'] = bb_data['upper']
            df['bb_middle'] = bb_data['middle']
            df['bb_lower'] = bb_data['lower']
            
            # Volume MA
            df['volume_ma'] = df['volume'].rolling(window=20).mean()
            
            return df
            
        except Exception as e:
            print(f"❌ Erro ao calcular indicadores: {e}")
            return df
            
    def generate_optimized_signal(self, df: pd.DataFrame) -> Dict:
        """
        Gera sinal otimizado baseado em múltiplos indicadores
        Foco em precisão e redução de falsos sinais
        """
        if df is None or len(df) < 2:
            return {"signal": "NEUTRO", "confidence": 0}
            
        try:
            current = df.iloc[-1]
            previous = df.iloc[-2]
            
            # Indicadores atuais
            rsi = current['rsi']
            macd = current['macd']
            macd_signal = current['macd_signal']
            price = current['close']
            volume = current['volume']
            volume_ma = current['volume_ma']
            
            # Inicializar score de sinal
            buy_score = 0
            sell_score = 0
            confidence = 0
            
            # 1. Análise RSI (peso: 30%)
            if rsi < self.rsi_oversold:
                buy_score += 30
                confidence += 25
            elif rsi > self.rsi_overbought:
                sell_score += 30
                confidence += 25
            
            # 2. Análise MACD (peso: 25%)
            if macd > macd_signal and previous['macd'] <= previous['macd_signal']:
                buy_score += 25  # MACD bullish crossover
                confidence += 20
            elif macd < macd_signal and previous['macd'] >= previous['macd_signal']:
                sell_score += 25  # MACD bearish crossover
                confidence += 20
                
            # 3. Análise de Volume (peso: 20%)
            if volume > volume_ma * 1.5:  # Volume alto
                confidence += 15
                if buy_score > sell_score:
                    buy_score += 10
                else:
                    sell_score += 10
                    
            # 4. Análise de Tendência com EMAs (peso: 15%)
            ema_12 = current['ema_12']
            ema_26 = current['ema_26']
            
            if ema_12 > ema_26 and previous['ema_12'] <= previous['ema_26']:
                buy_score += 15  # Golden cross
                confidence += 10
            elif ema_12 < ema_26 and previous['ema_12'] >= previous['ema_26']:
                sell_score += 15  # Death cross
                confidence += 10
                
            # 5. Bollinger Bands (peso: 10%)
            bb_upper = current['bb_upper']
            bb_lower = current['bb_lower']
            
            if price <= bb_lower:
                buy_score += 10  # Oversold
                confidence += 5
            elif price >= bb_upper:
                sell_score += 10  # Overbought
                confidence += 5
                
            # Determinar sinal final
            if buy_score > sell_score and buy_score >= 40:
                if buy_score >= 60:
                    signal = "COMPRA"
                else:
                    signal = "COMPRA_FRACA"
            elif sell_score > buy_score and sell_score >= 40:
                if sell_score >= 60:
                    signal = "VENDA"
                else:
                    signal = "VENDA_FRACA"
            else:
                signal = "NEUTRO"
                
            # Ajustar confiança baseada na força do sinal
            if signal in ["COMPRA", "VENDA"]:
                confidence = min(confidence + 10, 95)
            elif signal in ["COMPRA_FRACA", "VENDA_FRACA"]:
                confidence = min(confidence, 75)
            else:
                confidence = max(confidence - 20, 10)
                
            return {
                "signal": signal,
                "confidence": confidence,
                "rsi": rsi,
                "macd": macd,
                "macd_signal": macd_signal,
                "price": price,
                "volume_ratio": volume / volume_ma if volume_ma > 0 else 1,
                "buy_score": buy_score,
                "sell_score": sell_score,
                "timestamp": datetime.now()
            }
            
        except Exception as e:
            print(f"❌ Erro ao gerar sinal: {e}")
            return {"signal": "NEUTRO", "confidence": 0}
            
    def get_current_status(self) -> Dict:
        """Retorna status atual do bot"""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "is_running": self.is_running,
            "current_signal": self.current_signal,
            "last_price": self.last_price,
            "data_available": self.current_data is not None,
            "total_candles": len(self.current_data) if self.current_data is not None else 0
        }
        
    def stop(self):
        """Para a análise em tempo real"""
        self.is_running = False
        print(f"⏹️  Análise em tempo real parada para {self.symbol}")
        
    async def get_multi_symbol_data(self, symbols: list, callback):
        """
        Monitora múltiplos símbolos simultaneamente
        
        Args:
            symbols: Lista de símbolos (ex: ['BTCUSDT', 'ETHUSDT'])
            callback: Função para processar dados de qualquer símbolo
        """
        streams = []
        for symbol in symbols:
            streams.append(f"{symbol.lower()}@kline_{self.timeframe}")
            
        print(f"🔗 Monitorando {len(symbols)} símbolos: {', '.join(symbols)}")
        
        async def multi_callback(data):
            symbol = data['symbol']
            await self.data_manager.process_kline_update(data)
            
            # Gerar sinal para este símbolo
            df = self.data_manager.get_latest_data(symbol)
            if df is not None and len(df) >= 20:
                df_with_indicators = self.calculate_indicators(df.copy())
                signal_data = self.generate_optimized_signal(df_with_indicators)
                signal_data['symbol'] = symbol
                
                await callback(signal_data)
                
        await self.ws_client.connect_multi_stream(streams, multi_callback)

# Função utilitária para executar bot
async def run_streamlined_bot(symbol: str = "BTCUSDT", timeframe: str = "5m"):
    """Executa o bot otimizado"""
    bot = StreamlinedTradingBot(symbol, timeframe)
    
    try:
        await bot.start_real_time_analysis()
    except KeyboardInterrupt:
        print("\n🛑 Interrompido pelo usuário")
    finally:
        bot.stop()

if __name__ == "__main__":
    # Executar bot para BTCUSDT 5m
    asyncio.run(run_streamlined_bot("BTCUSDT", "5m"))