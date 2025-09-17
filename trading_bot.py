import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import os
from indicators import TechnicalIndicators

class TradingBot:
    def __init__(self):
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.symbol = "XLM/USDT"
        self.timeframe = "5m"
        self.rsi_period = 9
        self.rsi_min = 20
        self.rsi_max = 80
        self.indicators = TechnicalIndicators()
        
    def update_config(self, symbol=None, timeframe=None, rsi_period=None, rsi_min=None, rsi_max=None):
        """Update bot configuration parameters"""
        if symbol:
            self.symbol = symbol
        if timeframe:
            self.timeframe = timeframe
        if rsi_period:
            self.rsi_period = rsi_period
        if rsi_min:
            self.rsi_min = rsi_min
        if rsi_max:
            self.rsi_max = rsi_max
    
    def get_market_data(self, limit=200):
        """Fetch OHLCV data from exchange"""
        try:
            # Fetch raw OHLCV data
            ohlcv = self.exchange.fetch_ohlcv(self.symbol, self.timeframe, limit=limit)
            
            if not ohlcv:
                raise Exception("No data received from exchange")
            
            # Convert to DataFrame
            df = pd.DataFrame(ohlcv)
            df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            
            # Convert timestamp to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Calculate technical indicators
            df = self.calculate_indicators(df)
            
            return df
            
        except Exception as e:
            print(f"Error fetching market data for {self.symbol}: {e}")
            raise e
    
    def calculate_indicators(self, df):
        """Calculate technical indicators for the dataframe"""
        # Calculate RSI
        df['rsi'] = self.indicators.calculate_rsi(df['close'], self.rsi_period)
        
        # Calculate moving averages for additional context
        df['sma_20'] = df['close'].rolling(window=20).mean()
        df['sma_50'] = df['close'].rolling(window=50).mean()
        
        # Calculate volume moving average
        df['volume_ma'] = df['volume'].rolling(window=20).mean()
        
        # Generate signals
        df['signal'] = df.apply(self._generate_signal, axis=1)
        
        return df
    
    def _generate_signal(self, row):
        """Generate trading signal based on RSI"""
        if pd.isna(row['rsi']):
            return "NEUTRO"
        
        if row['rsi'] < self.rsi_min:
            return "COMPRA"
        elif row['rsi'] > self.rsi_max:
            return "VENDA"
        else:
            return "NEUTRO"
    
    def check_signal(self, df):
        """Check the current trading signal"""
        if df is None or df.empty:
            return "NEUTRO"
        
        last_row = df.iloc[-1]
        return self._generate_signal(last_row)
    
    def get_market_summary(self, df):
        """Get market summary statistics"""
        if df is None or df.empty:
            return None
        
        last_candle = df.iloc[-1]
        
        # Calculate price change
        price_change = last_candle['close'] - last_candle['open']
        price_change_pct = (price_change / last_candle['open']) * 100
        
        # Calculate 24h high/low (approximation using available data)
        high_24h = df['high'].tail(288).max() if len(df) >= 288 else df['high'].max()  # 288 = 24h in 5min candles
        low_24h = df['low'].tail(288).min() if len(df) >= 288 else df['low'].min()
        
        return {
            'current_price': last_candle['close'],
            'price_change': price_change,
            'price_change_pct': price_change_pct,
            'high_24h': high_24h,
            'low_24h': low_24h,
            'volume': last_candle['volume'],
            'rsi': last_candle['rsi'],
            'signal': self.check_signal(df)
        }
    
    def validate_symbol(self, symbol):
        """Validate if symbol exists on the exchange"""
        try:
            markets = self.exchange.load_markets()
            return symbol in markets
        except:
            return False
