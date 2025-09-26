"""
Binance Futures WebSocket Client
Implementação limpa e eficiente para streaming de dados em tempo real
"""

import asyncio
import json
import websockets
import pandas as pd
from datetime import datetime
from typing import Dict, Callable, Optional
import os
import hmac
import hashlib
import time

class BinanceFuturesWebSocket:
    """Cliente WebSocket para Binance Futures com funcionalidades essenciais"""
    
    def __init__(self):
        self.base_url = "wss://fstream.binance.com/ws/"
        # Usar apenas WebSocket público - sem credenciais necessárias
        self.connections = {}
        self.callbacks = {}
        
    async def connect_kline_stream(self, symbol: str, interval: str, callback: Callable):
        """
        Conecta ao stream de klines (candlesticks) em tempo real
        
        Args:
            symbol: Par de trading (ex: 'BTCUSDT')
            interval: Intervalo (1m, 5m, 15m, 1h, etc)
            callback: Função para processar dados recebidos
        """
        stream_name = f"{symbol.lower()}@kline_{interval}"
        url = f"{self.base_url}{stream_name}"
        
        print(f"🔗 Conectando ao stream: {stream_name}")
        
        try:
            async with websockets.connect(url) as websocket:
                self.connections[stream_name] = websocket
                self.callbacks[stream_name] = callback
                
                print(f"✅ Conectado ao stream: {stream_name}")
                
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        if 'k' in data:  # Kline data
                            kline_data = self._process_kline_data(data['k'])
                            await callback(kline_data)
                    except Exception as e:
                        print(f"❌ Erro ao processar mensagem: {e}")
                        
        except Exception as e:
            print(f"❌ Erro na conexão WebSocket: {e}")
            
    async def connect_ticker_stream(self, symbol: str, callback: Callable):
        """
        Conecta ao stream de ticker (preço 24h) em tempo real
        
        Args:
            symbol: Par de trading (ex: 'BTCUSDT')
            callback: Função para processar dados de ticker
        """
        stream_name = f"{symbol.lower()}@ticker"
        url = f"{self.base_url}{stream_name}"
        
        print(f"🔗 Conectando ao ticker stream: {stream_name}")
        
        try:
            async with websockets.connect(url) as websocket:
                self.connections[stream_name] = websocket
                self.callbacks[stream_name] = callback
                
                print(f"✅ Conectado ao ticker stream: {stream_name}")
                
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        ticker_data = self._process_ticker_data(data)
                        await callback(ticker_data)
                    except Exception as e:
                        print(f"❌ Erro ao processar ticker: {e}")
                        
        except Exception as e:
            print(f"❌ Erro na conexão ticker: {e}")
            
    async def connect_multi_stream(self, streams: list, callback: Callable):
        """
        Conecta a múltiplos streams simultâneos
        
        Args:
            streams: Lista de streams (ex: ['btcusdt@kline_5m', 'ethusdt@ticker'])
            callback: Função para processar dados de qualquer stream
        """
        # Criar URL para múltiplos streams
        stream_names = "/".join(streams)
        url = f"wss://fstream.binance.com/stream?streams={stream_names}"
        
        print(f"🔗 Conectando a múltiplos streams: {len(streams)} streams")
        
        try:
            async with websockets.connect(url) as websocket:
                self.connections['multi'] = websocket
                self.callbacks['multi'] = callback
                
                print(f"✅ Conectado a {len(streams)} streams")
                
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        if 'stream' in data and 'data' in data:
                            stream_name = data['stream']
                            stream_data = data['data']
                            
                            # Processar baseado no tipo de stream
                            if '@kline_' in stream_name:
                                processed_data = self._process_kline_data(stream_data['k'])
                                processed_data['stream'] = stream_name
                            elif '@ticker' in stream_name:
                                processed_data = self._process_ticker_data(stream_data)
                                processed_data['stream'] = stream_name
                            else:
                                processed_data = stream_data
                                processed_data['stream'] = stream_name
                                
                            await callback(processed_data)
                    except Exception as e:
                        print(f"❌ Erro ao processar multi-stream: {e}")
                        
        except Exception as e:
            print(f"❌ Erro na conexão multi-stream: {e}")
            
    def _process_kline_data(self, kline: Dict) -> Dict:
        """Processa dados de kline para formato padronizado"""
        return {
            'symbol': kline['s'],
            'open_time': int(kline['t']),
            'close_time': int(kline['T']),
            'open': float(kline['o']),
            'high': float(kline['h']),
            'low': float(kline['l']),
            'close': float(kline['c']),
            'volume': float(kline['v']),
            'trades': int(kline['n']),
            'is_closed': kline['x'],  # True se este kline está fechado
            'timestamp': datetime.fromtimestamp(int(kline['t']) / 1000),
            'price_change': float(kline['c']) - float(kline['o']),
            'price_change_percent': ((float(kline['c']) - float(kline['o'])) / float(kline['o'])) * 100
        }
        
    def _process_ticker_data(self, ticker: Dict) -> Dict:
        """Processa dados de ticker para formato padronizado"""
        return {
            'symbol': ticker['s'],
            'price': float(ticker['c']),
            'price_change': float(ticker['P']),
            'price_change_percent': float(ticker['p']),
            'high_24h': float(ticker['h']),
            'low_24h': float(ticker['l']),
            'volume_24h': float(ticker['v']),
            'count_24h': int(ticker['n']),
            'timestamp': datetime.fromtimestamp(int(ticker['E']) / 1000)
        }
        
    # Removido - usar apenas dados públicos conforme solicitado pelo usuário
        
    def format_symbol(self, symbol: str) -> str:
        """Formata símbolo para padrão Binance (remove barra)"""
        return symbol.replace('/', '').upper()
        
    def create_stream_name(self, symbol: str, stream_type: str, interval: str = None) -> str:
        """Cria nome do stream formatado"""
        symbol_formatted = self.format_symbol(symbol)
        if interval:
            return f"{symbol_formatted.lower()}@{stream_type}_{interval}"
        else:
            return f"{symbol_formatted.lower()}@{stream_type}"

# Classe para gerenciar dados em tempo real
class RealTimeDataManager:
    """Gerenciador de dados em tempo real com cache e indicadores"""
    
    def __init__(self, max_candles: int = 200):
        self.data = {}  # {symbol: DataFrame}
        self.max_candles = max_candles
        self.callbacks = {}  # {symbol: [callbacks]}
        
    def add_callback(self, symbol: str, callback: Callable):
        """Adiciona callback para ser executado quando dados são atualizados"""
        if symbol not in self.callbacks:
            self.callbacks[symbol] = []
        self.callbacks[symbol].append(callback)
        
    async def process_kline_update(self, kline_data: Dict):
        """Processa atualização de kline e atualiza DataFrame"""
        symbol = kline_data['symbol']
        
        # Criar DataFrame se não existir
        if symbol not in self.data:
            self.data[symbol] = pd.DataFrame()
            
        df = self.data[symbol]
        
        # Se o kline está fechado, adicionar como nova linha
        if kline_data['is_closed']:
            new_row = pd.DataFrame([{
                'timestamp': kline_data['timestamp'],
                'open': kline_data['open'],
                'high': kline_data['high'],
                'low': kline_data['low'],
                'close': kline_data['close'],
                'volume': kline_data['volume']
            }])
            
            if not df.empty:
                # Remover linha antiga se for o mesmo timestamp
                df = df[df['timestamp'] != kline_data['timestamp']]
                
            df = pd.concat([df, new_row], ignore_index=True)
            
            # Manter apenas últimas N candles
            if len(df) > self.max_candles:
                df = df.tail(self.max_candles)
                
            self.data[symbol] = df
            
            # Executar callbacks
            if symbol in self.callbacks:
                for callback in self.callbacks[symbol]:
                    try:
                        await callback(symbol, df, kline_data)
                    except Exception as e:
                        print(f"❌ Erro em callback: {e}")
                        
    def get_latest_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Retorna dados mais recentes do símbolo"""
        return self.data.get(symbol)
        
    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Retorna último preço do símbolo"""
        if symbol in self.data and not self.data[symbol].empty:
            return self.data[symbol].iloc[-1]['close']
        return None

# Exemplo de uso
async def example_usage():
    """Exemplo de como usar o WebSocket client"""
    
    ws_client = BinanceFuturesWebSocket()
    data_manager = RealTimeDataManager()
    
    # Callback para processar dados de kline
    async def handle_kline_data(kline_data):
        await data_manager.process_kline_update(kline_data)
        print(f"📊 {kline_data['symbol']}: ${kline_data['close']:.4f} "
              f"({kline_data['price_change_percent']:+.2f}%)")
    
    # Callback para processar dados de ticker
    async def handle_ticker_data(ticker_data):
        print(f"🏷️  {ticker_data['symbol']}: ${ticker_data['price']:.4f} "
              f"({ticker_data['price_change_percent']:+.2f}%)")
    
    # Conectar a streams
    await asyncio.gather(
        ws_client.connect_kline_stream('BTCUSDT', '5m', handle_kline_data),
        ws_client.connect_ticker_stream('BTCUSDT', handle_ticker_data)
    )

if __name__ == "__main__":
    # Executar exemplo
    asyncio.run(example_usage())